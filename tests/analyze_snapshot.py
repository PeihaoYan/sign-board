"""Decode a PNG screenshot and inspect the signature wall composition.

Checks performed:
- the venue background image occupies most of the screen (dominant colour is not the fallback ink colour)
- white ink is present in the stage (the signatures)
- white ink is absent inside the floating QR card area (card is not overlapped)
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


def decode_png(path: Path) -> tuple[int, int, list[list[tuple[int, int, int]]]]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG file"
    position = 8
    width = height = 0
    bit_depth = colour_type = 0
    idat = bytearray()
    while position < len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        chunk_type = data[position + 4 : position + 8]
        chunk_body = data[position + 8 : position + 8 + length]
        if chunk_type == b"IHDR":
            width, height, bit_depth, colour_type = struct.unpack(">IIBB", chunk_body[:10])
        elif chunk_type == b"IDAT":
            idat.extend(chunk_body)
        elif chunk_type == b"IEND":
            break
        position += 12 + length

    assert bit_depth == 8, f"unsupported bit depth {bit_depth}"
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[colour_type]
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    rows: list[list[tuple[int, int, int]]] = []
    prior = bytearray(stride)

    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset : offset + stride])
        offset += stride
        for index in range(stride):
            left = line[index - channels] if index >= channels else 0
            up = prior[index]
            up_left = prior[index - channels] if index >= channels else 0
            if filter_type == 1:
                line[index] = (line[index] + left) & 0xFF
            elif filter_type == 2:
                line[index] = (line[index] + up) & 0xFF
            elif filter_type == 3:
                line[index] = (line[index] + ((left + up) >> 1)) & 0xFF
            elif filter_type == 4:
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                predictor = left if (pa <= pb and pa <= pc) else (up if pb <= pc else up_left)
                line[index] = (line[index] + predictor) & 0xFF
        row = []
        for x in range(width):
            base = x * channels
            if channels >= 3:
                row.append((line[base], line[base + 1], line[base + 2]))
            else:
                value = line[base]
                row.append((value, value, value))
        rows.append(row)
        prior = line
    return width, height, rows


def main() -> int:
    path = Path(sys.argv[1])
    width, height, rows = decode_png(path)
    print(f"size={width}x{height}")

    ink = 0
    dark_fallback = 0
    colours: dict[tuple[int, int, int], int] = {}
    for y in range(0, height, 3):
        for x in range(0, width, 3):
            pixel = rows[y][x]
            colours[pixel] = colours.get(pixel, 0) + 1
            if pixel[0] > 245 and pixel[1] > 245 and pixel[2] > 245:
                ink += 1
            if abs(pixel[0] - 16) < 6 and abs(pixel[1] - 29) < 6 and abs(pixel[2] - 43) < 6:
                dark_fallback += 1

    sampled = ((width // 3) * (height // 3))
    print(f"white_ink_samples={ink}")
    print(f"fallback_ink_samples={dark_fallback} of {sampled}")
    top = sorted(colours.items(), key=lambda item: item[1], reverse=True)[:3]
    print("dominant_colours=" + ", ".join(f"{colour}:{count}" for colour, count in top))

    # QR card area: 218 px wide plus margins at the bottom-right of the viewport.
    # The card itself is near-white, so look for the dark signature board instead:
    # that colour never belongs inside the card, so any hit means a bubble is hidden behind it.
    card_left = width - 34 - 218 - 8
    card_top = height - 34 - 300
    board_pixels_in_card = 0
    for y in range(max(card_top, 0), height):
        for x in range(max(card_left, 0), width):
            pixel = rows[y][x]
            if abs(pixel[0] - 22) < 14 and abs(pixel[1] - 40) < 14 and abs(pixel[2] - 58) < 14:
                board_pixels_in_card += 1
    print(f"signature_board_pixels_inside_qr_area={board_pixels_in_card}")

    card_width = 226
    strip_left = width - 34 - card_width
    strip_board = 0
    for y in range(height):
        for x in range(max(strip_left, 0), width):
            pixel = rows[y][x]
            if abs(pixel[0] - 22) < 14 and abs(pixel[1] - 40) < 14 and abs(pixel[2] - 58) < 14:
                strip_board += 1
    print(f"signature_board_pixels_in_right_strip={strip_board}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
