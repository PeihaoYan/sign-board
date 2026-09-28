"""Try candidate-scoring rules for the crowded spread and measure each one.

The crowded placement draws random candidates and picks one per signature. "First candidate that
clears every neighbour by the required spacing" is simple but takes the first adequate spot, which
leaves signatures bunched against the stage edges and lets pairs sit closer than they need to. This
compares that rule against rules that score candidates by spacing, distance from the wall and
distance from the stage edge, so the change is chosen from numbers rather than taste.

Usage:
    python tests/tune_scatter.py [--count 200,500] [--width 1884] [--height 1044]
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Each rule is a body for one candidate's score; the harness supplies the variables.
RULES = {
    "first adequate": "if (gap >= 0.98 && edge >= 28) { chosen = {x, y, gap, score: 0}; break; }",
    "best gap": "const score = gap;",
    "gap + wall": "const score = gap + 0.35 * wall;",
    "gap + wall + edge": "const score = gap + 0.35 * wall + 0.30 * edge;",
    "gap + wall + edge, strict tie": "const score = gap + 0.45 * wall + 0.35 * edge;",
}

NODE_PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/wallLayout.js', 'utf8'), sandbox);
const L = sandbox.window.wallLayout;
const stageWidth = %WIDTH%, stageHeight = %HEIGHT%, count = %COUNT%;
const qr = { left: 86.5, right: 99.6, top: 68.4, bottom: 99.6 };
const items = Array.from({ length: count }, (_, i) => ({ id: i + 1 }));
const probes = L.computeWallLayout(items, { stageWidth, stageHeight, qr, count }).bubbles.map((b) => [
  b.item.id, b.position.x / 100 * stageWidth, b.position.y / 100 * stageHeight, b.position.rotation,
]);
const metrics = L.metricsFor(count, { stageWidth, stageHeight });
const box = L.cardBoxInPixels(qr, stageWidth, stageHeight);

function hash(value) {
  let result = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    result ^= value.charCodeAt(index);
    result = Math.imul(result, 16777619);
  }
  return result >>> 0;
}
const ratio = (seed, salt) => (hash(`${seed}:${salt}`) % 100000) / 100000;

const cellWidth = metrics.width, cellHeight = metrics.height;
const grid = new Map();
const cellOf = (x, y) => Math.floor(x / cellWidth) + ':' + Math.floor(y / cellHeight);
const addPoint = (x, y) => {
  const key = cellOf(x, y);
  if (!grid.has(key)) grid.set(key, []);
  grid.get(key).push({ x, y });
};
function nearest(x, y) {
  let best = Infinity;
  const c0 = Math.floor(x / cellWidth) - 3, c1 = Math.floor(x / cellWidth) + 3;
  const r0 = Math.floor(y / cellHeight) - 3, r1 = Math.floor(y / cellHeight) + 3;
  for (let c = c0; c <= c1; c += 1) for (let r = r0; r <= r1; r += 1) {
    const bucket = grid.get(c + ':' + r);
    if (!bucket) continue;
    for (const p of bucket) {
      const d = Math.hypot((x - p.x) / metrics.width, (y - p.y) / metrics.height);
      if (d < best) best = d;
    }
  }
  return best;
}
const marginX = metrics.width / 2 + 2, marginY = metrics.height / 2 + 2;
const spanX = stageWidth - marginX * 2, spanY = stageHeight - marginY * 2;
const overlapsCard = (x, y) => x + metrics.width / 2 + 12 > box.left && x - metrics.width / 2 - 12 < box.right
  && y + metrics.height / 2 + 12 > box.top && y - metrics.height / 2 - 12 < box.bottom;

%RULE%

const result = [];
probes.forEach(([id, nominalX, nominalY, rotation]) => {
  const seed = id + ':' + (id - 1);
  let chosen = null;
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const x = marginX + ratio(seed, 'sx' + attempt) * spanX;
    const y = marginY + ratio(seed, 'sy' + attempt) * spanY;
    if (overlapsCard(x, y)) continue;
    const gap = nearest(x, y);
    const wall = Math.hypot((x - nominalX) / metrics.width, (y - nominalY) / metrics.height);
    const edge = Math.min(x - marginX, stageWidth - marginX - x, y - marginY, stageHeight - marginY - y) / Math.max(metrics.width, metrics.height);
    %SCORE%
  }
  const position = chosen || { x: nominalX, y: nominalY };
  addPoint(position.x, position.y);
  result.push([id, position.x, position.y, rotation]);
});
console.log(JSON.stringify({ metrics, box, points: result }));
"""


def measure(points, metrics, box, stage_w, stage_h) -> dict:
    bubble_w, bubble_h = metrics["width"], metrics["height"]
    minimum = math.inf
    overlaps = 0
    for index, (_, x, y, _rotation) in enumerate(points):
        for other_index, (_, other_x, other_y, _rotation) in enumerate(points):
            if other_index <= index:
                continue
            dx = abs(x - other_x) / bubble_w
            dy = abs(y - other_y) / bubble_h
            distance = math.hypot(dx, dy)
            physical = math.hypot(x - other_x, y - other_y) / ((bubble_w + bubble_h) / 2)
            minimum = min(minimum, physical)
            if dx < 1 and dy < 1:
                overlaps += 1
    edge_margin = min(
        min(min(x, stage_w - x, y, stage_h - y) for _, x, y, _ in points) / bubble_w,
        math.inf,
    )
    on_card = sum(
        1 for _, x, y, _ in points
        if box["left"] < x < box["right"] and box["top"] < y < box["bottom"]
    )
    # How many signatures sit in the central half of the stage: a uniform spread puts a quarter there,
    # and a spread that clings to the edges puts far fewer.
    central = sum(
        1 for _, x, y, _ in points
        if stage_w * 0.25 < x < stage_w * 0.75 and stage_h * 0.25 < y < stage_h * 0.75
    )
    return {
        "min physical separation (bubble widths)": round(minimum, 2),
        "overlapping pairs": overlaps,
        "edge inset (bubble widths)": round(edge_margin, 2),
        "central quarter share": round(central / len(points) * 100, 1),
        "on card": on_card,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", default="200,500")
    parser.add_argument("--width", type=int, default=1884)
    parser.add_argument("--height", type=int, default=1044)
    arguments = parser.parse_args()

    for count_text in arguments.count.split(","):
        count = int(count_text)
        print(f"=== {count} signatures on {arguments.width}x{arguments.height} ===")
        for label, body in RULES.items():
            rule = ""
            score = ""
            if body.startswith("if ("):
                rule = "const gap = 0; const wall = 0; const edge = 0;"
                score = body
            else:
                rule = "let chosen = null; let best = -Infinity;"
                score = (
                    body.replace("const score =", "const score =")
                    + " if (chosen === null || score > best) { best = score; chosen = { x, y, gap, score }; }"
                )
            program = (
                NODE_PROGRAM.replace("%WIDTH%", str(arguments.width))
                .replace("%HEIGHT%", str(arguments.height))
                .replace("%COUNT%", str(count))
                .replace("%RULE%", rule)
                .replace("%SCORE%", score)
            )
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "tune.js"
                path.write_text(program, encoding="utf-8")
                completed = subprocess.run(
                    ["node", str(path)], capture_output=True, text=True, cwd=str(ROOT)
                )
            if completed.returncode != 0:
                print(f"  {label}: node failed: {completed.stderr.strip()[:200]}")
                continue
            report = json.loads(completed.stdout)
            stats = measure(report["points"], report["metrics"], report["box"], arguments.width, arguments.height)
            print(f"  {label:<26} " + "  ".join(f"{key} {value}" for key, value in stats.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
