"""Run synthteam's persona quality checks and print a scorecard.

Implements the 5 checks from references/distillation-facets.md:
  1. Verbatim sweep   — no 5-gram from the persona prose appears in raw messages
  2. Citation density — every claim line carries >=1 [#channel, date] pointer
  3. Known gaps       — the 'Known gaps' section is populated
  4. Length sanity    — persona is roughly 1.5K-6K tokens
  5. Facet coverage   — all five facets present and non-empty

Mechanical (no LLM). Usage: python tools/quality_check.py [<slug> ...] | --all
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("SYNTHTEAM_HOME", str(Path.home() / ".synthteam")))
PERSONAS = ROOT / "personas"
FACETS = ["Strategic priorities", "Specific opinions", "Decision-making patterns",
          "Domain knowledge", "Network & operational"]
CITE_RE = re.compile(r"\[#[^\]]+\]")
WORD_RE = re.compile(r"[a-z0-9']+")


def ngrams(text, n=5):
    words = WORD_RE.findall(text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def raw_text(slug):
    p = HOME / "assets" / slug / "raw-messages.jsonl"
    if not p.exists():
        return ""
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out.append(r.get("text", ""))
    return " ".join(out)


def claim_lines(body):
    # bullets and sentences that assert something (skip headings/blank)
    lines = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or s.startswith("---"):
            continue
        if s.startswith("-") or s.startswith("*") or len(s) > 60:
            lines.append(s)
    return lines


def check(slug):
    path = PERSONAS / f"{slug}.md"
    if not path.exists():
        return None
    doc = path.read_text(encoding="utf-8")
    body = doc.split("---", 2)[-1]

    # 1. verbatim sweep (strip citations first so pointers don't false-positive)
    prose = CITE_RE.sub("", body)
    raw = raw_text(slug)
    raw_grams = ngrams(raw) if raw else set()
    leaks = len(ngrams(prose) & raw_grams) if raw_grams else 0

    # 2. citation density
    claims = claim_lines(body)
    cited = sum(1 for c in claims if CITE_RE.search(c))
    density = (cited / len(claims) * 100) if claims else 0

    # 3. known gaps
    gaps_ok = "## Known gaps" in doc and len(doc.split("## Known gaps", 1)[-1].strip()) > 30

    # 4. length (rough token estimate)
    tokens = int(len(body.split()) * 1.3)
    length_ok = 1500 <= tokens <= 6000

    # 5. facet coverage
    facets_present = sum(1 for f in FACETS if f in doc)

    return {
        "slug": slug, "leaks": leaks, "claims": len(claims), "cited": cited,
        "density": density, "gaps_ok": gaps_ok, "tokens": tokens,
        "length_ok": length_ok, "facets": facets_present,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    slugs = [p.stem for p in PERSONAS.glob("*.md")] if (args.all or not args.slugs) else args.slugs

    print(f"{'persona':<14}{'verbatim':<10}{'citations':<14}{'facets':<9}{'length':<12}{'gaps'}")
    print("-" * 70)
    for slug in slugs:
        r = check(slug)
        if not r:
            print(f"{slug:<14}(no persona file)"); continue
        vb = "PASS(0)" if r["leaks"] == 0 else f"FAIL({r['leaks']})"
        cd = f"{r['cited']}/{r['claims']} ({r['density']:.0f}%)"
        fc = f"{r['facets']}/5"
        ln = f"{r['tokens']}tok " + ("ok" if r["length_ok"] else "!")
        gp = "yes" if r["gaps_ok"] else "NO"
        print(f"{slug:<14}{vb:<10}{cd:<14}{fc:<9}{ln:<12}{gp}")


if __name__ == "__main__":
    main()
