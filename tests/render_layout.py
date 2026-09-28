"""Draw a picture of an arrangement, so its habit can be seen rather than guessed.

Renders the wall's own layout to a PNG — each signature as a rectangle at its position and size, on
the stage, with the QR card's box outlined — and prints the numbers that describe the pattern: how
much the positions move off a perfect grid, how many signatures share a position, and how regular the
neighbour distances are.

Usage:
    python tests/render_layout.py 200 [--out tests/shots/layout-200.png] [--width 1884] [--height 1044]
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
const qr = %QR%;
const items = Array.from({ length: count }, (_, i) => ({ id: i + 1 }));
const layout = L.computeWallLayout(items, { stageWidth, stageHeight, qr, count });
const m = layout.metrics;
console.log(JSON.stringify({
  strategy: layout.strategy,
  metrics: m,
  stage: [stageWidth, stageHeight],
  box: L.cardBoxInPixels(qr, stageWidth, stageHeight),
  points: layout.bubbles.map((b) => [b.position.x / 100 * stageWidth, b.position.y / 100 * stageHeight]),
}));
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("count", type=int, nargs="?", default=200)
    parser.add_argument("--width", type=int, default=1884)
    parser.add_argument("--height", type=int, default=1044)
    parser.add_argument("--out", default="")
    parser.add_argument("--qr", default="86.5,99.6,68.4,99.6", help="left,right,top,bottom in percent")
    arguments = parser.parse_args()

    left, right, top, bottom = (float(value) for value in arguments.qr.split(","))
    script = (
        NODE_SCRIPT.replace("%WIDTH%", str(arguments.width))
        .replace("%HEIGHT%", str(arguments.height))
        .replace("%COUNT%", str(arguments.count))
        .replace("%QR%", json.dumps({"left": left, "right": right, "top": top, "bottom": bottom}))
    )
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "layout.js"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            ["node", str(path)], capture_output=True, text=True, cwd=str(ROOT), check=True
        )
    report = json.loads(result.stdout)
    points = report["points"]
    metrics = report["metrics"]
    stage_w, stage_h = report["stage"]
    bubble_w, bubble_h = metrics["width"], metrics["height"]
    strategy = report["strategy"]

    # --- how regular is the arrangement? -------------------------------------------------------
    # Off-grid movement: how far each position is from the lattice cell it was dealt to.
    columns = max(2, int(stage_w // bubble_w))
    rows = max(2, int(stage_h // bubble_h))
    pitch_x, pitch_y = stage_w / columns, stage_h / rows
    grid_offsets = []
    for x, y in points:
        column = min(max(int(x // pitch_x), 0), columns - 1)
        row = min(max(int(y // pitch_y), 0), rows - 1)
        grid_offsets.append(
            abs(x - (column + 0.5) * pitch_x) + abs(y - (row + 0.5) * pitch_y)
        )
    mean_offset = sum(grid_offsets) / len(grid_offsets)
    max_offset = max(grid_offsets)

    # Positions shared to the nearest pixel, which is what a viewer sees as "two signatures stacked".
    slots: dict[tuple[int, int], int] = {}
    for x, y in points:
        key = (round(x), round(y))
        slots[key] = slots.get(key, 0) + 1
    shared = [amount for amount in slots.values() if amount > 1]

    # Nearest-neighbour distances: a lattice gives one value, a random spread gives a range.
    distances = []
    for index, (x, y) in enumerate(points):
        nearest = min(
            ((x - other_x) ** 2 + (y - other_y) ** 2) ** 0.5
            for other_index, (other_x, other_y) in enumerate(points)
            if other_index != index
        )
        distances.append(nearest / bubble_w)
    distances.sort()

    print(f"{arguments.count} signatures on {stage_w}x{stage_h}, strategy {strategy}, bubble {bubble_w}x{bubble_h}")
    print(f"  off-grid movement: mean {mean_offset:.1f}px, max {max_offset:.1f}px"
          f" (a pitch of {pitch_x:.1f}x{pitch_y:.1f})")
    print(f"  positions shared by more than one signature: {len(shared)}"
          f" (largest group {max(shared) if shared else 0})")
    print(f"  nearest-neighbour distance in bubble widths:"
          f" min {distances[0]:.2f}, p10 {distances[len(distances) // 10]:.2f},"
          f" median {distances[len(distances) // 2]:.2f}, max {distances[-1]:.2f}")
    # How many distinct columns and rows the positions actually take: a perfect lattice has one
    # bucket per column, a random scatter has many.
    columns_used = len({round(x / 8) for x, _ in points})
    rows_used = len({round(y / 8) for _, y in points})
    print(f"  distinct 8px columns {columns_used} of {columns}, rows {rows_used} of {rows}")

    out = Path(arguments.out) if arguments.out else ROOT / "tests" / "shots" / f"layout-{arguments.count}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    from PIL import Image, ImageDraw

    scale = 1.0
    image = Image.new("RGB", (int(stage_w * scale), int(stage_h * scale)), (16, 32, 48))
    draw = ImageDraw.Draw(image)
    box = report["box"]
    if box:
        draw.rectangle(
            [box["left"], box["top"], box["right"], box["bottom"]],
            outline=(230, 184, 92), width=2,
        )
    for x, y in points:
        draw.rectangle(
            [x - metrics["inkWidth"] / 2, y - metrics["inkHeight"] / 2,
             x + metrics["inkWidth"] / 2, y + metrics["inkHeight"] / 2],
            outline=(236, 240, 245), fill=(60, 78, 96),
        )
    image.save(out)
    print(f"  picture: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
