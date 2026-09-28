"""Restore every signature in the local test database and make them all visible.

After a run of the verification scripts the wall may hold only a handful of signatures, because
they hide rows to set up specific cases. This puts the local wall back to its full set.

Usage:
    python tests/restore_local_wall.py [--limit 500]
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / ".probe-data" / "sign-board.sqlite3"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500)
    arguments = parser.parse_args()

    connection = sqlite3.connect(DB)
    connection.execute("UPDATE events SET display_limit = ?", (arguments.limit,))
    connection.execute("UPDATE submissions SET status = 'approved'")
    connection.commit()
    limit = connection.execute("SELECT display_limit FROM events").fetchone()[0]
    approved = connection.execute(
        "SELECT COUNT(*) FROM submissions WHERE status = 'approved'"
    ).fetchone()[0]
    connection.close()
    print(f"display_limit={limit} approved={approved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
