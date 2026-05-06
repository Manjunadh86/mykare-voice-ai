# Mykare Voice AI — Aria

A production-grade web voice agent that talks, understands, and **takes real actions** for a healthcare clinic. Aria is a friendly AI receptionist who books, modifies, cancels, and looks up appointments — entirely by voice — with a live talking avatar, real-time tool-call visualization, and an end-of-call summary.

> Built for the Mykare Voice AI Engineer task.

---

## ✨ Highlights

| Area | What it does |
|---|---|
| 🎤 **Voice I/O** | OpenAI Realtime API (gpt-4o-realtime). Server-VAD turn-taking, sub-second latency, natural speech (Whisper transcription + neural TTS). |
| 🛠 **7 tools, all real DB-backed** | `identify_user`, `fetch_slots`, `book_appointment`, `retrieve_appointments`, `cancel_appointment`, `modify_appointment`, `end_conversation` |
| 🛡 **Double-booking prevention** | Partial unique index in SQL (`(provider, slot_start) WHERE status='confirmed'`) — race-safe at the DB layer, not just app layer. |
| 👤 **Lip-sync avatar** | Custom SVG avatar driven by audio amplitude — zero external service, zero lag, no extra API key. Designed to be swappable for Tavus/Beyond Presence. |
| 📺 **Live tool UI** | Every tool call appears on screen as it happens (started / completed / failed) with arguments and results. |
| 📝 **Auto summary** | At call end, a structured JSON summary is generated in <10s: extracted name/phone/intent/preferences, actions taken, follow-ups, and the user's full appointment list. |
| 💸 **Cost tracking** | Live cost meter (audio in/out minutes + token counts) plus per-session totals saved to DB. |
| 🧪 **End-to-end tested** | Tool layer has a deterministic test that verifies booking, double-booking prevention, modify, cancel, retrieve. |
| 🐳 **One-command deploy** | `docker-compose up` runs the whole stack. Render + Vercel configs included. |

---

## 🏛 Architecture

```
                    ┌──────────────────────────────────────┐
                    │           Browser (Next.js)         │
                    │  ┌─────────┐  ┌──────────────────┐  │
   🎤 mic ──────────┤  │ AudioWorklet → 24kHz PCM16    │  │
                    │  │     RealtimeVoiceClient       │  │
   🔈 speaker ◀─────┤  │  (queue+playback, lip-sync)  │  │
                    │  └─────────┬────────────────────┘  │
                    └────────────│───────────────────────┘
                                 │  WebSocket (JSON)
                                 ▼
                    ┌──────────────────────────────────────┐
                    │        FastAPI backend              │
                    │  ┌─────────────────────────────────┐ │
                    │  │ RealtimeBridge (proxy)         │ │
                    │  │   • forwards audio frames     │ │
                    │  │   • catches function_calls    │ │
                    │  │   • runs tools against DB     │ │
                    │  │   • injects results back      │ │
                    │  │   • streams transcript +      │ │
                    │  │     tool events to browser    │ │
                    │  └────────────┬────────────────────┘ │
                    │               │ WebSocket            │
                    │               ▼                      │
                    │   OpenAI Realtime API (gpt-4o)       │
                    └──────────────┬───────────────────────┘
                                   │ async sessions
                                   ▼
                          ┌────────────────┐
                          │  SQLite (DB)   │
                          │  users         │
                          │  appointments  │
                          │  sessions      │
                          │  messages      │
                          │  tool_calls    │
                          └────────────────┘
```

### Why a proxy and not direct browser → OpenAI?

1. **Security.** The OpenAI API key never leaves the server.
2. **Tool execution.** Function calls land on the backend so they can mutate the DB safely.
3. **Persistence.** Every utterance + tool call is logged for audit, replay, and the summary step.
4. **Cost tracking.** Per-session token + audio metering are aggregated server-side.

### Why OpenAI Realtime instead of a 4-layer stack (Deepgram → LLM → Cartesia → ...)?

The task PDF lists those as *suggestions*. OpenAI Realtime is functionally equivalent (Whisper STT + GPT-4o + neural TTS + server-VAD) but in **one round trip**, giving us the <3-5s latency requirement comfortably (typically 700–1500 ms total). The architecture is modular, so swapping in Deepgram + Cartesia later means changing only the `services/realtime_proxy.py` file.

---

## 🚀 Quick start (local)

### Prerequisites
- Python **3.11** (we tested 3.11.x; pydantic-core needs prebuilt wheels)
- Node **18+**
- An **OpenAI API key** with Realtime API access (`gpt-4o-realtime-preview-*`)

### 1. Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and put your real OPENAI_API_KEY

uvicorn app.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for the interactive Swagger UI.

### 2. Frontend

```bash
cd frontend
npm install

cp .env.example .env.local
# Defaults are correct for local dev

npm run dev
```

