"""Measure the real signatures: their own size, their point spacing, and the pen they were written with.

Everything the keepsake picture does — how much to shrink a signature, how thick to draw its line —
has to come from the data the phones actually sent, not from an assumed size. This reports the
bounding box of every signature, the median gap between consecutive points, and the stroke width the
live wall would give the same signature, so the picture can match the wall's pen weight.

Usage:
    python tools/measure_signatures.py [--count 8]
"""

from __future__ import annotations

import argparse
import json
import statistics
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The wall's own numbers: static/wallLayout.js and static/display.js.
WALL_STAGE = (1884, 1044)
REFERENCE_STAGE = (1920, 1080)
BASE_INK_WIDTH, BASE_INK_HEIGHT = 136, 88
INK_SIZE_FACTOR = 0.74
SCALE_LADDER = [(40, 1.0), (90, 0.8), (160, 0.7), (260, 0.6), (400, 0.5), (10**9, 0.45)]


def wall_ink_box(count: int) -> tuple[float, float]:
    crowd = next(scale for up_to, scale in SCALE_LADDER if count <= up_to)
    stage = min(WALL_STAGE[0] / REFERENCE_STAGE[0], WALL_STAGE[1] / REFERENCE_STAGE[1])
    scale = crowd * stage
    return BASE_INK_WIDTH * scale * INK_SIZE_FACTOR, BASE_INK_HEIGHT * scale * INK_SIZE_FACTOR


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=8)
    arguments = parser.parse_args()

    token = (ROOT / ".secrets" / "admin-token.txt").read_text(encoding="utf-8").strip()
    request = urllib.request.Request(
        "http://127.0.0.1:18180/api/admin/events/integrity-2026/submissions",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        rows = json.load(response).get("items", [])
    signatures = [row for row in rows if row.get("status") == "approved" and row.get("strokes")]

    box_w, box_h = wall_ink_box(len(signatures))
    print(f"the wall draws {len(signatures)} signatures in a {box_w:.0f}x{box_h:.0f} px ink box")

    extents = []
    spacings = []
    for row in signatures:
        strokes = [stroke for stroke in row["strokes"] if len(stroke) > 1]
        xs = [p[0] for stroke in strokes for p in stroke]
        ys = [p[1] for stroke in strokes for p in stroke]
        width, height = max(xs) - min(xs), max(ys) - min(ys)
        gaps = [
            ((stroke[i + 1][0] - stroke[i][0]) ** 2 + (stroke[i + 1][1] - stroke[i][1]) ** 2) ** 0.5
            for stroke in strokes for i in range(len(stroke) - 1)
        ]
        extents.append((width, height))
        spacings.extend(gaps)
        # The scale the wall gives this signature, and the pen it draws it with.
        scale = min(box_w / max(width, 1), box_h / max(height, 1))
        print(
            f"  {row['name']:<8} strokes {len(strokes):>2}  bbox {width:>6.0f}x{height:>5.0f}"
            f"  median point gap {statistics.median(gaps):>5.1f} px"
            f"  wall scale {scale:.3f}  wall pen {3.2 * scale:.2f} px"
        )

    widths = [w for w, _ in extents]
    heights = [h for _, h in extents]
    print()
    print(f"bounding boxes: width median {statistics.median(widths):.0f} (min {min(widths):.0f}, max {max(widths):.0f})"
          f" | height median {statistics.median(heights):.0f} (min {min(heights):.0f}, max {max(heights):.0f})")
    print(f"median gap between recorded points: {statistics.median(spacings):.2f} px")
    full_scale = min(box_w / max(widths), box_h / max(heights))
    print(f"scale that fits the largest signature into the wall's ink box: {full_scale:.3f}")
    print(f"the wall's pen at that scale: {3.2 * full_scale:.2f} px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
