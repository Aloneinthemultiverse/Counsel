"""Counsel web app — FastAPI backend wrapping the board engine.

Sync endpoints (run in threadpool) so the sync Hindsight client doesn't clash
with the event loop. Serves the single-page UI in web/index.html.

Run: .venv\\Scripts\\python -m uvicorn web:app --host 0.0.0.0 --port 8200
"""

import io
import os
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import json as _json

from fastapi import Body, FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

import board

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from tools import slack_to_synth as s2s
from tools import distill_fanout as df

app = FastAPI(title="Counsel")

FLAG_RE = re.compile(r"^(CONTRADICTION|REVISING):", re.MULTILINE)


def flags_in(text: str) -> list:
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("CONTRADICTION:") or s.startswith("REVISING:"):
            out.append(s)
    return out


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/board")
def board_state():
    c = board.hs()
    advisors = []
    for slug in board.personas():
        name, glance, _ = board.load_persona(slug)
        try:
            resp = c.list_memories(bank_id=board.bank_id(slug))
            items = getattr(resp, "items", None) or getattr(resp, "memories", None) or []
            n = len(items)
        except Exception:
            n = 0
        advisors.append({"slug": slug, "name": name, "glance": glance, "remembers": n})
    return JSONResponse({"advisors": advisors})


@app.post("/api/ask")
def ask(body: dict = Body(...)):
    slug = body["slug"]
    question = body["question"].strip()
    c = board.hs()
    remembered = board.remember_from_message(c, question)   # auto-memory
    name, take = board.advisor_take(c, slug, question)
    board.stamp(c, slug, f"On {datetime.now().date()} the user asked: '{question}'. "
                         f"I ({name}) advised: {take[:400]}")
    board.board_write(c, f"{name} advised on '{question[:80]}': {take[:200]}")
    return JSONResponse({"name": name, "take": take, "flags": flags_in(take), "remembered": remembered})


@app.post("/api/profile")
def profile():
    return JSONResponse({"profile": board.profile(board.hs())})


def _safe_cfg():
    c = dict(board.LLM_CFG)
    c["api_key"] = "•••" if c.get("api_key") else ""
    return c


@app.get("/api/llm-config")
def llm_config_get():
    return JSONResponse({"config": _safe_cfg()})


@app.post("/api/llm-config")
def llm_config_set(body: dict = Body(...)):
    board.set_llm(provider=body.get("provider"), base_url=body.get("base_url"),
                  api_key=body.get("api_key"), model=body.get("model"))
    test = board.gen("You reply with exactly: OK", "ping", max_tokens=10)
    ok = ("OK" in test.upper()) and ("UNREACHABLE" not in test.upper())
    return JSONResponse({"config": _safe_cfg(), "ok": ok, "test": test[:100]})


@app.post("/api/llm-reset")
def llm_reset():
    board.set_llm(provider=os.environ.get("LLM_PROVIDER", "anthropic"),
                  base_url=os.environ.get("LLM_BASE_URL", "http://localhost:8080"),
                  api_key=os.environ.get("LLM_API_KEY", "proxy"),
                  model=os.environ.get("MODEL", "claude-sonnet-4-6"))
    return JSONResponse({"config": _safe_cfg(), "ok": True})


# ---------------- conversational boardroom chat ----------------
CONVO_FILE = ROOT / ".tmp" / "conversations.json"


