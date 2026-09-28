"""Set the event display limit (used to raise the wall to 500 signatures)."""

from __future__ import annotations

import sqlite3
import sys

DB = "/opt/sign-board/data/sign-board.sqlite3"


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    connection = sqlite3.connect(DB)
    connection.execute("UPDATE events SET display_limit = ?", (limit,))
    connection.commit()
    print("display_limit", connection.execute("SELECT display_limit FROM events").fetchone()[0])
    print("submissions", connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0])
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
