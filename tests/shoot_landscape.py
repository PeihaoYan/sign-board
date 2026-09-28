"""Take a picture of the landscape writing mode, the way the participant sees it.

Opens the phone page, enters landscape writing mode, draws a sample signature and saves two
pictures: the raw screenshot as the upright phone shows it, and the same picture rotated 90° so it
reads the way the participant reads it while writing. The second one is what to look at when judging
the hint's wording, placement and legibility.

Usage:
    python tests/shoot_landscape.py [--base http://127.0.0.1:18195] [--device "iPhone 14"]
                                    [--draw] [--out landscape]
"""

from __future__ import annotations

import argparse
import base64
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobile_probe import DEVICES, DevTools, load_mobile_page, prepare_session, start_edge  # noqa: E402

DRAW = """(() => {
  // The ink goes on the canvas in bitmap pixels, in the strip's own space, which is the space the
  // guide is laid out in too. Drawing through pointer events would map through the box's rotation
  // and put the sample signature the long way round, which reads as a fault in the page.
  const canvas = document.querySelector('#signature-canvas');
  const context = canvas.getContext('2d');
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const strip = { w: canvas.width / ratio, h: canvas.height / ratio };
  context.lineCap = 'round';
  context.lineJoin = 'round';
  context.lineWidth = 4.6;
  context.strokeStyle = '#ffffff';
  context.beginPath();
  const bandY = strip.h * 0.62;
  for (let step = 0; step <= 60; step += 1) {
    const along = step / 60;
    const x = strip.w * (0.16 + along * 0.68);
    const y = bandY + Math.sin(along * 14) * 13;
    if (step === 0) context.moveTo(x * ratio, y * ratio);
    else context.lineTo(x * ratio, y * ratio);
  }
  context.stroke();
  // A short second stroke, so the sample looks like a written name rather than one wave.
  context.beginPath();
  context.moveTo(strip.w * 0.22 * ratio, strip.h * 0.75 * ratio);
  context.lineTo(strip.w * 0.7 * ratio, strip.h * 0.78 * ratio);
  context.stroke();
  return JSON.stringify({ strip: [Math.round(strip.w), Math.round(strip.h)] });
})()"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--device", default="iPhone 14")
    parser.add_argument("--out", default="landscape")
    parser.add_argument("--draw", action="store_true", help="draw a sample signature first")
    arguments = parser.parse_args()

    device = next((item for item in DEVICES if item[0].lower() == arguments.device.lower()), None)
    if device is None:
        print(f"unknown device; known: {[item[0] for item in DEVICES]}")
        return 1
    label, width, height = device

    from PIL import Image

    port = 19341
    profile = Path(tempfile.mkdtemp(prefix="edge-shot-"))
    process = start_edge(port, profile)
    try:
        devtools = DevTools(port)
        prepare_session(devtools, width, height, "portraitPrimary", "fallback")
        load_mobile_page(devtools, url=f"{arguments.base}/mobile?event={arguments.slug}")
        devtools.evaluate("document.querySelector('#landscape-toggle').click()")
        time.sleep(1.2)
        if arguments.draw:
            print("drawing:", devtools.evaluate(DRAW))
            time.sleep(0.4)

        shots = Path(__file__).resolve().parent / "shots"
        shots.mkdir(exist_ok=True)
        png = devtools.call("Page.captureScreenshot", format="png").get("data", "")
        raw_path = shots / f"{arguments.out}-phone.png"
        raw_path.write_bytes(base64.b64decode(png))
        image = Image.open(raw_path)
        # The participant turns the phone to write, so the readable view is the phone turned the way
        # its own long edge becomes horizontal: the same rotation the guide uses.
        readable = image.rotate(-90, expand=True)
        readable_path = shots / f"{arguments.out}-read.png"
        readable.save(readable_path)
        print(f"{label}: {width}x{height} -> {raw_path} {image.size}, readable {readable_path} {readable.size}")
        return 0
    finally:
        try:
            devtools.close()
        except Exception:
            pass
        process.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