def _load_convos() -> dict:
    try:
        return _json.loads(CONVO_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_convos():
    CONVO_FILE.parent.mkdir(exist_ok=True)
    CONVO_FILE.write_text(_json.dumps(CONVOS), encoding="utf-8")


CONVOS: dict = _load_convos()


def _title(thread):
    for m in thread:
        if m.get("role") == "user":
            return m["text"][:50]
    return "New conversation"


@app.post("/api/chat/new")
def chat_new():
    n = 1
    while f"c{n}" in CONVOS:
        n += 1
    cid = f"c{n}"
    CONVOS[cid] = []
    _save_convos()
    return JSONResponse({"id": cid})


@app.get("/api/chats")
def chats_list():
    items = [{"id": cid, "title": _title(t), "count": len(t)} for cid, t in CONVOS.items() if t]
    return JSONResponse({"chats": list(reversed(items))})


@app.get("/api/chat/{cid}")
def chat_get(cid: str):
    return JSONResponse({"thread": CONVOS.get(cid, [])})


def _sse(obj) -> str:
    return f"data: {_json.dumps(obj)}\n\n"


@app.post("/api/chat/{cid}/send")
async def chat_send(cid: str, body: dict = Body(...)):
    msg = (body.get("message") or "").strip()
    thread = CONVOS.setdefault(cid, [])

    async def stream():
        c = board.hs()
        remembered = await run_in_threadpool(board.remember_from_message, c, msg)
        thread.append({"role": "user", "name": "You", "text": msg})
        if remembered:
            yield _sse({"type": "remembered", "text": remembered})

        targets = board.parse_targets(msg)
        # Round 1 — each addressed advisor replies, streamed one at a time
        for slug in targets:
            name = board.display_name(slug)
            yield _sse({"type": "typing", "slug": slug, "name": name})
            name, take = await run_in_threadpool(board.chat_reply, c, slug, list(thread), msg, False)
            thread.append({"role": slug, "name": name, "text": take})
            await run_in_threadpool(board.stamp, c, slug, f"In chat the user said '{msg[:80]}'. I ({name}) replied: {take[:200]}")
            await run_in_threadpool(board.board_write, c, f"{name} said in chat: {take[:200]}")
            yield _sse({"type": "message", "slug": slug, "name": name, "text": take, "flags": flags_in(take)})

        # Round 2 — light cross-talk when the whole board was addressed (cap to 2 for speed)
        if len(targets) > 1:
            for slug in targets[:2]:
                name = board.display_name(slug)
                yield _sse({"type": "typing", "slug": slug, "name": name, "react": True})
                name, take = await run_in_threadpool(board.chat_reply, c, slug, list(thread), msg, True)
                if take and len(take) > 15:
                    thread.append({"role": slug, "name": name, "text": take})
                    yield _sse({"type": "message", "slug": slug, "name": name, "text": take, "flags": flags_in(take), "react": True})

        _save_convos()
        yield _sse({"type": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/chat/{cid}/decision")
def session_decision(cid: str):
    """End-of-session weighted board decision over the whole conversation."""
    thread = CONVOS.get(cid, [])
    if len(thread) < 2:
        return JSONResponse({"error": "Not enough discussion yet — debate something first."}, status_code=400)
    c = board.hs()
    d = board.session_decision(thread)
    if d.get("decision"):
        board.board_write(c, f"END-OF-SESSION DECISION: {d['decision']}. {d.get('rationale','')}")
        thread.append({"role": "chair", "name": "Board decision", "text": d["decision"]})
    return JSONResponse(d)


@app.post("/api/evolve")
def evolve():
    changes = board.evolve(board.hs())
    return JSONResponse({"changes": changes})


@app.get("/api/graph")
def graph():
    """Who-told-whom: how advisor points flowed through the boardroom into decisions."""
    c = board.hs()
    try:
        resp = c.list_memories(bank_id=board.BOARDROOM)
        items = getattr(resp, "items", None) or getattr(resp, "memories", None) or []
        texts = []
        for m in items:
            d = m if isinstance(m, dict) else (m.to_dict() if hasattr(m, "to_dict") else {})
            texts.append(d.get("text") or "")
    except Exception:
        texts = []

    advisors = [{"slug": s, "name": board.display_name(s)} for s in board.personas()]
    first_names = {a["name"].split()[0].lower(): a for a in advisors}

    contrib = {a["name"]: 0 for a in advisors}     # advisor -> boardroom
    decided = {a["name"]: 0 for a in advisors}     # advisor -> decision (cited in a decision)
    decisions = []
    for t in texts:
        low = t.lower()
        is_decision = "decision" in low[:40]
        for fn, a in first_names.items():
            if fn in low:
                if is_decision:
                    decided[a["name"]] += 1
                else:
                    contrib[a["name"]] += 1
        if is_decision:
            decisions.append(t[:160])

    return JSONResponse({
        "advisors": [a["name"] for a in advisors],
        "contrib": contrib,            # advisor -> boardroom weight
        "decided": decided,            # advisor -> decision weight
        "decisions": decisions[:3],
        "total_memories": len(texts),
    })


@app.get("/api/persona/{slug}")
def persona(slug: str):
    path = ROOT / "personas" / f"{slug}.md"
    if not path.exists():
        return JSONResponse({"error": "no persona"}, status_code=404)
    doc = path.read_text(encoding="utf-8")
    body = doc.split("---", 2)[-1]
    name = board.display_name(slug)
    sections = []
    for chunk in re.split(r"\n## ", "\n" + body):
        chunk = chunk.strip()
        if not chunk:
            continue
        title, _, rest = chunk.partition("\n")
        sections.append({"title": title.lstrip("# ").strip(), "body": rest.strip()})
    return JSONResponse({"slug": slug, "name": name, "sections": sections})

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/team")
def team(body: dict = Body(...)):
    question = body["question"].strip()
    c = board.hs()
    remembered = board.remember_from_message(c, question)   # auto-memory
    slugs = board.personas()
    takes = []
    all_flags = []
    for slug in slugs:
        name, take = board.advisor_take(c, slug, question)
        f = flags_in(take)
        all_flags += [f"{name}: {x}" for x in f]
        board.board_write(c, f"{name} argued on '{question[:80]}': {take[:200]}")
        takes.append({"slug": slug, "name": name, "take": take, "flags": f})

    others = "\n".join(f"{t['name']}: {t['take'][:300]}" for t in takes)
    flag_note = ("\n\nMemory flags raised by advisors:\n" + "\n".join(all_flags)) if all_flags else ""
    synthesis = board.gen(
        "You are the board chair. Summarize where advisors agree, where they split, and the core "
        "tension. Then echo any memory flags (contradictions/revisions) you are given. Be concise.",
        f"Question: {question}\n\nPositions:\n{others}{flag_note}")

    devil = board.devils_advocate(question, others)

    for t in takes:
        board.stamp(c, t["slug"], f"On {datetime.now().date()} the board was asked: '{question}'. "
                                  f"I ({t['name']}) argued: {t['take'][:300]}")
    return JSONResponse({"takes": takes, "synthesis": synthesis, "flags": all_flags,
                         "remembered": remembered, "devil": devil})


@app.post("/api/decide")
def decide(body: dict = Body(...)):
    decision = body["decision"].strip()
    c = board.hs()
    for slug in board.personas():
        board.stamp(c, slug, f"DECISION by the user on {datetime.now().date()}: {decision}")
    return JSONResponse({"ok": True, "decision": decision})


def _find_export_root(base: Path) -> Path:
    """Locate the dir holding users.json (or org_users.json) in an extracted export."""
    for fn in ("users.json", "org_users.json"):
        if (base / fn).exists():
            return base
        for p in base.rglob(fn):
            return p.parent
    return base


@app.post("/api/upload")
def upload(file: UploadFile = File(...)):
    """Accept a real Slack export (.zip), parse it, return detected people."""
    tmp = Path(tempfile.mkdtemp(prefix="counsel_"))
    try:
        data = file.file.read()
        name = (file.filename or "").lower()
        if name.endswith(".zip") or data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extractall(tmp)
        else:
            return JSONResponse({"error": "Please upload a Slack export .zip (with users.json)."}, status_code=400)

        root = _find_export_root(tmp)
        if not s2s.users_file(root):
            return JSONResponse({"error": "No users.json / org_users.json found — that doesn't look like a Slack export."}, status_code=400)

        users = s2s.load_users(root)
        by_user = s2s.collect(root, users)
        ranked = sorted(by_user.items(), key=lambda kv: len(kv[1]), reverse=True)
        ranked = [(u, r) for u, r in ranked if len(r) >= s2s.MIN_MESSAGES]
        if not ranked:
            return JSONResponse({"error": "No users with enough substantive messages to distill."}, status_code=400)

        detected = []
        for uid, recs in ranked[:8]:
            slug = s2s.write_assets(uid, recs, users)
            detected.append({"slug": slug, "name": users[uid]["real_name"], "msgs": len(recs)})
        return JSONResponse({"detected": detected})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


SAMPLE_EXPORT = Path(r"C:\Users\Sujit Narrayan M\Downloads\slack-data")


@app.post("/api/sample")
def sample():
    """Ingest the bundled houstondatavis sample export."""
    root = _find_export_root(SAMPLE_EXPORT)
    if not s2s.users_file(root):
        return JSONResponse({"error": "sample export not found"}, status_code=404)
    users = s2s.load_users(root)
    by_user = s2s.collect(root, users)
    ranked = sorted(by_user.items(), key=lambda kv: len(kv[1]), reverse=True)
    ranked = [(u, r) for u, r in ranked if len(r) >= s2s.MIN_MESSAGES]
    detected = []
    for uid, recs in ranked[:8]:
        slug = s2s.write_assets(uid, recs, users)
        detected.append({"slug": slug, "name": users[uid]["real_name"], "msgs": len(recs)})
    return JSONResponse({"detected": detected})


@app.post("/api/build")
def build(body: dict = Body(...)):
    """Wipe old advisors, distill the selected people, create their memory banks."""
    slugs = body.get("slugs", [])
    if not slugs:
        return JSONResponse({"error": "no advisors selected"}, status_code=400)
    c = board.hs()
    # 1. clear previous data
    for old in board.personas():
        try:
            c.delete_bank(bank_id=board.bank_id(old))
        except Exception:
            pass
    for p in board.PERSONAS.glob("*.md"):
        p.unlink()
    # 2. distill the selected people (synth fanout)
    for slug in slugs:
        df.distill(slug)
    # 3. create + seed their Hindsight banks
    board.init()
    return JSONResponse({"ok": True, "built": slugs})


@app.get("/api/memory/{slug}")
def memory(slug: str):
    c = board.hs()
    try:
        resp = c.list_memories(bank_id=board.bank_id(slug))
        items = getattr(resp, "items", None) or getattr(resp, "memories", None) or []
        out = []
        for m in items:
            d = m if isinstance(m, dict) else (m.to_dict() if hasattr(m, "to_dict") else {})
            out.append({"type": d.get("fact_type") or d.get("type") or "?",
                        "text": d.get("text") or ""})
        return JSONResponse({"slug": slug, "count": len(out), "items": out})
    except Exception as e:
        return JSONResponse({"slug": slug, "count": 0, "items": [], "error": str(e)})
