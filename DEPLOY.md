# Deployment guide

This project uses a **two-host** setup because the backend needs persistent
WebSocket connections that Vercel's serverless functions can't keep alive.

| Layer | Host | URL pattern |
|---|---|---|
| Frontend (Next.js) | Vercel | `https://mykare-voice.vercel.app` |
| Backend (FastAPI + WebSocket) | Render | `https://mykare-backend.onrender.com` |

The user-facing demo URL is the **Vercel one**.

---

## 1. Deploy backend to Render (do this first)

The backend URL is what the frontend needs, so it must come up first.

1. Go to <https://dashboard.render.com/blueprints> and click **"New Blueprint Instance"**.
2. Connect your GitHub account if you haven't already.
3. Select the `mykare-voice-ai` repo.
4. Render will detect `render.yaml` at the root and propose creating
   `mykare-backend` (web service, Python, free).
5. **Set the secret env vars** when prompted:
   - `OPENAI_API_KEY` → your real OpenAI key (with Realtime API access)
   - `CORS_ORIGINS` → Vercel URL once you have it (you can come back and edit
     this after step 2). For the first deploy, use `*` temporarily.
6. Click **"Apply"**. Render builds and deploys (~3–5 min on free tier).
7. When it's live, copy the URL (e.g. `https://mykare-backend.onrender.com`).
   Test it:
   ```
   curl https://mykare-backend.onrender.com/health
   # {"status":"ok","openai_configured":true}
   ```

> ⚠️ **Free-tier note:** Render free instances sleep after 15 min of inactivity
> and take ~30s to wake up on first request. The WebSocket *will* time out the
> first time after a sleep — refresh and try again. For demos, hit `/health`
> just before the recording to wake it up.

---

## 2. Deploy frontend to Vercel

```bash
cd frontend
vercel login          # one-time
vercel link           # link to a new Vercel project
vercel --prod         # production deploy
```

Once deployed, set two env vars in the Vercel dashboard
(`Project → Settings → Environment Variables`) for **Production**:

- `NEXT_PUBLIC_API_URL` → `https://mykare-backend.onrender.com`
- `NEXT_PUBLIC_WS_URL` → `wss://mykare-backend.onrender.com/ws/voice`

Then redeploy:

```bash
vercel --prod
```

> 💡 The browser will ONLY allow microphone access on `https://` URLs.
> Vercel handles HTTPS automatically.

---

## 3. Wire CORS

Once the Vercel URL is finalized, go back to Render →
`mykare-backend → Environment` and update:

- `CORS_ORIGINS` → `https://mykare-voice.vercel.app` (your real Vercel URL)

Render auto-redeploys. Done.

---

## 4. Smoke test

1. Visit your Vercel URL.
2. Top-left should say "Mykare Health" with no amber warning.
3. Click the mic, allow microphone access, wait ~1s for Aria's greeting.
4. Have a 2-3 turn conversation. Tool cards should appear. End with "bye".
5. Summary modal pops up.

---

## Cost while running on free tiers

- **Render free** — $0. Spins down when idle.
- **Vercel hobby** — $0.
- **OpenAI Realtime API** — pay-per-use, ~$0.05–$0.10 per 2-min call.
- **Total demo cost** for evaluators clicking around: typically **<$1/day**.
