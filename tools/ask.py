"""ask-colleague — consult a distilled persona (synthteam Phase 1-4 logic).

Loads ~/.synthteam/personas/<slug>.md (or counsel/personas/<slug>.md), answers
in first-person grounded in the persona, pushes back where patterns indicate,
and closes with the simulation disclaimer.

Usage: python tools/ask.py <slug> "<question>"
"""

import os
import re
import sys
from pathlib import Path

from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
PERSONAS = ROOT / "personas"
MODEL = os.environ.get("ASK_MODEL", "claude-sonnet-4-6")

SYSTEM = """You are simulating a colleague's reasoning, grounded ONLY in their distilled persona doc.
Capture what they know, believe, and HOW they decide — substance, not voice. Rules:
- Lead with the take, no preamble.
- Show the reasoning: name which decision-making pattern applies.
- Ground every claim in the persona doc. If extrapolating, say so in-frame.
- Push back where their patterns indicate skepticism — surface the objection, don't be agreeable.
- Do NOT mimic phrasing or invent catchphrases. First-person is for perspective, not voice."""


def load_persona(slug: str) -> tuple[str, str]:
    path = PERSONAS / f"{slug}.md"
    if not path.exists():
        print(f"No persona for '{slug}'. Distill one first (tools/distill.py).")
        sys.exit(1)
    text = path.read_text(encoding="utf-8")
    m = re.search(r"display_name:\s*(.+)", text)
    name = m.group(1).strip() if m else slug
    m2 = re.search(r"last_distilled_at:\s*(.+)", text)
    refreshed = m2.group(1).strip() if m2 else "unknown"
    return text, name, refreshed


def ask(slug: str, question: str) -> str:
    persona, name, refreshed = load_persona(slug)
    print(f"Channelling {name}'s persona — a simulation grounded in their Slack history, not the real {name}.\n")
    client = Anthropic(base_url=os.environ.get("LLM_BASE_URL", "http://localhost:8080"),
                       api_key=os.environ.get("LLM_API_KEY", "proxy"))
    resp = client.messages.create(
        model=MODEL, max_tokens=1024, system=SYSTEM,
        messages=[{"role": "user", "content":
                   f"=== PERSONA DOC ===\n{persona}\n=== END ===\n\n"
                   f"Question to answer in first-person as this colleague:\n{question}"}],
    )
    body = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    return f"{body}\n\n— Simulated {name}, distilled from Slack history (refreshed {refreshed}). Verify load-bearing assumptions with the real {name}."


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('usage: python tools/ask.py <slug> "<question>"'); sys.exit(1)
    print(ask(sys.argv[1], sys.argv[2]))
