"""Replace the current board with the Lumio synthetic startup (debate-ready).

Extracts sample_slack_export.zip -> writes assets -> distills the 4 personas ->
clears old advisors -> creates fresh banks + the shared boardroom.
"""

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import slack_to_synth as s2s
from tools import distill_fanout as df
import board

OLD = ["neerajt", "micahstubbs", "javier", "colinnlsn", "jkim"]


def main():
    zip_path = ROOT / "sample_slack_export.zip"
    tmp = ROOT / ".tmp_lumio"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    root = tmp if (tmp / "users.json").exists() else next(tmp.rglob("users.json")).parent

    users = s2s.load_users(root)
    by_user = s2s.collect(root, users)
    ranked = sorted(by_user.items(), key=lambda kv: len(kv[1]), reverse=True)
    ranked = [(u, r) for u, r in ranked if len(r) >= s2s.MIN_MESSAGES]
    slugs = []
    for uid, recs in ranked[:4]:
        slugs.append(s2s.write_assets(uid, recs, users))
    print("assets written:", slugs)

    # clear old persona files
    for p in board.PERSONAS.glob("*.md"):
        p.unlink()

    # distill the new board
    for s in slugs:
        print("distilling", s, "...")
        df.distill(s)

    # delete every old advisor bank, then create fresh banks + boardroom
    c = board.hs()
    for old in OLD:
        try:
            c.delete_bank(bank_id=board.bank_id(old))
        except Exception:
            pass
    board.init()
    print("LUMIO BOARD READY:", board.personas())


if __name__ == "__main__":
    main()
