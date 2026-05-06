"use client";

import { DollarSign } from "lucide-react";
import type { CostEvent } from "@/lib/realtime-client";

export function CostMeter({ cost }: { cost: CostEvent | null }) {
  if (!cost) return null;
  return (
    <div className="glass px-3.5 py-2 flex items-center gap-3 text-xs">
      <div className="flex items-center gap-1.5 text-emerald-300">
        <DollarSign className="h-3.5 w-3.5" />
        <span className="font-mono font-semibold">
          ${cost.total_cost_usd.toFixed(4)}
        </span>
      </div>
      <div className="w-px h-4 bg-white/10" />
      <div className="text-white/60">
        <span className="text-white/40">in</span>{" "}
        <span className="font-mono">{cost.audio_input_min.toFixed(2)}m</span>{" "}
        <span className="text-white/40">· out</span>{" "}
        <span className="font-mono">{cost.audio_output_min.toFixed(2)}m</span>{" "}
        <span className="text-white/40">· tok</span>{" "}
        <span className="font-mono">
          {cost.text_input_tokens + cost.text_output_tokens}
        </span>
      </div>
    </div>
  );
}
