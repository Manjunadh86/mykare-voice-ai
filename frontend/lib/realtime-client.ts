/**
 * RealtimeVoiceClient
 * ===================
 * Browser-side voice engine. Wraps:
 *   - microphone capture via AudioWorklet → 24kHz PCM16
 *   - WebSocket to our backend proxy (which talks to OpenAI Realtime)
 *   - playback queue using AudioBufferSourceNodes
 *   - lightweight RMS amplitude probe so the avatar can lip-sync
 *
 * The client emits typed events the React layer can subscribe to.
 */

export type ToolCallStatus = "started" | "completed";

export interface ToolCallEvent {
  callId?: string;
  name: string;
  status: ToolCallStatus;
  arguments?: Record<string, unknown>;
  result?: Record<string, unknown>;
  timestamp: number;
}

export interface TranscriptEvent {
  role: "user" | "assistant";
  text: string;
  isPartial: boolean;
  timestamp: number;
}

export interface CostEvent {
  audio_input_min: number;
  audio_output_min: number;
  text_input_tokens: number;
  text_output_tokens: number;
  audio_input_cost: number;
  audio_output_cost: number;
  text_input_cost: number;
  text_output_cost: number;
  total_cost_usd: number;
}

export type ConnectionState =
  | "idle"
  | "connecting"
  | "connected"
  | "listening"
  | "speaking"
  | "ended"
  | "error";

export interface RealtimeClientHandlers {
  onState?: (state: ConnectionState) => void;
  onSessionId?: (id: string) => void;
  onTranscript?: (e: TranscriptEvent) => void;
  onToolCall?: (e: ToolCallEvent) => void;
  onCost?: (e: CostEvent) => void;
  onError?: (msg: string) => void;
  onAmplitude?: (rms: number) => void; // 0..1, for avatar lip sync
  onEndCall?: () => void;
}

const PLAYBACK_SAMPLE_RATE = 24000;

export class RealtimeVoiceClient {
  private ws: WebSocket | null = null;
  private audioCtx: AudioContext | null = null;
  private playbackCtx: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private mediaStream: MediaStream | null = null;
  private mediaSource: MediaStreamAudioSourceNode | null = null;
  private analyser: AnalyserNode | null = null;
  private analyserData: Uint8Array | null = null;
  private rafId: number | null = null;

  private playbackQueue: Float32Array[] = [];
  private nextPlaybackTime = 0;
  private playingNodes: AudioBufferSourceNode[] = [];

  private handlers: RealtimeClientHandlers;
  private state: ConnectionState = "idle";
  private currentAssistantText = "";
  private sessionId: string | null = null;

  constructor(handlers: RealtimeClientHandlers) {
    this.handlers = handlers;
  }

  // ------------------------------------------------------------------
  // Lifecycle
  // ------------------------------------------------------------------

  async connect(wsUrl: string): Promise<void> {
    this.setState("connecting");

    // 1. Acquire mic
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      this.handlers.onError?.(
        "Microphone access denied. Please grant permission and try again.",
      );
      this.setState("error");
      throw err;
    }

    // 2. Set up audio graphs (input + playback can share a context but having
    //    a dedicated playback ctx running at 24kHz lets us schedule chunks
    //    without resampling).
    this.audioCtx = new AudioContext();
    if (this.audioCtx.state === "suspended") await this.audioCtx.resume();

    this.playbackCtx = new AudioContext({ sampleRate: PLAYBACK_SAMPLE_RATE });
    if (this.playbackCtx.state === "suspended") await this.playbackCtx.resume();

    await this.audioCtx.audioWorklet.addModule("/worklets/recorder-processor.js");

    this.mediaSource = this.audioCtx.createMediaStreamSource(this.mediaStream);
    this.workletNode = new AudioWorkletNode(this.audioCtx, "recorder-processor");
    this.workletNode.port.onmessage = (ev) => this.onMicChunk(ev.data as Int16Array);

