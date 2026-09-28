"""Report how large the QR code actually is on the wall, at each size setting.

The card's height is what caps the setting, and the QR inside the card is smaller than the card, so
this measures what a participant would see: the QR image's printed size in pixels and in millimetres
on a 1920x1080 projector with a 3 m wide screen, at 1x and at the cap.

Usage:
    python tests/measure_qr_size.py [--base http://127.0.0.1:18195] [--stage-width 1884]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mobile_probe import DevTools, start_edge  # noqa: E402

PROBE = """(() => {
  const card = document.querySelector('.qr-card');
  const image = document.querySelector('#qr-image');
  const cardBox = card.getBoundingClientRect();
  const imageBox = image.getBoundingClientRect();
  const style = getComputedStyle(image);
  return JSON.stringify({
    scale: getComputedStyle(document.documentElement).getPropertyValue('--qr-scale').trim(),
    card: [Math.round(cardBox.width), Math.round(cardBox.height)],
    image: [Math.round(imageBox.width), Math.round(imageBox.height)],
    padding: style.padding,
  });
})()"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--key", default="probe-token")
    parser.add_argument("--stage", default="1920x1080")
    parser.add_argument("--screen-width-mm", type=float, default=3000.0, help="projected screen width")
    arguments = parser.parse_args()

    svg = urllib.request.urlopen(
        f"{arguments.base}/api/events/{arguments.slug}/qr.svg", timeout=20
    ).read().decode()
    header = svg[:400]
    view_box = re.search(r'viewBox="([^"]+)"', header)
    modules = None
    if view_box:
        parts = view_box.group(1).split()
        if len(parts) == 4:
            modules = int(float(parts[2]))
    print(f"qr.svg viewBox: {view_box.group(1) if view_box else 'none'}  -> {modules} modules across")

    width_text, height_text = arguments.stage.lower().split("x")
    port = 19331
    profile = Path(tempfile.mkdtemp(prefix="edge-qrmeasure-"))
    process = start_edge(port, profile)
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)
        devtools.call(
            "Emulation.setDeviceMetricsOverride",
            width=int(width_text),
            height=int(height_text),
            deviceScaleFactor=1,
            mobile=False,
        )
        for scale in (1.0, 1.596):
            request = urllib.request.Request(
                f"{arguments.base}/api/admin/events/{arguments.slug}",
                data=json.dumps({"qr_scale": scale}).encode(),
                headers={"Authorization": f"Bearer {arguments.key}", "Content-Type": "application/json"},
                method="PUT",
            )
            urllib.request.urlopen(request, timeout=20).read()
            devtools.call("Page.navigate", url=f"{arguments.base}/display?event={arguments.slug}")
            time.sleep(3.5)
            value = json.loads(devtools.evaluate(PROBE))
            image_px = value["image"][0]
            stage_px = int(width_text)
            mm = image_px / stage_px * arguments.screen_width_mm
            module_mm = mm / modules if modules else float("nan")
            print(
                f"scale {value['scale']:<6} card {value['card'][0]}x{value['card'][1]}"
                f" qr image {image_px}x{value['image'][1]} px (padding {value['padding']})"
                f" = {mm:.0f} mm on a {arguments.screen_width_mm / 1000:.0f} m screen"
                f" -> {module_mm:.1f} mm per module"
            )
            # A QR needs roughly 4 modules per mm of scanning distance to stay comfortable; this is
            # the rule of thumb for phones at a moderate angle.
            if modules:
                print(f"         comfortable scanning distance: about {module_mm * 4 / 10:.1f} m")
    finally:
        try:
            devtools.close()
        except Exception:
            pass
        process.terminate()
        request = urllib.request.Request(
            f"{arguments.base}/api/admin/events/{arguments.slug}",
            data=json.dumps({"qr_scale": 1}).encode(),
            headers={"Authorization": f"Bearer {arguments.key}", "Content-Type": "application/json"},
            method="PUT",
        )
        urllib.request.urlopen(request, timeout=20).read()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
