# I turned my team's Slack into a board of advisors that argue with each other

I typed a question into a chat box — *"should we ship the dashboard next week to hit the deal, or hold to test it?"* — and four advisors answered, one after another. Maya pushed to ship. Raj said the instrumentation wasn't ready and called Maya's timeline "a wish, not a plan." Tomas backed Raj with usage numbers. Aisha reminded everyone we'd burned two accounts doing exactly this before.

None of those four people were in the room. None of them are even people anymore, in the sense that matters here — they're advisors I built by feeding a Slack export into a system I call Counsel. Each one talks and decides like the real person it was distilled from, and the whole thing runs on persistent memory, so they remember what I told them last week and what each other said last session.

This is the story of building that, and the two problems that turned out to be interesting: how you turn a real person's messy chat history into an advisor worth listening to, and what happens to memory when you have a *room* of agents instead of one.

## What it actually is

Counsel does one thing: you give it a team's Slack history, and it gives you back a board of advisors you can consult any time, in a chat that feels like a group thread.

The build pipeline is short to describe. A Slack export goes in. For each person, I distill their messages into a persona — not a vibe, a structured profile of what they believe and how they decide. Each persona gets its own memory bank. Then you talk to the board: `@all` to ask everyone, `@maya` to ask one of them. They reply in a streaming chat, they push back on each other by name, and when you're done you can ask the board to score the whole discussion into a weighted decision.

