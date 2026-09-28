"""Diagnose where the exported picture's ink actually lands.

Draws the wall twice — once with all signatures, once without a chosen signature's stroke — and
reports, per signature, the ink's painted extent as a fraction of the picture, next to where the
layout says that signature's bubble is. Also reports the painted extent of the whole picture.

Usage:
    python tests/diag_export_geometry.py [--base http://127.0.0.1:18195] [--slug integrity-2026]
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
  const rendered = await window.wallExport.renderWallPng({ slug: '%SLUG%' });
  const canvas = rendered.canvas;
  const metrics = rendered.metrics
    || window.wallLayout.metricsFor(
      rendered.geometry.count || rendered.items.length,
      { stageWidth: rendered.stage.logicalWidth, stageHeight: rendered.stage.logicalHeight },
    );
  // Where is the white ink in the picture? Colour-threshold the whole canvas.
  const context = canvas.getContext('2d');
  const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
  let minX = Infinity, minY = Infinity, maxX = -1, maxY = -1, white = 0;
  for (let y = 0; y < canvas.height; y += 1) {
    for (let x = 0; x < canvas.width; x += 1) {
      const index = (y * canvas.width + x) * 4;
      if (data[index] > 225 && data[index + 1] > 225 && data[index + 2] > 225) {
        white += 1;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }
  const ratio = rendered.ratio;
  const inkBoxes = rendered.bubbles.map((bubble) => {
    const cx = (bubble.x / 100) * rendered.stage.logicalWidth * ratio;
    const cy = (bubble.y / 100) * rendered.stage.logicalHeight * ratio;
    return {
      id: String(bubble.id),
      name: bubble.name || '',
      cx: Math.round(cx),
      cy: Math.round(cy),
      box: [
        Math.round(cx - metrics.inkWidth * ratio / 2),
        Math.round(cy - metrics.height * ratio / 2 + metrics.padding * ratio),
        Math.round(metrics.inkWidth * ratio),
        Math.round(metrics.inkHeight * ratio),
      ],
    };
  });
  return JSON.stringify({
    canvas: [canvas.width, canvas.height],
    ratio,
    logical: [rendered.stage.logicalWidth, rendered.stage.logicalHeight],
    geometrySource: rendered.geometrySource,
    geometry: rendered.geometry,
    metrics,
    inkExtent: white ? [minX, minY, maxX, maxY] : null,
    white,
    total: canvas.width * canvas.height,
    bubbles: inkBoxes,
  });
})()"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--key", default="probe-monitor")
    parser.add_argument("--stage", default="1920x1080")
    arguments = parser.parse_args()

    port = 19271
    profile = Path(tempfile.mkdtemp(prefix="edge-diag-"))
    process = start_edge(port, profile)
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)
        width_text, height_text = arguments.stage.lower().split("x")
        devtools.call(
            "Emulation.setDeviceMetricsOverride",
            width=int(width_text),
            height=int(height_text),
            deviceScaleFactor=1,
            mobile=False,
        )
        devtools.call("Page.navigate", url=f"{arguments.base}/display?event={arguments.slug}")
        time.sleep(4)
        devtools.call(
            "Page.navigate",
            url=f"{arguments.base}/monitor?event={arguments.slug}&key={arguments.key}",
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            if devtools.evaluate("Boolean(window.wallExport && window.wallSync)"):
                break
            time.sleep(0.3)
        time.sleep(1.5)
        result = json.loads(devtools.evaluate(PROBE.replace("%SLUG%", arguments.slug)))
        print(f"geometry source: {result['geometrySource']}")
        print(f"geometry: {json.dumps(result['geometry'], ensure_ascii=False)}")
        print(
            f"canvas {result['canvas'][0]}x{result['canvas'][1]}"
            f" logical {result['logical'][0]:.0f}x{result['logical'][1]:.0f}"
            f" ratio {result['ratio']:.3f}"
        )
        print(f"metrics: {json.dumps(result['metrics'])}")
        print(
            f"white {result['white']} of {result['total']}"
            f" ({result['white'] / result['total'] * 100:.2f}%)"
            f" extent {result['inkExtent']}"
        )
        for bubble in result["bubbles"]:
            left, top, width, height = bubble["box"]
            print(
                f"  {bubble['id']:<4} {bubble['name'][:8]:<9} centre {bubble['cx']:>5},{bubble['cy']:>5}"
                f" ink box {left},{top} {width}x{height}"
            )
        return 0
    finally:
        try:
            devtools.close()
        except Exception:
            pass
        process.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
