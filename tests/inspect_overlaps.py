"""Zoom into the closest pairs of an arrangement, to judge them the way an audience would.

A pair of signatures is only a problem when the ink (or the name under it) of one lands on the other,
not when two bounding boxes merely come near each other, so this crops the picture around the worst
pairs at scale and reports the numbers next to them.

Usage:
    python tests/inspect_overlaps.py 500 [--pairs 4] [--zoom 3]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NODE_SCRIPT = """
const fs = require('fs');
const vm = require('vm');
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/wallLayout.js', 'utf8'), sandbox);
const L = sandbox.window.wallLayout;
const stageWidth = %WIDTH%, stageHeight = %HEIGHT%, count = %COUNT%;
const qr = { left: 86.5, right: 99.6, top: 68.4, bottom: 99.6 };
const items = Array.from({ length: count }, (_, i) => ({ id: i + 1 }));
const layout = L.computeWallLayout(items, { stageWidth, stageHeight, qr, count });
console.log(JSON.stringify({
  metrics: layout.metrics,
  points: layout.bubbles.map((b) => [b.item.id, b.position.x / 100 * stageWidth, b.position.y / 100 * stageHeight]),
}));
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("count", type=int, nargs="?", default=500)
    parser.add_argument("--pairs", type=int, default=4)
    parser.add_argument("--zoom", type=int, default=3)
    parser.add_argument("--width", type=int, default=1884)
    parser.add_argument("--height", type=int, default=1044)
    arguments = parser.parse_args()

    script = (
        NODE_SCRIPT.replace("%WIDTH%", str(arguments.width))
        .replace("%HEIGHT%", str(arguments.height))
        .replace("%COUNT%", str(arguments.count))
    )
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "inspect.js"
        path.write_text(script, encoding="utf-8")
        completed = subprocess.run(["node", str(path)], capture_output=True, text=True, cwd=str(ROOT), check=True)
    report = json.loads(completed.stdout)
    metrics = report["metrics"]
    points = report["points"]
    ink_w, ink_h = metrics["inkWidth"], metrics["inkHeight"]
    name_h = metrics["nameSize"] + 4

    # The rectangle a spectator sees: the ink, plus the name line under it.
    def footprint(x, y):
        return (x - ink_w / 2, y - ink_h / 2, x + ink_w / 2, y + ink_h / 2 + name_h)

    pairs = []
    for index, (first_id, x, y) in enumerate(points):
        for other_id, other_x, other_y in points[index + 1:]:
            dx = abs(x - other_x)
            dy = abs(y - other_y)
            if dx < ink_w and dy < ink_h + name_h:
                overlap_w = ink_w - dx
                overlap_h = (ink_h + name_h) - dy
                pairs.append((overlap_w * overlap_h, first_id, other_id, x, y, other_x, other_y, overlap_w, overlap_h))
    pairs.sort(reverse=True)
    print(f"{arguments.count} signatures, bubble {metrics['width']}x{metrics['height']},"
          f" ink {ink_w}x{ink_h} + name {name_h}px")
    print(f"pairs whose visible rectangles intersect: {len(pairs)} of {len(points) * (len(points) - 1) // 2}")
    for entry in pairs[: arguments.pairs]:
        area, first_id, other_id, x, y, other_x, other_y, overlap_w, overlap_h = entry
        fraction = overlap_w * overlap_h / (ink_w * (ink_h + name_h)) * 100
        print(f"  ids {first_id} & {other_id}: centres {abs(x - other_x):.0f}x{abs(y - other_y):.0f}px apart,"
              f" rectangles overlap {overlap_w:.0f}x{overlap_h:.0f}px"
              f" = {fraction:.0f}% of one signature's area, at {x:.0f},{y:.0f}")

    from PIL import Image, ImageDraw

    zoom = arguments.zoom
    tiles = []
    for entry in pairs[: arguments.pairs]:
        _, first_id, other_id, x, y, other_x, other_y, _, _ = entry
        centre_x = (x + other_x) / 2
        centre_y = (y + other_y) / 2
        half_w = metrics["width"] * 1.6
        half_h = metrics["height"] * 1.9
        image = Image.new("RGB", (int(half_w * zoom), int(half_h * zoom)), (16, 32, 48))
        draw = ImageDraw.Draw(image)
        for item_id, point_x, point_y in points:
            if abs(point_x - centre_x) > half_w or abs(point_y - centre_y) > half_h:
                continue
            left = (point_x - ink_w / 2 - (centre_x - half_w)) * zoom
            top = (point_y - ink_h / 2 - (centre_y - half_h)) * zoom
            right = (point_x + ink_w / 2 - (centre_x - half_w)) * zoom
            bottom = (point_y + ink_h / 2 + name_h - (centre_y - half_h)) * zoom
            colour = (255, 120, 90) if item_id in (first_id, other_id) else (120, 140, 160)
            draw.rectangle([left, top, right, bottom], outline=colour, width=2)
            draw.line([left + ink_w * 0.15 * zoom, (top + bottom) / 2 - name_h * zoom / 2,
                       right - ink_w * 0.15 * zoom, (top + bottom) / 2 - name_h * zoom / 2],
                      fill=(245, 245, 245), width=2)
        tiles.append(image)
    if tiles:
        width = max(tile.width for tile in tiles)
        height = sum(tile.height for tile in tiles) + 8 * (len(tiles) - 1)
        sheet = Image.new("RGB", (width, height), (8, 16, 24))
        offset = 0
        for tile in tiles:
            sheet.paste(tile, (0, offset))
            offset += tile.height + 8
        out = ROOT / "tests" / "shots" / f"overlaps-{arguments.count}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out)
        print(f"  picture of the worst pairs, red rectangles: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
