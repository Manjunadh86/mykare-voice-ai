"use client";

import clsx from "clsx";
import {
  CalendarCheck,
  CalendarX,
  CalendarClock,
  CalendarSearch,
  ListChecks,
  PhoneOff,
  UserCheck,
  Wrench,
  Loader2,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import type { ToolCallEvent } from "@/lib/realtime-client";

const TOOL_META: Record<
  string,
  { label: string; verb: string; icon: typeof Wrench; color: string }
> = {
  identify_user: { label: "Identify caller", verb: "Looking you up…", icon: UserCheck, color: "text-sky-300" },
  fetch_slots: { label: "Find slots", verb: "Fetching slots…", icon: CalendarSearch, color: "text-amber-300" },
  book_appointment: { label: "Book appointment", verb: "Booking…", icon: CalendarCheck, color: "text-emerald-300" },
  retrieve_appointments: { label: "Get appointments", verb: "Loading appointments…", icon: ListChecks, color: "text-indigo-300" },
  cancel_appointment: { label: "Cancel appointment", verb: "Cancelling…", icon: CalendarX, color: "text-rose-300" },
  modify_appointment: { label: "Reschedule", verb: "Rescheduling…", icon: CalendarClock, color: "text-violet-300" },
  end_conversation: { label: "End call", verb: "Wrapping up…", icon: PhoneOff, color: "text-white/70" },
};

export interface FeedItem extends ToolCallEvent {
  id: string;
}

function fmtVal(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

function ToolCard({ item }: { item: FeedItem }) {
  const meta = TOOL_META[item.name] ?? {
    label: item.name,
    verb: "Working…",
    icon: Wrench,
    color: "text-white/80",
  };
  const Icon = meta.icon;
  const ok = item.result?.ok !== false;
  const inflight = item.status === "started";

  return (
    <div
      className={clsx(
        "glass p-3.5 animate-slide-up border-l-4",
        inflight
          ? "border-brand-400 shadow-[0_0_24px_-8px_rgba(96,144,255,0.6)]"
          : ok
          ? "border-emerald-400/70"
          : "border-rose-400/70",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <Icon className={clsx("h-4 w-4", meta.color)} />
          <div className="text-sm font-medium text-white">{meta.label}</div>
        </div>
        <div className="flex items-center gap-1.5 text-xs">
          {inflight ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin text-brand-300" />
              <span className="text-brand-200">{meta.verb}</span>
            </>
          ) : ok ? (
            <>
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
              <span className="text-emerald-300">Done</span>
            </>
          ) : (
            <>
              <XCircle className="h-3.5 w-3.5 text-rose-400" />
              <span className="text-rose-300">Failed</span>
            </>
          )}
        </div>
      </div>

      {item.arguments && Object.keys(item.arguments).length > 0 && (
        <div className="mt-2 text-[11px] text-white/70 space-y-0.5">
          {Object.entries(item.arguments).map(([k, v]) => (
            <div key={k} className="flex gap-1.5">
              <span className="text-white/40">{k}:</span>
              <span className="font-mono">{fmtVal(v)}</span>
            </div>
          ))}
        </div>
      )}

      {item.result && (
        <div className="mt-2 rounded-md bg-black/25 px-2.5 py-1.5 text-[11px] text-white/80">
          {item.result.message ? (
            <div className="leading-snug">{String(item.result.message)}</div>
          ) : item.result.error ? (
            <div className="text-rose-300 leading-snug">{String(item.result.error)}</div>
          ) : (
            <pre className="whitespace-pre-wrap font-mono text-[10px] leading-tight max-h-40 overflow-y-auto">
              {JSON.stringify(item.result, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

export function ToolCallFeed({ items }: { items: FeedItem[] }) {
  return (
    <div className="space-y-2.5">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/60">
        <Wrench className="h-3.5 w-3.5" />
        Tool activity
      </div>
      {items.length === 0 ? (
        <div className="glass p-4 text-sm text-white/50 italic">
          When Aria calls a tool (book, cancel, lookup…) you&apos;ll see it
          here in real time.
        </div>
      ) : (
        items.map((it) => <ToolCard key={it.id} item={it} />)
      )}
    </div>
  );
}