The plumbing is unremarkable on purpose — a FastAPI backend, a single HTML file for the UI, a small engine module, and an MCP server so I can consult the board from inside my editor. The two things worth writing about both sit underneath that: **distillation** and **memory**. The memory half leans entirely on [Hindsight, an open-source agent memory system](https://github.com/vectorize-io/hindsight), which is the only reason the interesting parts were tractable at all.

## Turning a person into an advisor

Here's the problem with distilling a human from Slack: real chat is a mess. People write *"deploying now"*, *"build's broken"*, *"lol"*, *"+1"*, half-thoughts buried in threads. You cannot hand all of that to a model and ask "who is this person?" — it's too much, too noisy, and you get a horoscope back.

So I fan it out: many readers, then a few editors.

First I chunk the person's substantive messages (the *"+1"*s get filtered out). Each chunk goes to a "worker" pass that doesn't write anything final — it just takes notes, reading the chunk through five lenses at once: priorities, opinions, decision patterns, domain knowledge, and who they work with. Every note is a one-line claim plus a pointer to where it was said:

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

Then five "reducers" — one per lens — take over. The decisions reducer gets *every* decision-note from *every* chunk, dedupes them (a claim seen five times is a pattern; seen once is a hint), and writes one clean section. The workers spread wide so nothing is missed; the reducers go deep so nothing is redundant. Assemble the five sections, add a two-sentence summary and an honest "here's what I don't know about this person" list, and you have an advisor.

The detail I care about most: every claim traces back to a real message. When Maya argues against cutting analytics, it's not because a model decided founders like analytics — it's because the real Maya said so, in `#product`, on a date I can point to.

This is also where I learned the system's honest limit, and I'd rather state it than hide it. Pure ops chatter — *"deploying now", "fixed the timeout"* — builds a great picture of what someone *knows*, but a thin one of how they *judge*. People who argue and decide in Slack make rich advisors; people who only ship status updates make shallow ones. Garbage in, thin persona out. The distiller is honest about it and will literally tell you when there isn't enough signal.

## The part I actually got wrong first: shared memory

My first instinct was one big memory store for the whole board. It's the obvious move and it's wrong, and figuring out *why* it's wrong was the most useful thing I did.

If Maya and Raj write to the same memory, they stop being distinct advisors — their accumulated read on the situation blends into mush. But if they're completely isolated, they can't reference each other, and you can't ask "what does the *board* think we already decided?"

So memory has two scopes, and that one decision shaped the rest of the system:

- a **private bank per advisor** — what *they* know, believe, and have said, and
- a **shared boardroom bank** — your decisions, plus what *every* advisor has said.

Hindsight calls these partitions "banks," and the fact that spinning one up is cheap is the whole reason I could afford to give every advisor their own. Creating them, I don't store the raw chat — I store the distilled persona and let the memory layer extract typed facts out of the prose:

```python
c.create_bank(
    bank_id=f"advisor-{slug}",
    name=f"{name} (advisor)",
    mission=f"You are {name}. Your worldview: {glance}",  # this steers reasoning later
    disposition_skepticism=4, disposition_literalism=3, disposition_empathy=2,
)
for section in persona_facets(doc):
    c.retain(bank_id=f"advisor-{slug}", content=section)
```

That `mission` field isn't metadata — it's the advisor's worldview, and it later steers how the memory layer reasons on that advisor's behalf. If you want the conceptual version of why typed, mission-aware memory beats a vector store with a prompt stapled on, Vectorize's explainer on [what agent memory actually is](https://vectorize.io/what-is-agent-memory) is the cleanest I've read.

Every time an advisor speaks, the reply is assembled from both scopes plus the live thread — what I know, what the room remembers, and the conversation so far:

```python
def advisor_take(c, slug, question):
    mem_own   = recall(c, slug, question)              # what I know and have said
    mem_board = recall_bank(c, "boardroom", question)  # decisions + what others said
    return gen(persona(slug) + mem_own + mem_board + thread + question)
```

Recall is the load-bearing call, and it's a real retrieval problem I was glad not to hand-roll: it pulls only what's relevant to the question by blending meaning, keywords, entity relationships, and recency. As a bank grows across dozens of sessions, that's the difference between a grounded prompt and one that falls over. The retrieval model is documented well in the [Hindsight docs](https://hindsight.vectorize.io/); the short version is that it scales without me thinking about it.

## The behaviors that surprised me

This is the part that turned it from a toy into something I actually use.

**It catches me contradicting myself, and I never set the trap.** Recording a decision used to be a button you clicked. It felt dead, because *I* was the one planting the contradiction it would later "catch." So I made it implicit: every message I send gets a quick "is this a commitment?" classification and, if so, is filed silently across the banks. The result:

> **Me:** we're going async-first for the worker queue
> *(later, same session)*
> **Me:** @all should we add a synchronous fallback?
> **Raj:** Before anyone answers — you committed to async-first earlier. A sync fallback partially reverses that. Intentional, or are we relitigating?

I didn't tell it to watch for that. The gap between *"I configured this"* and *"wait, how did it know that"* is the entire product.

**It profiles me, and the profile stings.** There's a button that asks the board what it knows about *me*. Instead of recalling fragments and prompting my own model to summarize, I hand the whole job to the memory layer's `reflect`, which finds the relevant memories itself and synthesizes:

```python
def profile(c):
    return c.reflect(
        bank_id="boardroom",
        query="A sharp portrait of the user from their decisions, reversals, and "
              "blind spots. Tell them something true they never stated outright.",
    ).text
```

It told me I *"treat the last persuasive voice as consensus, which makes my decisions more like temporary agreements than commitments."* I did not enjoy that. It was also correct, and I never typed anything close to it — it was reasoned out of scattered evidence across sessions.

**The advisors change their minds.** The same `reflect` call, run against an advisor's own bank, lets them revise what they emphasize based on the debates they've been in — and because it reflects through that advisor's mission, the shift stays in character. After enough arguments where Raj kept hammering reliability, Maya — the ship-fast one — started weighting it more heavily on her own. I didn't reprogram her. She absorbed it.

And there's a class of work I deliberately don't do: deduping memories, tracking which facts have more evidence, aging stale ones along a freshness curve. Hindsight consolidates the banks on its own. I didn't build it and I didn't want to — memory maintenance is the kind of chore that looks small and quietly becomes its own project.

## What I'd take to the next one

1. **Two scopes of memory, private and shared.** It's the smallest design that keeps agents distinct *and* lets them reference each other. One shared blob collapses their identities; full isolation kills the room.
2. **Make memory writes implicit.** The instant a user has to click "remember this," the emergent behavior dies. Detect what matters and store it silently.
3. **Let the memory layer reason — don't reimplement it.** I burned real time on recall-then-summarize before `reflect` did it better and kept the reasoning anchored to each bank's worldview.
4. **Don't own consolidation.** Deduping, evidence, and freshness is more work than it looks. Use a system that does it and spend your time on orchestration.
5. **State your system's limits out loud.** "People who only post status updates make shallow advisors" is a real constraint. Saying it builds more trust than pretending the model is magic.

The single-agent version of all this — one assistant that remembers one user — is genuinely easy now. The interesting problems start the moment there's a second agent that has to remember the same world, and a third one watching how they decide. That's the room I wanted to build, and it's where I'd point anyone trying to make something memory-shaped that isn't just a smarter autocomplete.
