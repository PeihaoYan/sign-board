"""Check the deployed wall renders the same signature at every screen density.

Measures the ink of the first signature bubble on the live display page at device pixel ratios 1, 2
and 3: the drawing must be identical and must not touch its canvas edge.

Usage:
    python tools/verify_wall_density.py [--base http://127.0.0.1:18195] [--slug integrity-2026]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

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
  return JSON.stringify({
    density: window.devicePixelRatio,
    count: bubbles.length,
    bitmap: [canvas.width, canvas.height],
    ink: painted
      ? {
        box: [maxX - minX + 1, maxY - minY + 1],
        margins: [minX, minY, canvas.width - 1 - maxX, canvas.height - 1 - maxY],
        painted,
      }
      : { box: [0, 0], margins: [0, 0, 0, 0], painted: 0 },
  });
})()"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    arguments = parser.parse_args()

    port = 19283
    profile = Path(tempfile.mkdtemp(prefix="edge-live-density-"))
    process = start_edge(port, profile)
    failures: list[str] = []
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)

        results = []
        for density in (1, 2, 3):
            devtools.call(
                "Emulation.setDeviceMetricsOverride",
                width=1280,
                height=800,
                deviceScaleFactor=density,
                mobile=False,
            )
            devtools.call("Page.navigate", url=f"{arguments.base}/display?event={arguments.slug}")
            deadline = time.time() + 30
            while time.time() < deadline:
                if devtools.evaluate("document.querySelectorAll('.signature-bubble').length > 0"):
                    break
                time.sleep(0.3)
            time.sleep(1.5)
            result = json.loads(devtools.evaluate(PROBE))
            if result.get("error"):
                print(result["error"])
                return 1
            results.append(result)
            ink = result["ink"]
            print(
                f"density {result['density']}: {result['count']} signatures, first bubble canvas"
                f" {result['bitmap']}"
            )
            print(
                f"  ink box {ink['box']} of {result['bitmap']}, painted {ink['painted']},"
                f" margins {ink['margins']}"
            )
            if ink["painted"] == 0:
                failures.append(f"no ink at density {density}")
                continue
            if ink["box"][0] > result["bitmap"][0] or ink["box"][1] > result["bitmap"][1]:
                failures.append(f"ink larger than the canvas at density {density}")
            if ink["margins"][1] + ink["margins"][3] == 0 and ink["margins"][0] + ink["margins"][2] == 0:
                failures.append(f"ink fills the whole canvas at density {density}, so it is clipped")

        boxes = [result["ink"]["box"] for result in results]
        if boxes and len({tuple(box) for box in boxes}) > 1:
            failures.append(f"the signature is drawn differently per screen density: {boxes}")

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
