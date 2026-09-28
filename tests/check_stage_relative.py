"""Confirm that a signature keeps the same share of the stage on any resolution.

Opens /display at two very different window sizes (a 1920x1080 projector and a
1280x720 laptop) and compares the bubble box and the ink bitmap against the
stage, so the ink is always the same fraction of the background picture.
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

DEVICES = [
    ("1920x1080 projector", 1920, 1080),
    ("1366x768 laptop", 1366, 768),
    ("3840x2160 4K", 3840, 2160),
]
PROBE = """
(() => {
  const stage = document.querySelector('#wall-stage');
  const bubbles = [...document.querySelectorAll('.signature-bubble')];
  if (!stage || !bubbles.length) return null;
  const bubble = bubbles[0];
  const box = bubble.getBoundingClientRect();
  const ink = bubble.querySelector('canvas');
  return {
    stage: [stage.clientWidth, stage.clientHeight],
    bubble: [box.width, box.height],
    inkBitmap: ink ? [ink.width, ink.height] : null,
    count: bubbles.length,
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    arguments = parser.parse_args()
    url = f"{arguments.base}/display?event={arguments.slug}"

    port = 19311
    profile = Path(tempfile.mkdtemp(prefix="edge-stage-"))
    proc = start_edge(port, profile)
    failures: list[str] = []
    rows = []
    try:
        dev = DevTools(port)
        for name, width, height in DEVICES:
            dev.call("Page.enable")
            dev.call("Runtime.enable")
            dev.call("Network.enable")
            dev.call("Network.setCacheDisabled", cacheDisabled=True)
            dev.call(
                "Emulation.setDeviceMetricsOverride",
                width=width,
                height=height,
                deviceScaleFactor=1,
                mobile=False,
            )
            dev.call("Page.navigate", url=url)
            time.sleep(3.5)
            value = dev.evaluate(PROBE)
            if not value:
                failures.append(f"{name}: no bubble rendered")
                continue
            stage_w, stage_h = value["stage"]
            bubble_w, bubble_h = value["bubble"]
            ink_w, ink_h = value["inkBitmap"] or (0, 0)
            share_w = bubble_w / stage_w * 100
            share_h = bubble_h / stage_h * 100
            ink_share = ink_w / stage_w * 100 if stage_w else 0
            rows.append(
                {
                    "device": name,
                    "stage": value["stage"],
                    "bubble": [round(bubble_w, 1), round(bubble_h, 1)],
                    "inkBitmap": value["inkBitmap"],
                    "shareW": round(share_w, 2),
                    "shareH": round(share_h, 2),
                    "inkShareW": round(ink_share, 2),
                    "count": value["count"],
                }
            )
            print(json.dumps(rows[-1], ensure_ascii=False))
        if len(rows) >= 2:
            base = rows[0]
            for row in rows[1:]:
                for key in ("shareW", "shareH", "inkShareW"):
                    delta = abs(row[key] - base[key])
                    print(f"  {row['device']} {key}: {base[key]}% -> {row[key]}%  delta {delta:.2f}")
                    if delta > 1.2:
                        failures.append(
                            f"{row['device']}: {key} drifted {delta:.2f} points from the projector"
                        )
    finally:
        proc.terminate()
    print(f"failures={len(failures)}")
    for failure in failures:
        print("FAIL:", failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
