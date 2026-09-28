"""Check the phone's writing board is dark and the ink reads on it.

Draws a stroke on the real page, then measures, in a screenshot of the writing box:

* the board colour (it must be dark, not the pale paper it used to be);
* the ink's colour and its contrast against that board;
* the contrast of the placeholder hint text on the board.

Usage:
    python tests/check_board_contrast.py [--base http://127.0.0.1:18195] [--device "iPhone 14"]
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobile_probe import (  # noqa: E402
    DEVICES,
    DevTools,
    load_mobile_page,
    prepare_session,
    start_edge,
)

DRAW = """(() => {
  const canvas = document.querySelector('#signature-canvas');
  const rect = canvas.getBoundingClientRect();
  const fire = (type, x, y) => canvas.dispatchEvent(new PointerEvent(type, {
    pointerId: 1, clientX: x, clientY: y, bubbles: true, cancelable: true,
    isPrimary: true, pointerType: 'touch',
  }));
  const startX = rect.left + rect.width * 0.25;
  const startY = rect.top + rect.height * 0.25;
  fire('pointerdown', startX, startY);
  for (let step = 1; step <= 12; step += 1) {
    fire('pointermove', startX + step * (rect.width * 0.04), startY + step * (rect.height * 0.03));
  }
  fire('pointerup', startX + rect.width * 0.48, startY + rect.height * 0.36);
  return JSON.stringify({
    canvas: [canvas.width, canvas.height],
    wrap: (() => {
      const box = document.querySelector('.canvas-wrap').getBoundingClientRect();
      return [Math.round(box.left), Math.round(box.top), Math.round(box.width), Math.round(box.height)];
    })(),
    board: getComputedStyle(document.querySelector('.canvas-wrap')).backgroundColor,
    hintColour: getComputedStyle(document.querySelector('.canvas-hint')).color,
  });
})()"""

# For the wall: the same question, but the surface is the background picture and the ink is the
# white stroke plus the small name under it.
WALL = """(() => {
  const stage = document.querySelector('#wall-stage');
  const card = document.querySelector('.qr-card');
  const stageRect = stage.getBoundingClientRect();
  const box = (element) => {
    const rect = element.getBoundingClientRect();
    return [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)];
  };
  return JSON.stringify({
    stage: [
      Math.round(stageRect.left), Math.round(stageRect.top),
      Math.round(stageRect.width), Math.round(stageRect.height),
    ],
    card: card ? box(card) : null,
    bubbles: Array.from(document.querySelectorAll('.signature-bubble')).map(box),
    signatureCount: document.querySelectorAll('.signature-bubble').length,
  });
})()"""


def relative_luminance(colour: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        share = value / 255
        return share / 12.92 if share <= 0.03928 else ((share + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in colour)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def check_wall(arguments) -> int:
    """The wall's version of the same question: is the white ink legible on the background picture?"""
    port = 19291
    profile = Path(tempfile.mkdtemp(prefix="edge-wall-contrast-"))
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
            width=1920,
            height=1080,
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

        info = json.loads(devtools.evaluate(WALL))
        print(f"wall stage {info['stage']} with {info['signatureCount']} signatures")

        png = devtools.call("Page.captureScreenshot", format="png").get("data", "")
        shots = Path(__file__).resolve().parent / "shots"
        shots.mkdir(exist_ok=True)
        target = shots / "wall-contrast.png"
        target.write_bytes(base64.b64decode(png))
        image = Image.open(target).convert("RGB")
        pixels = image.load()

        left, top, width, height = info["stage"]
        # Sample the background only: skip the QR card and a generous box around every signature, so
        # the white ink itself is not mistaken for a bright part of the picture.
        skip = []
        if info["card"]:
            skip.append(info["card"])
        for bubble in info.get("bubbles", []):
            skip.append([bubble[0] - 60, bubble[1] - 60, bubble[2] + 120, bubble[3] + 120])
        samples = []
        step = 6
        for y in range(top, min(top + height, image.height), step):
            for x in range(left, min(left + width, image.width), step):
                if any(
                    box[0] <= x <= box[0] + box[2] and box[1] <= y <= box[1] + box[3]
                    for box in skip
                ):
                    continue
                samples.append(pixels[x, y])
        if not samples:
            print("no background could be sampled")
            return 1
        average = tuple(sum(values) // len(samples) for values in zip(*samples))
        ranked = sorted(samples, key=lambda colour: sum(colour))
        p99 = ranked[int(len(ranked) * 0.99)]
        brightest = ranked[-1]
        # What matters is how much of the picture is bright, not whether a single pixel is: every
        # photograph has a few highlights, and a signature covers only a small part of the wall.
        bright = sum(1 for colour in samples if relative_luminance(colour) > 0.35) / len(samples)
        very_bright = sum(1 for colour in samples if relative_luminance(colour) > 0.6) / len(samples)
        print(
            f"  background sampled {len(samples)} px: average {average}"
            f" (luminance {relative_luminance(average):.3f}),"
            f" p99 {p99}, brightest {brightest}"
        )
        print(f"  white ink against the average: {contrast((255, 255, 255), average):.1f}:1")
        print(
            f"  bright areas: {bright * 100:.1f}% above 0.35 luminance,"
            f" {very_bright * 100:.1f}% above 0.60 (where white ink is lost)"
        )
        if relative_luminance(average) > 0.35:
            failures.append(f"the background is too bright for white ink: {average}")
        if bright > 0.05:
            failures.append(
                f"{bright * 100:.1f}% of the picture is bright enough to hide a white stroke"
            )
        print(f"screenshot: {target}")
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--device", default="iPhone 14")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--wall", action="store_true", help="check the big screen's background instead")
    arguments = parser.parse_args()

    if arguments.wall:
        return check_wall(arguments)

    device = next((item for item in DEVICES if item[0].lower() == arguments.device.lower()), None)
    if device is None:
        print(f"unknown device; known: {[item[0] for item in DEVICES]}")
        return 1
    label, width, height = device

    port = 19290
    profile = Path(tempfile.mkdtemp(prefix="edge-board-"))
    process = start_edge(port, profile)
    failures: list[str] = []
    try:
        devtools = DevTools(port)
        prepare_session(devtools, width, height, "portraitPrimary", "fallback")
        load_mobile_page(devtools, url=f"{arguments.base}/mobile?event={arguments.slug}")
        result = json.loads(devtools.evaluate(DRAW))
        print(f"{label}: board background {result['board']}, placeholder colour {result['hintColour']}")

        png = devtools.call("Page.captureScreenshot", format="png").get("data", "")
        shots = Path(__file__).resolve().parent / "shots"
        shots.mkdir(exist_ok=True)
        target = shots / "board.png"
        target.write_bytes(base64.b64decode(png))
        image = Image.open(target).convert("RGB")
        pixels = image.load()

        left, top, box_width, box_height = result["wrap"]
        # Sample the middle band of the box: that is board plus ink, not the border or the text.
        board_samples = []
        ink_samples = []
        for y in range(top + 8, min(top + box_height - 8, image.height), 3):
            for x in range(left + 8, min(left + box_width - 8, image.width), 3):
                colour = pixels[x, y]
                if sum(colour) > 660:
                    ink_samples.append(colour)
                elif sum(colour) < 400:
                    board_samples.append(colour)
        if not board_samples:
            failures.append("no dark board colour could be sampled")
        if not ink_samples:
            failures.append("no white ink could be sampled on the board")

        if board_samples:
            board = tuple(sum(values) // len(board_samples) for values in zip(*board_samples))
            print(f"  board sampled {len(board_samples)} px, average {board}, luminance {relative_luminance(board):.3f}")
            if relative_luminance(board) > 0.2:
                failures.append(f"the board is not dark: {board}")
            if ink_samples:
                ink = tuple(sum(values) // len(ink_samples) for values in zip(*ink_samples))
                ratio = contrast(ink, board)
                print(f"  ink sampled {len(ink_samples)} px, average {ink}, contrast against board {ratio:.1f}:1")
                if ratio < 4.5:
                    failures.append(f"the ink does not stand out on the board ({ratio:.1f}:1)")
            # The placeholder text is a translucent white; check it is at least visible.
            hint_ratio = contrast((226, 235, 244), board)
            print(f"  placeholder contrast (solid colour) {hint_ratio:.1f}:1")
            if hint_ratio < 4.5:
                failures.append(f"the placeholder is too faint on the dark board ({hint_ratio:.1f}:1)")
        print(f"screenshot: {target}")
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
