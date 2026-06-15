# Each AI advisor has its own memory. The hard part was the memory they share.

I have a chat window where four AI advisors argue with each other about my decisions. The interesting engineering isn't the arguing — it's that they remember what *each other* said last week, and they'll call me out when I quietly reverse a call I made a month ago.

This is a system I call Counsel. You give it a team's Slack history; it turns each person into an advisor you can consult, and the whole thing runs on persistent memory. Most of the "AI that remembers" work I'd seen was single-player: one assistant that remembers one user's preferences. That's the easy half. The half I actually cared about — and the half this post is about — is what happens when you have *several* agents that need to remember the same world, and each other.

## What it does, and how it hangs together

The flow is simple to describe: a Slack export goes in, a set of advisors comes out, and you talk to them.

Under that, there are four pieces:

- **`web.py`** — a FastAPI backend. It serves a single-page UI, streams the chat over SSE, and exposes the endpoints for building the board, consulting it, and inspecting memory.
- **`board.py`** — the engine. It owns the LLM calls and all the memory logic, sitting on top of [Hindsight, an open-source agent memory system](https://github.com/vectorize-io/hindsight).
- **`tools/`** — the ingestion and distillation pipeline that turns raw Slack into structured personas.
- **`mcp_server.py`** — an MCP server, so I can consult the board from inside an editor like Cursor without leaving my code.

The data path is: ingest Slack → distill each person into a persona document → give each persona a memory bank → consult. The first two steps are a one-time build; the last is where the system lives.

I want to be honest about where the real work was. Distilling a person from chat logs is fiddly but tractable — chunk their messages, have a model extract opinions and decision patterns, dedupe, assemble. The part that took the most thought was memory: deciding *what each agent should remember, what they should share, and who gets to write to whom.*

## The through-line: two scopes of memory

The mistake I almost made was giving every advisor one big shared memory. It seems efficient. It's wrong. If Maya and Raj write to the same store, you lose the thing that makes them distinct advisors — their own accumulated read on the situation. But if they're fully isolated, they can't reference each other, and you can't ask "what does the *board* think we decided?"

So I split memory into two scopes, and that single decision shaped everything else:

1. **A per-advisor bank** — what *I* (this advisor) know, believe, and have said.
2. **A shared boardroom bank** — the user's decisions, plus what *every* advisor has said.

Hindsight calls these partitions "banks," and creating them is cheap, which is exactly why I could afford to give every advisor their own. Here's the build step:

```python
def init():
    c = hs()
    # one shared bank for the collective record
    c.create_bank(
        bank_id="boardroom",
        name="The Boardroom (shared memory)",
        mission="Shared memory of the advisory board: the user's decisions and "
                "what each advisor has said in past sessions. Track who said what.",
        disposition_skepticism=4, disposition_literalism=4, disposition_empathy=2,
    )
    for slug in personas():
        name, glance, doc = load_persona(slug)
        c.create_bank(
            bank_id=f"advisor-{slug}",
            name=f"{name} (advisor)",
            mission=f"You are {name}. Your worldview: {glance}",
            disposition_skepticism=4, disposition_literalism=3, disposition_empathy=2,
        )
        # seed the bank with the distilled persona; Hindsight extracts typed facts
        for section in split_facets(doc):
            c.retain(bank_id=f"advisor-{slug}", content=section)
```

Two things worth noting. The bank's `mission` *is* the advisor's worldview — it's not metadata, it steers how the memory layer reasons later. And I never store the raw Slack; I store the distilled persona, and let Hindsight's `retain` do the extraction. One paragraph in becomes many typed memory units — observations, experiences, world facts — which I get to query later without having designed a schema. If you want the conceptual background on why that typed-memory model matters, Vectorize's write-up on [what agent memory actually is](https://vectorize.io/what-is-agent-memory) is the clearest version I've found.

## Reads: every reply is a recall against two scopes

When an advisor speaks, the reply is assembled from both memory scopes plus the live conversation:

```python
def advisor_take(c, slug, question):
    name, glance, _ = load_persona(slug)
    mem_own   = recall(c, slug, question)              # what I know and have said
    mem_board = recall_bank(c, "boardroom", question)  # decisions + what others said

    prompt = (
        f"You are {name}. Worldview: {glance}\n"
        f"What you remember: {mem_own}\n"
        f"The boardroom remembers (decisions + other advisors): {mem_board}\n"
        f"Question: {question}\nYour take:"
    )
    return name, gen(prompt)
```

The recall is the load-bearing call. It doesn't dump the whole bank into the prompt — it pulls only what's relevant to the question, blending semantic similarity, keyword match, graph relationships, and recency. As a bank grows to hundreds of units across many sessions, that's the difference between a prompt that stays grounded and one that explodes. The retrieval details are documented well in the [Hindsight documentation](https://hindsight.vectorize.io/); the short version is that recall is a real retrieval problem and I was glad not to be hand-rolling it.

Recalling the boardroom is what makes the advisors a group rather than four parallel monologues. When Raj has flagged a reliability concern in a past session, Maya recalls it and can build on it — or push back on it by name.

## Writes: making memory implicit

Here's the design decision I'm happiest with. Early on, recording a decision was a button. You'd consult the board, then click "save this decision." It worked, and it felt completely dead — because *I* was the one setting up the contradiction the system would later catch. There's no magic in a trap you set yourself.

So I made the writes implicit. Every message you send gets a quick classification pass: does this state a commitment? If it does, it's retained as a decision across every bank, no button:

```python
def remember_from_message(c, question):
    verdict = gen(
        "Does this message state a decision or commitment the board should "
        "remember? Reply with a one-sentence summary, or 'NONE'.",
        question,
    )
    if verdict.strip().upper().startswith("NONE"):
        return None
    line = f"DECISION by the user on {today()}: {verdict}"
    board_write(c, line)                    # the shared record
    for slug in personas():
        stamp(c, slug, line)                # and every advisor
    return verdict
```

The payoff is that contradiction detection stops feeling scripted. You say something in passing, the system files it, and three exchanges later an advisor recalls it and stops you. You never told it to watch for that. That gap — between "I configured this" and "wait, how did it know that" — is the entire product.

## Reasoning over memory, instead of around it

For a while I did all the *reasoning* myself: recall a pile of memories, then prompt my own model to synthesize them. It worked, but it meant I was using the memory system as a vector store and bolting my own brain on top.

The features that needed synthesis — a profile of the user, and letting advisors revise their own views — got noticeably better when I handed the reasoning back to the memory layer via `reflect`. With `reflect`, you give Hindsight a question and it finds the relevant memories itself and synthesizes an answer, weighted by the bank's mission and disposition:

```python
def profile(c):
    return c.reflect(
        bank_id="boardroom",
        query="Write a sharp portrait of the user from their decisions, "
              "reversals, and blind spots. Tell them something true they "
              "never stated outright.",
    ).text
```

The advisor-evolution feature uses the same call against each advisor's own bank, so the reflection runs through *that advisor's* worldview. The result is they update what they emphasize based on what actually happened in the debates — and because it reflects through the bank's mission, the change stays in character.

There's also a class of bookkeeping I deliberately don't do. Hindsight consolidates the banks on its own: it dedupes overlapping facts, tracks evidence counts, and ages memories along a freshness trend from strengthening to stale. I didn't build any of that, and I didn't want to. Memory maintenance is the kind of thing that looks easy and quietly becomes a project of its own.

## What it actually does

A real exchange, lightly trimmed:

> **Me:** we're going async-first for the worker queue
>
> *(later, same session)*
>
> **Me:** @all should we add a synchronous fallback path?
>
> **Raj:** Before anyone answers — you committed to async-first earlier this session. A sync fallback partially reverses that. Is that intentional, or are we relitigating?

Nothing in that exchange was scripted. The decision was filed implicitly; Raj recalled it from the shared bank; the contradiction surfaced on its own.

And the profile, which reads the accumulated boardroom and reflects over it, told me: *"You treat the last persuasive voice as consensus, which means your decisions are more like temporary agreements than commitments."* I did not enjoy reading that. It was also correct, and I never typed anything resembling it — it was synthesized from scattered evidence across sessions.

## Lessons

A few things I'd carry to the next system that needs more than one agent and a memory:

1. **Separate "what I know" from "what we know."** Two memory scopes — private and shared — is the smallest design that lets agents stay distinct *and* reference each other. One shared blob collapses their identities; full isolation kills collaboration.

2. **Make memory writes implicit.** The moment a user has to click "remember this," the emergent behavior dies. Detect what's worth storing and store it silently. The system feeling like it was paying attention is worth more than any explicit control.

3. **Let the memory layer reason, don't reimplement it.** I spent real time hand-building recall-then-synthesize before realizing `reflect` did it better and kept the reasoning anchored to each bank's worldview. Reach for the native operation first.

4. **Don't own consolidation and freshness.** Deduping, evidence tracking, and aging memories is a deceptively large amount of work. Use a system that does it for you and spend your effort on orchestration instead.

5. **Conversation context and long-term memory are different layers.** The live thread is what makes a follow-up coherent; the banks are what make it remember last week. I kept them separate on purpose, and every reply is assembled from both.

The single-agent version of all this is genuinely easy now. The interesting problems start the moment you have a second agent that has to remember the same world — and that's where I'd point anyone who wants to build something memory-shaped that isn't just a smarter autocomplete.
