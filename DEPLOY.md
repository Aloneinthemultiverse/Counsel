# Deploying Counsel

Counsel is a streaming FastAPI app. It needs:
- **Hindsight Cloud** (memory) — already cloud, set `HINDSIGHT_URL` + `HINDSIGHT_API_KEY`.
- **An LLM** — three options (see below).

## The LLM — three ways

1. **Host proxy via a public tunnel** (use *your* antigravity proxy)
   The deployed app can't reach `localhost:8080`. Expose it publicly:
   ```
   ngrok http 8080            # or: cloudflared tunnel --url http://localhost:8080
   ```
   Then set on the host: `LLM_BASE_URL=https://<your-tunnel>.ngrok-free.app`
   (Your machine + proxy must stay running.)

2. **A cloud LLM key in env** (simplest, always-on)
   ```
   LLM_PROVIDER=anthropic   LLM_BASE_URL=https://api.anthropic.com
   LLM_API_KEY=sk-ant-...    MODEL=claude-sonnet-4-6
   ```
   or OpenAI / Groq:
   ```
   LLM_PROVIDER=openai      LLM_BASE_URL=https://api.openai.com/v1
   LLM_API_KEY=sk-...        MODEL=gpt-4o
   ```

3. **Bring-your-own-LLM (per user, in the UI)**
   Each customer clicks **⚙ LLM** in the app and enters their own provider/URL/key/model.
   Nothing to configure at deploy time.

## Platform — Render or Railway (recommended), NOT Vercel

This app **streams** (SSE) and a whole-board debate can run 60–90s. Vercel's
serverless functions time out (10–60s) and are stateless, so the streaming
`@all` panel and saved conversations break there. A persistent server fits.

### Render (free tier)
1. Push `counsel/` to a GitHub repo.
2. Render → New → Web Service → connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn web:app --host 0.0.0.0 --port $PORT`
5. Add env vars: `HINDSIGHT_URL`, `HINDSIGHT_API_KEY`, and the LLM vars from above.
6. Deploy → you get a public URL.

### Railway
Same idea: `railway init` → add the env vars → it auto-detects the Procfile.

## Files in this repo for deploy
- `requirements.txt` — runtime deps (client only, not the heavy hindsight server)
- `Procfile` — start command with `$PORT`
- `runtime.txt` — Python version
- `personas/*.md` — the distilled board (committed so the deploy has advisors)

## Notes
- The board's banks live in **Hindsight Cloud**, so the deployed app shares the
  same memory as local — no migration needed.
- `.tmp/conversations.json` is local-only; on a fresh host, conversation history
  starts empty (the Hindsight memory persists regardless).
