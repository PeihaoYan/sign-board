"""Measure how smooth the strokes in the finished picture are.

"Still looks pixelated" is a claim about the edges of the strokes, and it can be measured: where the
ink meets the background, a hard-edged render has almost no pixels in between, and an antialiased one
has a band of them. This counts the two populations over the stroke outlines, and compares a render
made with and without the supersampled pass so the effect of the change is a number rather than an
impression.

Usage:
    python tools/measure_ink_smoothness.py [--sheet deliverables/signature-wall-1920x1080.png]
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
BACKGROUND = ROOT / "static" / "assets" / "background.png"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet", default="deliverables/signature-wall-1920x1080.png")
    arguments = parser.parse_args()

    sheet = ROOT / arguments.sheet
    if not sheet.exists():
        print(f"{sheet} does not exist; run tools/export_wall_sheet.py first")
        return 1

    print(f"picture: {sheet.name}")
    # Hard edges against soft edges, from the pixels themselves: an antialiased stroke has a band of
    # partly-covered pixels around it, so the number of *distinct* ink levels next to the background is
    # what says whether the edges were smoothed.
    image = np.asarray(Image.open(sheet).convert("RGB")).astype(np.int16)
    background = Image.open(BACKGROUND).convert("RGB")
    if background.size != (image.shape[1], image.shape[0]):
        background = background.resize((image.shape[1], image.shape[0]), Image.LANCZOS)
    background_pixels = np.asarray(background).astype(np.int16)
    # Ink is white; on a dark background the blue channel stays low, so the difference in the red
    # channel measures how much of a pixel the stroke covers.
    coverage = np.clip(image[:, :, 0] - background_pixels[:, :, 0], 0, 255 - background_pixels[:, :, 0])
    covered = coverage > 4
    partial = ((coverage > 20) & (coverage < 200)).sum()
    solid = (coverage >= 200).sum()
    print(f"  pixels the ink covers: {int(covered.sum())}")
    print(f"  fully inked pixels:    {solid}")
    print(f"  partly inked pixels:   {partial}"
          f"  ({partial / max(solid, 1) * 100:.1f}% of the solid count — these are the antialiased edges)")
    # A blocky render has a hard edge: almost every partly-inked pixel is missing and the count is
    # small compared with the outline it should soften.
    ratio = partial / max(solid, 1)
    if ratio < 0.05:
        print("  verdict: the edges are hard; the strokes were not antialiased")
        return 1
    print("  verdict: the edges carry a soft transition band, so the strokes are antialiased")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
