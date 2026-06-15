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

📖 **Read the deep dive:** [I gave a room of AI agents one shared memory — and they started arguing with each other](https://medium.com/@aerospacesujitnarrayan/i-gave-a-room-of-ai-agents-one-shared-memory-and-they-started-arguing-with-each-other-b4da304ca893)

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

## Inside the distillation — how it digests a person

A single person can have hundreds of messy Slack messages. You can't just hand them all to one
model and ask "who is this person?" — it's too much, too noisy, and the result is shallow. So
Counsel uses a **fan-out: many readers, then five editors.**

### Step 1 — Chunk
The person's substantive messages are split into **chunks** (~100 messages each). Chunking is what
lets the pipeline handle *any* volume — a power-user with thousands of messages just becomes more
chunks; nothing is truncated.

### Step 2 — Workers read each chunk (the note-takers)
Every chunk goes to a **worker** (one LLM pass). The worker doesn't write the profile — it only
takes **notes**. It reads the chunk through **all five facets at once** and emits structured findings:

```json
[
  {"facet": "priorities", "claim": "Pushes for shipping fast over polish",
   "evidence": [{"channel": "product", "date": "2024-03-04"}]},
  {"facet": "decisions",  "claim": "Won't greenlight a build without a validated spec",
   "evidence": [{"channel": "eng", "date": "2024-03-04"}]}
]
```

Each finding is a one-line claim **plus a pointer to where it was said** (channel + date) — so every
claim stays traceable. Workers are:
- **name-anchored** — told the subject is a specific human ("extract evidence about *Maya*"), so the
  model never accidentally describes itself or an AI instead of the person;
- **JSON-robust** — up to 3 retries with salvage parsing if the model returns malformed JSON;
- **quote-safe** — instructed to describe patterns in indirect prose, never paste raw message text.

### Step 3 — The five facets (the lenses every worker uses)
| # | Facet | What it captures |
|---|---|---|
| 1 | **Strategic priorities & recurring themes** | what they push for / dismiss repeatedly |
| 2 | **Specific opinions & positions** | concrete stances they champion or oppose |
| 3 | **Decision-making patterns** | *how* they reason — the questions they ask, the bar they set |
| 4 | **Domain knowledge** | topics where they bring real working knowledge |
| 5 | **Network & operational context** | who they work with, projects, external entities |

### Step 4 — Five reducers digest the notes (the editors)
Now there's a big pile of notes from all the workers. **One reducer per facet** (five editors) takes
over. Each reducer:
1. receives **every worker's notes tagged with its facet** (e.g. the "decisions" editor gets all
   decision-pattern findings from every chunk),
2. **dedupes** — the same claim seen across many chunks becomes one claim with merged evidence (and
   "seen many times = a pattern; once = a hint"),
3. **synthesizes** a clean Markdown section, keeping a `[#channel, date]` citation on each claim.

So the workers spread *wide* (cover every message), and the five reducers go *deep* (one polished,
non-redundant section per facet).

### Step 5 — Assemble the persona
The orchestrator stitches the five sections together and adds:
- **At a glance** — a 2–4 sentence synthesis across all facets (this becomes the advisor's bank
  *mission* — its worldview),
- **Known gaps** — topics the messages are silent on (so the advisor is honest about what it doesn't know),
- **frontmatter** — name, message/channel counts, method, timestamp.

The result is `personas/<slug>.md`. **`tools/quality_check.py`** then scores it — verbatim-leak sweep,
citation density, facet coverage, length — so you can see the persona is grounded, not invented.

> **In one line:** chunk the messages → many workers take per-facet notes with receipts → five
> reducers dedupe and write one section each → assemble into a cited persona → seed it into a
> Hindsight bank.

---

## Inside memory — the read / write flow

Once an advisor has a bank, every interaction either **writes** to memory or **reads** from it.
Here's exactly what happens.

### Writing memory (retain)
Three things get retained, and Hindsight **extracts** each into multiple typed units (a paragraph
becomes many `observation` / `experience` / `world` facts):

| When | What's written | Where |
|---|---|---|
| At build (`board.init`) | the distilled persona facets (the seed identity) | the advisor's bank |
| Every reply (`stamp`) | "On <date> the user asked … I advised …" | the advisor's bank |
| Every reply (`board_write`) | "<Advisor> said: …" | the shared **boardroom** |
| You state a decision (`remember_from_message`) | "DECISION by the user: …" | **every** bank + boardroom |

The decision-detection is itself a tiny LLM classification: each message you send is checked — *does
this state a commitment?* If yes, it's retained as a decision (this is what makes the contradiction
catch feel emergent — you never press "save").

### Reading memory (recall) — what happens before an advisor speaks
```
advisor_take() / chat_reply():
   mem_own   = recall(advisor_bank, query)          # what *I* know & have said
   mem_board = recall(BOARDROOM,   query)            # decisions + what others said
   prompt    = persona(mission) + mem_own + mem_board + running_thread + question
   reply     = LLM(prompt)
```
- **`recall` uses TEMPR** — it blends semantic (meaning), BM25 (exact keywords), graph (entity
  links), and temporal (recency) to fetch only the relevant memories, not the whole history. That's
  what keeps it grounded *and* scalable as a bank grows to hundreds of units.
- **Two context layers feed every reply:** the **running thread** (short-term, this conversation,
  held in `web.py`) and the **banks** (long-term, across all sessions, in Hindsight). The thread is
  why follow-ups are coherent; the banks are why it remembers last week.
- Recalling the **boardroom** is what lets advisors reference *each other* ("building on Raj's
  point…") and catch you contradicting a decision the *group* recorded.

### Reasoning over memory (reflect)
Two features don't just recall — they ask Hindsight to **reason**:
- **Profile** → `reflect(boardroom, "portrait of the user…")` — Hindsight finds the relevant
  memories itself and synthesizes a portrait.
- **Evolve** → `reflect(advisor_bank, "has your view shifted?…")` — reflection runs through the
  bank's *mission/disposition*, so the advisor's worldview shapes the answer; the result rewrites
  its persona + bank mission.

### Self-maintenance (consolidation / freshness)
Hindsight runs this on its own in the background: it **dedups** overlapping facts, tracks
**evidence/proof counts**, and computes a **freshness trend** (strengthening → stable → weakening →
stale) so old, contradicted, or unused memories decay. Counsel doesn't manage any of this — it's why
the memory *self-improves* the more you use it.

### Provenance (who-told-whom)
`/api/graph` reads the boardroom's memories and counts, per advisor, how many points they
**contributed** vs how many are **cited in decisions** — turning the collective memory into a flow
graph: advisor → boardroom → decision.

> **In one line:** writes go to a per-advisor bank + a shared boardroom (auto-extracted into typed
> facts); reads use TEMPR recall to pull only what's relevant; `reflect` reasons over it for the
> profile and evolution; Hindsight consolidates and ages everything automatically.

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
