# I gave a room of AI agents one shared memory — and they started arguing with each other

### A deep dive into Counsel: how I turn a team's Slack into a board of advisors that remember everything, push back on each other, and change their own minds.

---

I typed one question into a chat box — *"should we ship the dashboard next week to hit the deal, or hold to test it?"* — and four advisors answered in turn.

Maya pushed to ship: it's the one feature the customer asked for. Raj said the instrumentation wasn't ready and called Maya's timeline *"a wish, not a plan."* Tomas backed Raj with a number — *"where is X"* support tickets were 34% of the dashboard's volume. Aisha cut in last: we'd burned two accounts shipping half-finished before, and a third would cost more than the deal.

Then they did the thing I actually built this for. Maya turned to Raj by name and conceded the gate — *"fine, hooks green by midnight or we hold."* Raj agreed but flagged a dependency. They converged on a plan none of them had walked in with.

None of those four were in the room. They aren't people anymore, in the way that matters here — they're advisors I built by feeding a team's Slack history into a system I call **Counsel**. Each one is distilled from a real person, and the whole thing runs on persistent memory, so they remember what I told them last week and what each *other* said last session.

This is a long, honest write-up of how it works — the part that turns messy chat logs into an advisor worth listening to, and the part that gives a *room* of agents one memory instead of a single assistant remembering a single user. The second part is where it got genuinely interesting, and where I leaned hard on [Hindsight, an open-source agent memory system](https://github.com/vectorize-io/hindsight) so I could spend my time on orchestration instead of rebuilding retrieval from scratch.

---

## 1. What Counsel is

Counsel does one thing well: you give it a team's Slack history, and you get back a board of advisors you can consult any time, in a chat that feels like a group thread.

The premise is that a team's best judgment is already written down — it's just buried. Years of how your sharpest people think, argue, and decide sit dead in Slack history. The people who made the great calls aren't in the room when you need them, and you can't schedule a meeting every time you want their take. Counsel turns that latent history into something you can actually query.

What you get is not a generic "AI assistant." Each advisor carries a specific worldview pulled from a specific person: Maya optimizes for shipping speed and enterprise retention; Raj front-loads reliability and won't greenlight a build without a validated spec; Tomas wants instrumentation and a measurable success criterion before anyone touches code; Aisha treats user trust as a near-absolute constraint. Ask them the same question and you get four different, *consistent* answers — and an argument.

And it remembers. Every decision you make is filed. Every consultation is retained. So the board isn't a stateless oracle you re-explain yourself to — it's something that accumulates a model of your situation, and of you.

## 2. How it works, end to end

The flow has four stages. Three are a one-time build; the last is where the system lives.

```
 Slack export (.zip)
      │
  ① INGEST    parse the export, group messages per person, strip noise
      │
  ② DISTILL   turn each person into a persona (beliefs + decision style)
      │
  ③ SEED      give each persona its own memory bank + one shared "boardroom"
      │
  ④ CONSULT   @all or @maya → they reply, debate, react → a weighted decision
```

In practice it looks like this. You drop a Slack export into the build screen; it detects the people with enough substantive history and shows them with message counts. You pick who becomes an advisor and hit build. A couple of minutes later you're in a chat. You type `@all should we cut the analytics feature to hit the deadline?` and the advisors stream in one at a time, each with a "…is typing" beat, each pushing back on whoever they most disagree with. When the argument has run its course, you ask the board to *conclude* — and it scores the entire discussion into a weighted decision matrix: the strategies that were argued, scored across criteria it weighted itself, with a recommended winner.

The surrounding plumbing is deliberately unremarkable: a FastAPI backend that streams the chat over SSE, a single HTML file for the UI, a small engine module, and an MCP server so I can consult the board from inside my editor without leaving my code. The interesting parts — distillation and memory — sit underneath, and they're the rest of this article.

## 3. The internal working — turning a person into an advisor

Here's the core problem: real Slack is a mess. People write *"deploying now"*, *"build's broken"*, *"lol"*, *"+1"*, and half-thoughts buried three replies deep in a thread. You cannot hand all of that to a model and ask "who is this person?" — it's too much, too noisy, and you get a horoscope back.

So I fan it out — **many readers, then a few editors.**

```
person's substantive messages
   → chunk into ~100-message pieces
   → WORKERS:  each chunk → notes across 5 lenses (claim + where it was said)
   → REDUCERS: one per lens → dedupe all notes → write one clean section
   → ASSEMBLE: 5 sections + a summary + an honest "what I don't know" list
   = an advisor (a cited persona doc)
```

### Step 1 — Chunk

The person's messages are split into chunks of around a hundred. Chunking is what lets this handle any volume — a power user with thousands of messages just becomes more chunks. Nothing gets truncated, which matters, because the interesting people are usually the chatty ones.

### Step 2 — Workers take notes

Each chunk goes to a worker pass. A worker doesn't write anything final — it reads the chunk through five lenses at once (priorities, opinions, decision patterns, domain knowledge, network) and emits structured findings. Each finding is a one-line claim plus a pointer to where it was said:

```python
[
  {"facet": "decisions",
   "claim": "Won't greenlight a build without a validated spec and a prototype",
   "evidence": [{"channel": "product", "date": "2024-03-04"}]},
  {"facet": "priorities",
   "claim": "Treats shipping speed and enterprise retention as the deciding lens",
   "evidence": [{"channel": "strategy", "date": "2024-03-05"}]}
]
```

Three things make this survive real data:

- **Name-anchoring.** The worker is told the subject is a specific human — *"extract evidence about Maya"* — because without it, a model handed a chunk of technical chat will happily start describing *itself* or "an AI assistant" instead of the person. I learned that one the hard way; one early run produced a persona that opened "Antigravity is an agentic coding assistant built by…" It was describing the model, not Maya.
- **JSON robustness.** Models return malformed JSON often enough that I retry up to three times and salvage individual objects out of a broken array before giving up.
- **Quote-safety.** Workers describe patterns in indirect prose and never paste raw message text, so the persona captures *substance, not voice*.

### Step 3 — Reducers digest the notes

Now there's a big pile of notes from every chunk. One reducer per lens — five editors — takes over. The decisions reducer receives *every* decision-note from *every* chunk, dedupes them (a claim seen five times is a pattern; seen once is a hint, and it says so), merges the evidence, and writes one clean section with citations intact. Workers spread *wide* so nothing is missed; reducers go *deep* so nothing is redundant.

### Step 4 — Assemble

The orchestrator stitches the five sections together and adds a two-to-four sentence "At a glance" summary, an honest "Known gaps" list of what the messages are silent on, and frontmatter. The result is a persona document, and a separate quality pass scores it — verbatim-leak sweep, citation density, facet coverage, length — so I can see it's grounded, not invented.

> Every claim in a persona traces back to a real message. When Maya argues against cutting analytics, it's not because a model decided founders like analytics — it's because the real Maya said so, in `#product`, on a date I can point to.

### The honest limit

This is also where the system has a constraint I'd rather state than hide. Pure ops chatter — *"deploying now", "fixed the timeout"* — paints a great picture of what someone *knows*, but a thin one of how they *judge*. People who argue and decide in Slack make rich advisors; people who only post status updates make shallow ones. Garbage in, thin persona out — and the distiller is honest enough to tell you when there isn't enough signal rather than fabricate one.

## 4. The memory layer — the part I actually got wrong first

A persona is static. What makes an advisor feel alive is memory, and memory is where I made my most useful mistake.

My first instinct was a single memory store for the whole board. It's the obvious move and it's wrong. If Maya and Raj write to the same memory, they stop being distinct advisors — their accumulated reads blend into mush. But if they're completely isolated, they can't reference each other, and you can't ask "what does the *board* think we already decided?"

So memory has **two scopes**, and that one decision shaped the rest of the system:

- a **private bank per advisor** — what *they* know, believe, and have said, and
- a **shared boardroom bank** — your decisions, plus what *every* advisor has said.

### Banks, missions, and typed facts

Hindsight calls these partitions "banks." Spinning one up is cheap, which is the whole reason I could afford to give every advisor their own. When I create a bank I don't store the raw chat — I store the distilled persona and let the memory layer extract typed facts out of the prose:

```python
c.create_bank(
    bank_id=f"advisor-{slug}",
    name=f"{name} (advisor)",
    mission=f"You are {name}. Your worldview: {glance}",   # steers reasoning later
    disposition_skepticism=4, disposition_literalism=3, disposition_empathy=2,
)
for section in persona_facets(doc):
    c.retain(bank_id=f"advisor-{slug}", content=section)
```

Two details matter here. The `mission` field isn't metadata — it's the advisor's worldview, and it later steers how the memory layer reasons on their behalf. And `retain` doesn't just dump text; Hindsight extracts each paragraph into multiple typed memory units — observations, experiences, world facts — which I get to query later without ever having designed a schema. One seeded persona becomes dozens of atomic, searchable facts. For the conceptual background on why typed, mission-aware memory beats a vector store with a prompt stapled on top, Vectorize's explainer on [what agent memory actually is](https://vectorize.io/what-is-agent-memory) is the clearest version I've read.

### How a single reply gets built

When an advisor speaks, the reply is assembled from both memory scopes plus the live thread — what I know, what the room remembers, and the conversation so far:

```python
def advisor_take(c, slug, question):
    mem_own   = recall(c, slug, question)              # what I know and have said
    mem_board = recall_bank(c, "boardroom", question)  # decisions + what others said
    return gen(persona(slug) + mem_own + mem_board + thread + question)
```

`recall` is the load-bearing call, and it's a real retrieval problem I was glad not to hand-roll. It doesn't dump the bank into the prompt — it pulls only what's relevant to the question, blending semantic similarity, exact keyword match, entity-graph relationships, and recency. As a bank grows to hundreds of units across many sessions, that blend is the difference between a grounded prompt and one that falls over. The retrieval model is documented well in the [Hindsight docs](https://hindsight.vectorize.io/); the short version is that it scales without me thinking about it.

Two more things fall out of this design. There are **two context layers** in every reply — the live thread (short-term, this conversation) and the banks (long-term, across all sessions). The thread is why follow-ups are coherent; the banks are why it remembers last week. And recalling the **boardroom** is what makes the advisors a *group*: it's how Maya can build on Raj's point from a past session, and how the board can catch me reversing a decision the *collective* recorded.

### Reasoning over memory, not around it

For a while I did all the synthesis myself: recall a pile of memories, then prompt my own model to summarize them. It worked, but it meant I was using the memory system as a vector store with my own brain bolted on. The features that needed real synthesis got noticeably better when I handed the reasoning back to the memory layer's `reflect`, which finds the relevant memories itself and reasons through the bank's mission:

```python
def profile(c):
    return c.reflect(
        bank_id="boardroom",
        query="A sharp portrait of the user from their decisions, reversals, and "
              "blind spots. Tell them something true they never stated outright.",
    ).text
```

### The work I deliberately don't do

Deduping overlapping facts, tracking which ones have more evidence, aging stale memories along a freshness curve from strengthening to stale — Hindsight consolidates the banks on its own. I didn't build any of it and I didn't want to. Memory maintenance is the kind of chore that looks small and quietly becomes its own project.

## 5. The behaviors that emerge

This is the part that turned it from a toy into something I use.

**It catches me contradicting myself — and I never set the trap.** Recording a decision used to be a button you clicked. It felt dead, because *I* was planting the contradiction the system would later "catch." So I made writes implicit: every message I send gets a quick "is this a commitment?" classification and, if so, is filed silently across the banks.

> **Me:** we're going async-first for the worker queue
> *(later, same session)*
> **Me:** @all should we add a synchronous fallback?
> **Raj:** Before anyone answers — you committed to async-first earlier. A sync fallback partially reverses that. Intentional, or are we relitigating?

I didn't tell it to watch for that. The gap between *"I configured this"* and *"wait, how did it know that"* is the entire product.

**It profiles me, and the profile stings.** That `reflect` call over the boardroom told me I *"treat the last persuasive voice as consensus, which makes my decisions more like temporary agreements than commitments."* I did not enjoy reading that. It was also correct, and I never typed anything close to it — it was reasoned out of scattered evidence across sessions.

**The advisors change their minds.** The same `reflect` call, run against an advisor's own bank, lets them revise what they emphasize based on the debates they've been in — and because it reflects through that advisor's mission, the shift stays in character. After enough arguments where Raj kept hammering reliability, Maya — the ship-fast one — started weighting it more heavily on her own. I didn't reprogram her. She absorbed it.

**You can trace whose advice won.** Because every contribution lands in the shared boardroom tagged with who said it, I can read it back as a flow graph: which advisor's points fed the boardroom, and whose points are cited in the decisions. It turns "the board decided X" into "Maya and Tomas drove this, Aisha dissented" — provenance for a decision that no single agent owns.

## 6. Going where I work

Two integrations make it usable rather than a curiosity. The first is an **MCP server**: the board's six core operations are exposed as tools, so I can type *"ask my board whether to ship this refactor now"* inside Cursor or Claude Code and get an answer grounded in the same shared memory as the web app. The second is **bring-your-own-LLM**: the reasoning layer is swappable at runtime between a local proxy and any cloud API, so the board isn't welded to one provider.

## 7. What I'd take to the next one

1. **Two scopes of memory, private and shared.** It's the smallest design that keeps agents distinct *and* lets them reference each other. One shared blob collapses their identities; full isolation kills the room.
2. **Make memory writes implicit.** The instant a user has to click "remember this," the emergent behavior dies. Detect what matters and store it silently.
3. **Let the memory layer reason — don't reimplement it.** I burned real time on recall-then-summarize before `reflect` did it better and kept the reasoning anchored to each bank's worldview.
4. **Don't own consolidation.** Deduping, evidence, and freshness is more work than it looks. Use a system that does it and spend your effort on orchestration.
5. **Anchor extraction to a name, and state your limits out loud.** Name-anchoring stopped models from describing themselves; admitting that status-update people make shallow advisors builds more trust than pretending the model is magic.

---

The single-agent version of all this — one assistant that remembers one user — is genuinely easy now. The interesting problems start the moment there's a second agent that has to remember the same world, and a third one watching how they decide. That's the room I wanted to build, and where I'd point anyone trying to make something memory-shaped that isn't just a smarter autocomplete.
