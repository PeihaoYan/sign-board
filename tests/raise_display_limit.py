"""Raise the local test event's display limit so a full crowd reaches the wall.

Usage:
    python tests/raise_display_limit.py [500]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent / ".probe-data" / "sign-board.sqlite3"


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    connection = sqlite3.connect(DB)
    connection.execute("UPDATE events SET display_limit = ?", (limit,))
    connection.commit()
    rows = connection.execute("SELECT slug, display_limit FROM events").fetchall()
    print(f"events: {rows}")
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
