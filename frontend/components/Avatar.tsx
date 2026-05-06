"use client";

import clsx from "clsx";
import { useEffect, useState } from "react";

interface Props {
  /** 0..1 — current speaking amplitude (drives mouth opening). */
  amplitude: number;
  /** Whether the avatar is the active speaker right now. */
  speaking: boolean;
  /** Whether the avatar is listening to the user. */
  listening: boolean;
  /** Display name shown under the avatar. */
  name?: string;
}

/**
 * Audio-amplitude-driven SVG avatar. Production-quality 3rd-party options
 * (Tavus, Beyond Presence) require their own API keys + iframe embeds; this
 * SVG implementation gives us instant, lag-free lip-sync for the demo and
 * looks great. Easy to swap for an iframe later — the parent component
 * controls when/why to show it.
 */
export function Avatar({ amplitude, speaking, listening, name = "Aria" }: Props) {
  // Smooth the raw amplitude so the mouth doesn't jitter
  const [smoothed, setSmoothed] = useState(0);
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      setSmoothed((s) => s + (amplitude - s) * 0.35);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [amplitude]);

  // Map amplitude → mouth open height
  const mouthOpen = speaking ? Math.max(2, Math.min(28, smoothed * 60)) : 4;
  const mouthWidth = speaking ? 38 + smoothed * 10 : 38;

  // Eye blink every ~3.5s
  const [blink, setBlink] = useState(false);
  useEffect(() => {
    const id = setInterval(() => {
      setBlink(true);
      setTimeout(() => setBlink(false), 130);
    }, 3500 + Math.random() * 1500);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="relative flex flex-col items-center">
      {/* Pulse rings while listening */}
      {listening && (
        <>
          <div className="absolute inset-0 m-auto h-56 w-56 rounded-full border border-brand-400/40 animate-pulse-ring" />
          <div
            className="absolute inset-0 m-auto h-56 w-56 rounded-full border border-brand-400/40 animate-pulse-ring"
            style={{ animationDelay: "0.5s" }}
          />
        </>
      )}

      <div
        className={clsx(
          "relative h-56 w-56 rounded-full overflow-hidden",
          "bg-gradient-to-b from-brand-500 to-brand-800",
          "ring-4 ring-white/10 shadow-2xl shadow-brand-900/50",
          speaking && "ring-brand-300/60",
        )}
      >
        <svg
          viewBox="0 0 200 200"
          className="absolute inset-0 h-full w-full"
          aria-hidden
        >
          {/* Background glow */}
          <defs>
            <radialGradient id="faceGrad" cx="50%" cy="40%" r="60%">
              <stop offset="0%" stopColor="#fde7d3" />
              <stop offset="60%" stopColor="#f4c9a3" />
              <stop offset="100%" stopColor="#c69672" />
            </radialGradient>
            <radialGradient id="hairGrad" cx="50%" cy="40%" r="60%">
              <stop offset="0%" stopColor="#3b2a1a" />
              <stop offset="100%" stopColor="#1a1108" />
            </radialGradient>
          </defs>

          {/* Hair / head silhouette */}
          <ellipse cx="100" cy="92" rx="78" ry="86" fill="url(#hairGrad)" />

          {/* Face */}
          <ellipse cx="100" cy="108" rx="62" ry="72" fill="url(#faceGrad)" />

          {/* Cheeks */}
          <ellipse cx="68" cy="130" rx="14" ry="8" fill="#ec9b8c" opacity="0.5" />
          <ellipse cx="132" cy="130" rx="14" ry="8" fill="#ec9b8c" opacity="0.5" />

          {/* Eyebrows */}
          <path d="M62 84 Q76 78 90 84" stroke="#2a1a0e" strokeWidth="3" fill="none" strokeLinecap="round" />
          <path d="M110 84 Q124 78 138 84" stroke="#2a1a0e" strokeWidth="3" fill="none" strokeLinecap="round" />

          {/* Eyes (or lashes when blinking) */}
          {blink ? (
            <>
              <path d="M64 100 Q76 104 88 100" stroke="#2a1a0e" strokeWidth="2.5" fill="none" strokeLinecap="round" />
              <path d="M112 100 Q124 104 136 100" stroke="#2a1a0e" strokeWidth="2.5" fill="none" strokeLinecap="round" />
            </>
          ) : (
            <>
              <ellipse cx="76" cy="100" rx="6.5" ry="8" fill="#fff" />
              <circle cx="76" cy="101" r="4" fill="#3b2a1a" />
              <circle cx="77.5" cy="99" r="1.4" fill="#fff" />

              <ellipse cx="124" cy="100" rx="6.5" ry="8" fill="#fff" />
              <circle cx="124" cy="101" r="4" fill="#3b2a1a" />
              <circle cx="125.5" cy="99" r="1.4" fill="#fff" />
            </>
          )}

          {/* Nose */}
          <path d="M100 110 Q96 130 100 138 Q104 135 105 132" stroke="#a87655" strokeWidth="2" fill="none" strokeLinecap="round" />

          {/* Mouth — driven by amplitude */}
          <g transform={`translate(${100 - mouthWidth / 2}, 154)`}>
            <rect
              x={0}
              y={0}
              rx={mouthOpen / 2 + 4}
              ry={mouthOpen / 2 + 2}
              width={mouthWidth}
              height={mouthOpen + 6}
              fill="#5a1a1a"
              opacity={0.95}
            />
            {/* Teeth hint */}
            {mouthOpen > 8 && (
              <rect
                x={3}
                y={2}
                rx={2}
                ry={2}
                width={mouthWidth - 6}
                height={3}
                fill="#fff"
                opacity={0.9}
              />
            )}
          </g>

          {/* Hair fringe over forehead */}
          <path
            d="M30 78 Q100 30 170 78 Q160 86 150 78 Q140 70 130 80 Q120 70 110 78 Q100 70 90 80 Q80 70 70 78 Q60 86 50 78 Q40 86 30 78 Z"
            fill="url(#hairGrad)"
          />
        </svg>
      </div>

      <div className="mt-4 text-center">
        <div className="text-xl font-semibold tracking-tight text-white">{name}</div>
        <div className="text-xs text-white/60">
          {speaking ? "Speaking…" : listening ? "Listening…" : "Standby"}
        </div>
      </div>
    </div>
  );
}