Open `http://localhost:3000`, click the mic button, **allow microphone access**, and start talking to Aria.

### 3. (Optional) Docker

```bash
# from repo root
cp backend/.env.example backend/.env
# add your OPENAI_API_KEY

docker-compose up --build
```

Backend on `:8000`, frontend on `:3000`.

---

## 🎬 Try this script

> "Hi, I'd like to book an appointment.
> My phone is **555-123-9876**, name is **Alex Doe**.
> What slots do you have **tomorrow** with **Dr. Khan**?"
>
> *(Aria reads 3-4 slots)*
>
> "**The 11:30** one works. It's a follow-up for a fever."
>
> *(Aria books and confirms)*
>
> "Actually, can you **move it to 2 PM** instead?"
>
> *(Aria reschedules)*
>
> "Great. **Show me my appointments.**"
>
> *(Aria lists)*
>
> "Cool, **cancel that one**."
>
> *(Aria cancels)*
>
> "Thanks, **bye!**"
>
> *(Aria says farewell, hangs up, summary modal pops open)*

You should see, in real time:
- Every utterance in the transcript
- Tool cards for `identify_user`, `fetch_slots`, `book_appointment`, `modify_appointment`, `retrieve_appointments`, `cancel_appointment`, `end_conversation`
- The appointments panel updating after each mutation
- The cost meter ticking up in the header
- A summary modal at the end with: extracted name/phone/intent, actions taken, all appointments, and total cost

---

## 🧪 Verify everything works

A single command runs **all 8 categories** of automated checks against an isolated tmp DB and an ephemeral live server — no OpenAI key needed:

```bash
backend/.venv/bin/python scripts/verify.py
```

Expected output:

```
1. Database schema
  PASS  init_db creates 5 tables + partial unique index

2. Tool layer end-to-end (all 7 tools)
  PASS  identify → fetch → book → double-book-rejected → modify → cancel → end

3. Edge cases
  PASS  phone normalization (7 cases incl. invalid)
  PASS  natural-language date parsing (7 phrases)

4. Cost arithmetic
  PASS  1m audio in + 0.5m out + 1k+2k tokens = $0.225

5. Tool catalog
  PASS  7 schemas, 7 executors, all valid JSON-Schema

6. Summary fallback (no OpenAI key)
  PASS  structured fallback summary populated from tool log

7. Live HTTP/WebSocket server
  PASS  uvicorn serves all routes + WS handshake works

✓ 8/8 checks passed
```

You can also run just the tool-layer test directly:

```bash
cd backend && PYTHONPATH=. .venv/bin/python tests/test_tools.py
```

### Frontend verification

```bash
cd frontend
npx tsc --noEmit          # type-check
npm run lint              # eslint (next/core-web-vitals)
npm run build             # production build
```

All three pass cleanly.

### What automated tests can't cover

These require a real OpenAI key + a real browser and have to be tested manually:

| What | How to verify |
|---|---|
| Microphone capture & PCM streaming | Open `http://localhost:3000` → click mic → speak → watch the transcript update |
| Avatar lip sync | Watch the avatar's mouth open/close while Aria is speaking |
| Real voice conversation | Have a 5-turn dialogue with Aria |
| LLM-generated structured summary | Hang up → verify the summary modal includes name, intent, actions |

---

## 📚 API reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness probe + reports `openai_configured` |
| `/config` | GET | Public clinic config used by the frontend at boot |
| `/ws/voice` | WS | Bidirectional voice channel (browser ↔ backend ↔ OpenAI) |
| `/sessions` | GET | List recent sessions |
| `/sessions/{id}` | GET | Full session detail (messages, tool calls, appointments) |
| `/sessions/{id}/summary` | POST | Generate (or regenerate) the summary |
| `/users` | GET | List all users |
| `/users/{phone}/appointments` | GET | A user's appointments (incl. cancelled) |
| `/appointments` | GET | All appointments (admin-style view) |

The interactive OpenAPI docs live at `/docs`.

---

## 🛠 Tool catalog

All seven tools are defined in `backend/app/tools.py` with JSON schemas the model sees, and Python executors that hit the DB.

| Tool | Required args | Notes |
|---|---|---|
| `identify_user` | `phone` (+ optional `name`) | The phone number is the unique identifier. Auto-creates if new. |
| `fetch_slots` | `date` (+ optional `provider`) | Generates the day's slot grid (9–6, 30 min) and marks taken ones. |
| `book_appointment` | `phone`, `slot_start`, `provider` | Race-safe via partial unique index. Friendly error on conflict. |
| `retrieve_appointments` | `phone` | Returns all confirmed (or include cancelled). |
| `cancel_appointment` | `phone`, `appointment_id` | Soft cancel (status flag), so history is preserved. |
| `modify_appointment` | `phone`, `appointment_id`, `new_slot_start` (+ `new_provider`) | Atomic reschedule with conflict check. |
| `end_conversation` | `farewell` | Frontend disconnects after the assistant finishes the farewell. |

