"use client";

import {
  Calendar,
  CircleCheck,
  Clock,
  DollarSign,
  FileText,
  Loader2,
  Mail,
  Phone,
  Sparkles,
  User,
  X,
} from "lucide-react";
import type { SummaryResponse } from "@/lib/api";

interface Props {
  summary: SummaryResponse | null;
  loading: boolean;
  onClose: () => void;
}

function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function CallSummary({ summary, loading, onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in p-4">
      <div className="glass max-w-3xl w-full max-h-[90vh] overflow-y-auto p-6 md:p-8 relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-2 rounded-full hover:bg-white/10 transition"
          aria-label="Close summary"
        >
          <X className="h-5 w-5 text-white/70" />
        </button>

        <div className="flex items-center gap-3 mb-6">
          <div className="p-2.5 rounded-xl bg-brand-500/20">
            <Sparkles className="h-5 w-5 text-brand-300" />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-white">Call summary</h2>
            <div className="text-xs text-white/50">
              {summary
                ? `Generated ${formatDateTime(summary.generated_at)}`
                : "Generating…"}
            </div>
          </div>
        </div>

        {loading || !summary ? (
          <div className="space-y-3">
            <div className="shimmer h-5 w-3/4 rounded" />
            <div className="shimmer h-5 w-1/2 rounded" />
            <div className="shimmer h-32 w-full rounded" />
            <div className="shimmer h-24 w-full rounded" />
            <div className="flex items-center gap-2 text-white/60 text-sm pt-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              Aria is wrapping up your call…
            </div>
          </div>
        ) : (
          <>
            {/* Summary text */}
            <section className="mb-6">
              <SectionHeader icon={FileText} label="Summary" />
              <p className="text-white/90 leading-relaxed">
                {summary.summary || "No summary available."}
              </p>
            </section>

            {/* Extracted entities */}
            <section className="mb-6 grid sm:grid-cols-2 gap-3">
              <Entity icon={User} label="Caller" value={summary.name} />
              <Entity icon={Phone} label="Phone" value={summary.phone} />
              <Entity icon={Mail} label="Intent" value={summary.intent} />
              <Entity
                icon={DollarSign}
                label="Estimated cost"
                value={`$${summary.cost_usd.toFixed(4)}`}
              />
            </section>

            {/* Actions */}
            {summary.actions_taken?.length > 0 && (
              <section className="mb-6">
                <SectionHeader icon={CircleCheck} label="What we did" />
                <ul className="space-y-1.5">
                  {summary.actions_taken.map((a, i) => (
                    <li key={i} className="flex gap-2 text-sm text-white/85">
                      <CircleCheck className="h-4 w-4 mt-0.5 text-emerald-400 shrink-0" />
                      {a}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Preferences */}
            {summary.preferences?.length > 0 && (
              <section className="mb-6">
                <SectionHeader icon={Sparkles} label="Caller preferences" />
                <div className="flex flex-wrap gap-2">
                  {summary.preferences.map((p, i) => (
                    <span
                      key={i}
                      className="px-2.5 py-1 rounded-full bg-brand-500/15 text-brand-200 text-xs"
                    >
                      {p}
                    </span>
                  ))}
                </div>
              </section>
            )}

            {/* Follow-ups */}
            {summary.follow_ups?.length > 0 && (
              <section className="mb-6">
                <SectionHeader icon={Clock} label="Follow-ups" />
                <ul className="space-y-1.5">
                  {summary.follow_ups.map((f, i) => (
                    <li key={i} className="flex gap-2 text-sm text-amber-200">
                      <Clock className="h-4 w-4 mt-0.5 shrink-0" />
                      {f}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Appointments */}
            <section>
              <SectionHeader icon={Calendar} label="All appointments on file" />
              {summary.appointments.length === 0 ? (
                <div className="text-sm text-white/60 italic">
                  No appointments on record.
                </div>
              ) : (
                <div className="space-y-2">
                  {summary.appointments.map((a) => (
                    <div
                      key={a.id}
                      className="flex items-center justify-between gap-3 rounded-xl bg-white/5 px-3.5 py-2.5"
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-white truncate">
                          {a.provider}
                        </div>
                        <div className="text-xs text-white/60">
                          {formatDateTime(a.slot_start)}
                          {a.reason ? ` · ${a.reason}` : ""}
                        </div>
                      </div>
                      <span
                        className={
                          a.status === "confirmed"
                            ? "px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider bg-emerald-500/20 text-emerald-300"
                            : "px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider bg-rose-500/20 text-rose-300"
                        }
                      >
                        {a.status}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function SectionHeader({
  icon: Icon,
  label,
}: {
  icon: typeof FileText;
  label: string;
}) {
  return (
    <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/60 mb-2">
      <Icon className="h-3.5 w-3.5" />
      {label}
    </div>
  );
}

function Entity({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof User;
  label: string;
  value: string | null | undefined;
}) {
  return (
    <div className="rounded-xl bg-white/5 px-3.5 py-2.5">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-white/50 mb-1">
        <Icon className="h-3 w-3" />
        {label}
      </div>
      <div className="text-sm text-white/90 truncate">
        {value || <span className="italic text-white/40">—</span>}
      </div>
    </div>
  );
}
