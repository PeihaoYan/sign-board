"""Check the wall draws the same signature the same size on screens with different pixel densities.

The complaint this answers: on some screens the signature ink came out enlarged and clipped. The
wall's ink canvas is sized in device pixels, so its bitmap size changes with the screen density while
the element's on-screen size does not; the drawing inside must therefore look identical on a 1x
laptop and a 2x projector, and must never touch the canvas edge (clipped ink ends up as a smear).

Usage:
    python tests/check_wall_density.py [--base http://127.0.0.1:18195] [--slug integrity-2026]
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

PROBE = """(() => {
  const bubbles = Array.from(document.querySelectorAll('.signature-bubble'));
  if (!bubbles.length) return JSON.stringify({ error: 'no signatures on the wall' });
  const canvas = bubbles[0].querySelector('canvas');
  const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, painted = 0;
  for (let y = 0; y < canvas.height; y += 1) {
    for (let x = 0; x < canvas.width; x += 1) {
      if (data[(y * canvas.width + x) * 4 + 3] > 8) {
        painted += 1;
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      }
    }
  }
  const style = getComputedStyle(canvas);
  return JSON.stringify({
    devicePixelRatio: window.devicePixelRatio,
    canvasBitmap: [canvas.width, canvas.height],
    canvasStyle: [style.width, style.height],
    ink: painted
      ? {
        box: [maxX - minX + 1, maxY - minY + 1],
        margins: [minX, minY, canvas.width - 1 - maxX, canvas.height - 1 - maxY],
        painted,
      }
      : { box: [0, 0], margins: [0, 0, 0, 0], painted: 0 },
  });
})()"""


def measure(devtools: DevTools, base: str, slug: str, density: float) -> dict:
    devtools.call(
        "Emulation.setDeviceMetricsOverride",
        width=1280,
        height=800,
        deviceScaleFactor=density,
        mobile=False,
    )
    devtools.call("Page.navigate", url=f"{base}/display?event={slug}")
    deadline = time.time() + 30
    while time.time() < deadline:
        if devtools.evaluate("document.querySelectorAll('.signature-bubble').length > 0"):
            break
        time.sleep(0.3)
    time.sleep(2.0)
    return json.loads(devtools.evaluate(PROBE))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    arguments = parser.parse_args()

    port = 19282
    profile = Path(tempfile.mkdtemp(prefix="edge-density-"))
    process = start_edge(port, profile)
    failures: list[str] = []
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)

        shares = []
        for density in (1, 2, 3):
            result = measure(devtools, arguments.base, arguments.slug, density)
            if result.get("error"):
                print(f"density {density}x: {result['error']}")
                return 1
            bitmap = result["canvasBitmap"]
            ink = result["ink"]
            share = [ink["box"][0] / bitmap[0], ink["box"][1] / bitmap[1]]
            shares.append(share)
            print(
                f"device pixel ratio {result['devicePixelRatio']}: canvas bitmap {bitmap}"
                f" style {result['canvasStyle']}"
            )
            print(
                f"  ink box {ink['box']} = {100 * share[0]:.1f}% x {100 * share[1]:.1f}% of the bitmap,"
                f" painted {ink['painted']}, margins {ink['margins']}"
            )
            if ink["painted"] == 0:
                failures.append(f"no ink at {density}x")
                continue
            # A stroke is fitted inside its box, so it reaches the edge along its long axis; what
            # clipping does is push ink past the edge, which shows as a zero margin on both sides of
            # one axis at once, or as an ink box larger than the canvas.
            if ink["box"][0] > bitmap[0] or ink["box"][1] > bitmap[1]:
                failures.append(f"the ink is larger than its canvas at {density}x: {ink['box']} in {bitmap}")
            if ink["margins"][1] + ink["margins"][3] == 0 and ink["margins"][0] + ink["margins"][2] == 0:
                failures.append(f"the ink fills the whole canvas at {density}x, so it is clipped")

        widths = [share[0] for share in shares]
        heights = [share[1] for share in shares]
        if shares and (max(widths) - min(widths) > 0.15 or max(heights) - min(heights) > 0.15):
            failures.append(
                f"the signature takes a different share of its canvas per screen density:"
                f" widths {[round(value, 3) for value in widths]},"
                f" heights {[round(value, 3) for value in heights]}"
            )

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
