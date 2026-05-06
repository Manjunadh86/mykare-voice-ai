"use client";

import { Calendar, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Appointment } from "@/lib/api";

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

export function AppointmentsPanel({ refreshKey }: { refreshKey: number }) {
  const [appts, setAppts] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setAppts(await api.listAppointments());
    } catch {
      /* noop */
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between text-xs uppercase tracking-wider text-white/60">
        <div className="flex items-center gap-2">
          <Calendar className="h-3.5 w-3.5" />
          Recent appointments
        </div>
        <button
          onClick={load}
          className="p-1.5 rounded-md hover:bg-white/10 transition"
          aria-label="Refresh appointments"
        >
          <RefreshCw className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
        </button>
      </div>
      {appts.length === 0 ? (
        <div className="glass p-4 text-sm text-white/50 italic">
          No appointments yet. Try booking one with Aria.
        </div>
      ) : (
        <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
          {appts.map((a) => (
            <div key={a.id} className="glass px-3.5 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-medium text-white truncate">
                  {a.provider}
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
              <div className="text-xs text-white/60 mt-0.5">
                {formatDateTime(a.slot_start)}
                {a.reason ? ` · ${a.reason}` : ""}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
