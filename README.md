# Counsel — a board of advisors that remembers you

> Feed it your team's Slack. Get a board of AI advisors you can consult anytime — and they never forget.

Built for the **Vectorize Hindsight** hackathon. Counsel distills the real people in a Slack
export into AI advisors, gives each one a persistent memory bank, and lets you consult the board
in a live chat. They debate, reach a weighted decision, remember every decision you make, catch you
when you contradict yourself, build a profile of you, and even evolve their own views over time.

Most "AI with memory" projects build **one** agent that remembers **you**. Counsel builds a
**society of agents that remember each other** — a shared "boardroom" memory where advisors track
who said what, flag contradictions against the collective record, and trace whose advice drove a
decision.

## What it does

- **Build the board** — upload a Slack export (or use the sample) → it distills each person into an
  advisor with their real opinions and decision style.
- **Consult (chat)** — `@all` or `@advisor`; the board debates and reacts to each other by name.
- **Decide** — scores the whole discussion into a weighted decision (criteria × weight → winner).
- **Memory** — auto-remembers your decisions, catches contradictions, profiles you, advisors evolve,
  and a who-told-whom provenance graph.
- **Integrate** — an MCP server lets you consult the board from Claude Code / Cursor; bring-your-own-LLM.

## How memory works (Hindsight)

Each advisor is a **Hindsight bank** (their mind) plus a shared **boardroom** bank (collective memory).
Counsel uses `retain` (store + auto-extract typed facts), `recall` (TEMPR retrieval), `reflect`
(reason over memory — powers the profile and the evolution loop), and Hindsight's automatic
consolidation/freshness.

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
# set HINDSIGHT_URL, HINDSIGHT_API_KEY, and an LLM (see DEPLOY.md / .env.example)
python -m uvicorn web:app --port 8200
# open http://localhost:8200
```

LLM options (configurable in the UI under **⚙ LLM**, or via env): a local/Anthropic-style proxy,
or any OpenAI-compatible API (OpenAI, Groq, …).

## Layout

```
web.py                FastAPI backend (chat, decision, profile, evolve, graph, MCP info)
board.py              the memory engine (banks, recall/reflect, advisors, decisions)
mcp_server.py         MCP server — 6 tools for Claude Code / Cursor
web/index.html        the dark single-page UI
tools/                ingestion (slack_to_synth) + persona distillation
personas/             the distilled advisors
DEPLOY.md             hosting notes (Render/Railway, tunnels, LLM config)
```

## Deploy

See `DEPLOY.md`. The memory lives in Hindsight Cloud, so a deployed instance shares the same board.
