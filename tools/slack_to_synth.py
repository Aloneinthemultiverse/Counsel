"""Convert a raw Slack export into synthteam's ingestion format.

Reads a standard Slack export (users.json + per-channel folders of daily JSON),
groups substantive messages by user, ranks users by volume, and writes
synthteam-format assets for the top users:

  <SYNTHTEAM_HOME>/assets/<slug>/raw-messages.jsonl   (one standalone record/line)
  <SYNTHTEAM_HOME>/assets/<slug>/metadata.json

Usage:
  python tools/slack_to_synth.py --export ../slack-data --top 4 --rank-only
  python tools/slack_to_synth.py --export ../slack-data --users niik,zach,kyle
"""

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SKIP_SUBTYPES = {"channel_join", "channel_leave", "bot_message", "channel_topic",
                 "channel_purpose", "channel_name", "pinned_item"}
MIN_LEN = 25          # ignore very short / low-signal messages
MIN_MESSAGES = 30     # a user needs at least this many to be distillable


def home() -> Path:
    return Path(os.environ.get("SYNTHTEAM_HOME", str(Path.home() / ".synthteam")))


def users_file(export: Path):
    """Standard exports use users.json; enterprise/org exports use org_users.json."""
    for fn in ("users.json", "org_users.json"):
        if (export / fn).exists():
            return export / fn
    return None


def load_users(export: Path) -> dict:
    uf = users_file(export)
    users = json.loads(uf.read_text(encoding="utf-8")) if uf else []
    out = {}
    for u in users:
        out[u["id"]] = {
            "name": u.get("name", u["id"]),
            "real_name": (u.get("real_name") or u.get("profile", {}).get("real_name")
                          or u.get("name", u["id"])),
            "is_bot": u.get("is_bot", False) or u.get("deleted", False),
        }
    return out


def channel_dirs(export: Path) -> list:
    return [p for p in export.iterdir() if p.is_dir() and not p.name.startswith(".")]


def collect(export: Path, users: dict):
    """Return {user_id: [records...]} in synth standalone shape.

    Reconstructs thread context: a reply gets a short '[re: <parent>]' prefix so
    the distiller understands what the person was responding to."""
    by_user = defaultdict(list)
    for ch in channel_dirs(export):
        all_msgs = []
        for day in sorted(ch.glob("*.json")):
            try:
                all_msgs.extend(json.loads(day.read_text(encoding="utf-8")))
            except Exception:
                continue
        # index every message in the channel by its timestamp (for thread parents)
        ts_text = {m["ts"]: (m.get("text") or "") for m in all_msgs if m.get("ts")}

        for m in all_msgs:
            if m.get("type") != "message" or m.get("subtype") in SKIP_SUBTYPES:
                continue
            uid = m.get("user")
            text = (m.get("text") or "").strip()
            if not uid or uid not in users or users[uid]["is_bot"]:
                continue
            clean = re.sub(r"<[^>]+>", "", text).strip()
            if len(clean) < MIN_LEN:
                continue
            # if this is a reply in a thread, prepend the parent message as context
            tts = m.get("thread_ts")
            kind = "standalone"
            if tts and tts != m.get("ts") and tts in ts_text:
                parent = re.sub(r"<[^>]+>", "", ts_text[tts]).strip()
                if parent:
                    text = f"[re: {parent[:90]}] {text}"
                    kind = "thread_reply"
            by_user[uid].append({
                "kind": kind,
                "channel_name": ch.name,
                "ts": m.get("ts"),
                "user": uid,
                "user_name": users[uid]["name"],
                "text": text,
            })
    return by_user


def write_assets(uid: str, records: list, users: dict) -> str:
    # base slug from the Slack handle (usually unique); fall back to real name
    base = re.sub(r"[^a-z0-9]+", "", users[uid]["name"].lower()) \
        or re.sub(r"[^a-z0-9]+", "", users[uid]["real_name"].lower()) or uid.lower()
    slug, i = base, 2
    # ensure uniqueness: if this slug's assets belong to a DIFFERENT user, bump it
    while True:
        meta_path = home() / "assets" / slug / "metadata.json"
        if not meta_path.exists():
            break
        try:
            if json.loads(meta_path.read_text(encoding="utf-8")).get("user_id") == uid:
                break
        except Exception:
            break
        slug = f"{base}{i}"
        i += 1
    adir = home() / "assets" / slug
    adir.mkdir(parents=True, exist_ok=True)
    with open(adir / "raw-messages.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    channels = defaultdict(int)
    for r in records:
        channels[r["channel_name"]] += 1
    meta = {
        "slug": slug,
        "user_id": uid,
        "user_name": users[uid]["name"],
        "real_name": users[uid]["real_name"],
        "dumped_at": datetime.now(timezone.utc).isoformat(),
        "total_messages": len(records),
        "total_threads": 0,
        "channels": [{"name": c, "message_count": n} for c, n in channels.items()],
        "excludes": ["dms", "short_messages", "bots", "join/leave"],
        "source": "houstondatavis/slack-export (public)",
    }
    (adir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return slug


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True)
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--rank-only", action="store_true")
    ap.add_argument("--users", help="comma-separated usernames to write (overrides --top)")
    args = ap.parse_args()

    export = Path(args.export).resolve()
    users = load_users(export)
    by_user = collect(export, users)

    ranked = sorted(by_user.items(), key=lambda kv: len(kv[1]), reverse=True)
    ranked = [(uid, recs) for uid, recs in ranked if len(recs) >= MIN_MESSAGES]

    print(f"{len(users)} users in export; {len(ranked)} have >= {MIN_MESSAGES} substantive msgs\n")
    print("Top candidates:")
    for uid, recs in ranked[:15]:
        print(f"  {users[uid]['name']:<20} {len(recs):>5} msgs   ({users[uid]['real_name']})")

    if args.rank_only:
        return

    if args.users:
        want = {u.strip().lower() for u in args.users.split(",")}
        chosen = [(uid, recs) for uid, recs in ranked if users[uid]["name"].lower() in want]
    else:
        chosen = ranked[: args.top]

    print("\nWriting assets:")
    for uid, recs in chosen:
        slug = write_assets(uid, recs, users)
        print(f"  -> {home() / 'assets' / slug}  ({len(recs)} msgs)")


if __name__ == "__main__":
    main()