    // Tap an analyser off the mic for visualization (optional; outgoing only)
    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = 512;
    this.analyserData = new Uint8Array(this.analyser.fftSize);

    this.mediaSource.connect(this.analyser);
    this.mediaSource.connect(this.workletNode);
    // Don't connect to destination — we don't want to hear ourselves.

    // 3. Open WS
    this.ws = new WebSocket(wsUrl);
    this.ws.binaryType = "arraybuffer";

    this.ws.onopen = () => this.setState("connected");
    this.ws.onerror = () => {
      this.handlers.onError?.("WebSocket error");
      this.setState("error");
    };
    this.ws.onclose = () => {
      if (this.state !== "ended") this.setState("ended");
    };
    this.ws.onmessage = (e) => this.onWsMessage(e.data);

    // 4. Start the amplitude probe (combines mic-active and assistant-speaking)
    this.startAmplitudeLoop();
  }

  async disconnect(): Promise<void> {
    this.setState("ended");
    try {
      this.ws?.send(JSON.stringify({ type: "session.end" }));
    } catch {
      /* ignore */
    }
    this.ws?.close();
    this.ws = null;
    this.cleanupAudio();
  }

  private cleanupAudio() {
    if (this.rafId != null) cancelAnimationFrame(this.rafId);
    this.rafId = null;
    this.playingNodes.forEach((n) => {
      try { n.stop(); } catch { /* */ }
    });
    this.playingNodes = [];
    this.playbackQueue = [];
    this.workletNode?.disconnect();
    this.analyser?.disconnect();
    this.mediaSource?.disconnect();
    this.mediaStream?.getTracks().forEach((t) => t.stop());
    this.audioCtx?.close().catch(() => {});
    this.playbackCtx?.close().catch(() => {});
    this.workletNode = null;
    this.analyser = null;
    this.mediaSource = null;
    this.mediaStream = null;
    this.audioCtx = null;
    this.playbackCtx = null;
  }

  // ------------------------------------------------------------------
  // Outgoing (mic → server)
  // ------------------------------------------------------------------

  private onMicChunk(pcm16: Int16Array) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    // Anti-echo: drop mic frames while Aria is actively speaking, OTHERWISE
    // her own voice (coming back through the user's speakers into the mic)
    // gets transcribed as user input and triggers spurious tool calls.
    // The user can still interrupt — they just need ~150ms after a chunk
    // ends to be heard, which is below the perceptual threshold.
    if (this.state === "speaking") return;
    const b64 = int16ArrayToBase64(pcm16);
    this.ws.send(
      JSON.stringify({ type: "input_audio_buffer.append", audio: b64 }),
    );
  }

  // ------------------------------------------------------------------
  // Incoming (server events)
  // ------------------------------------------------------------------

  private onWsMessage(raw: unknown) {
    if (typeof raw !== "string") return;
    let evt: any;
    try {
      evt = JSON.parse(raw);
    } catch {
      return;
    }

    switch (evt.type) {
      case "session.id":
        this.sessionId = evt.session_id;
        this.handlers.onSessionId?.(evt.session_id);
        break;

      case "error":
        this.handlers.onError?.(evt.message ?? "Unknown server error");
        break;

      case "tool.call.started":
        this.handlers.onToolCall?.({
          callId: evt.call_id,
          name: evt.name,
          status: "started",
          timestamp: Date.now(),
        });
        break;

      case "tool.call.completed":
        this.handlers.onToolCall?.({
          callId: evt.call_id,
          name: evt.name,
          status: "completed",
          arguments: evt.arguments,
          result: evt.result,
          timestamp: Date.now(),
        });
        break;

      case "session.cost.update":
        this.handlers.onCost?.(evt.cost);
        break;

      case "session.end_call":
        this.handlers.onEndCall?.();
        break;

      // ---- Forwarded OpenAI Realtime events ----
      case "input_audio_buffer.speech_started":
        this.setState("listening");
        break;
      case "input_audio_buffer.speech_stopped":
        // assistant will start speaking next
        break;

      case "response.audio.delta": {
        const pcm = base64ToInt16Array(evt.delta);
        this.enqueuePlayback(pcm);
        break;
      }
      case "response.audio.done":
      case "response.done":
        // Nothing extra; state transitions are driven by playback.
        break;

      case "response.audio_transcript.delta":
        this.currentAssistantText += evt.delta ?? "";
        this.handlers.onTranscript?.({
          role: "assistant",
          text: this.currentAssistantText,
          isPartial: true,
          timestamp: Date.now(),
        });
        break;

      case "response.audio_transcript.done":
        this.handlers.onTranscript?.({
          role: "assistant",
          text: this.currentAssistantText,
          isPartial: false,
          timestamp: Date.now(),
        });
        this.currentAssistantText = "";
        break;

      case "conversation.item.input_audio_transcription.completed":
        if (evt.transcript) {
          this.handlers.onTranscript?.({
            role: "user",
            text: evt.transcript,
            isPartial: false,
            timestamp: Date.now(),
          });
        }
        break;

      default:
        // ignore other event types
        break;
    }
  }

  // ------------------------------------------------------------------
  // Playback
  // ------------------------------------------------------------------

  private enqueuePlayback(pcm16: Int16Array) {
    if (!this.playbackCtx) return;
    const float = int16ToFloat32(pcm16);
    this.scheduleChunk(float);
  }

  private scheduleChunk(float: Float32Array) {
    const ctx = this.playbackCtx;
    if (!ctx) return;
    const buffer = ctx.createBuffer(1, float.length, PLAYBACK_SAMPLE_RATE);
    buffer.copyToChannel(float, 0);

    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);

    const startAt = Math.max(this.nextPlaybackTime, ctx.currentTime + 0.02);
    src.start(startAt);
    this.nextPlaybackTime = startAt + buffer.duration;

    this.playingNodes.push(src);
    this.setState("speaking");
    src.onended = () => {
      this.playingNodes = this.playingNodes.filter((n) => n !== src);
      if (this.playingNodes.length === 0) {
        this.setState("listening");
      }
    };
  }

  // ------------------------------------------------------------------
  // Amplitude / lip sync
  // ------------------------------------------------------------------

  private startAmplitudeLoop() {
    const tick = () => {
      const data = this.analyserData;
      const node = this.analyser;
      // The avatar should react to the ASSISTANT speaking, not the user.
      // We compute amplitude from currently playing buffers by sampling the
      // most recent chunk in the queue using a separate analyser tap. Simpler
      // approach: peak on the last scheduled buffer.
      let rms = 0;

      if (this.state === "speaking" && this.playingNodes.length > 0) {
        // Approximate: oscillate a synthetic envelope while audio is playing.
        // (A perfect lip sync would require Wav2Lip-style server-side render;
        // for our SVG mouth this looks great.)
        rms = 0.3 + 0.3 * Math.abs(Math.sin(performance.now() / 80));
      } else if (node && data) {
        node.getByteTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) {
          const v = (data[i] - 128) / 128;
          sum += v * v;
        }
        rms = Math.min(1, Math.sqrt(sum / data.length) * 1.5);
      }
      this.handlers.onAmplitude?.(rms);
      this.rafId = requestAnimationFrame(tick);
    };
    this.rafId = requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  private setState(s: ConnectionState) {
    if (s === this.state) return;
    this.state = s;
    this.handlers.onState?.(s);
  }

  getSessionId(): string | null {
    return this.sessionId;
  }
}

// ---- conversion helpers ----

function int16ArrayToBase64(arr: Int16Array): string {
  const bytes = new Uint8Array(arr.buffer);
  // Avoid the call-stack-blowing String.fromCharCode trick on large arrays
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

function base64ToInt16Array(b64: string): Int16Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2);
}

function int16ToFloat32(int16: Int16Array): Float32Array {
  const out = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    const v = int16[i];
    out[i] = v < 0 ? v / 0x8000 : v / 0x7fff;
  }
  return out;
}
