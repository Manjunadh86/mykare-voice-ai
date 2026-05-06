"use client";

import clsx from "clsx";
import { useEffect, useRef } from "react";

export interface TranscriptItem {
  id: string;
  role: "user" | "assistant";
  text: string;
  partial?: boolean;
  timestamp: number;
}

export function Transcript({ items }: { items: TranscriptItem[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" });
  }, [items]);

  return (
    <div
      ref={ref}
      className="glass max-h-[420px] flex-1 overflow-y-auto p-4 space-y-3"
    >
      {items.length === 0 ? (
        <div className="text-sm text-white/50 italic text-center py-8">
          The transcript will appear here as you talk.
        </div>
      ) : (
        items.map((m) => (
          <div
            key={m.id}
            className={clsx(
              "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed animate-slide-up",
              m.role === "user"
                ? "ml-auto bg-brand-500/30 text-white rounded-br-md"
                : "mr-auto bg-white/8 text-white/95 rounded-bl-md",
              m.partial && "opacity-70 italic",
            )}
          >
            <div className="text-[10px] uppercase tracking-wider opacity-60 mb-0.5">
              {m.role === "user" ? "You" : "Aria"}
            </div>
            {m.text || (m.partial ? "…" : "")}
          </div>
        ))
      )}
    </div>
  );
}
