"""Seed the local test wall with generated signatures.

Usage:
    python tests/seed_local_wall.py 200 [--base http://127.0.0.1:18195] [--slug integrity-2026]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import urllib.request
from pathlib import Path

DB = Path(__file__).resolve().parent / ".probe-data" / "sign-board.sqlite3"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("count", type=int, nargs="?", default=200)
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    arguments = parser.parse_args()

    connection = sqlite3.connect(DB)
    existing = connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
    connection.close()
    missing = max(0, arguments.count - existing)
    print(f"existing rows: {existing}, adding: {missing}")

    for index in range(missing):
        rng = random.Random(5000 + index)
        strokes = []
        for line in range(rng.randint(1, 3)):
            points = []
            for step in range(rng.randint(18, 36)):
                x = 12 + step * rng.uniform(6, 13)
                y = 60 + line * 42 + math.sin((step + index) / rng.uniform(2.0, 4.0)) * rng.uniform(10, 20)
                points.append([int(x), int(y)])
            strokes.append(points)
        body = json.dumps(
            {
                "name": f"参与者{index + 1:03d}",
                "strokes": strokes,
                "device_token": f"seed-local-{index}",
            }
        ).encode()
        request = urllib.request.Request(
            f"{arguments.base}/api/events/{arguments.slug}/submissions",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(request, timeout=15).read()

    connection = sqlite3.connect(DB)
    connection.execute("UPDATE submissions SET status = 'approved'")
    connection.commit()
    approved = connection.execute(
        "SELECT COUNT(*) FROM submissions WHERE status = 'approved'"
    ).fetchone()[0]
    connection.close()
    print(f"approved: {approved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
