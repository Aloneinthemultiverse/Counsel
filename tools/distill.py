"""Distill a synthteam persona doc from raw-messages.jsonl.

Follows synthteam's 5-facet spec (references/distillation-facets.md). The real
plugin fans out subagents per chunk; for our corpus sizes a single strong-model
pass produces the same persona.md structure. LLM via the antigravity proxy
(OpenAI-compatible at localhost:8080).

Usage: python tools/distill.py <slug> [<slug> ...]
       python tools/distill.py --all
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("SYNTHTEAM_HOME", str(Path.home() / ".synthteam")))
PERSONAS = ROOT / "personas"

PROXY_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8080")
MODEL = os.environ.get("DISTILL_MODEL", "claude-sonnet-4-6")

FACET_SPEC = """\
Produce a persona doc capturing WHAT this person knows, WHAT they believe, and HOW they decide
— substance, not voice. Third-person observational prose. NO verbatim quotes. Use exactly this
Markdown structure with these five facets:

## At a glance
2-4 sentences: what they do, what they care about, the shape of decisions they own.

## Strategic priorities & recurring themes
4-8 bullets: what they push for repeatedly, defend, or dismiss. Repetition = priority.

## Specific opinions & positions
Grouped by topic. Concrete stances — what they champion / oppose. Name tensions, don't smooth them.

## Decision-making patterns
6-10 short paragraphs on HOW they reason: reframes they reach for, disqualifying questions they
ask, what bar they set, tolerance for ambiguity, what makes them trust someone's call.

## Domain knowledge
Grouped by domain: topics where they bring real working knowledge (not just restating others).

## Network & operational context
People they work with, projects they track, external entities they reference.

## Known gaps
Topics the messages are silent on — load-bearing for honest 'ask-colleague' use.

Rules: every claim must be defensible from the messages. A position stated once is a hint; stated
several times is a pattern. If signal is thin on a facet, say so explicitly. Keep it ~2-4K tokens.
"""


def load_messages(slug: str):
    adir = HOME / "assets" / slug
    meta = json.loads((adir / "metadata.json").read_text(encoding="utf-8"))
    msgs = []
    for line in (adir / "raw-messages.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            msgs.append(f"[#{r['channel_name']}] {r['text']}")
    return meta, msgs


def distill(slug: str, client: OpenAI) -> Path:
    meta, msgs = load_messages(slug)
    corpus = "\n".join(msgs)
    if len(corpus) > 48000:                 # keep prompt bounded
        corpus = corpus[:48000]
    prompt = (
        f"{FACET_SPEC}\n\n"
        f"Colleague: {meta['real_name']} (@{meta['user_name']}). "
        f"{meta['total_messages']} messages across {len(meta['channels'])} channels.\n\n"
        f"=== MESSAGES ===\n{corpus}\n=== END ==="
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system="You are a careful analyst distilling a colleague persona from their chat history. Substance, not style. No verbatim quotes.",
        messages=[{"role": "user", "content": prompt}],
    )
    body = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    front = (
        f"---\nslug: {slug}\ndisplay_name: {meta['real_name'].split()[0]}\n"
        f"real_name: {meta['real_name']}\n"
        f"distilled_from:\n  total_messages: {meta['total_messages']}\n"
        f"  channel_count: {len(meta['channels'])}\n  source: {meta.get('source','')}\n"
        f"last_distilled_at: {datetime.now(timezone.utc).isoformat()}\n---\n\n"
    )
    PERSONAS.mkdir(exist_ok=True)
    out = PERSONAS / f"{slug}.md"
    out.write_text(front + body + "\n", encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    slugs = args.slugs
    if args.all:
        slugs = [p.name for p in (HOME / "assets").iterdir() if p.is_dir()]
    if not slugs:
        print("give slugs or --all"); sys.exit(1)

    client = Anthropic(base_url=PROXY_URL, api_key=os.environ.get("LLM_API_KEY", "proxy"))
    for slug in slugs:
        print(f"distilling {slug}...")
        out = distill(slug, client)
        print(f"  -> {out}  ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
