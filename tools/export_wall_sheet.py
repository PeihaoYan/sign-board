"""Arrange the event's signatures evenly on the wall background and save the finished picture.

The wall itself places signatures at random positions with a minimum spacing, which is right for a
live screen where signatures keep arriving, and wrong for a keepsake picture: the arrangement is
scattered, clustered in places, and when only a few dozen signatures exist they bunch near the middle
of the room's space rather than filling it.

This lays the same signatures out evenly instead — a centred block of cells, every signature scaled by
one shared factor so a naturally large signature does not dwarf its neighbours, names underneath — and
draws them on the venue background at the screen's own resolution. It also writes the strokes to a JSON
sidecar, so the handwriting is preserved as data and not only as pixels.

Usage:
    python tools/export_wall_sheet.py                       # the live event, 1920x1080
    python tools/export_wall_sheet.py --width 1920 --height 1080 --margin 0.06
    python tools/export_wall_sheet.py --seed-signatures 12  # a preview needing no server
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BACKGROUND = ROOT / "static" / "assets" / "background.png"
OUT_DIR = ROOT / "deliverables"

INK = (255, 255, 255)
NAME_INK = (255, 255, 255)
# The phone records a stroke at 4.6 px in the canvas's own pixels, and the signatures that come back
# measure about 280x126 px (median over the 30 signed at this event) with a point every 2.2 px. The
# pen for the picture is therefore 4.6 x (the same scale the coordinates get): fixing it to a share of
# the picture's height instead drew 59 px wide lines through a 250 px signature, and every signature
# came out as a solid blob.
PHONE_PEN = 4.6
# A floor, so a wall of several hundred signatures — where the shared scale falls to about a tenth —
# still has a visible line rather than a smudge. As a share of the picture's height.
MIN_PEN_SHARE = 0.0016
NAME_SHARE = 0.016            # name size as a share of the picture's height, by default
# The name is written smaller than the wall's own name size would suggest, because the picture is
# looked at as a whole rather than from across a room.
NAME_SHARE_OF_CELL = 0.115
# The share of a cell a signature's own bounding box may take. The rest is breathing room, which is
# what makes the block read as evenly spaced rather than as a contact sheet.
SIGNATURE_FIT = 0.82
# Rendering happens at this multiple of the final size and is then reduced with Lanczos. Pillow draws
# no antialiasing of its own, so a 2 px line at final resolution is a staircase; at 3x with Lanczos it
# is a smooth stroke. This is the whole of the smoothing — the pen stays the same weight, so the
# handwriting does not get bolder.
SUPERSAMPLE = 3
# How many pixels apart the inserted curve points are, at the supersampled resolution.
CURVE_STEP = 3.0
# How far a signature may wander from the centre of its cell, as a share of the cell's width/height.
# The allowance is bounded by what is left over: the block (handwriting plus the name under it) is
# 156 px tall in a 200 px cell, so only 22 px of vertical slack exists, and the row below has none to
# spare. These numbers move a signature by up to ~13 px across and ~6 px down in a 214x200 px cell:
# enough to break the grid, not enough to overlap a neighbour or run off the edge.
WANDER_X = 0.055
WANDER_Y = 0.028
# A signature occasionally sits further out, which is what makes the arrangement read as placed by hand
# rather than mechanically jittered: most stay near their cell, a few drift towards its edge.
WANDER_OUTLIER = 1.6
WANDER_OUTLIER_SHARE = 0.25
FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyhbd.ttc",   # Microsoft YaHei Bold
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",   # SimHei
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    raise SystemExit("no CJK-capable font found; add one to FONT_CANDIDATES")


def fetch_live(base: str, slug: str, token: str) -> list[dict]:
    request = urllib.request.Request(
        f"{base}/api/admin/events/{slug}/submissions",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        rows = json.load(response).get("items", [])
    signatures = []
    for row in rows:
        if row.get("status") != "approved":
            continue
        # Every recorded stroke is kept, including one that is a single tap: a dot is part of the
        # handwriting, and dropping it changes the signature. `bounds` reads all points, so a tap also
        # has to count towards the signature's own extent.
        strokes = [list(stroke) for stroke in (row.get("strokes") or []) if stroke]
        if not strokes:
            continue
        signatures.append({"id": row["id"], "name": row.get("name") or "", "strokes": strokes,
                           "created_at": row.get("created_at")})
    # Oldest first, so the picture reads in the order people signed.
    signatures.sort(key=lambda item: item.get("created_at") or "")
    return signatures


def make_preview(count: int, seed: int = 7) -> list[dict]:
    """Synthetic signatures, so the layout can be checked without touching the event."""
    rng = random.Random(seed)
    names = ["张伟", "李娜", "王芳", "刘洋", "陈静", "杨帆", "赵磊", "黄敏", "周涛", "吴迪",
             "徐强", "孙悦", "马超", "朱婷", "胡军", "郭鹏", "何洁", "高原", "林峰", "罗兰"]
    signatures = []
    for index in range(count):
        strokes = []
        for _ in range(rng.randint(2, 4)):
            x = rng.uniform(30, 160)
            y = rng.uniform(40, 150)
            points = []
            for _ in range(rng.randint(40, 90)):
                x += rng.uniform(0.5, 3.5)
                y += rng.gauss(0, 6)
                points.append([x, y])
            strokes.append(points)
        signatures.append({"id": index + 1, "name": names[index % len(names)], "strokes": strokes})
    return signatures


def bounds(strokes: list[list[list[float]]]) -> tuple[float, float, float, float]:
    xs = [point[0] for stroke in strokes for point in stroke]
    ys = [point[1] for stroke in strokes for point in stroke]
    return min(xs), min(ys), max(xs), max(ys)


def scatter_cells(count: int, width: int, height: int, margin: float, top: float, bottom: float,
                  gap: float, tries: int, seed: int = 20260923) -> tuple[list[tuple[float, float, float]], tuple[float, float]]:
    """Random positions with a minimum spacing — how signatures accumulate on a real signing wall.

    A real wall is not a grid: people sign wherever there is room, so signatures vary in size, sit at
    slightly different angles, and occasionally touch or overlap where the wall has filled up. This
    reproduces that by drawing a random position for each signature and accepting it when it clears the
    ones already placed by `gap` (a fraction of a signature's size); a position that cannot be found is
    accepted anyway, which is what produces the handful of overlaps.

    The budget is generous compared with the live wall's, because this runs once, offline, for a
    picture: the picture can afford to look carefully for a good spot, where the live wall cannot.

    Returns the positions and the size one signature is allowed, both in picture pixels.
    """
    usable_w = width * (1 - margin * 2)
    usable_h = height * (1 - top - bottom)
    # One signature's allowance: the band divided by the count, in the proportions a signature has.
    # This is the same density the grid layout uses, so the two versions of the picture differ in
    # arrangement rather than in how full the wall is.
    area_per_signature = (usable_w * usable_h) / max(count, 1)
    block_w = math.sqrt(area_per_signature / 0.72)
    block_h = block_w * 0.72
    rng = random.Random(seed)
    half_w, half_h = block_w / 2, block_h / 2
    placed: list[tuple[float, float]] = []
    positions: list[tuple[float, float, float]] = []
    for _ in range(count):
        best: tuple[float, float] | None = None
        best_gap = -1.0
        for _attempt in range(tries):
            x = width * margin + half_w + rng.random() * (usable_w - block_w)
            y = height * top + half_h + rng.random() * (usable_h - block_h)
            nearest = math.inf
            for other_x, other_y in placed:
                # Distance in units of one signature, so the clearance reads the same horizontally and
                # vertically despite a block being wider than it is tall.
                dx = (x - other_x) / block_w
                dy = (y - other_y) / block_h
                nearest = min(nearest, math.hypot(dx, dy))
            if nearest >= gap:
                best = (x, y)
                break
            if nearest > best_gap:
                best_gap = nearest
                best = (x, y)
        # The angle is small on purpose: a real wall of handwriting is written along lines, and a wall
        # of wildly tilted signatures reads as a fairground, not as a signing wall.
        positions.append((best[0], best[1], rng.uniform(-6.0, 6.0)))
        placed.append(best)
    return positions, (block_w, block_h)


def layout_cells(count: int, width: int, height: int, margin: float,
                 top: float = 0.2, bottom: float = 0.06) -> tuple[int, int, list[tuple[float, float]], tuple[float, float]]:
    """A centred block of cells, as square as the picture's proportions allow.

    The block is what gets the margin, not the picture: with a handful of signatures the cells stay
    comfortably large and sit together in the middle, and with a few hundred the block fills the
    screen. Positioning cells at fixed fractions of the whole screen instead is what puts two
    signatures in the middle of a big empty wall.

    The margins are not symmetric, because this background is not: its title and university mark fill
    the top fifth and the campus artwork fills the bottom, so the block lives in the band between
    them. A uniform margin ran the first row of signatures straight through the title.
    """
    usable_w = width * (1 - margin * 2)
    usable_h = height * (1 - top - bottom)
    # Cell shape: wider than tall, because a signature is wider than it is tall once its name is under
    # it. 1.25 keeps the block from becoming a tall column.
    best: tuple[tuple[float, ...], int, int] | None = None
    for columns in range(1, count + 1):
        rows = math.ceil(count / columns)
        cell_w = usable_w / columns
        cell_h = usable_h / rows
        if cell_w <= 0 or cell_h <= 0:
            continue
        ratio = cell_w / cell_h
        # Favour cells between 1.0 and 1.9 times as wide as they are tall; among those, prefer the
        # block that fills the band best, then the larger cell.
        penalty = 0 if 1.0 <= ratio <= 1.9 else min(abs(ratio - 1.0), abs(ratio - 1.9))
        used = min(cell_w * columns / usable_w, cell_h * rows / usable_h)
        score = (penalty, -used, -min(cell_w, cell_h))
        if best is None or score < best[0]:
            best = (score, columns, rows)
    assert best is not None
    _, columns, rows = best
    cell_w = usable_w / columns
    cell_h = usable_h / rows
    centers = []
    for index in range(count):
        row, column = divmod(index, columns)
        centers.append((
            width * margin + (column + 0.5) * cell_w,
            height * top + (row + 0.5) * cell_h,
        ))
    return columns, rows, centers, (cell_w, cell_h)


def smooth_points(points: list[list[float]], step: float) -> list[tuple[float, float]]:
    """Resample a stroke onto a smooth curve through its recorded points.

    The phone samples a stroke every ~2.2 px, and a cheap stylus or a finger leaves those samples
    slightly off the line the hand drew, so drawing straight segments between them gives handwriting
    that looks faceted and pixelated. Each span between two recorded points is replaced by a
    Catmull-Rom curve through their neighbours — the curve that passes through the recorded points
    rather than merely near them, so the shape of the signature is unchanged — and the curve is
    sampled at `step` intervals. The end points are preserved exactly.
    """
    if len(points) < 3:
        return [(float(x), float(y)) for x, y in points]
    control = [(float(x), float(y)) for x, y in points]
    result: list[tuple[float, float]] = [control[0]]
    for index in range(len(control) - 1):
        p0 = control[index - 1] if index > 0 else control[0]
        p1 = control[index]
        p2 = control[index + 1]
        p3 = control[index + 2] if index + 2 < len(control) else control[-1]
        span = math.dist(p1, p2)
        steps = max(2, min(24, int(span / step) + 1))
        for step_index in range(1, steps):
            t = step_index / steps
            t2, t3 = t * t, t * t * t
            # Catmull-Rom basis.
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
                       + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                       + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            result.append((x, y))
        result.append(p2)
    return result


def wander_offset(item_id: int, width: float, height: float) -> tuple[float, float]:
    """How far this signature sits from the centre of its cell.

    Seeded by the signature's id, so the picture is reproducible: re-running the export gives the same
    arrangement rather than a new shuffle. Most signatures land within about half the allowance and a
    few use all of it, which is what makes the block look placed by hand instead of mechanically
    jittered. The vertical allowance is the tighter of the two, because a block is tall — the
    handwriting plus its name — and a cell has only about a third of its height spare.
    """
    seed = 20260923 + item_id * 2654435761
    rng = random.Random(seed)

    def one(scale: float) -> float:
        reach = scale * (WANDER_OUTLIER if rng.random() < WANDER_OUTLIER_SHARE else 1.0)
        return rng.uniform(-reach, reach)

    return one(width * WANDER_X), one(height * WANDER_Y)


def draw_stroke(draw: ImageDraw.ImageDraw, points: list[list[float]], transform, stroke_width: int) -> None:
    """Draw one stroke: a smooth polyline with round ends, or a dot for a single-point stroke.

    `joint="curve"` must not be used here. Pillow's curved joints are drawn as filled circles of the
    *line width* at every vertex, so a dense handwritten stroke — a hundred points a few pixels apart,
    which is exactly what the phone records — comes out as one solid blob per stroke. `joint="curve"`
    is for wide, sparse polylines; handwriting needs plain segments plus round caps, and the smoothing
    comes from `smooth_points` and the supersampled render instead.
    """
    screen = [transform(point) for point in points]
    if not screen:
        return
    radius = max(stroke_width / 2, 0.5)
    if len(screen) == 1:
        # A tap: the phone records these, and they are part of a signature (a dot over a character).
        x, y = screen[0]
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=INK)
        return
    for start, end in zip(screen, screen[1:]):
        draw.line([start, end], fill=INK, width=stroke_width)
    # Round caps: a plain line has square ends, which makes handwriting look cut off.
    for x, y in (screen[0], screen[-1]):
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=INK)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18180")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--token-file", default=".secrets/admin-token.txt")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--margin", type=float, default=0.055, help="free space on the left and right")
    parser.add_argument("--top", type=float, default=0.2,
                        help="free space above the block, which is where the background's title sits")
    parser.add_argument("--bottom", type=float, default=0.06, help="free space below the block")
    parser.add_argument("--seed-signatures", type=int, default=0, help="use synthetic signatures instead")
    parser.add_argument("--style", choices=("grid", "random"), default="grid",
                        help="grid: an even block for a keepsake; random: the looser arrangement of a"
                             " real signing wall, with a few signatures touching")
    parser.add_argument("--scatter-gap", type=float, default=0.92,
                        help="for --style random: the clearance between signatures, in units of one"
                             " signature's size; 1.0 means they just touch, lower values crowd them")
    parser.add_argument("--scatter-tries", type=int, default=400,
                        help="for --style random: candidate positions tried per signature")
    parser.add_argument("--supersample", type=int, default=SUPERSAMPLE,
                        help="draw at this multiple of the output size and reduce, for smooth edges;"
                             " 1 turns the smoothing off, which is only useful for measuring it")
    parser.add_argument("--out", default="")
    arguments = parser.parse_args()

    if arguments.seed_signatures:
        signatures = make_preview(arguments.seed_signatures)
        source = f"{arguments.seed_signatures} synthetic signatures (preview)"
    else:
        token = (ROOT / arguments.token_file).read_text(encoding="utf-8").strip()
        signatures = fetch_live(arguments.base, arguments.slug, token)
        source = f"{arguments.base} / {arguments.slug}"
    if not signatures:
        print("no signatures to draw")
        return 1

    width, height = arguments.width, arguments.height
    # Everything is drawn at SUPERSAMPLE times the final size and reduced at the end, because Pillow
    # draws no antialiasing: a 2 px stroke at final resolution is a staircase of full white pixels.
    # The pen keeps its width in final pixels — drawing at 3x and reducing gives the same weight with
    # smooth edges, it does not thicken the handwriting.
    ss = max(1, arguments.supersample)
    canvas_w, canvas_h = width * ss, height * ss
    background = Image.open(BACKGROUND).convert("RGB")
    if background.size != (width, height):
        background = background.resize((width, height), Image.LANCZOS)
    if ss != 1:
        background = background.resize((canvas_w, canvas_h), Image.LANCZOS)
    image = background.copy()
    draw = ImageDraw.Draw(image)

    if arguments.style == "random":
        positions, (block_w, block_h) = scatter_cells(
            len(signatures), width, height, arguments.margin, arguments.top, arguments.bottom,
            arguments.scatter_gap, arguments.scatter_tries,
        )
        cell_w, cell_h = block_w * ss, block_h * ss
        centers = [(x * ss, y * ss) for x, y, _angle in positions]
        angles = [angle for _x, _y, angle in positions]
        columns, rows = 0, 0
    else:
        columns, rows, centers, (cell_w, cell_h) = layout_cells(
            len(signatures), width, height, arguments.margin, arguments.top, arguments.bottom
        )
        cell_w, cell_h = cell_w * ss, cell_h * ss
        centers = [(x * ss, y * ss) for x, y in centers]
        angles = [0.0] * len(centers)

    # One shared scale for every signature: fit the widest and tallest of them into the cell, and use
    # that for all. Scaling each signature to fill its own cell would make a small signature as large
    # as a sweeping one, which reads as noise rather than as a wall of signatures.
    #
    # What has to fit is the whole block — the handwriting *and* the name under it. Fitting only the
    # handwriting made blocks up to 25% taller than their cell (a 185 px signature became a 178 px block
    # in a 200 px cell before the name was counted), so names were written over the row below and the
    # last row was pushed off the edge of the picture.
    boxes = [bounds(item["strokes"]) for item in signatures]
    widest = max(box[2] - box[0] for box in boxes)
    tallest = max(box[3] - box[1] for box in boxes)
    name_size = max(11, round(cell_h * NAME_SHARE_OF_CELL))
    font = load_font(name_size)
    name_gap = round(name_size * 0.45)
    ink_h = cell_h * SIGNATURE_FIT - name_gap - name_size
    ink_w = cell_w * SIGNATURE_FIT
    scale = min(ink_w / widest, ink_h / tallest)
    # The pen is chosen in *final* pixels and then multiplied up for the supersampled canvas, so a
    # supersampled render and a plain one have exactly the same stroke weight — the only difference
    # between them is the antialiasing.
    pen_px = max(PHONE_PEN * scale / ss, canvas_h * MIN_PEN_SHARE / ss, 1.0)
    stroke_width = max(round(pen_px * ss), ss)
    # What each signature actually occupies, kept so the checks can confirm nothing overlaps and
    # nothing falls outside the picture.
    drawn_blocks: list[tuple[float, float, float, float]] = []
    # Smoothing is done once, on the recorded points, before any scaling: the curve only depends on the
    # shape of the stroke, so it is the same curve whatever the picture's size is.
    smoothed = [
        [smooth_points(stroke, CURVE_STEP / max(scale, 1e-6)) for stroke in item["strokes"]]
        for item in signatures
    ]

    for index, (item, (min_x, min_y, max_x, max_y)) in enumerate(zip(signatures, boxes)):
        center_x, center_y = centers[index]
        if arguments.style == "random":
            # A real wall has no cells, so nothing to wander within: the position already is the
            # arrangement. A little size variation is what a wall of different hands looks like.
            wander_x, wander_y = 0.0, 0.0
            signature_scale = scale * (1.0 + random.Random(int(item["id"])).uniform(-0.1, 0.1))
        else:
            wander_x, wander_y = wander_offset(int(item["id"]), cell_w, cell_h)
            signature_scale = scale
        drawn_w = (max_x - min_x) * signature_scale
        drawn_h = (max_y - min_y) * signature_scale
        # Centre the signature above the cell's baseline and put the name under it, so a tall
        # signature does not push its own name out of the cell.
        block_h = drawn_h + name_gap + name_size
        origin_y = center_y + wander_y - block_h / 2
        origin_x = center_x + wander_x - drawn_w / 2
        drawn_blocks.append((origin_x, origin_y, drawn_w, block_h))

        # A small tilt, applied about the signature's own centre in the supersampled space, so the
        # arrangement has the slight unevenness of a wall signed by different hands.
        angle = math.radians(angles[index])
        pivot_x = origin_x + drawn_w / 2
        pivot_y = origin_y + block_h / 2

        def transform(point, origin_x=origin_x, origin_y=origin_y, min_x=min_x, min_y=min_y,
                      signature_scale=signature_scale, angle=angle,
                      pivot_x=pivot_x, pivot_y=pivot_y):
            x = origin_x + (point[0] - min_x) * signature_scale
            y = origin_y + (point[1] - min_y) * signature_scale
            if not angle:
                return (x, y)
            dx, dy = x - pivot_x, y - pivot_y
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            return (pivot_x + dx * cos_a - dy * sin_a, pivot_y + dx * sin_a + dy * cos_a)

        for stroke in smoothed[index]:
            draw_stroke(draw, stroke, transform, stroke_width)
        if item["name"]:
            text_box = draw.textbbox((0, 0), item["name"], font=font)
            text_w = text_box[2] - text_box[0]
            draw.text(
                (center_x + wander_x - text_w / 2, origin_y + drawn_h + name_gap - text_box[1]),
                item["name"],
                font=font,
                fill=NAME_INK,
            )

    if ss != 1:
        image = image.resize((width, height), Image.LANCZOS)

    # Geometric checks on what was drawn, in final pixels. They are the picture's own invariants: a
    # signature that runs off the edge is cropped in the file, and two that overlap are unreadable.
    # The grid style must have neither; the random style is meant to have a few overlaps — that is what
    # a real signing wall looks like — so for it the overlaps are counted and reported instead.
    outside = [
        item["name"] for item, (x, y, w, h) in zip(signatures, drawn_blocks)
        if x < 0 or y < 0 or x + w > canvas_w or y + h > canvas_h
    ]
    overlaps: list[str] = []
    overlap_area = 0.0
    for first in range(len(drawn_blocks)):
        for second in range(first + 1, len(drawn_blocks)):
            ax, ay, aw, ah = drawn_blocks[first]
            bx, by, bw, bh = drawn_blocks[second]
            if ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by:
                overlaps.append(f"{signatures[first]['name']}/{signatures[second]['name']}")
                overlap_area += (min(ax + aw, bx + bw) - max(ax, bx)) * (min(ay + ah, by + bh) - max(ay, by))
    total_area = sum(w * h for _x, _y, w, h in drawn_blocks)
    overlap_share = overlap_area / max(total_area, 1) * 100

    OUT_DIR.mkdir(exist_ok=True)
    stamp = f"{width}x{height}"
    target = Path(arguments.out) if arguments.out else OUT_DIR / f"signature-wall-{stamp}.png"
    image.save(target, "PNG", optimize=True)
    strokes_file = target.with_suffix(".strokes.json")
    strokes_file.write_text(
        json.dumps(
            {
                "source": source,
                "exported_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
                "stage": [width, height],
                "layout": {"style": arguments.style,
                           "columns": columns if arguments.style == "grid" else None,
                           "rows": rows if arguments.style == "grid" else None,
                           "scatter_gap": arguments.scatter_gap if arguments.style == "random" else None,
                           "margin": arguments.margin,
                           "cell": [round(cell_w / ss, 1), round(cell_h / ss, 1)],
                           "shared_scale": round(scale / ss, 5),
                           "pen_px": round(stroke_width / ss, 2),
                           "supersample": ss, "name_px": round(name_size / ss, 1)},
                "signatures": signatures,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    print(f"source: {source}")
    print(f"signatures: {len(signatures)} in {arguments.style} style"
          f" (band {width * (1 - arguments.margin * 2):.0f}x{height * (1 - arguments.top - arguments.bottom):.0f} px,"
          f" one signature {cell_w / ss:.0f}x{cell_h / ss:.0f} px, shared scale {scale / ss:.3f},"
          f" pen {stroke_width / ss:.2f} px, drawn at {ss}x and reduced for smooth edges)")
    print(f"picture: {target}  {target.stat().st_size / 1024 / 1024:.2f} MB  {width}x{height}")
    print(f"strokes preserved as data: {strokes_file}  {strokes_file.stat().st_size / 1024:.0f} KB")
    print(f"  names: {'、'.join(item['name'] for item in signatures if item['name'])}")
    print(f"  layout checks: {len(outside)} signatures outside the picture,"
          f" {len(overlaps)} overlapping pairs, overlap {overlap_share:.1f}% of the ink area"
          f" (style {arguments.style})")
    if outside:
        print(f"  FAIL: outside the picture: {outside[:6]}")
    if overlaps:
        print(f"  note: touching or overlapping: {overlaps[:6]}")
    # The grid version promises no overlaps; the random one is allowed a few, which is the whole point
    # of it, but not so many that the wall stops being readable.
    limit = 0 if arguments.style == "grid" else max(1, round(len(signatures) * 0.35))
    if len(overlaps) > limit:
        print(f"  FAIL: {len(overlaps)} overlapping pairs is more than the {limit} this style allows")
        return 1
    if arguments.style == "random" and overlap_share > 12:
        print(f"  FAIL: {overlap_share:.1f}% of the ink sits on top of other ink")
        return 1
    print("  sha256 picture:", hashlib.sha256(target.read_bytes()).hexdigest()[:16])
    return 0 if not outside else 1


if __name__ == "__main__":
    raise SystemExit(main())
