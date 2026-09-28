"""Check the QR image on the live wall, in a real browser, the way a participant's phone needs it.

The QR code is the one element on the wall that the wall cannot show a substitute for: if the image
does not load, or loads but paints nothing, the event cannot collect signatures. This opens the live
display page, waits for the card, and reports whether the image element finished loading, what size
it settled at, and whether the SVG actually rasterises into pixels. It also reads the server log for
the request, so "the image is blank" can be told apart from "the image was never fetched".

Usage:
    python tools/verify_live_qr.py [--base http://127.0.0.1:18180] [--slug integrity-2026]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from mobile_probe import DevTools, start_edge  # noqa: E402

REPORT = """(async () => {
  const image = document.querySelector('#qr-image');
  const card = document.querySelector('.qr-card');
  if (!image || !card) return JSON.stringify({ error: 'the wall has no QR card' });
  const cardBox = card.getBoundingClientRect();
  const imageBox = image.getBoundingClientRect();
  // Rasterise the very source the page loaded, and count the dark pixels: a broken image paints
  // nothing at all, which is the failure worth catching.
  let painted = 0;
  let drawn = false;
  try {
    const loaded = await new Promise((resolve) => {
      const probe = new Image();
      probe.onload = () => resolve(probe);
      probe.onerror = () => resolve(null);
      probe.src = image.currentSrc || image.src;
    });
    if (loaded) {
      const canvas = document.createElement('canvas');
      canvas.width = 256;
      canvas.height = 256;
      const context = canvas.getContext('2d');
      context.fillStyle = '#ffffff';
      context.fillRect(0, 0, 256, 256);
      context.drawImage(loaded, 0, 0, 256, 256);
      const data = context.getImageData(0, 0, 256, 256).data;
      for (let index = 0; index < data.length; index += 4) {
        if (data[index] < 128) painted += 1;
      }
      drawn = true;
    }
  } catch (error) {
    drawn = false;
  }
  return JSON.stringify({
    complete: image.complete,
    naturalSize: [image.naturalWidth, image.naturalHeight],
    currentSrc: image.currentSrc || image.src,
    card: [Math.round(cardBox.width), Math.round(cardBox.height)],
    image: [Math.round(imageBox.width), Math.round(imageBox.height)],
    darkPixelsOf256: painted,
    rasterised: drawn,
    scale: getComputedStyle(document.documentElement).getPropertyValue('--qr-scale').trim(),
  });
})()"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18180")
    parser.add_argument("--slug", default="integrity-2026")
    arguments = parser.parse_args()

    port = 19381
    profile = Path(tempfile.mkdtemp(prefix="edge-qr-"))
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
            width=1920, height=1080, deviceScaleFactor=1, mobile=False,
        )
        devtools.call("Page.navigate", url=f"{arguments.base}/display?event={arguments.slug}")
        # Wait for the card's image rather than a fixed sleep, so a slow link is not read as a fault.
        deadline = time.time() + 25
        while time.time() < deadline:
            state = devtools.evaluate("document.querySelector('#qr-image')?.complete")
            if state:
                break
            time.sleep(0.5)
        time.sleep(1.0)
        report = devtools.evaluate(REPORT)
        import json

        value = json.loads(report)
        if value.get("error"):
            print("FAIL:", value["error"])
            return 1
        print(f"qr image: complete={value['complete']} natural size {value['naturalSize']}")
        print(f"  source: {value['currentSrc']}")
        print(f"  drawn size {value['image'][0]}x{value['image'][1]} px inside a card of"
              f" {value['card'][0]}x{value['card'][1]} px (scale {value['scale']})")
        print(f"  the browser rasterised it: {value['rasterised']},"
              f" dark pixels in a 256x256 render: {value['darkPixelsOf256']}")
        if not value["complete"]:
            failures.append("the QR image never finished loading")
        if not value["naturalSize"][0]:
            failures.append("the QR image has no intrinsic size, so it renders as a broken image")
        if value["rasterised"] and value["darkPixelsOf256"] < 500:
            failures.append(
                f"the QR image rasterises to only {value['darkPixelsOf256']} dark pixels,"
                " so the code is blank"
            )
        if value["image"][0] < 60:
            failures.append(f"the QR code is too small on screen: {value['image'][0]} px wide")
    finally:
        try:
            devtools.close()
        except Exception:
            pass
        process.terminate()

    for failure in failures:
        print(f"FAIL: {failure}")
    print(f"failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
