"""Counsel — the memory layer + ask-team panel.

Each distilled persona becomes a Hindsight bank (the advisor's mind). The bank is
seeded with the persona facets, then accumulates: consultations the advisor gave,
and decisions the user told the board. That memory is what makes the advisor
*living* rather than frozen — it recalls your history, revises its own advice, and
flags when you contradict a past decision.

Commands:
  python board.py init                          # create + seed one bank per persona
  python board.py ask <slug> "<question>"       # single advisor, with memory
  python board.py team "<question>"             # ask-team panel, with memory
  python board.py decide "<decision>"           # record a decision to the whole board
  python board.py memory <slug>                 # dump what an advisor remembers
"""

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from hindsight_client import Hindsight

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
PERSONAS = ROOT / "personas"

# ---- LLM config: host proxy by default; customers can plug in their own ----
LLM_CFG = {
    "provider": os.environ.get("LLM_PROVIDER", "anthropic"),   # "anthropic" | "openai"
    "base_url": os.environ.get("LLM_BASE_URL", "http://localhost:8080"),
    "api_key": os.environ.get("LLM_API_KEY", "proxy"),
    "model": os.environ.get("MODEL", "claude-sonnet-4-6"),
}
MODEL = LLM_CFG["model"]   # back-compat for any direct refs


def _make_client(cfg):
    if cfg["provider"] == "openai":
        from openai import OpenAI
        return OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
    return Anthropic(base_url=cfg["base_url"], api_key=cfg["api_key"])


llm = _make_client(LLM_CFG)


def set_llm(provider=None, base_url=None, api_key=None, model=None):
    """Swap the LLM at runtime (host proxy or a customer's own API)."""
    global llm, MODEL
    if provider:
        LLM_CFG["provider"] = provider
    if base_url:
        LLM_CFG["base_url"] = base_url
    if api_key:
        LLM_CFG["api_key"] = api_key
    if model:
        LLM_CFG["model"] = model
        MODEL = model
    llm = _make_client(LLM_CFG)
    return {k: (v if k != "api_key" else "•••") for k, v in LLM_CFG.items()}


def hs() -> Hindsight:
    return Hindsight(base_url=os.environ["HINDSIGHT_URL"], api_key=os.environ.get("HINDSIGHT_API_KEY"))


def bank_id(slug: str) -> str:
    return f"advisor-{slug}"


def personas() -> list:
    return [p.stem for p in PERSONAS.glob("*.md")]


def load_persona(slug: str) -> tuple:
    doc = (PERSONAS / f"{slug}.md").read_text(encoding="utf-8")
    name = (re.search(r"display_name:\s*(.+)", doc) or [None, slug])[1].strip()
    glance = ""
    m = re.search(r"## At a glance\s*(.+?)\n##", doc, re.DOTALL)
    if m:
        glance = " ".join(m.group(1).split())
    return name, glance, doc


LLM_DOWN = "⚠ The board is unreachable — the LLM proxy isn't responding. Make sure the antigravity proxy is running on http://localhost:8080 (run: acc start)."


