"""Generate a realistic synthetic Slack export (zip) for testing the upload flow.

Creates a fictional SaaS startup ("Lumio") with distinct personalities, real
opinions and decisions, in the standard Slack export format:
  users.json + <channel>/<YYYY-MM-DD>.json   (messages: type/user/text/ts)
Then zips it to counsel/sample_slack_export.zip.

LLM via the antigravity proxy (no Claude-budget hit).

Run: python tools/make_sample_export.py
"""

import json
import os
import re
import zipfile
from pathlib import Path

from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / ".tmp_export"
OUT_ZIP = ROOT / "sample_slack_export.zip"
MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")

client = Anthropic(base_url=os.environ.get("LLM_BASE_URL", "http://localhost:8080"),
                   api_key=os.environ.get("LLM_API_KEY", "proxy"))

PEOPLE = [
    ("U001", "maya",  "Maya Chen",    "Founder/CEO. Growth-hungry, visionary, biased to action, willing to take risks, impatient with caution. Pushes to ship and expand."),
    ("U002", "raj",   "Raj Patel",    "Staff engineer. Reliability-first, skeptical of hype, asks 'what breaks at scale', distrusts rushing, values boring proven tech."),
    ("U003", "tomas", "Tomas Rivera", "Product lead. User-obsessed and data-driven. Wants evidence, runs experiments, frames everything around user pain and metrics."),
    ("U004", "aisha", "Aisha Khan",   "Design lead. Pushes radical simplicity, opinionated on UX, fights feature creep, cares about craft and consistency."),
]
CHANNELS = ["product", "engineering", "strategy", "design"]


def gen_channel(channel: str) -> list:
    roster = "\n".join(f"- {rn} (@{name}): {voice}" for _, name, rn, voice in PEOPLE)
    prompt = (
        f"You are writing a realistic Slack #{channel} channel history for a fictional SaaS analytics "
        f"startup called Lumio. The team:\n{roster}\n\n"
        f"Write ~45 messages of substantive back-and-forth: real opinions, disagreements, decisions, "
        f"trade-offs, technical and product specifics. Each person stays in character and takes consistent "
        f"positions. Avoid greetings/logistics fluff — make every message carry substance (a stance, a "
        f"concern, a proposal, a decision). Spread messages across the four people.\n\n"
        f'Output ONLY a JSON array: [{{"speaker":"<first-name-lowercase>","text":"<message>"}}]'
    )
    r = client.messages.create(model=MODEL, max_tokens=4096,
                               system="You write realistic, in-character workplace chat. Output only JSON.",
                               messages=[{"role": "user", "content": prompt}])
    txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    m = re.search(r"\[.*\]", txt, re.DOTALL)
    return json.loads(m.group(0)) if m else []


def main():
    if OUT_DIR.exists():
        import shutil
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    name_to_id = {name: uid for uid, name, _, _ in PEOPLE}
    users = [{"id": uid, "name": name, "real_name": rn, "deleted": False, "is_bot": False,
              "profile": {"real_name": rn, "display_name": name}} for uid, name, rn, _ in PEOPLE]
    (OUT_DIR / "users.json").write_text(json.dumps(users, indent=2), encoding="utf-8")
    (OUT_DIR / "channels.json").write_text(json.dumps(
        [{"name": c, "id": f"C{i:03d}"} for i, c in enumerate(CHANNELS)], indent=2), encoding="utf-8")

    base = 1709500000  # ~2024-03-04
    counts = {name: 0 for name in name_to_id}
    for ci, channel in enumerate(CHANNELS):
        print(f"generating #{channel}...")
        msgs = gen_channel(channel)
        cdir = OUT_DIR / channel
        cdir.mkdir()
        day_msgs = []
        for j, m in enumerate(msgs):
            sp = (m.get("speaker") or "").lower().strip()
            if sp not in name_to_id:
                continue
            ts = base + ci * 100000 + j * 137
            day_msgs.append({"type": "message", "user": name_to_id[sp],
                             "text": m["text"], "ts": f"{ts}.000100"})
            counts[sp] += 1
        (cdir / "2024-03-04.json").write_text(json.dumps(day_msgs, indent=2), encoding="utf-8")
        print(f"  {len(day_msgs)} messages")

    print("per-person totals:", counts)

    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in OUT_DIR.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(OUT_DIR))
    print(f"\nwrote {OUT_ZIP}  ({OUT_ZIP.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
