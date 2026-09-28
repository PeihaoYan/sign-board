"""Does the signature ink scale with the stage when the wall is resized?

The complaint this answers: after the window (or projector resolution) changes, the signatures keep
the size they had when the page loaded instead of scaling with the background. The wall places each
signature in percentages of the stage, so the bubble's box scales with the stage; the ink is drawn
into a canvas whose bitmap size is chosen when the bubble is created, so it only scales if the bubble
is rebuilt or resized at the new size.

The check loads the wall at one size, resizes the viewport, and reports the stage, a bubble's box and
the ink canvas's bitmap before and after: the ink must stay the same fraction of the stage.

Usage:
    python tests/check_wall_resize_scaling.py [--base http://127.0.0.1:18195] [--slug integrity-2026]
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
  const stage = document.querySelector('#wall-stage');
  const bubbles = Array.from(document.querySelectorAll('.signature-bubble'));
  const first = bubbles[0];
  const box = first.getBoundingClientRect();
  const ink = first.querySelector('canvas');
  const inkRect = ink.getBoundingClientRect();
  return JSON.stringify({
    stage: [stage.clientWidth, stage.clientHeight],
    bubbles: bubbles.length,
    box: [Math.round(box.width), Math.round(box.height)],
    inkDisplay: [Math.round(inkRect.width), Math.round(inkRect.height)],
    inkBitmap: [ink.width, ink.height],
    inkStyle: [ink.style.width, ink.style.height],
  });
})()"""


def read(devtools: DevTools) -> dict:
    return json.loads(devtools.evaluate(PROBE))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    arguments = parser.parse_args()

    port = 19300
    profile = Path(tempfile.mkdtemp(prefix="edge-resize-"))
    process = start_edge(port, profile)
    failures: list[str] = []
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)

        def open_at(width: int, height: int) -> dict:
            devtools.call(
                "Emulation.setDeviceMetricsOverride",
                width=width,
                height=height,
                deviceScaleFactor=1,
                mobile=False,
            )
            devtools.call("Page.navigate", url=f"{arguments.base}/display?event={arguments.slug}")
            deadline = time.time() + 30
            while time.time() < deadline:
                if devtools.evaluate("document.querySelectorAll('.signature-bubble').length > 0"):
                    break
                time.sleep(0.3)
            time.sleep(2.0)
            return read(devtools)

        big = open_at(1920, 1080)
        print(f"opened at 1920x1080: stage {big['stage']} bubble {big['box']} ink bitmap {big['inkBitmap']}")

        # Resize the viewport without reloading, the way a projector change or a window drag does.
        devtools.call(
            "Emulation.setDeviceMetricsOverride",
            width=1280, height=720, deviceScaleFactor=1, mobile=False,
        )
        time.sleep(2.5)
        small = read(devtools)
        print(f"resized to 1280x720: stage {small['stage']} bubble {small['box']} ink bitmap {small['inkBitmap']}")

        for label, state in (("1920x1080", big), ("1280x720", small)):
            share = [state["box"][0] / state["stage"][0], state["box"][1] / state["stage"][1]]
            print(f"  {label}: bubble is {100 * share[0]:.1f}% x {100 * share[1]:.1f}% of the stage")

        # The bubble keeps its share of the stage (that is what the page already did); the ink must
        # keep its share of the bubble, which is the part that used to be left behind.
        bubble_ratios = [big["box"][0] / small["box"][0], big["box"][1] / small["box"][1]]
        ink_ratios = [big["inkBitmap"][0] / small["inkBitmap"][0], big["inkBitmap"][1] / small["inkBitmap"][1]]
        display_ratios = [big["inkDisplay"][0] / small["inkDisplay"][0], big["inkDisplay"][1] / small["inkDisplay"][1]]
        print(f"  1920/1280 ratios — bubble {[round(value, 3) for value in bubble_ratios]}"
              f" ink bitmap {[round(value, 3) for value in ink_ratios]}"
              f" ink display {[round(value, 3) for value in display_ratios]}")

        if abs(bubble_ratios[0] - 1.5) > 0.1:
            failures.append(f"the bubble did not scale with the stage: {bubble_ratios}")
        # The ink has to scale like the bubble. A stale bitmap shows up as a ratio of 1.
        for index, axis in enumerate(("width", "height")):
            if abs(ink_ratios[index] - bubble_ratios[index]) > 0.15:
                failures.append(
                    f"the ink bitmap {axis} did not follow the stage: bubble ratio"
                    f" {bubble_ratios[index]:.2f} against ink ratio {ink_ratios[index]:.2f}"
                )
            if abs(display_ratios[index] - bubble_ratios[index]) > 0.15:
                failures.append(
                    f"the ink's on-screen {axis} did not follow the stage: bubble ratio"
                    f" {bubble_ratios[index]:.2f} against ink display ratio {display_ratios[index]:.2f}"
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
