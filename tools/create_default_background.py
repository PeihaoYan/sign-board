"""Create the neutral, no-brand default wall background without external assets."""

from __future__ import annotations

import argparse
import math
import struct
import zlib
from pathlib import Path


WIDTH = 1920
HEIGHT = 1080


def blend(pixels: bytearray, x: int, y: int, colour: tuple[int, int, int], alpha: float) -> None:
    if not (0 <= x < WIDTH and 0 <= y < HEIGHT) or alpha <= 0:
        return
    offset = (y * WIDTH + x) * 3
    inverse = 1 - alpha
    pixels[offset] = int(pixels[offset] * inverse + colour[0] * alpha)
    pixels[offset + 1] = int(pixels[offset + 1] * inverse + colour[1] * alpha)
    pixels[offset + 2] = int(pixels[offset + 2] * inverse + colour[2] * alpha)


def line(pixels: bytearray, first: tuple[float, float], second: tuple[float, float], colour: tuple[int, int, int], width: float, alpha: float) -> None:
    x0, y0 = first
    x1, y1 = second
    distance = max(abs(x1 - x0), abs(y1 - y0), 1)
    radius = max(width / 2, 0.5)
    for step in range(int(distance) + 1):
        ratio = step / distance
        x = x0 + (x1 - x0) * ratio
        y = y0 + (y1 - y0) * ratio
        left = max(0, int(x - radius - 1))
        right = min(WIDTH - 1, int(x + radius + 1))
        top = max(0, int(y - radius - 1))
        bottom = min(HEIGHT - 1, int(y + radius + 1))
        for pixel_y in range(top, bottom + 1):
            for pixel_x in range(left, right + 1):
                distance_to_point = math.hypot(pixel_x - x, pixel_y - y)
                if distance_to_point <= radius:
                    edge = max(0.0, min(1.0, radius + 0.8 - distance_to_point))
                    blend(pixels, pixel_x, pixel_y, colour, alpha * edge)


def curve_points(control: tuple[tuple[float, float], ...], steps: int = 240) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for index in range(steps + 1):
        t = index / steps
        inverse = 1 - t
        x = (
            inverse**3 * control[0][0]
            + 3 * inverse**2 * t * control[1][0]
            + 3 * inverse * t**2 * control[2][0]
            + t**3 * control[3][0]
        )
        y = (
            inverse**3 * control[0][1]
            + 3 * inverse**2 * t * control[1][1]
            + 3 * inverse * t**2 * control[2][1]
            + t**3 * control[3][1]
        )
        points.append((x, y))
    return points


def draw_curve(pixels: bytearray, control: tuple[tuple[float, float], ...], colour: tuple[int, int, int], width: float, alpha: float) -> None:
    points = curve_points(control)
    for first, second in zip(points, points[1:]):
        line(pixels, first, second, colour, width, alpha)


def chunk(tag: bytes, payload: bytes) -> bytes:
    return len(payload).to_bytes(4, "big") + tag + payload + zlib.crc32(tag + payload).to_bytes(4, "big")


def write_png(path: Path, pixels: bytearray) -> None:
    rows = bytearray()
    for y in range(HEIGHT):
        rows.append(0)
        start = y * WIDTH * 3
        rows.extend(pixels[start : start + WIDTH * 3])
    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )


def create_background() -> bytearray:
    pixels = bytearray(WIDTH * HEIGHT * 3)
    for y in range(HEIGHT):
        vertical = y / (HEIGHT - 1)
        for x in range(WIDTH):
            horizontal = x / (WIDTH - 1)
            lower = max(0.0, (vertical - 0.55) / 0.45)
            red = 5 + int(5 * vertical + 2 * horizontal)
            green = 16 + int(18 * vertical + 5 * horizontal + 8 * lower)
            blue = 30 + int(25 * vertical + 12 * (1 - horizontal) + 14 * lower)
            offset = (y * WIDTH + x) * 3
            pixels[offset : offset + 3] = bytes((red, green, blue))

    curves = [
        (((-80, 790), (330, 670), (610, 900), (1010, 770)), (24, 92, 118), 4.0, 0.72),
        (((650, 810), (1060, 650), (1420, 890), (2000, 735)), (34, 128, 132), 2.5, 0.64),
        (((-100, 930), (420, 820), (1120, 1060), (2020, 920)), (175, 125, 61), 2.0, 0.56),
        (((-80, 1020), (480, 900), (1210, 1080), (2000, 970)), (48, 153, 160), 1.5, 0.48),
    ]
    for control, colour, width, alpha in curves:
        draw_curve(pixels, control, colour, width, alpha)

    for start, end in [
        ((60, 1080), (430, 770)),
        ((285, 1080), (620, 800)),
        ((1570, 1080), (1830, 790)),
        ((1760, 1080), (1960, 900)),
    ]:
        line(pixels, start, end, (24, 73, 95), 2.0, 0.62)

    for x, y, colour in (
        (150, 170, (156, 201, 206)),
        (1780, 210, (225, 187, 109)),
        (1510, 620, (156, 201, 206)),
        (260, 520, (156, 201, 206)),
    ):
        for radius in range(3, -1, -1):
            blend(pixels, x + radius, y, colour, 0.7 if radius == 0 else 0.22)
            blend(pixels, x - radius, y, colour, 0.7 if radius == 0 else 0.22)
            blend(pixels, x, y + radius, colour, 0.7 if radius == 0 else 0.22)
            blend(pixels, x, y - radius, colour, 0.7 if radius == 0 else 0.22)
    return pixels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("static/assets/background.png"))
    arguments = parser.parse_args()
    write_png(arguments.output, create_background())
    print(f"created {arguments.output} ({WIDTH}x{HEIGHT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
