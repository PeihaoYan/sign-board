"""Check that the monitor page's PNG export is the big screen, in the same arrangement.

The picture is produced by the page, so the check drives a real browser: it opens the wall in one
tab, records where every bubble sits on it, opens the monitor page in another, triggers the export
and compares the two arrangements bubble by bubble. It also inspects the exported bitmap, so an
export that is completely blank, or that never painted the venue background, fails instead of
passing on metadata alone.

Usage:
    python tests/check_wall_export.py [--url http://127.0.0.1:18195] [--key <monitor token>]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobile_probe import DevTools, start_edge  # noqa: E402

WALL_POSITIONS = """(() => {
  const stage = document.querySelector('.wall-stage');
  const stageRect = stage.getBoundingClientRect();
  const positions = {};
  document.querySelectorAll('.signature-bubble').forEach((bubble) => {
    const rect = bubble.getBoundingClientRect();
    positions[bubble.dataset.id] = {
      x: ((rect.left + rect.width / 2 - stageRect.left) / stageRect.width) * 100,
      y: ((rect.top + rect.height / 2 - stageRect.top) / stageRect.height) * 100,
      inline: [bubble.style.left, bubble.style.top],
    };
  });
  const card = document.querySelector('.qr-card');
  const cardRect = card ? card.getBoundingClientRect() : null;
  return JSON.stringify({
    count: Object.keys(positions).length,
    positions,
    stage: { width: stage.clientWidth, height: stage.clientHeight },
    rendered: window.wallLayout ? window.wallLayout.lastRendered : null,
    qr: cardRect ? {
      left: cardRect.left - stageRect.left,
      right: cardRect.right - stageRect.left,
      top: cardRect.top - stageRect.top,
      bottom: cardRect.bottom - stageRect.top,
    } : null,
  });
})()"""

# The wall lays out once more after its QR card settles, so the comparison reads the wall only
# once its own arrangement has stopped changing.
WALL_FINGERPRINT = """JSON.stringify(Array.from(document.querySelectorAll('.signature-bubble'))
  .map((bubble) => bubble.dataset.id + bubble.style.left + bubble.style.top))"""


def wait_for_stable(devtools: DevTools, timeout: float = 8.0, interval: float = 0.4) -> bool:
    deadline = time.time() + timeout
    previous = devtools.evaluate(WALL_FINGERPRINT)
    while time.time() < deadline:
        time.sleep(interval)
        current = devtools.evaluate(WALL_FINGERPRINT)
        if current and current == previous:
            return True
        previous = current
    return False

# Runs the export inside the monitor page and reports the arrangement plus what the bitmap holds.
RUN_EXPORT = """(async () => {
  const rendered = await window.wallExport.renderWallPng({ slug: 'integrity-2026' });
  const canvas = rendered.canvas;
  const context = canvas.getContext('2d');
  const { width, height } = canvas;
  const pixels = context.getImageData(0, 0, width, height).data;
  const colours = new Map();
  let white = 0;
  let transparent = 0;
  const step = 4;
  for (let index = 0; index < pixels.length; index += 4 * step) {
    const r = pixels[index];
    const g = pixels[index + 1];
    const b = pixels[index + 2];
    const a = pixels[index + 3];
    if (a < 8) transparent += 1;
    if (r > 235 && g > 235 && b > 235) white += 1;
    const key = `${r >> 5}:${g >> 5}:${b >> 5}`;
    colours.set(key, (colours.get(key) || 0) + 1);
  }
  const sampled = Math.ceil(pixels.length / (4 * step));
  return JSON.stringify({
    canvas: { width, height },
    ratio: rendered.ratio,
    stage: rendered.stage,
    geometry: rendered.geometry,
    items: rendered.items.length,
    bubbles: rendered.bubbles,
    stats: {
      sampled,
      transparent,
      white,
      distinct_colour_buckets: colours.size,
      top_buckets: Array.from(colours.entries()).sort((a, b) => b[1] - a[1]).slice(0, 5),
    },
  });
})()"""


def open_target(devtools: DevTools, url: str, wait_for: str, timeout: float = 25.0, settle: float = 0.6) -> None:
    devtools.call("Page.navigate", url=url)
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready = devtools.evaluate(f"Boolean({wait_for})")
        if ready:
            time.sleep(settle)
            return
        time.sleep(0.3)
    raise RuntimeError(f"page did not become ready: {url}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--key", default="")
    parser.add_argument("--min-bubbles", type=int, default=1)
    arguments = parser.parse_args()

    port = 19231
    profile = Path(tempfile.mkdtemp(prefix="edge-export-"))
    process = start_edge(port, profile)
    failures: list[str] = []
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        # The pages are served with a content-hashed asset version, but during development the
        # hashes only change when the server recomputes them, so caching is switched off here to
        # make sure the test drives the files on disk.
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)

        wall_url = f"{arguments.base}/display?event={arguments.slug}"
        # The wall re-lays out once its QR card has settled (the card is taller until its image
        # loads), so the comparison waits for the arrangement to stop changing instead of reading
        # whichever pass happened to be on screen.
        open_target(
            devtools,
            wall_url,
            "document.querySelectorAll('.signature-bubble').length > 0",
            settle=0.8,
        )
        if not wait_for_stable(devtools):
            print("wall: the arrangement did not settle; comparing the last state anyway")
        wall_raw = devtools.evaluate(WALL_POSITIONS)
        wall = json.loads(wall_raw)
        print(f"wall: bubbles={wall['count']} stage={wall['stage']['width']}x{wall['stage']['height']}")
        print(f"  wall geometry={wall.get('rendered')}")

        # The monitor opens in the same tab, which is also how an operator uses it: the wall has
        # been loaded in this browser at least once, so its geometry is available to the export.
        monitor_url = f"{arguments.base}/monitor?event={arguments.slug}"
        if arguments.key:
            monitor_url += f"&key={arguments.key}"
        open_target(devtools, monitor_url, "window.wallExport && window.wallSync", settle=1.0)
        resolved = devtools.evaluate(
            "window.wallSync.resolveGeometry().then((r) => JSON.stringify(r))"
        )
        print(f"monitor: geometry source = {resolved}")

        raw = devtools.evaluate(RUN_EXPORT)
        if not raw:
            print("export: no result (the export threw or the page lacks wallExport)")
            return 1
        exported = json.loads(raw)
        print(
            f"export: items={exported['items']} canvas={exported['canvas']['width']}x{exported['canvas']['height']}"
            f" ratio={exported['ratio']} stage={exported['stage']['width']}x{exported['stage']['height']}"
        )
        print(f"  geometry={exported.get('geometry')}")
        printed = wall.get("rendered")
        if exported.get("geometry") and printed:
            same_stage = (
                exported["geometry"]["stageWidth"] == printed["stageWidth"]
                and exported["geometry"]["stageHeight"] == printed["stageHeight"]
            )
            print(f"  wall geometry={printed} match={same_stage}")
            if not same_stage:
                failures.append("the export was laid out on a different stage than the wall")
            reported = devtools.evaluate(
                "fetch('/api/events/integrity-2026/wall-geometry', { cache: 'no-store' })"
                ".then((r) => r.json()).then((d) => JSON.stringify(d.geometry))"
            )
            print(f"  geometry reported by the wall to the server={reported}")
            if not reported or json.loads(reported) is None:
                failures.append("the wall never reported its geometry to the server")
        elif not exported.get("geometry"):
            failures.append("the export had no wall geometry to lay out with")
        stats = exported["stats"]
        print(
            f"  bitmap: sampled={stats['sampled']} transparent={stats['transparent']} white={stats['white']}"
            f" colour_buckets={stats['distinct_colour_buckets']} top={stats['top_buckets']}"
        )

        if exported["items"] < arguments.min_bubbles:
            failures.append(f"the export contains only {exported['items']} signatures")
        if stats["white"] < 12:
            failures.append("the exported picture has almost no white ink")
        if stats["distinct_colour_buckets"] < 6:
            failures.append("the exported picture is a flat colour, so the wall was not drawn")
        if stats["transparent"] > stats["sampled"] * 0.02:
            failures.append("the exported picture has transparent areas")

        positions = wall["positions"]
        exported_positions = {str(bubble["id"]): {"x": bubble["x"], "y": bubble["y"]} for bubble in exported["bubbles"]}
        shared = sorted(set(exported_positions) & set(positions))
        print(f"  arrangement: compared={len(shared)} wall={len(positions)} export={len(exported_positions)}")
        mismatched = []
        worst = 0.0
        for identifier in shared:
            # The wall's own `style.left/top` percentages are the arrangement it computed; the
            # bounding rectangle of a floating, rotated bubble is not.
            inline = positions[identifier]["inline"]
            left = {"x": float(str(inline[0]).rstrip("%")), "y": float(str(inline[1]).rstrip("%"))}
            right = exported_positions[identifier]
            delta = max(abs(left["x"] - right["x"]), abs(left["y"] - right["y"]))
            worst = max(worst, delta)
            if delta > 0.2:
                mismatched.append((identifier, inline, {"x": round(right["x"], 4), "y": round(right["y"], 4)}, round(delta, 3)))
        print(f"  largest position difference: {worst:.4f} (percentage points of the stage)")
        if mismatched:
            failures.append(f"{len(mismatched)} signatures are in a different place, first: {mismatched[0]}")
        if not shared:
            failures.append("no signature could be compared between the wall and the export")

        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"checked={len(shared)} failures={len(failures)}")
        return 1 if failures else 0
    finally:
        try:
            devtools.close()
        except Exception:
            pass
        process.terminate()


if __name__ == "__main__":
    sys.exit(main())
