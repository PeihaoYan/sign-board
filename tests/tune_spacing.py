"""Find the spacing that keeps the drawn signatures off each other.

The placement spaces signature *centres* by one bubble in each direction, but what a spectator sees
is the ink plus the name under it, and the name hangs below the ink. Two centres a bubble apart
vertically therefore still put one signature's name on the ink of the one below — measured at 500
signatures: 272 ink-on-ink and 201 name-on-ink collisions. This measures the collisions for several
spacings, in the units the drawn rectangles actually need, so the spacing can be chosen from numbers.

Usage:
    python tests/tune_spacing.py [--count 200,500] [--width 1884] [--height 1044]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NODE_PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/wallLayout.js', 'utf8'), sandbox);
const L = sandbox.window.wallLayout;
const stageWidth = %WIDTH%, stageHeight = %HEIGHT%, count = %COUNT%;
const qr = { left: 86.5, right: 99.6, top: 68.4, bottom: 99.6 };
const names = ['张三','李四','王五','欧阳雨辰','李','赵钱孙','Alexander'];
const items = Array.from({ length: count }, (_, i) => ({ id: i + 1, name: names[i % names.length] }));
const metrics = L.metricsFor(count, { stageWidth, stageHeight });
const box = L.cardBoxInPixels(qr, stageWidth, stageHeight);

// The rectangles a spectator sees for one signature at (x, y).
function footprints(x, y, name) {
  const chinese = (name.match(/[\u4e00-\u9fff]/g) || []).length;
  const nameWidth = chinese * metrics.nameSize + (name.length - chinese) * metrics.nameSize * 0.55;
  const inkTop = y - metrics.inkHeight / 2;
  const inkBottom = y + metrics.inkHeight / 2;
  return {
    ink: [x - metrics.inkWidth / 2, inkTop, x + metrics.inkWidth / 2, inkBottom],
    name: [x - nameWidth / 2, inkBottom + 2, x + nameWidth / 2, inkBottom + 2 + metrics.nameSize],
  };
}
const hit = (a, b) => a[0] < b[2] && a[2] > b[0] && a[1] < b[3] && a[3] > b[1];
function collisions(placed) {
  let inkOnInk = 0, nameOnInk = 0;
  for (let i = 0; i < placed.length; i += 1) for (let j = i + 1; j < placed.length; j += 1) {
    if (hit(placed[i].ink, placed[j].ink)) inkOnInk += 1;
    if (hit(placed[i].name, placed[j].ink) || hit(placed[j].name, placed[i].ink)) nameOnInk += 1;
  }
  return { inkOnInk, nameOnInk };
}

// The public entry point, so the real arrangement is the one measured.
const layout = L.computeWallLayout(items, { stageWidth, stageHeight, qr, count });
const placed = layout.bubbles.map(({ item, position }) =>
  footprints(position.x / 100 * stageWidth, position.y / 100 * stageHeight, item.name));
const result = collisions(placed);

// How far apart the closest centres are, in the units the drawn rectangles occupy.
let minX = Infinity, minY = Infinity;
for (let i = 0; i < placed.length; i += 1) for (let j = i + 1; j < placed.length; j += 1) {
  const ax = (placed[i].ink[0] + placed[i].ink[2]) / 2, ay = (placed[i].ink[1] + placed[i].ink[3]) / 2;
  const bx = (placed[j].ink[0] + placed[j].ink[2]) / 2, by = (placed[j].ink[1] + placed[j].ink[3]) / 2;
  minX = Math.min(minX, Math.abs(ax - bx) / metrics.inkWidth);
  minY = Math.min(minY, Math.abs(ay - by) / (metrics.inkHeight + metrics.nameSize));
}
console.log(JSON.stringify({
  metrics, strategy: layout.strategy, ...result,
  minGapInInkWidths: Number(minX.toFixed(2)),
  minGapInInkPlusName: Number(minY.toFixed(2)),
}));
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", default="100,200,300,500")
    parser.add_argument("--width", type=int, default=1884)
    parser.add_argument("--height", type=int, default=1044)
    arguments = parser.parse_args()

    for count_text in arguments.count.split(","):
        count = int(count_text)
        program = (
            NODE_PROGRAM.replace("%WIDTH%", str(arguments.width))
            .replace("%HEIGHT%", str(arguments.height))
            .replace("%COUNT%", str(count))
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "spacing.js"
            path.write_text(program, encoding="utf-8")
            completed = subprocess.run(["node", str(path)], capture_output=True, text=True, cwd=str(ROOT))
        if completed.returncode != 0:
            print(f"{count}: node failed: {completed.stderr.strip()[:300]}")
            continue
        report = json.loads(completed.stdout)
        metrics = report["metrics"]
        print(
            f"{count:>4} signatures  bubble {metrics['width']}x{metrics['height']}"
            f"  ink {metrics['inkWidth']}x{metrics['inkHeight']}  name {metrics['nameSize']}px"
            f"  | ink over ink {report['inkOnInk']:>4}  name over ink {report['nameOnInk']:>4}"
            f"  | closest centres {report['minGapInInkWidths']} ink widths, {report['minGapInInkPlusName']} ink+name"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
