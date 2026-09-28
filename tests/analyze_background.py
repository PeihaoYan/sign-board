"""How much of a background picture is bright enough to swallow white ink?

The wall draws white strokes. On a dark picture that is very legible; on a picture with bright
patches the signature simply disappears where it lands. This reports the brightness distribution and
where the bright areas are, so the background can be judged before it is used or darkened.

Usage:
    python tests/analyze_background.py path/to/background.png [--limit 0.35]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def luminance(pixel: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        share = value / 255
        return share / 12.92 if share <= 0.03928 else ((share + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in pixel)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", help="PNG or JPEG background to analyze")
    parser.add_argument("--limit", type=float, default=0.35, help="luminance above which white ink fails")
    parser.add_argument("--grid", type=int, default=12, help="cells per axis in the brightness map")
    arguments = parser.parse_args()

    path = Path(arguments.image)
    image = Image.open(path).convert("RGB")
    width, height = image.size
    pixels = image.load()

    values = []
    for y in range(0, height, 3):
        for x in range(0, width, 3):
            values.append(luminance(pixels[x, y]))
    values.sort()
    total = len(values)

    def percentile(share: float) -> float:
        return values[min(total - 1, int(total * share))]

    print(f"{path}: {width}x{height}")
    print(
        "  luminance: min {:.3f}  p50 {:.3f}  p90 {:.3f}  p99 {:.3f}  max {:.3f}".format(
            values[0], percentile(0.5), percentile(0.9), percentile(0.99), values[-1]
        )
    )
    share = sum(1 for value in values if value > arguments.limit) / total
    print(f"  above {arguments.limit:.2f} luminance (white ink would vanish): {share * 100:.1f}% of the picture")
    share_hard = sum(1 for value in values if value > 0.6) / total
    print(f"  above 0.60 (white ink is gone): {share_hard * 100:.1f}%")

    # A coarse map of where the bright areas are, so a fix can be aimed at them.
    cells = arguments.grid
    print(f"  brightness map ({cells}x{cells}, '@' > {arguments.limit:.2f}, '+' > 0.2, '.' otherwise):")
    for row in range(cells):
        line = []
        for column in range(cells):
            total_l = 0.0
            count = 0
            for y in range(row * height // cells, (row + 1) * height // cells, 6):
                for x in range(column * width // cells, (column + 1) * width // cells, 6):
                    total_l += luminance(pixels[x, y])
                    count += 1
            average = total_l / max(count, 1)
            line.append("@" if average > arguments.limit else "+" if average > 0.2 else ".")
        print("    " + "".join(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
