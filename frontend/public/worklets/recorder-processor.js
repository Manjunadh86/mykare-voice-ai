// AudioWorklet that downsamples mic input from the browser's native sample rate
// (typically 44.1kHz or 48kHz) to 24kHz mono PCM16 — the format the OpenAI
// Realtime API expects. Sends Int16Array chunks of ~100ms back to the main
// thread via `port.postMessage`.

class RecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetSampleRate = 24000;
    this.inputSampleRate = sampleRate; // global from AudioWorkletGlobalScope
    this.ratio = this.inputSampleRate / this.targetSampleRate;

    // Buffer ~100ms worth of 24kHz PCM16 (2400 samples) before flushing.
    this.flushSize = 2400;
    this.buffer = new Float32Array(0);
  }

  // Naive linear-interpolation downsampler. Input is Float32 [-1, 1] mono.
  downsample(input) {
    const outLength = Math.floor(input.length / this.ratio);
    const out = new Float32Array(outLength);
    for (let i = 0; i < outLength; i++) {
      const idx = i * this.ratio;
      const i0 = Math.floor(idx);
      const i1 = Math.min(i0 + 1, input.length - 1);
      const t = idx - i0;
      out[i] = input[i0] * (1 - t) + input[i1] * t;
    }
    return out;
  }

  flush() {
    if (this.buffer.length < this.flushSize) return;
    const chunk = this.buffer.subarray(0, this.flushSize);
    this.buffer = this.buffer.subarray(this.flushSize);

    // Float32 → Int16
    const pcm16 = new Int16Array(chunk.length);
    for (let i = 0; i < chunk.length; i++) {
      const s = Math.max(-1, Math.min(1, chunk[i]));
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    // Transfer the underlying buffer for zero-copy
    this.port.postMessage(pcm16, [pcm16.buffer]);
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channel = input[0]; // mono
    if (!channel) return true;

    const downsampled = this.downsample(channel);

    // Append to buffer
    const merged = new Float32Array(this.buffer.length + downsampled.length);
    merged.set(this.buffer, 0);
    merged.set(downsampled, this.buffer.length);
    this.buffer = merged;

    while (this.buffer.length >= this.flushSize) {
      this.flush();
    }
    return true;
  }
}

registerProcessor("recorder-processor", RecorderProcessor);
