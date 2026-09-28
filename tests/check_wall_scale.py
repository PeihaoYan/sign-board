"""Measure the wall with a real crowd: bubble size, spread, and the exported PNG.

Drives the display page at a real wall size (1920x1080 by default) with the signatures the event
holds, then reports:

* the CSS variable sizes the wall applied, and how many distinct bubble boxes ended up on screen;
* the closest pair of bubble centres in units of the bubble size, so signatures that cover each
  other show up as a number below 1;
* the same measurements for the monitor page's PNG export, which must match the wall.

Usage:
    python tests/check_wall_scale.py [--count 200] [--base http://127.0.0.1:18195] [--key <token>]
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

WALL_REPORT = """(() => {
  const layer = document.querySelector('.signature-layer');
  const stage = document.querySelector('.wall-stage');
  const style = getComputedStyle(layer);
  const bubbles = Array.from(document.querySelectorAll('.signature-bubble'));
  const stageRect = stage.getBoundingClientRect();
  const metrics = {
    width: parseFloat(style.getPropertyValue('--bubble-width')),
    height: parseFloat(style.getPropertyValue('--bubble-height')),
    inkWidth: parseFloat(style.getPropertyValue('--ink-width')),
    inkHeight: parseFloat(style.getPropertyValue('--ink-height')),
    nameSize: parseFloat(style.getPropertyValue('--name-size')),
  };
  // `style.left/top` is the placement the wall computed. The bounding rectangle is not usable
  // here: each bubble is rotated by up to 9 degrees and floats up and down, so the rectangle is
  // larger than the bubble and its centre moves with the animation.
  const points = bubbles.map((bubble) => ({
    id: bubble.dataset.id,
    x: (parseFloat(bubble.style.left) / 100) * stageRect.width,
    y: (parseFloat(bubble.style.top) / 100) * stageRect.height,
  }));
  const distances = [];
  for (let i = 0; i < points.length; i += 1) {
    for (let j = i + 1; j < points.length; j += 1) {
      distances.push(Math.max(
        Math.abs(points[i].x - points[j].x) / metrics.width,
        Math.abs(points[i].y - points[j].y) / metrics.height,
      ));
    }
  }
  distances.sort((a, b) => a - b);
  const ink = bubbles.length ? bubbles[0].querySelector('canvas') : null;
  const name = bubbles.length ? bubbles[0].querySelector('.signature-name') : null;
  return JSON.stringify({
    count: bubbles.length,
    stage: [stage.clientWidth, stage.clientHeight],
    metrics,
    canvasBitmap: ink ? [ink.width, ink.height, ink.style.width, ink.style.height] : null,
    nameFont: name ? getComputedStyle(name).fontSize : null,
    closest: [distances[0] || 0, distances[Math.floor(distances.length * 0.05)] || 0],
    overlapping: distances.filter((value) => value < 0.6).length,
    crowded: distances.filter((value) => value < 1).length,
  });
})()"""


def run(devtools: DevTools, url: str, wait_for: str, settle: float = 3.0) -> None:
    devtools.call("Page.navigate", url=url)
    deadline = time.time() + 40
    while time.time() < deadline:
        if devtools.evaluate(f"Boolean({wait_for})"):
            time.sleep(settle)
            return
        time.sleep(0.3)
    raise RuntimeError(f"page not ready: {url}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--key", default="probe-monitor")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    arguments = parser.parse_args()

    port = 19250
    profile = Path(tempfile.mkdtemp(prefix="edge-scale-"))
    process = start_edge(port, profile)
    failures: list[str] = []
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)
        devtools.call(
            "Emulation.setDeviceMetricsOverride",
            width=arguments.width,
            height=arguments.height,
            deviceScaleFactor=1,
            mobile=False,
        )

        run(
            devtools,
            f"{arguments.base}/display?event={arguments.slug}",
            "document.querySelectorAll('.signature-bubble').length > 0",
            settle=4.0,
        )
        wall = json.loads(devtools.evaluate(WALL_REPORT))
        print(f"wall {wall['stage'][0]}x{wall['stage'][1]} with {wall['count']} signatures")
        print(
            f"  css variables: bubble {wall['metrics']['width']}x{wall['metrics']['height']}"
            f" ink {wall['metrics']['inkWidth']}x{wall['metrics']['inkHeight']}"
            f" name {wall['metrics']['nameSize']}px"
        )
        print(f"  ink canvas bitmap: {wall['canvasBitmap']} name font: {wall['nameFont']}")
        print(
            f"  closest centres: {wall['closest'][0]:.2f} (min) {wall['closest'][1]:.2f} (p05)"
            f" bubble widths; pairs overlapping: {wall['overlapping']}, closer than 1: {wall['crowded']}"
        )
        if wall["count"] < 100:
            failures.append(f"the wall only holds {wall['count']} signatures")
        if wall["overlapping"] > 5:
            failures.append(f"{wall['overlapping']} pairs overlap")
        if wall["closest"][0] < 0.5:
            failures.append(f"the closest pair is {wall['closest'][0]:.2f} bubble widths apart")
        if wall["metrics"]["width"] > 120:
            failures.append(f"bubbles are still {wall['metrics']['width']}px wide for this crowd")
        # The ink canvas must be rendered at the displayed size, or the strokes would be resampled.
        if wall["canvasBitmap"] and wall["canvasBitmap"][2] != f"{wall['metrics']['inkWidth']}px":
            failures.append("the ink canvas is not rendered at the bubble's ink size")

        # Positions of the wall, read while the display page is still open.
        wall_positions = json.loads(
            devtools.evaluate(
                "JSON.stringify(Object.fromEntries(Array.from(document.querySelectorAll('.signature-bubble')).map("
                "  (bubble) => [bubble.dataset.id, [parseFloat(bubble.style.left), parseFloat(bubble.style.top)]])))"
            )
        )
        wall_count = wall["count"]

        monitor_url = f"{arguments.base}/monitor?event={arguments.slug}&key={arguments.key}"
        run(devtools, monitor_url, "window.wallExport && window.wallSync", settle=1.5)
        exported = json.loads(
            devtools.evaluate(
                "window.wallExport.renderWallPng({ slug: '" + arguments.slug + "' }).then((r) => JSON.stringify({"
                "  items: r.items.length,"
                "  canvas: [r.canvas.width, r.canvas.height],"
                "  count: (r.geometry && r.geometry.count) || null,"
                "  source: r.geometrySource,"
                "  bubbles: r.bubbles.map((b) => [String(b.id), [Number(b.x.toFixed(4)), Number(b.y.toFixed(4))]]),"
                "}))"
            )
        )
        print(
            f"export: canvas {exported['canvas'][0]}x{exported['canvas'][1]}"
            f" items {exported['items']} geometry count {exported['count']} source {exported['source']}"
        )
        if exported["items"] != wall_count:
            failures.append("the export and the wall do not hold the same signatures")

        exported_positions = dict(exported["bubbles"])
        shared = set(exported_positions) & set(wall_positions)
        worst = 0.0
        for identifier in shared:
            left = wall_positions[identifier]
            right = exported_positions[identifier]
            worst = max(worst, abs(left[0] - right[0]), abs(left[1] - right[1]))
        print(f"  position check: compared={len(shared)} largest difference={worst:.4f} points")
        if not shared:
            failures.append("no signature positions could be compared between the wall and the export")
        elif worst > 0.2:
            failures.append(f"the export arrangement differs from the wall by {worst:.2f} points")

        # The exported picture must hold ink at the smaller size too.
        stats = json.loads(
            devtools.evaluate(
                """(() => {
                  const canvas = document.createElement('canvas');
                  return window.wallExport.renderWallPng({ slug: '""" + arguments.slug + """' }).then((rendered) => {
                    const target = rendered.canvas;
                    const context = target.getContext('2d');
                    const pixels = context.getImageData(0, 0, target.width, target.height).data;
                    let white = 0;
                    let sampled = 0;
                    for (let index = 0; index < pixels.length; index += 4 * 7) {
                      sampled += 1;
                      if (pixels[index] > 235 && pixels[index + 1] > 235 && pixels[index + 2] > 235) white += 1;
                    }
                    return JSON.stringify({ sampled, white });
                  });
                })()"""
            )
        )
        print(f"  bitmap: sampled {stats['sampled']} white {stats['white']}")
        if stats["white"] < 20:
            failures.append("the exported picture has almost no ink")

        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"failures={len(failures)}")
        return 1 if failures else 0
    finally:
        try:
            devtools.close()
        except Exception:
            pass
        process.terminate()


if __name__ == "__main__":
    sys.exit(main())
