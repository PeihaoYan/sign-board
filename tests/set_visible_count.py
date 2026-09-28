"""Toggle how many signatures are visible on the local test wall.

Usage:
    python tests/set_visible_count.py 60        # keep the newest 60 approved
    python tests/set_visible_count.py all       # restore every signature
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent / ".probe-data" / "sign-board.sqlite3"


def main() -> int:
    connection = sqlite3.connect(DB)
    if len(sys.argv) > 1 and sys.argv[1] != "all":
        keep = int(sys.argv[1])
        connection.execute(
            """
            UPDATE submissions SET status = CASE
                WHEN id IN (SELECT id FROM submissions ORDER BY id LIMIT ?) THEN 'approved'
                ELSE 'hidden'
            END
            """,
            (keep,),
        )
    else:
        connection.execute("UPDATE submissions SET status = 'approved'")
    connection.commit()
    approved = connection.execute(
        "SELECT COUNT(*) FROM submissions WHERE status = 'approved'"
    ).fetchone()[0]
    print(f"approved: {approved}")
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