def gen(system: str, user: str, max_tokens: int = 1000) -> str:
    try:
        if LLM_CFG["provider"] == "openai":
            r = llm.chat.completions.create(
                model=LLM_CFG["model"], max_tokens=max_tokens,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}])
            return (r.choices[0].message.content or "").strip()
        r = llm.messages.create(model=LLM_CFG["model"], max_tokens=max_tokens, system=system,
                                messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
    except Exception:
        return LLM_DOWN


BOARDROOM = "boardroom"   # shared bank: decisions + what every advisor has said


# ---------------------------------------------------------------- init
def init():
    c = hs()
    # shared collective memory of the whole board
    try:
        c.delete_bank(bank_id=BOARDROOM)
    except Exception:
        pass
    c.create_bank(
        bank_id=BOARDROOM,
        name="The Boardroom (shared memory)",
        mission=("Shared memory of the advisory board: the user's stated decisions and "
                 "commitments, and the key points each advisor has made in past sessions. "
                 "Track who said what so advisors can build on each other."),
        disposition_skepticism=4, disposition_literalism=4, disposition_empathy=2,
    )
    for slug in personas():
        name, glance, doc = load_persona(slug)
        bid = bank_id(slug)
        try:
            c.delete_bank(bank_id=bid)
        except Exception:
            pass
        c.create_bank(
            bank_id=bid,
            name=f"{name} (advisor)",
            mission=(f"You are {name}, an advisor on a board. Your worldview: {glance} "
                     f"Give your honest take grounded in what you believe and what you remember "
                     f"about this user's situation and your own past advice. Push back when warranted."),
            disposition_skepticism=4, disposition_literalism=3, disposition_empathy=2,
        )
        # seed persona facets as memories
        for sec in re.split(r"\n## ", doc):
            sec = sec.strip()
            if not sec or sec.startswith("---") or sec.lower().startswith("at a glance"):
                continue
            title = sec.split("\n", 1)[0]
            c.retain(bank_id=bid, content=f"[{name}'s persona — {title}] {sec[:1500]}",
                     document_id=f"persona-{slug}-{title[:30]}")
        print(f"  bank ready: {bid}  ({name})")
    print("board initialized.")


# ---------------------------------------------------------------- recall helper
def recall(c, slug, query, k=6):
    try:
        res = c.recall(bank_id=bank_id(slug), query=query, budget="mid")
        items = getattr(res, "results", None) or getattr(res, "memories", None) or []
        out = []
        for r in items[:k]:
            d = r if isinstance(r, dict) else (r.to_dict() if hasattr(r, "to_dict") else {})
            out.append(d.get("text") or getattr(r, "text", str(r)))
        return out
    except Exception as e:
        return [f"(recall error: {e})"]


ADVISOR_SYS = (
    "You simulate an advisor's reasoning, grounded in their persona and their MEMORY of this "
    "user. Lead with the take. Use first person. Rules:\n"
    "- If memory shows the user made a past decision this question contradicts, SAY SO explicitly "
    "(prefix that line with 'CONTRADICTION:').\n"
    "- If memory shows YOU gave related advice before and you're revising it, say so (prefix "
    "'REVISING:').\n"
    "- Ground claims in persona/memory; if extrapolating, say so. Push back where your patterns "
    "indicate. No voice mimicry.")


def recall_bank(c, bid, query, k=6):
    try:
        res = c.recall(bank_id=bid, query=query, budget="mid")
        items = getattr(res, "results", None) or getattr(res, "memories", None) or []
        out = []
        for r in items[:k]:
            d = r if isinstance(r, dict) else (r.to_dict() if hasattr(r, "to_dict") else {})
            out.append(d.get("text") or getattr(r, "text", str(r)))
        return out
    except Exception:
        return []


def advisor_take(c, slug, question, see_others=""):
    name, glance, _ = load_persona(slug)
    mem = recall(c, slug, question)
    # collective memory: the user's decisions + what OTHER advisors have said before
    shared = recall_bank(c, BOARDROOM, question, k=6)
    mem_block = "\n".join(f"- {m}" for m in mem) if mem else "(no memory yet)"
    shared_block = "\n".join(f"- {m}" for m in shared) if shared else "(nothing yet)"
    user = (f"You are {name}.\nYour worldview: {glance}\n\n"
            f"YOUR memory (persona + your past advice):\n{mem_block}\n\n"
            f"THE BOARDROOM remembers (the user's decisions + points OTHER advisors made — "
            f"reference a colleague by name if you're building on or pushing against their point):\n{shared_block}\n\n"
            + (f"In this same session other advisors just said:\n{see_others}\n\n" if see_others else "")
            + f"Question from the user:\n{question}\n\nYour take:")
    return name, gen(ADVISOR_SYS, user, max_tokens=700)


def stamp(c, slug, content):
    c.retain(bank_id=bank_id(slug), content=content, timestamp=datetime.now(timezone.utc))


def board_write(c, content):
    """Write to the shared boardroom memory."""
    try:
        c.retain(bank_id=BOARDROOM, content=content, timestamp=datetime.now(timezone.utc))
    except Exception:
        pass


DECISION_SYS = (
    "You detect whether a user's message to their advisory board states a DECISION, commitment, "
    "preference, or stance the board should remember for later (e.g. 'we're going with X', "
    "'let's prioritize Y', 'I've decided Z'). Reply with ONLY a one-sentence summary of the decision "
    "if there is one, or exactly 'NONE' if it's just a question with no decision.")


def remember_from_message(c, question):
    """Auto-detect a decision in the user's message and store it to shared + all banks.
    Returns the decision text if one was found, else None."""
    verdict = gen(DECISION_SYS, f"User message:\n{question}", max_tokens=120).strip()
    if not verdict or verdict.upper().startswith("NONE") or len(verdict) < 8:
        return None
    line = f"DECISION by the user on {datetime.now().date()}: {verdict}"
    board_write(c, line)
    for slug in personas():
        stamp(c, slug, line)
    return verdict


def display_name(slug):
    return load_persona(slug)[0]


def parse_targets(message):
    """@mentions -> advisor slugs. @all / no mention -> everyone."""
    slugs = personas()
    mentions = re.findall(r"@(\w+)", message.lower())
    if not mentions or "all" in mentions or "everyone" in mentions or "board" in mentions:
        return slugs
    picked = []
    for slug in slugs:
        first = display_name(slug).split()[0].lower()
        if slug in mentions or first in mentions:
            picked.append(slug)
    return picked or slugs


def render_thread(thread, limit=14):
    lines = []
    for m in thread[-limit:]:
        who = "You" if m["role"] == "user" else m["name"]
        lines.append(f"{who}: {m['text']}")
    return "\n".join(lines)


CHAT_SYS = (
    "You are one member of an advisory board in a live, fast group chat. Reply IN CHARACTER, grounded "
    "in your persona and memory. This is a heated working conversation, NOT an essay.\n"
    "STYLE RULES:\n"
    "- SHORT and punchy: 1-3 sentences max. Talk like a sharp person in a group chat, not a memo.\n"
    "- Have a spine. Take a clear position and defend it. Don't hedge, don't 'on the other hand'.\n"
    "- FIGHT when you disagree. Call out other advisors BY NAME and say why they're wrong: "
    "'Maya, that's reckless because…', 'Raj is overthinking this.' Interrupt, challenge, get pointed.\n"
    "- Don't rush to agree or wrap things up. If you hold a different view, hold your ground.\n"
    "- No corporate filler ('I appreciate', 'great point', 'let's circle back'). Real, direct, a little spiky.\n"
    "- If the latest message contradicts a past decision in memory, open with 'CONTRADICTION:'.\n"
    "- If you're revising your own earlier advice, open with 'REVISING:'.")


def chat_reply(c, slug, thread, latest, react=False):
    name, glance, _ = load_persona(slug)
    mem = recall(c, slug, latest)
    shared = recall_bank(c, BOARDROOM, latest, k=5)
    mem_block = "\n".join(f"- {m}" for m in mem[:5]) if mem else "(nothing yet)"
    shared_block = "\n".join(f"- {m}" for m in shared) if shared else "(nothing yet)"
    extra = ("\nThe other advisors just spoke. PUSH BACK on whoever you most disagree with, by name — "
             "don't just nod along or summarize. One or two sharp sentences." if react else "")
    user = (f"You are {name}. Your worldview: {glance}\n\n"
            f"YOUR memory: {mem_block}\n"
            f"BOARDROOM (decisions + what others said): {shared_block}\n\n"
            f"The conversation so far:\n{render_thread(thread)}\n\n"
            f"Reply as {name} — short, sharp, opinionated (1-3 sentences).{extra}")
    return name, gen(CHAT_SYS, user, max_tokens=220)


def session_decision(thread):
    """End-of-session weighted decision matrix over the WHOLE conversation.
    Returns a scored verdict: options × weighted criteria → winner."""
    convo = render_thread(thread, limit=80)
    prompt = (
        "Analyze the ENTIRE boardroom conversation above and produce a weighted decision scorecard.\n"
        "Use EXACTLY this line format, nothing else:\n\n"
        "CRITERIA: <crit1>=<weight> | <crit2>=<weight> | <crit3>=<weight> | <crit4>=<weight>\n"
        "(exactly 4 criteria; integer weights summing to 100; e.g. Revenue impact=35)\n"
        "OPTION: <short label> | <s1>,<s2>,<s3>,<s4>\n"
        "(one OPTION line per strategy argued — 2 or 3 of them; scores 1-10 for each criterion IN ORDER)\n"
        "DECISION: <winning option label>\n"
        "RATIONALE: <2 sentences citing the key tension>\n\n"
        "Plain text only. No markdown, no extra lines.")
    out = gen("You are the board chair. Follow the exact line format. No prose outside it.",
              f"Conversation:\n{convo}\n\n{prompt}", max_tokens=900)

    criteria, options, scores = [], [], {}
    decision, rationale = "", ""
    for line in out.splitlines():
        line = line.strip()
        up = line.upper()
        if up.startswith("CRITERIA:"):
            for part in line.split(":", 1)[1].split("|"):
                if "=" in part:
                    nm, _, w = part.rpartition("=")
                    num = re.sub(r"[^0-9]", "", w)
                    if nm.strip() and num:
                        criteria.append({"name": nm.strip(), "weight": int(num)})
        elif up.startswith("OPTION:"):
            body = line.split(":", 1)[1]
            if "|" in body:
                label, _, sc = body.partition("|")
                label = label.strip()
                nums = [int(x) for x in re.findall(r"\d+", sc)]
                if label:
                    options.append(label)
                    scores[label] = {criteria[i]["name"]: nums[i] for i in range(min(len(nums), len(criteria)))}
        elif up.startswith("DECISION:"):
            decision = line.split(":", 1)[1].strip()
        elif up.startswith("RATIONALE:"):
            rationale = line.split(":", 1)[1].strip()

    if not options or not criteria:
        return {"error": "could not parse decision", "raw": out[:600]}
    weights = {c["name"]: c["weight"] for c in criteria}
    totals = {o: round(sum(scores[o].get(cn, 0) * weights[cn] for cn in weights) / 100.0, 1) for o in options}
    winner = max(totals, key=totals.get) if totals else ""
    return {"options": options, "criteria": criteria, "scores": scores, "totals": totals,
            "winner": winner, "decision": decision or winner, "rationale": rationale}


def evolve(c):
    """Each advisor reflects on accumulated memory and updates its own worldview.
    Returns the list of changes. This is the self-improvement loop."""
    changes = []
    for slug in personas():
        name, glance, doc = load_persona(slug)
        mem = recall_bank(c, bank_id(slug),
                          "decisions the board made, debates I was in, where colleagues pushed back on me, "
                          "concerns that keep coming up, tensions I keep having", k=12)
        if len(mem) < 3:
            continue
        # Use Hindsight's native reflect() over the advisor's OWN bank — it pulls the
        # relevant debates itself and reasons through the bank's mission (their worldview).
        reflect_q = (
            f"Reflecting on the debates and decisions in your memory: as {name}, you are NOT abandoning "
            f"your core worldview, but name ONE thing you now weight MORE heavily or have conceded ground "
            f"on, driven by a specific colleague or decision. Output exactly two lines:\n"
            f"EVOLVED: <your worldview, same core but now including that sharpened emphasis, 1-2 sentences>\n"
            f"CHANGE: <one line: what you now weight more, and which colleague/debate drove it>\n"
            f"Only output STABLE if you would genuinely be inventing a change.")
        out = hs_reflect(c, bank_id(slug), reflect_q)
        if not out or "UNREACHABLE" in out.upper():
            # fallback to our own LLM over recalled memory
            mem_block = "\n".join(f"- {m}" for m in mem)
            out = gen(
                f"You are {name}, an advisor. You are NOT abandoning your core worldview. But after the "
                f"debates below, name ONE thing you now weight MORE heavily or have conceded ground on, "
                f"driven by a specific colleague or decision.\n"
                f"Output exactly two lines:\nEVOLVED: <updated worldview, 1-2 sentences>\n"
                f"CHANGE: <what you now weight more, and which colleague/debate drove it>\n"
                f"Only output STABLE if you would be inventing a change.",
                f"Your current worldview: {glance}\n\nThe debates you've been part of:\n{mem_block}",
                max_tokens=260)
        if out.strip().upper().startswith("STABLE") or "EVOLVED:" not in out:
            continue
        new_view = ""
        change = ""
        for line in out.splitlines():
            if line.strip().startswith("EVOLVED:"):
                new_view = line.split(":", 1)[1].strip()
            elif line.strip().startswith("CHANGE:"):
                change = line.split(":", 1)[1].strip()
        if not new_view:
            continue
        # update the persona's 'At a glance' so it persists and drives future replies
        try:
            new_doc = re.sub(r"(## At a glance\n).*?(\n##)", rf"\1{new_view}\2", doc, count=1, flags=re.DOTALL)
            (PERSONAS / f"{slug}.md").write_text(new_doc, encoding="utf-8")
        except Exception:
            pass
        # update the bank mission so reflect/recall behavior shifts too
        try:
            c.set_mission(bank_id=bank_id(slug),
                          mission=f"You are {name}, an advisor on a board. Your (evolved) worldview: {new_view} "
                                  f"Give honest takes grounded in what you believe and remember. Push back when warranted.")
        except Exception:
            pass
        # record the evolution as a memory
        board_write(c, f"{name}'s view evolved: {change}")
        changes.append({"name": name, "slug": slug, "new_view": new_view, "change": change})
    return changes


def devils_advocate(question, positions):
    """Force a hard counter-argument against the board's emerging consensus."""
    return gen(
        "You are the board's designated devil's advocate. The advisors below have largely converged. "
        "Your job is to RED-TEAM that consensus: name the advisor best positioned to dissent, then "
        "argue the strongest case for the OPPOSITE conclusion in their voice — concrete risks, blind "
        "spots, and what everyone is ignoring because they agree. Be sharp, not contrarian-for-its-own-sake. "
        "Start with 'DEVIL'S ADVOCATE (<advisor>):' then the challenge.",
        f"Question: {question}\n\nThe board's positions:\n{positions}", max_tokens=500)


def hs_reflect(c, bid, query, budget="mid"):
    """Call Hindsight's native reflect() — it finds relevant memories itself and
    synthesizes an answer using the bank's mission/disposition."""
    try:
        ans = c.reflect(bank_id=bid, query=query, budget=budget)
        return (getattr(ans, "text", "") or "").strip()
    except Exception:
        return ""


def profile(c):
    """'What the board knows about you' — uses Hindsight's native reflect() over the
    shared boardroom (the user's decisions + what advisors said), with a recall+gen fallback."""
    q = ("Write a sharp 4-6 sentence portrait of THE USER, drawn from their decisions, reversals, "
         "recurring priorities, and blind spots in memory. Second person ('You…'). Tell them "
         "something true they never stated outright. No preamble.")
    text = hs_reflect(c, BOARDROOM, q)
    if text and "UNREACHABLE" not in text.upper() and len(text) > 40:
        return text

    # fallback: manual recall + our own synthesis
    snippets = recall_bank(c, BOARDROOM, q, k=10)
    for slug in personas():
        snippets += recall_bank(c, slug, q, k=4)
    seen, uniq = set(), []
    for s in snippets:
        if s[:60] not in seen:
            seen.add(s[:60]); uniq.append(s)
    corpus = "\n".join(f"- {s}" for s in uniq) or "(not enough history yet)"
    return gen(
        "You are the advisory board reflecting on what you collectively know about this user. "
        "From the memory fragments, write a sharp 4-6 sentence portrait: what they consistently "
        "value, patterns in how they decide, any time they reversed themselves, and one blind spot. "
        "Tell them something true they never stated outright. Second person ('You…'). No preamble.",
        f"Memory fragments about the user:\n{corpus}", max_tokens=400)


# ---------------------------------------------------------------- ask (single)
def ask(slug, question):
    c = hs()
    name, take = advisor_take(c, slug, question)
    print(f"\n=== {name} ===\n{take}\n")
    stamp(c, slug, f"On {datetime.now().date()} the user asked: '{question}'. "
                   f"I ({name}) advised: {take[:400]}")
    print(f"[memory updated: {name} remembers this consultation]")


# ---------------------------------------------------------------- team panel
def team(question):
    c = hs()
    slugs = personas()
    print(f"\n### CONSULTING THE BOARD: \"{question}\"\n")

    # Round 1 — each advisor forms a position from memory
    takes = {}
    for slug in slugs:
        name, take = advisor_take(c, slug, question)
        takes[slug] = (name, take)
        print(f"--- {name} ---\n{take}\n")

    # Round 2 — react to the room
    others = "\n".join(f"{takes[s][0]}: {takes[s][1][:300]}" for s in slugs)
    print("\n### SYNTHESIS\n")
    synth = gen(
        "You are the board chair. Summarize where the advisors agree, where they split, and the "
        "core tension. Then list any memory flags (CONTRADICTION/REVISING lines any advisor raised). Be concise.",
        f"Question: {question}\n\nAdvisor positions:\n{others}")
    print(synth)

    # retain the consultation to every advisor's memory
    for slug in slugs:
        name, take = takes[slug]
        stamp(c, slug, f"On {datetime.now().date()} the board was asked: '{question}'. "
                       f"I ({name}) argued: {take[:300]}")
    print(f"\n[memory updated: all {len(slugs)} advisors remember this board session]")


# ---------------------------------------------------------------- record a decision
def decide(decision):
    c = hs()
    for slug in personas():
        stamp(c, slug, f"DECISION by the user on {datetime.now().date()}: {decision}")
    print(f"recorded to all advisors: \"{decision}\"")


# ---------------------------------------------------------------- inspect memory
def memory(slug):
    c = hs()
    try:
        resp = c.list_memories(bank_id=bank_id(slug))
        items = getattr(resp, "items", None) or getattr(resp, "memories", None) or []
        print(f"{slug} remembers {len(items)} things:")
        for m in items:
            d = m if isinstance(m, dict) else (m.to_dict() if hasattr(m, "to_dict") else {})
            print(f"  - [{d.get('fact_type','?')}] {(d.get('text') or '')[:120]}")
    except Exception as e:
        print("error:", e)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "init":
        init()
    elif cmd == "ask":
        ask(sys.argv[2], sys.argv[3])
    elif cmd == "team":
        team(sys.argv[2])
    elif cmd == "decide":
        decide(sys.argv[2])
    elif cmd == "memory":
        memory(sys.argv[2])
    else:
        print("unknown command:", cmd)
