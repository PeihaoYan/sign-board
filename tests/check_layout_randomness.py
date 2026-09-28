"""Check that a crowded wall looks scattered rather than laid out on a grid.

The wall puts 60 or more signatures out with a random spread and a minimum spacing. Two things can go
wrong and both have happened:

* the spread stops being random — a jittered lattice was used at one point, and because the jitter
  could only ever be as large as the slack between a bubble and its cell (1.7 px across, 1.6 px down
  at 200 signatures), every signature sat within about a pixel of its cell centre and the wall read
  as a grid with holes in it;
* the spread stops being even — pure random placement piles signatures on each other at a few
  hundred of them (333 pairs closer than 0.6 bubble widths at 200 signatures).

So this measures both, in browser-less Node against the real `wallLayout.js`: how far positions move
off a lattice, how many distinct rows and columns they occupy, and how close the closest pair gets.

Usage:
    python tests/check_layout_randomness.py [--width 1884] [--height 1044] [--base <url>]

With `--base` the module is fetched from that server instead of read from the working tree, which
checks the deployment rather than the checkout.

Usage:
    python tests/check_layout_randomness.py [--width 1884] [--height 1044]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NODE_PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const sandbox = { window: {} };
vm.createContext(sandbox);
const source = %SOURCE%;
vm.runInContext(source, sandbox);
const L = sandbox.window.wallLayout;
const stageWidth = %WIDTH%, stageHeight = %HEIGHT%;
const qr = { left: 86.5, right: 99.6, top: 68.4, bottom: 99.6 };
const out = {};
[60, 100, 200, 300, 500].forEach((count) => {
  const items = Array.from({ length: count }, (_, i) => ({ id: i + 1 }));
  const started = Date.now();
  const layout = L.computeWallLayout(items, { stageWidth, stageHeight, qr, count });
  const buildMs = Date.now() - started;
  const m = layout.metrics;
  const points = layout.bubbles.map((b) => [b.position.x / 100 * stageWidth, b.position.y / 100 * stageHeight]);

  // How far each position sits from the centre of the lattice cell it falls in. A lattice layout
  // leaves this near zero whatever its jitter is; a scatter spreads it over the cell.
  const columns = Math.max(2, Math.floor(stageWidth / m.width));
  const rows = Math.max(2, Math.floor(stageHeight / m.height));
  const pitchX = stageWidth / columns;
  const pitchY = stageHeight / rows;
  let offsetSum = 0;
  points.forEach(([x, y]) => {
    const column = Math.min(Math.max(Math.floor(x / pitchX), 0), columns - 1);
    const row = Math.min(Math.max(Math.floor(y / pitchY), 0), rows - 1);
    offsetSum += Math.abs(x - (column + 0.5) * pitchX) + Math.abs(y - (row + 0.5) * pitchY);
  });

  // Distinct 4px tracks: a lattice uses one per column and one per row.
  const trackX = new Set(points.map(([x]) => Math.round(x / 4)));
  const trackY = new Set(points.map(([, y]) => Math.round(y / 4)));

  let closest = Infinity;
  let overlapping = 0;
  for (let i = 0; i < points.length; i += 1) {
    for (let j = i + 1; j < points.length; j += 1) {
      const dx = Math.abs(points[i][0] - points[j][0]) / m.width;
      const dy = Math.abs(points[i][1] - points[j][1]) / m.height;
      const distance = Math.hypot(dx, dy);
      if (distance < closest) closest = distance;
      if (dx < 0.5 && dy < 0.5) overlapping += 1;
    }
  }
  out[count] = {
    strategy: layout.strategy,
    buildMs,
    bubble: [m.width, m.height],
    meanOffGrid: Number((offsetSum / points.length).toFixed(1)),
    pitch: [Number(pitchX.toFixed(1)), Number(pitchY.toFixed(1))],
    tracksX: trackX.size,
    tracksY: trackY.size,
    columns,
    rows,
    closest: Number(closest.toFixed(2)),
    stacked: overlapping,
  };
});
console.log(JSON.stringify(out));
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=1884)
    parser.add_argument("--height", type=int, default=1044)
    parser.add_argument("--base", default="", help="fetch wallLayout.js from this server")
    arguments = parser.parse_args()

    if arguments.base:
        source = urllib.request.urlopen(
            f"{arguments.base}/assets/wallLayout.js", timeout=30
        ).read().decode("utf-8")
        print(f"checking {arguments.base}/assets/wallLayout.js ({len(source)} bytes)")
    else:
        source = (ROOT / "static" / "wallLayout.js").read_text(encoding="utf-8")

    program = (
        NODE_PROGRAM.replace("%WIDTH%", str(arguments.width))
        .replace("%HEIGHT%", str(arguments.height))
        .replace("%SOURCE%", json.dumps(source))
    )
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "randomness.js"
        path.write_text(program, encoding="utf-8")
        completed = subprocess.run(["node", str(path)], capture_output=True, text=True, cwd=str(ROOT))
    if completed.returncode != 0:
        print("node failed:", completed.stderr.strip()[:400])
        return 1
    report = json.loads(completed.stdout)

    failures: list[str] = []
    for count_text, row in report.items():
        print(
            f"{count_text:>4} signatures ({row['strategy']}): bubble {row['bubble'][0]}x{row['bubble'][1]}"
            f"  off-grid {row['meanOffGrid']}px of a {row['pitch'][0]}x{row['pitch'][1]} pitch"
            f"  tracks {row['tracksX']}x{row['tracksY']} (a grid has {row['columns']}x{row['rows']})"
            f"  closest pair {row['closest']} bubbles  stacked {row['stacked']}"
            f"  built in {row['buildMs']}ms"
        )
        # A scatter has to move well off the lattice, and to use far more tracks than a lattice has
        # columns and rows.
        if row["meanOffGrid"] < max(row["pitch"]) * 0.15:
            failures.append(
                f"{count_text} signatures: positions stay {row['meanOffGrid']}px off a lattice pitch of"
                f" {row['pitch']}, which reads as a grid"
            )
        if row["tracksX"] < row["columns"] * 2 or row["tracksY"] < row["rows"] * 2:
            failures.append(
                f"{count_text} signatures: only {row['tracksX']}x{row['tracksY']} distinct tracks against"
                f" {row['columns']}x{row['rows']} lattice cells"
            )
        # And it still has to keep the signatures apart.
        if row["closest"] < 0.6:
            failures.append(f"{count_text} signatures: the closest pair is {row['closest']} bubbles apart")
        if row["stacked"]:
            failures.append(f"{count_text} signatures: {row['stacked']} pairs sit within half a bubble")
        if row["buildMs"] > 700:
            failures.append(f"{count_text} signatures: laying the wall out took {row['buildMs']}ms")

    for failure in failures:
        print(f"FAIL: {failure}")
    print(f"failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
