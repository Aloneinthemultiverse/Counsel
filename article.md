# I turned my team's Slack into a board of advisors that argue with each other

### What I learned building a system where several agents share one memory — and remember everything I decide.

---

**The short version**

- I feed a team's Slack export into a system called Counsel. It distills each person into an advisor that talks and decides like them, then lets me consult the whole board in a chat.
- Two problems were actually interesting: turning a messy chat history into an advisor worth listening to, and giving a *room* of agents a memory instead of a single one.
- The memory layer is [Hindsight, an open-source agent memory system](https://github.com/vectorize-io/hindsight). It's the reason the hard parts were tractable.

---

I typed a question into a chat box — *"should we ship the dashboard next week to hit the deal, or hold to test it?"* — and four advisors answered, one after another. Maya pushed to ship. Raj said the instrumentation wasn't ready and called Maya's timeline "a wish, not a plan." Tomas backed Raj with usage numbers. Aisha reminded everyone we'd burned two accounts doing exactly this before.

None of those four people were in the room. They're advisors I built by feeding a Slack export into Counsel — each one distilled from a real person, each running on persistent memory, so they remember what I told them last week and what each other said last session.

This is the story of building that.

## 1. What it is, end to end

Counsel does one thing: you give it a team's Slack history, and you get back a board of advisors you consult in a chat that feels like a group thread.

```
 Slack export
     │
  distill each person → a persona (what they believe + how they decide)
     │
  give each persona its own memory bank  ── + one shared "boardroom" bank
     │
  consult the board:  @all  or  @maya
     │
  they reply, debate, react to each other → a weighted decision
```

The plumbing is deliberately boring: a FastAPI backend, a single HTML file for the UI, a small engine module, and an MCP server so I can consult the board from inside my editor. The two parts worth writing about sit underneath — **distillation** and **memory** — and the memory half leans entirely on Hindsight.

## 2. Turning a person into an advisor

Real Slack is a mess. People write *"deploying now"*, *"build's broken"*, *"lol"*, *"+1"*, half-thoughts buried in threads. You cannot hand all of that to a model and ask "who is this person?" — it's too much, too noisy, and you get a horoscope back.

So I fan it out — **many readers, then a few editors:**

```
person's messages
   → chunk them
   → WORKERS:  each chunk → notes across 5 lenses (claim + where it was said)
   → REDUCERS: one per lens → dedupe all notes → write one clean section
   → assemble: 5 sections + a summary + an honest "what I don't know" list
   = an advisor
```

A worker pass doesn't write anything final — it just takes notes, reading a chunk through five lenses at once: priorities, opinions, decision patterns, domain knowledge, and who they work with. Every note is a claim plus a pointer:

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

Then five reducers — one per lens — dedupe and synthesize. The decisions reducer gets *every* decision-note from *every* chunk, collapses repeats (a claim seen five times is a pattern; seen once is a hint), and writes one section. Workers spread wide so nothing's missed; reducers go deep so nothing's redundant.

> Every claim traces back to a real message. When Maya argues against cutting analytics, it's because the real Maya said so, in `#product`, on a date I can point to.

This is also where the system has an honest limit, and I'd rather state it than hide it. Pure ops chatter — *"deploying now", "fixed the timeout"* — paints a great picture of what someone *knows*, but a thin one of how they *judge*. People who argue and decide in Slack make rich advisors; people who only post status updates make shallow ones. The distiller is honest about it and will tell you when there isn't enough signal.

## 3. The mistake I made first: one shared memory

My first instinct was a single memory store for the whole board. It's the obvious move, it's wrong, and figuring out *why* was the most useful thing I did.

If Maya and Raj write to the same memory, they stop being distinct advisors — their reads blend into mush. If they're completely isolated, they can't reference each other, and you can't ask "what does the *board* think we already decided?"

So memory has **two scopes:**

- a **private bank per advisor** — what *they* know, believe, and have said, and
- a **shared boardroom bank** — your decisions, plus what *every* advisor has said.

Hindsight calls these partitions "banks," and spinning one up is cheap — which is the whole reason I could afford to give every advisor their own. I don't store the raw chat; I store the distilled persona and let the memory layer extract typed facts from the prose:

```python
c.create_bank(
    bank_id=f"advisor-{slug}",
    name=f"{name} (advisor)",
    mission=f"You are {name}. Your worldview: {glance}",  # steers reasoning later
    disposition_skepticism=4, disposition_literalism=3, disposition_empathy=2,
)
for section in persona_facets(doc):
    c.retain(bank_id=f"advisor-{slug}", content=section)
```

That `mission` field isn't metadata — it's the advisor's worldview, and it later steers how the memory layer reasons on their behalf. For the conceptual version of why typed, mission-aware memory beats a vector store with a prompt stapled on, Vectorize's explainer on [what agent memory actually is](https://vectorize.io/what-is-agent-memory) is the cleanest I've read.

## 4. How a single reply gets built

When an advisor speaks, the reply is assembled from both scopes plus the live thread — what I know, what the room remembers, and the conversation so far:

```python
def advisor_take(c, slug, question):
    mem_own   = recall(c, slug, question)              # what I know and have said
    mem_board = recall_bank(c, "boardroom", question)  # decisions + what others said
    return gen(persona(slug) + mem_own + mem_board + thread + question)
```

Recall is the load-bearing call, and it's a real retrieval problem I was glad not to hand-roll: it pulls only what's relevant by blending meaning, keywords, entity relationships, and recency. As a bank grows across dozens of sessions, that's the difference between a grounded prompt and one that falls over. It's documented well in the [Hindsight docs](https://hindsight.vectorize.io/); the short version is that it scales without me thinking about it. Recalling the *boardroom* is what lets advisors reference each other instead of talking past one another.

## 5. The behaviors that surprised me

This is the part that turned it from a toy into something I use.

### It catches me contradicting myself — and I never set the trap

Recording a decision used to be a button. It felt dead, because *I* was planting the contradiction it would later "catch." So I made it implicit: every message gets a quick "is this a commitment?" classification and, if so, is filed silently across the banks.

> **Me:** we're going async-first for the worker queue
> *(later, same session)*
> **Me:** @all should we add a synchronous fallback?
> **Raj:** Before anyone answers — you committed to async-first earlier. A sync fallback partially reverses that. Intentional, or are we relitigating?

I didn't tell it to watch for that. The gap between *"I configured this"* and *"wait, how did it know that"* is the entire product.

### It profiles me, and the profile stings

There's a button that asks the board what it knows about *me*. Instead of recalling fragments and prompting my own model to summarize, I hand the whole job to the memory layer's `reflect`, which finds the relevant memories itself and synthesizes:

```python
def profile(c):
    return c.reflect(
        bank_id="boardroom",
        query="A sharp portrait of the user from their decisions, reversals, and "
              "blind spots. Tell them something true they never stated outright.",
    ).text
```

It told me I *"treat the last persuasive voice as consensus, which makes my decisions more like temporary agreements than commitments."* I did not enjoy that. It was also correct, and I never typed anything close to it.

### The advisors change their minds

The same `reflect` call, run against an advisor's own bank, lets them revise what they emphasize based on the debates they've been in — and because it reflects through that advisor's mission, the shift stays in character. After enough arguments where Raj kept hammering reliability, Maya — the ship-fast one — started weighting it more heavily on her own. I didn't reprogram her. She absorbed it.

### The work I deliberately don't do

Deduping memories, tracking which facts have more evidence, aging stale ones along a freshness curve — Hindsight consolidates the banks on its own. I didn't build it and I didn't want to. Memory maintenance is the kind of chore that looks small and quietly becomes its own project.

## 6. What I'd take to the next one

1. **Two scopes of memory, private and shared.** The smallest design that keeps agents distinct *and* lets them reference each other.
2. **Make memory writes implicit.** The instant a user has to click "remember this," the emergent behavior dies.
3. **Let the memory layer reason — don't reimplement it.** I burned real time on recall-then-summarize before `reflect` did it better and kept the reasoning anchored to each bank's worldview.
4. **Don't own consolidation.** Deduping, evidence, and freshness is more work than it looks.
5. **State your system's limits out loud.** "People who only post status updates make shallow advisors" is a real constraint, and saying it builds more trust than pretending the model is magic.

---

The single-agent version of all this — one assistant that remembers one user — is genuinely easy now. The interesting problems start the moment there's a second agent that has to remember the same world, and a third one watching how they decide. That's the room I wanted to build, and where I'd point anyone trying to make something memory-shaped that isn't just a smarter autocomplete.