---

## 🔐 Security notes

- The OpenAI API key lives **only** in `backend/.env`. It is never sent to or visible from the browser.
- CORS is locked down via `CORS_ORIGINS` env var.
- WebSocket frames are JSON-only; binary forwarding is disabled.
- SQLite path is configurable; for production swap to Postgres by changing `DATABASE_URL` (no code changes needed).

---

## 💸 Cost model

Cost tracking is computed live and saved on each `Session`:

```
audio_in_cost  = audio_input_min  × $0.06
audio_out_cost = audio_output_min × $0.24
text_in_cost   = (text_in_tokens  / 1k) × $0.005
text_out_cost  = (text_out_tokens / 1k) × $0.020
```

Defaults match OpenAI's published Realtime API pricing as of the build date. Override via `COST_*` env vars.

A typical 2-minute booking call costs **~$0.05–$0.10**.

---

## 🌐 Deployment

### Backend → Render

The `backend/render.yaml` blueprint is ready to import. Set `OPENAI_API_KEY` and `CORS_ORIGINS` as secrets in the Render dashboard.

### Frontend → Vercel

```bash
cd frontend
vercel deploy
```

Set the env vars `NEXT_PUBLIC_API_URL` (e.g. `https://mykare-backend.onrender.com`) and `NEXT_PUBLIC_WS_URL` (e.g. `wss://mykare-backend.onrender.com/ws/voice`) in the Vercel project settings.

> ⚠️ Microphone capture **requires HTTPS** in production browsers. Both Vercel (`https://`) and Render (`wss://`) handle this for you out of the box.

---

## 🧠 Edge cases handled

- **Mis-transcribed phone numbers** → normalizer strips non-digits, requires ≥7 digits.
- **Natural-language dates** ("tomorrow", "next Friday", "in 3 days") → custom resolver before falling back to `dateutil`.
- **Race-condition double-booking** → partial unique SQL index + `IntegrityError` catch + friendly retry message.
- **Provider name fuzzy match** → "Khan" → "Dr. Aisha Khan".
- **Mid-conversation provider switch on reschedule** → supported via `new_provider`.
- **Tool failure** → returned to the model as a structured error message that the model gracefully apologizes for and retries.
- **Network drop** → both sockets close cleanly, summary is still generated from whatever was captured.
- **Missing OpenAI key** → backend falls back to a deterministic rule-based summary so the UI never breaks during dev.

---

## 📁 Project layout

```
mykare/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app + lifespan
│   │   ├── config.py                # pydantic-settings
│   │   ├── database.py              # async SQLAlchemy
│   │   ├── models.py                # User, Appointment, Session, Message, ToolCallLog
│   │   ├── schemas.py               # Pydantic response models
│   │   ├── tools.py                 # 7 tool schemas + executors
│   │   ├── routers/
│   │   │   ├── voice.py             # /ws/voice
│   │   │   ├── sessions.py          # /sessions/* + summary
│   │   │   └── appointments.py      # /users + /appointments
│   │   ├── services/
│   │   │   ├── realtime_proxy.py    # OpenAI Realtime WebSocket bridge
│   │   │   └── summary.py           # End-of-call structured summary
│   │   └── utils/time_utils.py      # date parsing, slot math, phone normalize
│   ├── tests/test_tools.py          # E2E tool test
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── render.yaml
│   └── .env.example
├── frontend/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                 # The whole orchestration lives here
│   │   └── globals.css
│   ├── components/
│   │   ├── Avatar.tsx               # SVG avatar w/ amplitude lip-sync
│   │   ├── Transcript.tsx
│   │   ├── ToolCallFeed.tsx
│   │   ├── CallSummary.tsx
│   │   ├── AppointmentsPanel.tsx
│   │   └── CostMeter.tsx
│   ├── lib/
│   │   ├── realtime-client.ts       # Audio capture + WS + playback queue
│   │   └── api.ts                   # REST client
│   ├── public/worklets/
│   │   └── recorder-processor.js    # AudioWorklet 48k→24k PCM16
│   ├── package.json
│   ├── Dockerfile
│   ├── vercel.json
│   └── .env.example
├── docker-compose.yml
└── README.md
```

---

## 🗺 Future enhancements

- Drop-in **Tavus / Beyond Presence** photoreal avatar (the SVG component is a single-file swap).
- **Postgres + Alembic** migrations (just change `DATABASE_URL`).
- **SMS / email** confirmation via Twilio + Resend after `book_appointment` succeeds.
- Multi-tenant clinic support (subdomain routing, per-clinic providers).
- **Wav2Lip** server-side rendering for true phoneme-level lip sync (when latency budget allows).

---

## 📝 License

MIT — built for evaluation purposes.
