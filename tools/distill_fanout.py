"""Distill a persona using synthteam's REAL multi-stage fanout pipeline.

Faithful to references/distillation-facets.md:
  Stage 1 (workers):  split raw-messages.jsonl into chunks; each chunk -> one
                      worker call that emits per-facet findings (claim+evidence).
  Stage 2 (reducers): one call per facet; dedupe + synthesize all workers'
                      findings for that facet into the section.
  Stage 3 (assemble): orchestrator writes 'At a glance' + 'Known gaps' +
                      frontmatter, joins the 5 sections -> personas/<slug>.md

Runs on the antigravity proxy (Anthropic-style at localhost:8080) so it does not
consume the main Claude budget. Handles arbitrarily large corpora (chunked).

Usage: python tools/distill_fanout.py <slug> [<slug> ...]   |   --all
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("SYNTHTEAM_HOME", str(Path.home() / ".synthteam")))
PERSONAS = ROOT / "personas"
MODEL = os.environ.get("DISTILL_MODEL", "claude-sonnet-4-6")
CHUNK = int(os.environ.get("CHUNK_SIZE", "100"))   # records per worker

FACETS = {
    "priorities": "Strategic priorities & recurring themes — what they push for repeatedly, defend, dismiss.",
    "positions": "Specific opinions & positions — concrete stances they champion or oppose.",
    "decisions": "Decision-making patterns — HOW they reason: reframes, disqualifying questions, what bar they set, trust signals.",
    "domain": "Domain knowledge — topics where they bring real working knowledge, not just restating others.",
    "network": "Network & operational context — people they work with, projects, external entities.",
}
SECTION_TITLE = {
    "priorities": "Strategic priorities & recurring themes",
    "positions": "Specific opinions & positions",
    "decisions": "Decision-making patterns",
    "domain": "Domain knowledge",
    "network": "Network & operational context",
}

client = Anthropic(base_url=os.environ.get("LLM_BASE_URL", "http://localhost:8080"),
                   api_key=os.environ.get("LLM_API_KEY", "proxy"))


def llm(system: str, user: str, max_tokens: int = 2000) -> str:
    r = client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                               messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()


def load(slug: str):
    adir = HOME / "assets" / slug
    meta = json.loads((adir / "metadata.json").read_text(encoding="utf-8"))
    recs = [json.loads(l) for l in (adir / "raw-messages.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return meta, recs


def chunks(recs, n):
    for i in range(0, len(recs), n):
        yield recs[i:i + n]


WORKER_SYS = ("You extract persona evidence from a chunk of one HUMAN colleague's chat messages. "
              "The subject is a person on a team — NEVER an AI assistant; never describe yourself "
              "or any AI product. Emit findings for EVERY facet you see signal for. NEVER quote "
              "message text — describe patterns in indirect prose. Output ONLY a JSON array.")


def worker(chunk, person="this colleague") -> list:
    facet_list = "\n".join(f"- {k}: {v}" for k, v in FACETS.items())
    lines = "\n".join(f"[#{r.get('channel_name','?')} {r.get('ts','')}] {r['text']}" for r in chunk)
    prompt = (
        f"These are chat messages written by {person} (a human colleague). Extract evidence about "
        f"{person} only.\n\nFacets:\n{facet_list}\n\n"
        f'Output a JSON array of findings: [{{"facet":"<id>","claim":"<one line, no quotes>",'
        f'"evidence":[{{"channel":"<name>","date":"<ts>"}}]}}]\n\n'
        f"=== MESSAGES ===\n{lines}\n=== END ===\nJSON only:"
    )
    for attempt in range(3):
        out = llm(WORKER_SYS, prompt, max_tokens=2500)
        out = re.sub(r"^```(?:json)?|```$", "", out.strip(), flags=re.MULTILINE).strip()
        m = re.search(r"\[.*\]", out, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                if data:
                    return data
            except Exception:
                # salvage individual objects
                objs = re.findall(r"\{[^{}]*\}", m.group(0))
                parsed = []
                for o in objs:
                    try:
                        parsed.append(json.loads(o))
                    except Exception:
                        pass
                if parsed:
                    return parsed
        # retry with a firmer nudge
        prompt += "\n\nIMPORTANT: respond with ONLY a valid JSON array, nothing else."
    return []


REDUCER_SYS = ("You synthesize one persona facet from many extracted findings. Dedupe overlapping "
               "claims (merge evidence). Third-person observational prose. NO verbatim quotes. "
               "Every claim MUST end with its evidence pointer(s) in the form [#channel, date] — "
               "copy them from the findings; keep the 1-3 strongest. Output only the section body.")


def _ev(f: dict) -> str:
    out = []
    for e in (f.get("evidence") or [])[:3]:
        ch = e.get("channel", "?")
        dt = str(e.get("date", ""))[:10]
        out.append(f"[#{ch}, {dt}]")
    return " ".join(out)


def reducer(facet: str, findings: list) -> str:
    rows = [f"- {f.get('claim','')}  {_ev(f)}" for f in findings if f.get("facet") == facet]
    blob = "\n".join(rows)
    if not blob.strip():
        return "_Limited signal on this facet in the available messages._"
    prompt = (f"Facet: {SECTION_TITLE[facet]} — {FACETS[facet]}\n\n"
              f"Findings (claim followed by its evidence pointers):\n{blob}\n\n"
              f"Synthesize into the section. Keep an evidence pointer [#channel, date] on each claim. "
              f"A claim seen many times = a pattern; once = a hint (say so).")
    return llm(REDUCER_SYS, prompt, max_tokens=1800)


def distill(slug: str) -> Path:
    meta, recs = load(slug)
    print(f"  {slug}: {len(recs)} msgs -> {((len(recs)-1)//CHUNK)+1} chunks")
    findings = []
    for i, ch in enumerate(chunks(recs, CHUNK)):
        f = worker(ch, meta["real_name"])
        findings.extend(f)
        print(f"    worker {i+1}: {len(f)} findings")
    sections = {}
    for facet in FACETS:
        sections[facet] = reducer(facet, findings)
        print(f"    reduced: {facet}")

    person = meta["real_name"]
    glance = llm(
        f"You write a 2-4 sentence summary of a HUMAN colleague named {person}. "
        f"Third person, no quotes. {person} is a person on a team — NEVER an AI assistant. "
        f"Never describe yourself, an AI, or any product. Write only about {person}.",
        f"From {person}'s persona sections below, write their 'At a glance' (2-4 sentences "
        f"describing {person} the person):\n\n"
        + "\n\n".join(f"## {SECTION_TITLE[k]}\n{sections[k]}" for k in FACETS),
        max_tokens=400)
    gaps = llm("You list topics the messages are silent on. Terse bullets.",
               f"Channels: {[c['name'] for c in meta['channels']]}. "
               f"Given the sections below, list 2-4 'Known gaps' for someone in this role:\n\n"
               + sections["domain"], max_tokens=300)

    front = (f"---\nslug: {slug}\ndisplay_name: {meta['real_name'].split()[0]}\n"
             f"real_name: {meta['real_name']}\ndistilled_from:\n"
             f"  total_messages: {meta['total_messages']}\n  channel_count: {len(meta['channels'])}\n"
             f"  method: synthteam-fanout (workers+reducers)\n  source: {meta.get('source','')}\n"
             f"last_distilled_at: {datetime.now(timezone.utc).isoformat()}\n---\n\n")
    body = f"# {meta['real_name']} — Persona\n\n## At a glance\n{glance}\n\n"
    for k in FACETS:
        body += f"## {SECTION_TITLE[k]}\n{sections[k]}\n\n"
    body += f"## Known gaps\n{gaps}\n"

    PERSONAS.mkdir(exist_ok=True)
    out = PERSONAS / f"{slug}.md"
    out.write_text(front + body, encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    slugs = [p.name for p in (HOME / "assets").iterdir() if p.is_dir()] if args.all else args.slugs
    if not slugs:
        print("give slugs or --all"); sys.exit(1)
    for slug in slugs:
        print(f"distilling {slug} (fanout)...")
        out = distill(slug)
        print(f"  -> {out} ({out.stat().st_size} bytes)\n")


if __name__ == "__main__":
    main()
