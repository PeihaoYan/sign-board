"""Inspect the transform the export itself installs when it draws a signature.

Runs the monitor page's export, intercepts the first stroke that is issued, and reports the matrix
in effect at that moment together with the bubble box and the stroke bounds. That is where the
"ink is drawn too small" question is decided.

Usage:
    python tests/check_export_transform.py [--base http://127.0.0.1:18195] [--slug integrity-2026]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobile_probe import DevTools, start_edge  # noqa: E402

PROBE = """(async () => {
  const captured = [];
  const realStroke = CanvasRenderingContext2D.prototype.stroke;
  CanvasRenderingContext2D.prototype.stroke = function () {
    if (captured.length < 3) {
      const matrix = this.getTransform();
      captured.push({
        matrix: [matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f],
        lineWidth: this.lineWidth,
        canvas: [this.canvas.width, this.canvas.height],
      });
    }
    return realStroke.apply(this, arguments);
  };
  let rendered;
  try {
    rendered = await window.wallExport.renderWallPng({ slug: '%SLUG%' });
  } finally {
    CanvasRenderingContext2D.prototype.stroke = realStroke;
  }
  const metrics = window.wallLayout.metricsFor(rendered.geometry.count || rendered.items.length, { stageWidth: rendered.stage.logicalWidth, stageHeight: rendered.stage.logicalHeight });
  const item = rendered.items[0];
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const stroke of item.strokes || []) {
    for (const point of stroke) {
      if (point[0] < minX) minX = point[0];
      if (point[0] > maxX) maxX = point[0];
      if (point[1] < minY) minY = point[1];
      if (point[1] > maxY) maxY = point[1];
    }
  }
  return JSON.stringify({
    ratio: rendered.ratio,
    canvas: [rendered.canvas.width, rendered.canvas.height],
    metrics,
    firstItemId: String(item.id),
    strokeBounds: [minX, minY, maxX, maxY],
    captured,
  });
})()"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--key", default="probe-monitor")
    arguments = parser.parse_args()

    port = 19259
    profile = Path(tempfile.mkdtemp(prefix="edge-extf-"))
    process = start_edge(port, profile)
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)
        devtools.call(
            "Emulation.setDeviceMetricsOverride",
            width=1920,
            height=1080,
            deviceScaleFactor=1,
            mobile=False,
        )
        devtools.call("Page.navigate", url=f"{arguments.base}/display")
        time.sleep(3)
        devtools.call(
            "Page.navigate",
            url=f"{arguments.base}/monitor?key={arguments.key}&event={arguments.slug}",
        )
        time.sleep(2.5)

        result = json.loads(devtools.evaluate(PROBE.replace("%SLUG%", arguments.slug)))
        print(
            f"export canvas {result['canvas']} ratio {result['ratio']:.4f}"
            f" metrics ink {result['metrics']['inkWidth']}x{result['metrics']['inkHeight']}"
            f" bubble {result['metrics']['width']}x{result['metrics']['height']}"
        )
        print(f"first item id {result['firstItemId']} stroke bounds {result['strokeBounds']}")
        for index, entry in enumerate(result["captured"]):
            print(f"  stroke {index}: matrix {[round(value, 4) for value in entry['matrix']]}"
                  f" lineWidth {entry['lineWidth']:.3f}")

        # What signature.js would compute on its own for this box, for comparison.
        metrics = result["metrics"]
        min_x, min_y, max_x, max_y = result["strokeBounds"]
        ink_w = max(max_x - min_x, 1) + 12
        ink_h = max(max_y - min_y, 1) + 12
        ink_scale = min(metrics["inkWidth"] / ink_w, metrics["inkHeight"] / ink_h)
        print(f"  the ink scale for this stroke is {ink_scale:.4f}, so in device pixels it must be")
        print(f"  {ink_scale * result['ratio']:.4f} per stroke pixel")
        return 0
    finally:
        try:
            devtools.close()
        except Exception:
            pass
        process.terminate()


if __name__ == "__main__":
    sys.exit(main())
