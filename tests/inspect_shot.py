"""Pixel summary of a screenshot: where the ink, the paper and the gold accents actually are.

The canvas is the dark "paper" of the drawing area and the buttons are gold, so their bounding
boxes in the PNG say whether the parts of the page are inside the frame, independently of what the
page's own JavaScript reports. Handy as the cheapest sanity check that the pointer is still inside
the screen after the shell is rotated.

Usage:
    python tests/inspect_shot.py tests/shots/iPhone14-portraitPrimary-fallback.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def classify(pixel: tuple[int, int, int]) -> str | None:
    red, green, blue = pixel
    if red > 190 and green < 110 and blue < 110:
        return "red"
    if red > 190 and 140 < green < 230 and blue < 140:
        return "gold"
    if red < 80 and green < 90 and blue < 110:
        return "paper"
    if red > 240 and green > 235 and blue > 220:
        return "white"
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    image = Image.open(path).convert("RGB")
    width, height = image.size
    pixels = image.load()
    groups: dict[str, list[int]] = {}
    for y in range(height):
        for x in range(width):
            kind = classify(pixels[x, y])
            if kind is None:
                continue
            box = groups.setdefault(kind, [width, height, -1, -1, 0])
            box[0] = min(box[0], x)
            box[1] = min(box[1], y)
            box[2] = max(box[2], x)
            box[3] = max(box[3], y)
            box[4] += 1
    print(f"{path.name}: {width}x{height}")
    for kind, (left, top, right, bottom, count) in sorted(groups.items()):
        print(
            f"  {kind:<6} box={left},{top} -> {right},{bottom}"
            f" size={right - left + 1}x{bottom - top + 1} pixels={count}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
