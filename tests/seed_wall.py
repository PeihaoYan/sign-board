"""Seed a wall with N generated signatures so the display path can be timed.

Run on the application host:
    sudo -u signboard /opt/sign-board/.venv/bin/python seed_wall.py 500
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
import sys
import time

DB = "/opt/sign-board/data/sign-board.sqlite3"


def strokes_for(seed: int, index: int) -> list[list[list[int]]]:
    rng = random.Random(seed)
    strokes = []
    for line in range(rng.randint(1, 3)):
        points = []
        for step in range(rng.randint(20, 45)):
            x = 10 + step * rng.uniform(6, 14)
            y = 60 + line * 40 + math.sin((step + seed) / rng.uniform(2.0, 4.0)) * rng.uniform(10, 22)
            points.append([int(x), int(y)])
        strokes.append(points)
    return strokes


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    connection = sqlite3.connect(DB)
    connection.execute("DELETE FROM submissions")
    event_id = connection.execute("SELECT id FROM events ORDER BY id LIMIT 1").fetchone()[0]
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    rows = [
        (
            event_id,
            f"嘉宾{index:03d}",
            "",
            "",
            "",
            json.dumps(strokes_for(index, index), separators=(",", ":")),
            f"seed-{index}",
            "approved",
            now,
            now,
        )
        for index in range(1, count + 1)
    ]
    connection.executemany(
        """
        INSERT INTO submissions
            (event_id, name, organization, message, signature_data, stroke_data, device_hash, status, created_at, approved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    connection.commit()
    total = connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
    average_points = connection.execute(
        "SELECT AVG(LENGTH(stroke_data)) FROM submissions"
    ).fetchone()[0]
    connection.close()
    print("rows", total, "average_stroke_json_length", round(average_points or 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
