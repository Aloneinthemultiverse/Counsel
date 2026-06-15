"""Counsel MCP server — let Claude Code / Cursor consult your advisory board.

The board is distilled from your team's Slack and remembers every decision via
Hindsight. Through MCP, a coding agent can ask the board for a take, get a
weighted decision, record a commitment, or pull the board's profile of you —
all sharing the same persistent memory as the Counsel web app.

Run (stdio):  python mcp_server.py
Add to Claude Code:
  claude mcp add counsel -- "C:/.../lifecycle-memory/.venv/Scripts/python.exe" "C:/.../counsel/mcp_server.py"
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP
import board

mcp = FastMCP("counsel")


def _slug(name: str):
    n = (name or "").strip().lower()
    for s in board.personas():
        if s == n or board.display_name(s).split()[0].lower() == n:
            return s
    return None


@mcp.tool()
def list_advisors() -> str:
    """List the advisory board members with a one-line description of each."""
    rows = []
    for s in board.personas():
        name, glance, _ = board.load_persona(s)
        rows.append(f"- {name}: {glance[:130]}")
    return "Your advisory board (distilled from your team's Slack):\n" + "\n".join(rows)


@mcp.tool()
def ask_advisor(advisor: str, question: str) -> str:
    """Ask ONE advisor (by first name, e.g. 'Maya') for their take, grounded in
    their persona and their memory of your team and past decisions."""
    s = _slug(advisor)
    if not s:
        return f"No advisor named '{advisor}'. Call list_advisors first."
    c = board.hs()
    board.remember_from_message(c, question)
    name, take = board.advisor_take(c, s, question)
    board.stamp(c, s, f"Via MCP the user asked: '{question[:80]}'. I replied: {take[:200]}")
    return f"{name}: {take}"


@mcp.tool()
def consult_board(question: str) -> str:
    """Ask the WHOLE board a question. Returns every advisor's take. They reason
    from memory of your team's Slack and your past decisions."""
    c = board.hs()
    board.remember_from_message(c, question)
    out = []
    for s in board.personas():
        name, take = board.advisor_take(c, s, question)
        board.stamp(c, s, f"Via MCP board consult: '{question[:80]}'. I argued: {take[:200]}")
        board.board_write(c, f"{name} said: {take[:200]}")
        out.append(f"### {name}\n{take}")
    return "\n\n".join(out)


@mcp.tool()
def board_decision(question: str) -> str:
    """Consult the board AND return a weighted decision scorecard: the strategies
    argued, scored across weighted criteria, with a recommended winner."""
    c = board.hs()
    board.remember_from_message(c, question)
    thread = [{"role": "user", "name": "You", "text": question}]
    for s in board.personas():
        name, take = board.advisor_take(c, s, question)
        thread.append({"role": s, "name": name, "text": take})
    d = board.session_decision(thread)
    if d.get("error"):
        return "Could not produce a decision from the discussion."
    lines = [f"DECISION: {d['decision']}", d.get("rationale", ""), "", "Weighted scorecard:"]
    for o in d["options"]:
        mark = "  <- winner" if o == d.get("winner") else ""
        lines.append(f"  {o}: {d['totals'].get(o)}{mark}")
    board.board_write(c, f"Board decision (MCP): {d['decision']}")
    return "\n".join(lines)


@mcp.tool()
def record_decision(decision: str) -> str:
    """Record a decision to the board's memory so the advisors remember it and can
    flag it if you later contradict yourself."""
    c = board.hs()
    for s in board.personas():
        board.stamp(c, s, f"DECISION by the user: {decision}")
    board.board_write(c, f"DECISION: {decision}")
    return f"Recorded to the board's memory: {decision}"


@mcp.tool()
def what_board_knows() -> str:
    """Return the board's synthesized profile of you — values, patterns, blind
    spots — built from everything it has accumulated in memory."""
    return board.profile(board.hs())


if __name__ == "__main__":
    mcp.run()
