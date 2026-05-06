/** Tiny typed REST client for the FastAPI backend. */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Appointment {
  id: number;
  user_id?: number;
  provider: string;
  reason: string | null;
  slot_start: string;
  slot_end: string;
  status: "confirmed" | "cancelled";
  created_at?: string;
}

export interface SummaryResponse {
  session_id: string;
  generated_at: string;
  summary: string | null;
  name: string | null;
  phone: string | null;
  intent: string | null;
  preferences: string[];
  actions_taken: string[];
  follow_ups: string[];
  appointments: Appointment[];
  cost_usd: number;
}

export interface PublicConfig {
  clinic_name: string;
  clinic_timezone: string;
  providers: string[];
  voice: string;
  model: string;
  openai_configured: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  config: () => request<PublicConfig>("/config"),
  generateSummary: (sessionId: string) =>
    request<SummaryResponse>(`/sessions/${sessionId}/summary`, { method: "POST" }),
  listAppointments: () => request<Appointment[]>("/appointments"),
  userAppointments: (phone: string) =>
    request<Appointment[]>(
      `/users/${encodeURIComponent(phone)}/appointments?include_cancelled=true`,
    ),
};

export { API_BASE };
