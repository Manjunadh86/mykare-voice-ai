"use client";

import clsx from "clsx";
import { Mic, MicOff, PhoneOff, Stethoscope } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Avatar } from "@/components/Avatar";
import { CallSummary } from "@/components/CallSummary";
import { CostMeter } from "@/components/CostMeter";
import { Transcript, type TranscriptItem } from "@/components/Transcript";
import { ToolCallFeed, type FeedItem } from "@/components/ToolCallFeed";
import { AppointmentsPanel } from "@/components/AppointmentsPanel";
import { api, type PublicConfig, type SummaryResponse } from "@/lib/api";
import {
  RealtimeVoiceClient,
  type ConnectionState,
  type CostEvent,
} from "@/lib/realtime-client";

const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/voice";

export default function HomePage() {
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [state, setState] = useState<ConnectionState>("idle");
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [tools, setTools] = useState<FeedItem[]>([]);
  const [amplitude, setAmplitude] = useState(0);
  const [cost, setCost] = useState<CostEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const clientRef = useRef<RealtimeVoiceClient | null>(null);

  // Load public config on mount
  useEffect(() => {
    api
      .config()
      .then(setConfig)
      .catch((e) => setError(`Backend unreachable: ${e.message}`));
  }, []);

  const isLive = useMemo(
    () => state === "connected" || state === "listening" || state === "speaking",
    [state],
  );

  const handleStart = useCallback(async () => {
    setError(null);
    setTranscript([]);
    setTools([]);
    setCost(null);
    setSummary(null);
    setSummaryOpen(false);

    const client = new RealtimeVoiceClient({
      onState: setState,
      onSessionId: setSessionId,
      onError: (m) => setError(m),
      onAmplitude: setAmplitude,
      onCost: setCost,
      onTranscript: (e) => {
        setTranscript((prev) => {
          // Coalesce streaming partials into a single bubble
          if (e.role === "assistant" && e.isPartial) {
            const last = prev[prev.length - 1];
            if (last?.role === "assistant" && last.partial) {
              return [
                ...prev.slice(0, -1),
                { ...last, text: e.text, timestamp: e.timestamp },
              ];
            }
            return [
              ...prev,
              {
                id: `a-${e.timestamp}`,
                role: "assistant",
                text: e.text,
                partial: true,
                timestamp: e.timestamp,
              },
            ];
          }
          if (e.role === "assistant" && !e.isPartial) {
            const last = prev[prev.length - 1];
            if (last?.role === "assistant" && last.partial) {
              return [
                ...prev.slice(0, -1),
                { ...last, text: e.text, partial: false },
              ];
            }
          }
          return [
            ...prev,
            {
              id: `${e.role[0]}-${e.timestamp}`,
              role: e.role,
              text: e.text,
              timestamp: e.timestamp,
            },
          ];
        });
      },
      onToolCall: (e) => {
        setTools((prev) => {
          if (e.status === "completed") {
            // Try to find a matching "started" entry and upgrade it
            const idx = prev.findIndex(
              (t) => t.callId && t.callId === e.callId && t.status === "started",
            );
            if (idx >= 0) {
              const next = [...prev];
              next[idx] = { ...next[idx], ...e };
              return next;
            }
          }
          return [...prev, { id: `${e.timestamp}-${e.name}`, ...e }];
        });
        if (e.status === "completed") {
          // Refresh appointments panel after any mutating tool
          if (
            ["book_appointment", "cancel_appointment", "modify_appointment"].includes(
              e.name,
            )
          ) {
            setRefreshKey((k) => k + 1);
          }
        }
      },
      onEndCall: () => {
        // Give the assistant a moment to finish the farewell, then close.
        setTimeout(() => handleStop(true), 1500);
      },
    });
    clientRef.current = client;

    try {
      await client.connect(WS_URL);
    } catch {
      /* error already surfaced */
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleStop = useCallback(
    async (autoSummary = true) => {
      const client = clientRef.current;
      const sid = client?.getSessionId() ?? sessionId;
      await client?.disconnect();
      clientRef.current = null;

      if (sid && autoSummary) {
        setSummaryOpen(true);
        setSummaryLoading(true);
        try {
          const s = await api.generateSummary(sid);
          setSummary(s);
        } catch (e) {
          setError(`Summary failed: ${(e as Error).message}`);
        } finally {
          setSummaryLoading(false);
          setRefreshKey((k) => k + 1);
        }
      }
    },
    [sessionId],
  );

  return (
    <main className="mx-auto max-w-7xl px-4 md:px-8 py-6 md:py-10 min-h-screen">
      <Header config={config} cost={cost} />

      {error && (
        <div className="mt-4 glass border-l-4 border-rose-400 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <div className="mt-6 grid lg:grid-cols-12 gap-6">
        {/* LEFT: Avatar + controls */}
        <section className="lg:col-span-4 space-y-6">
          <div className="glass p-6 flex flex-col items-center">
            <Avatar
              amplitude={amplitude}
              speaking={state === "speaking"}
              listening={state === "listening" || state === "connected"}
              name="Aria"
            />

            <div className="mt-6 flex items-center gap-3">
              {!isLive ? (
                <button
                  onClick={handleStart}
                  disabled={state === "connecting"}
                  className={clsx(
                    "btn-mic h-16 w-16 rounded-full flex items-center justify-center transition",
                    "disabled:opacity-50 disabled:cursor-not-allowed",
                  )}
                  aria-label="Start call"
                >
                  {state === "connecting" ? (
                    <span className="h-5 w-5 rounded-full border-2 border-white border-t-transparent animate-spin" />
                  ) : (
                    <Mic className="h-7 w-7 text-white" />
                  )}
                </button>
              ) : (
                <button
                  onClick={() => handleStop(true)}
                  className="btn-mic active h-16 w-16 rounded-full flex items-center justify-center transition"
                  aria-label="End call"
                >
                  <PhoneOff className="h-7 w-7 text-white" />
                </button>
              )}
            </div>

            <div className="mt-4 text-xs text-white/60 text-center max-w-xs">
              {isLive
                ? "Speak naturally — Aria detects when you're done."
                : "Tap the mic to start a call. Allow microphone access."}
            </div>
          </div>

          <AppointmentsPanel refreshKey={refreshKey} />
        </section>

        {/* MIDDLE: Transcript */}
        <section className="lg:col-span-5 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm uppercase tracking-wider text-white/60">
              Conversation
            </h2>
            {sessionId && (
              <span className="text-[10px] font-mono text-white/40">
                session {sessionId.slice(0, 8)}…
              </span>
            )}
          </div>
          <Transcript items={transcript} />
        </section>

        {/* RIGHT: Tool feed */}
        <section className="lg:col-span-3">
          <ToolCallFeed items={tools} />
        </section>
      </div>

      <Footer config={config} />

      {summaryOpen && (
        <CallSummary
          summary={summary}
          loading={summaryLoading}
          onClose={() => setSummaryOpen(false)}
        />
      )}
    </main>
  );
}

function Header({
  config,
  cost,
}: {
  config: PublicConfig | null;
  cost: CostEvent | null;
}) {
  return (
    <header className="flex items-center justify-between gap-4 flex-wrap">
      <div className="flex items-center gap-3">
        <div className="p-2.5 rounded-2xl bg-gradient-to-br from-brand-400 to-brand-700 shadow-lg shadow-brand-900/40">
          <Stethoscope className="h-5 w-5 text-white" />
        </div>
        <div>
          <div className="text-lg font-semibold tracking-tight text-white">
            {config?.clinic_name ?? "Mykare Health"}
          </div>
          <div className="text-xs text-white/50">
            Voice AI receptionist
            {config?.openai_configured === false && (
              <span className="ml-2 text-amber-300">
                · OpenAI key not configured
              </span>
            )}
          </div>
        </div>
      </div>
      <CostMeter cost={cost} />
    </header>
  );
}

function Footer({ config }: { config: PublicConfig | null }) {
  return (
    <footer className="mt-10 text-center text-[11px] text-white/40 space-x-2">
      <span>Powered by OpenAI Realtime</span>
      {config?.model && (
        <>
          <span>·</span>
          <span className="font-mono">{config.model}</span>
        </>
      )}
      {config?.voice && (
        <>
          <span>·</span>
          <span>voice: {config.voice}</span>
        </>
      )}
      {config?.providers && config.providers.length > 0 && (
        <>
          <span>·</span>
          <span>{config.providers.length} provider(s)</span>
        </>
      )}
    </footer>
  );
}
