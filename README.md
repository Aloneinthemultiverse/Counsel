# Counsel — a board of advisors that remembers you

> Feed it your team's Slack. Get a board of AI advisors you can consult anytime — and they never forget.

Built for the **Vectorize Hindsight** hackathon. Counsel distills the real people in a Slack export
into AI advisors, gives each one a persistent memory bank (Hindsight), and lets you consult the board
in a live chat. They debate, reach a weighted decision, remember every decision you make, catch you
when you contradict yourself, build a profile of you, and evolve their own views over time.

**The wedge:** most "AI with memory" projects build *one* agent that remembers *you*. Counsel builds
a **society of agents that remember each other** — a shared "boardroom" memory where advisors track
who said what, flag contradictions against the collective record, and trace whose advice drove a
decision.

---

## Table of contents
- [File structure](#file-structure)
- [The full process, step by step](#the-full-process-step-by-step)
- [Functionality (every feature)](#functionality-every-feature)
- [Memory architecture (Hindsight)](#memory-architecture-hindsight)
- [API reference](#api-reference)
- [MCP server](#mcp-server)
- [Run it](#run-it)
- [Configuration](#configuration)

---

## File structure

```
counsel/
├── web.py                 FastAPI backend — all HTTP endpoints + SSE streaming chat
├── board.py               the engine — Hindsight memory, advisors, decisions, LLM
├── mcp_server.py          MCP server — exposes the board as 6 tools for Claude Code / Cursor
│
├── web/
│   └── index.html         the entire single-page UI (dark theme, no build step)
│
├── personas/              the distilled advisors (one Markdown doc each)
│   ├── maya.md  raj.md  tomas.md  aisha.md
│
├── tools/
│   ├── slack_to_synth.py  Slack export  →  per-person message assets
│   ├── distill_fanout.py  assets  →  a 5-facet persona doc (chunk → workers → reducers)
│   ├── distill.py         single-pass distiller (lighter alternative)
│   ├── quality_check.py   persona quality scorecard (verbatim/citations/length/facets)
│   ├── make_sample_export.py  generates a synthetic Slack export for testing
│   ├── build_lumio.py     one-shot: build the sample "Lumio startup" board
│   └── ask.py             CLI single-advisor consult (no server)
│
├── sample_slack_export.zip        synthetic startup team (uploadable test data)
├── houstondatavis_slack_export.zip  real public Slack export (uploadable test data)
│
├── requirements.txt       runtime deps (Hindsight client only, not the server)
├── Procfile               start command for Render/Railway
├── runtime.txt            Python version
├── DEPLOY.md              hosting + LLM/tunnel options
└── .env.example           required environment variables
```

### What each file does

| File | Responsibility |
|---|---|
| **`web.py`** | FastAPI app. Serves the UI and every `/api/*` endpoint: board state, upload/sample/build, streaming chat (SSE), weighted decision, profile, evolve, who-told-whom graph, per-advisor persona/memory, LLM config, MCP-info. Conversations persist to `.tmp/conversations.json`. |
| **`board.py`** | The brain. Wraps the Hindsight client (`hs()`), the LLM (`gen()`, swappable at runtime via `set_llm()`), and all logic: creating/seeding banks (`init`), recall, native `reflect`, an advisor's reply (`advisor_take`, `chat_reply`), @mention routing (`parse_targets`), auto-decision detection (`remember_from_message`), the user profile (`profile`), the evolution loop (`evolve`), the weighted decision (`session_decision`), and the devil's advocate. |
| **`mcp_server.py`** | A FastMCP stdio server exposing 6 tools that call `board.py`, so an AI coding agent can consult the board with the same shared memory. |
| **`web/index.html`** | The whole front end in one file — setup/upload screen, advisor sidebar with avatars, the boardroom chat (streaming + typing), decision scorecard, profile/evolve/graph modals, LLM settings, MCP connect panel. |
| **`tools/slack_to_synth.py`** | Ingestion. Reads a Slack export, groups substantive messages per person, filters noise, reconstructs threads, and writes synth-format assets. |
| **`tools/distill_fanout.py`** | The distillation pipeline (chunk → per-chunk workers → per-facet reducers → assemble), name-anchored and JSON-robust. |
| **`tools/quality_check.py`** | Scores each persona doc (verbatim leaks, citation density, length, facet coverage). |

---

## The full process, step by step

```
 Slack export (.zip)
        │
   ① INGEST  (tools/slack_to_synth.py)
        │   load_users() → read users.json OR org_users.json (enterprise)
        │   collect()    → group messages per person; drop noise (<25 chars,
        │                  "lol", "+1", joins, bots); reconstruct threads
        │                  (a reply gets a "[re: <parent>]" context prefix)
        │   write_assets()→ unique slug (from Slack handle, deduped);
        │                  writes raw-messages.jsonl + metadata.json
        ▼
   ② DISTILL  (tools/distill_fanout.py)  — one persona per selected person
        │   chunk the person's messages
        │   WORKERS  → each chunk → per-facet findings (claim + evidence)
        │             (3 retries + JSON salvage; name-anchored so the model
        │              never describes itself instead of the person)
        │   REDUCERS → one per facet → dedupe + synthesize, keep [#channel,date]
        │   assemble → persona.md: At a glance · priorities · opinions ·
        │              decision patterns · domain knowledge · network · known gaps
        ▼
   ③ GIVE EACH PERSONA A MEMORY  (board.init)
        │   create a Hindsight BANK per persona
        │     mission     = the advisor's worldview ("At a glance")
        │     disposition = how they argue (skepticism/literalism/empathy)
        │   retain the persona facets as seed memories
        │     → Hindsight auto-EXTRACTS prose into typed units
        │       (observation / experience / world)
        │   also create one shared BOARDROOM bank (collective memory)
        ▼
   ④ CONSULT  (chat)
        │   parse @mentions → route to one advisor or the whole board
        │   each advisor: RECALL own bank + boardroom (TEMPR) → reply
        │     (conversational, sees the running thread, can react to others)
        │   stream replies one-by-one over SSE (typing → message)
        │   RETAIN each reply to the advisor's bank + the boardroom
        ▼
   ⑤ MEMORY EFFECTS  (happen automatically as you talk)
        │   AUTO-MEMORY     → remember_from_message detects a decision in your
        │                     message and retains it to every bank
        │   CONTRADICTION   → an advisor recalls a past decision and flags
        │                     "CONTRADICTION:" if your new message reverses it
        │   PROFILE         → reflect() over the boardroom → a portrait of you
        │   EVOLVE          → each advisor reflect()s over its own bank and
        │                     updates its worldview (rewrites its persona +
        │                     bank mission)
        │   WHO-TOLD-WHOM   → trace boardroom memories: who contributed, whose
        │                     points are cited in decisions
        ▼
   ⑥ DECIDE  (session_decision)
            read the WHOLE conversation → identify the strategies argued →
            define weighted criteria → score each option 1-10 →
            compute weighted totals server-side → recommend a winner
```

---

## Functionality (every feature)

### Build the board
- **Upload a Slack export** (`.zip`) or **use the bundled sample** — the backend parses it, detects the people with enough substantive messages, and shows them with message counts.
- **Pick advisors → Build** — distills the chosen people and creates their memory banks. Building **wipes the previous board** so you always have a clean set.
- Handles real-world messes: noise filtering, **thread reconstruction**, **duplicate names** (unique slugs), and **enterprise exports** (`org_users.json`).

### Consult — the boardroom chat
- **`@all`** asks the whole board; **`@maya` / `@raj`** asks specific advisors.
- **Streaming** with per-advisor "…is typing" indicators.
- Advisors see the **whole running thread** (true conversation continuity) and **react to each other by name** in a second round.
- **Saved conversations** — every thread persists; reopen any past conversation from History.

### Decide — weighted decision
- **Conclude the session** → the chair reads the entire discussion and returns a **weighted decision matrix**: the strategies argued, scored across weighted criteria, with a clear winner. Totals are computed in code so the math is always correct.

### Memory
- **Auto-memory** — your decisions are remembered from natural conversation (no save button).
- **Contradiction detection** — flags the moment you reverse a past decision, citing it.
- **"What the board knows about you"** — a synthesized profile (via Hindsight `reflect`).
- **Evolve the board** — advisors reflect on the debates and update their own worldview.
- **Who-told-whom graph** — visual provenance: whose points flowed into the board's decisions.
- **Per-advisor view** — click an advisor for tabs: **Persona** (their distilled character) and **Memory** (their live Hindsight units, typed).

### Integrate
- **MCP server** — consult the board from Claude Code / Cursor (6 tools, same shared memory).
- **Bring-your-own-LLM** — keep the host LLM or plug in your own Anthropic / OpenAI / Groq API in the **⚙ LLM** panel; the key stays on the server.
- **Graceful degradation** — if the LLM is unreachable, advisors return a clear message instead of crashing.

---

## Memory architecture (Hindsight)

Each advisor is a **Hindsight bank** (their mind). A shared **boardroom** bank holds the collective
record. Counsel uses Hindsight's primitives directly:

| Primitive | How Counsel uses it |
|---|---|
| **retain** (+ extract) | Persona seed, every consultation, every decision are retained; Hindsight extracts prose into typed `observation` / `experience` / `world` units. |
| **recall** (TEMPR) | Before each reply, an advisor recalls relevant memory from its bank + the boardroom (semantic · BM25 · graph · temporal). |
| **reflect** | Powers the **profile** (reflect over the boardroom) and the **evolution loop** (each advisor reflects over its own bank, guided by its mission/disposition). |
| **consolidation / freshness** | Hindsight automatically dedups, tracks evidence, and ages memories (strengthening → stable → weakening → stale). |

**What goes in each bank**
- An advisor bank = ① **seed** (the distilled persona) + ② **consultations** (what they advised) + ③ **decisions** (what you committed to).
- The **boardroom** = your decisions + what every advisor said — which is what lets advisors remember each other and powers who-told-whom.

---

## API reference

| Method & path | Purpose |
|---|---|
| `GET /` | Serve the UI |
| `GET /api/board` | List advisors + memory counts |
| `POST /api/upload` | Parse an uploaded Slack `.zip` → detected people |
| `POST /api/sample` | Parse the bundled sample export → detected people |
| `POST /api/build` | Distill selected people + create banks (wipes old board) |
| `POST /api/ask` | Ask one advisor (`{slug, question}`) |
| `POST /api/team` | Ask the whole board (returns each take + flags) |
| `POST /api/chat/new` | Start a conversation |
| `GET /api/chats` | List saved conversations |
| `GET /api/chat/{cid}` | Fetch a conversation thread |
| `POST /api/chat/{cid}/send` | **SSE stream** — @mention-routed chat with typing + reactions |
| `POST /api/chat/{cid}/decision` | End-of-session weighted decision matrix |
| `POST /api/profile` | "What the board knows about you" (reflect) |
| `POST /api/evolve` | Advisors update their own worldviews (reflect) |
| `GET /api/graph` | Who-told-whom provenance data |
| `GET /api/persona/{slug}` | An advisor's distilled persona |
| `GET /api/memory/{slug}` | An advisor's live memory units |
| `GET /api/llm-config` · `POST /api/llm-config` · `POST /api/llm-reset` | Bring-your-own-LLM config |

---

## MCP server

`mcp_server.py` exposes the board as tools any AI coding agent can call:

| Tool | Purpose |
|---|---|
| `list_advisors` | the board members |
| `ask_advisor` | one advisor's take |
| `consult_board` | the whole board weighs in |
| `board_decision` | a weighted decision scorecard |
| `record_decision` | save a commitment to memory |
| `what_board_knows` | the board's profile of you |

Add to Claude Code:
```
claude mcp add counsel -- python /path/to/counsel/mcp_server.py
```

---

## Run it

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # (Windows)  or  .venv/bin/pip
cp .env.example .env                                # then fill in your keys
python -m uvicorn web:app --port 8200
# open http://localhost:8200
```

You'll also need an LLM endpoint (see below) and a Hindsight Cloud key.

## Configuration

Set in `.env` (or in the UI under **⚙ LLM**):

```
LLM_PROVIDER=anthropic            # anthropic | openai
LLM_BASE_URL=http://localhost:8080  # a local proxy, or a cloud endpoint
LLM_API_KEY=proxy                 # or sk-ant-… / sk-…
MODEL=claude-sonnet-4-6           # or gpt-4o / llama-3.3-70b-versatile

HINDSIGHT_URL=https://api.hindsight.vectorize.io
HINDSIGHT_API_KEY=hsk_your_key_here
```

See **`DEPLOY.md`** for hosting (Render/Railway) and the tunnel/LLM options. The board's memory lives
in Hindsight Cloud, so a deployed instance shares the same advisors and history as local.
