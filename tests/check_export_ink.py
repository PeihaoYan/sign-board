"""Check the exported PNG itself: is every signature's ink drawn, inside its own bubble?

The export is rendered by the page, saved as a PNG and then analysed with Pillow — no second render
to subtract, no assumptions about which layer a pixel belongs to. For every signature the check
reports the white ink found inside its bubble's box and compares that with what the same submission
renders to on its own at the export's scale.

Usage:
    python tests/check_export_ink.py [--base http://127.0.0.1:18195] [--slug integrity-2026]

The export is a share-of-stage rendering, so it is only the wall's own arrangement when it is laid
out with the wall's own geometry. The check therefore opens /display first, at `--stage`, lets it
report the geometry it laid out with, and only then exports from /monitor.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobile_probe import DevTools, start_edge  # noqa: E402

WIDE_STROKE = [[[10, 100], [120, 100], [240, 100], [360, 100], [470, 100]]]

CAPTURE = """(async () => {
  const rendered = await window.wallExport.renderWallPng({ slug: '%SLUG%' });
  return JSON.stringify({
    dataUrl: rendered.canvas.toDataURL('image/png'),
    canvas: [rendered.canvas.width, rendered.canvas.height],
    ratio: rendered.ratio,
    logical: [rendered.stage.logicalWidth, rendered.stage.logicalHeight],
    metrics: window.wallLayout.metricsFor(
      (rendered.geometry && rendered.geometry.count) || rendered.items.length,
      { stageWidth: rendered.stage.logicalWidth, stageHeight: rendered.stage.logicalHeight },
    ),
    bubbles: rendered.bubbles.map((bubble) => ({
      id: String(bubble.id),
      name: bubble.name || '',
      x: bubble.x,
      y: bubble.y,
    })),
  });
})()"""

REFERENCE = """(() => {
  const out = {};
  const metrics = %METRICS%;
  const ratio = %RATIO%;
  for (const item of %ITEMS%) {
    const canvas = document.createElement('canvas');
    window.renderSignatureInto(canvas, item, {
      width: metrics.inkWidth * ratio,
      height: metrics.inkHeight * ratio,
      lineWidth: 3.2,
      resolutionRatio: 1,
    });
    const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
    let minX = Infinity, maxX = -Infinity, painted = 0;
    for (let y = 0; y < canvas.height; y += 1) {
      for (let x = 0; x < canvas.width; x += 1) {
        if (data[(y * canvas.width + x) * 4 + 3] > 8) {
          painted += 1;
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
        }
      }
    }
    out[String(item.id)] = painted ? [maxX - minX + 1, painted] : [0, 0];
  }
  return JSON.stringify(out);
})()"""


def ink_in_box(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """White pixels inside the box: how many, and how wide and tall they span."""
    left, top, right, bottom = box
    width, height = image.size
    left, top = max(0, left), max(0, top)
    right, bottom = min(width, right), min(height, bottom)
    if right <= left or bottom <= top:
        return 0, 0, 0
    crop = image.crop((left, top, right, bottom))
    pixels = crop.load()
    count = 0
    min_x, min_y, max_x, max_y = crop.width, crop.height, -1, -1
    for y in range(crop.height):
        for x in range(crop.width):
            red, green, blue = pixels[x, y]
            if red > 225 and green > 225 and blue > 225:
                count += 1
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if count == 0:
        return 0, 0, 0
    return count, max_x - min_x + 1, max_y - min_y + 1


def read_geometry(base: str, slug: str) -> dict | None:
    """The geometry the wall last reported, or None when it never did."""
    try:
        with urllib.request.urlopen(
            f"{base}/api/events/{slug}/wall-geometry", timeout=5
        ) as response:
            return json.load(response).get("geometry")
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--key", default="probe-monitor")
    parser.add_argument("--out", default="tests/shots/export-ink.png")
    parser.add_argument("--stage", default="1920x1080", help="the wall's own window size, WxH")
    parser.add_argument("--keep-geometry", action="store_true", help="do not open /display first")
    arguments = parser.parse_args()

    # A stroke that spans its whole bubble, submitted under a unique name so it can be found again.
    marker = f"墨迹{int(time.time())}"
    request = urllib.request.Request(
        f"{arguments.base}/api/events/{arguments.slug}/submissions",
        data=json.dumps({"name": marker, "strokes": WIDE_STROKE, "device_token": f"ink-{marker}"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        print(f"submitted the probe stroke as {marker}: {response.status}")

    port = 19263
    profile = Path(tempfile.mkdtemp(prefix="edge-ink2-"))
    process = start_edge(port, profile)
    failures: list[str] = []
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)
        if not arguments.keep_geometry:
            width_text, height_text = arguments.stage.lower().split("x")
            devtools.call(
                "Emulation.setDeviceMetricsOverride",
                width=int(width_text),
                height=int(height_text),
                deviceScaleFactor=1,
                mobile=False,
            )
            before = read_geometry(arguments.base, arguments.slug)
            devtools.call(
                "Page.navigate",
                url=f"{arguments.base}/display?event={arguments.slug}",
            )
            # Wait for a *fresh* report: the stored one may be from an entirely different screen,
            # and a stale report lays the export out at the wrong size. Comparing the report's
            # timestamp catches that, where merely waiting for a non-empty answer does not.
            deadline = time.time() + 40
            reported = before
            while time.time() < deadline:
                reported = read_geometry(arguments.base, arguments.slug)
                fresh = reported and reported.get("updated_at")
                if fresh and (not before or fresh != before.get("updated_at")):
                    break
                time.sleep(0.4)
            print(
                f"wall reported geometry {json.dumps(reported, ensure_ascii=False)}"
                if reported
                else "wall reported no geometry; the export will use this window's size"
            )
        devtools.call(
            "Page.navigate",
            url=f"{arguments.base}/monitor?event={arguments.slug}&key={arguments.key}",
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            if devtools.evaluate("Boolean(window.wallExport && window.wallSync)"):
                break
            time.sleep(0.3)
        time.sleep(1.5)

        result = json.loads(devtools.evaluate(CAPTURE.replace("%SLUG%", arguments.slug)))
        target = Path(arguments.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(result["dataUrl"].split(",", 1)[1]))
        ratio = result["ratio"]
        metrics = result["metrics"]
        print(
            f"export {result['canvas'][0]}x{result['canvas'][1]} ratio {ratio:.3f}"
            f" bubble {metrics['width']}x{metrics['height']} ink {metrics['inkWidth']}x{metrics['inkHeight']}"
        )
        print(f"saved {target} ({(target.stat().st_size / 1024):.0f} KB)")

        items = json.loads(
            devtools.evaluate(
                "fetch('/api/events/" + arguments.slug + "/display', { cache: 'no-store' })"
                ".then((r) => r.json()).then((d) => JSON.stringify(d.items))"
            )
        )
        references = json.loads(
            devtools.evaluate(
                REFERENCE.replace("%METRICS%", json.dumps(metrics))
                .replace("%RATIO%", json.dumps(ratio))
                .replace("%ITEMS%", json.dumps(items))
            )
        )

        image = Image.open(target).convert("RGB")
        bubble_w = metrics["width"] * ratio
        bubble_h = metrics["height"] * ratio
        ink_w = metrics["inkWidth"] * ratio
        checked = 0
        empty = 0
        for bubble in result["bubbles"]:
            centre_x = (bubble["x"] / 100) * result["logical"][0] * ratio
            centre_y = (bubble["y"] / 100) * result["logical"][1] * ratio
            half_w = bubble_w / 2 + 6
            half_h = bubble_h / 2 + 6
            count, box_w, box_h = ink_in_box(image, (
                round(centre_x - half_w), round(centre_y - half_h),
                round(centre_x + half_w), round(centre_y + half_h),
            ))
            expected_w = references.get(bubble["id"], [0, 0])[0]
            ratio_w = box_w / expected_w if expected_w else 0
            is_probe = bubble["name"] == marker
            print(
                f"  {bubble['id']:<4} {bubble['name'][:8]:<9} at {round(centre_x):>5},{round(centre_y):>5}"
                f" white {count:>6} box {box_w}x{box_h} renderer {expected_w}px"
                f" ratio {ratio_w:.2f}{'  <- probe' if is_probe else ''}"
            )
            if count == 0:
                empty += 1
                continue
            checked += 1
            if is_probe:
                # The probe stroke spans its bubble, so its ink must come out wide; this is the
                # assertion that catches a scaling fault in the export's transform.
                if box_w < ink_w * 0.5:
                    failures.append(f"the probe stroke spans {box_w}px of its {ink_w:.0f}px ink area")
                elif ratio_w and ratio_w < 0.25:
                    failures.append(
                        f"the probe stroke is {box_w}px wide against the renderer's {expected_w}px"
                    )

        if checked == 0:
            failures.append("no signature had any ink in the picture")
        # A handful of empty boxes is tolerated: a bubble's box can hold only the tail of a
        # neighbour's ink, and the wall carries test signatures from earlier runs. A collapse
        # towards zero is not.
        if result["bubbles"] and empty > len(result["bubbles"]) * 0.2:
            failures.append(
                f"{empty} of {len(result['bubbles'])} signatures have no ink in their own box"
            )

        # A whole-picture check that does not depend on the per-bubble boxes at all: the export must
        # be much whiter than the bare venue background, wherever the ink happens to be.
        background = devtools.evaluate(
            """(async () => {
              const canvas = document.createElement('canvas');
              const image = new Image();
              await new Promise((resolve, reject) => {
                image.onload = resolve;
                image.onerror = reject;
                image.src = '/assets/assets/background.svg';
              });
              canvas.width = 400;
              canvas.height = 254;
              const context = canvas.getContext('2d');
              context.drawImage(image, 0, 0, canvas.width, canvas.height);
              const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
              let white = 0;
              for (let index = 0; index < data.length; index += 4) {
                if (data[index] > 225 && data[index + 1] > 225 && data[index + 2] > 225) white += 1;
              }
              return JSON.stringify({ white, total: data.length / 4 });
            })()"""
        )
        background_stats = json.loads(background)
        print(
            f"background alone: {background_stats['white']} of {background_stats['total']} sampled"
            f" pixels are white ({background_stats['white'] / background_stats['total'] * 100:.1f}%)"
        )

        # The picture's own white count, sampled the same way, must be clearly higher: that is the
        # ink and the names.
        picture = Image.open(target).convert("RGB")
        picture_pixels = picture.load()
        picture_white = 0
        picture_total = 0
        for y in range(0, picture.height, 4):
            for x in range(0, picture.width, 4):
                red, green, blue = picture_pixels[x, y]
                picture_total += 1
                if red > 225 and green > 225 and blue > 225:
                    picture_white += 1
        picture_share = picture_white / picture_total * 100
        background_share = background_stats["white"] / background_stats["total"] * 100
        print(
            f"export picture: {picture_white} of {picture_total} sampled pixels are white"
            f" ({picture_share:.1f}%)"
        )
        if picture_share <= background_share + 0.3:
            failures.append(
                f"the picture is no whiter than the bare background"
                f" ({picture_share:.1f}% against {background_share:.1f}%), so no ink was drawn"
            )

        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"checked={checked} failures={len(failures)}")
        return 1 if failures else 0
    finally:
        try:
            devtools.close()
        except Exception:
            pass
        process.terminate()


if __name__ == "__main__":
    sys.exit(main())
