"""Measure the collisions on the rendered wall, from its own pixels.

Every previous number in this investigation was an approximation of what a spectator sees: bounding
boxes, an assumed name width, a spacing in bubble units. This reads the wall as drawn — each bubble's
ink canvas and name are rasterised by the page itself — and reports how much visible ink actually
lands on other signatures, plus a picture where each signature is a distinct colour so an overlap is
visible at a glance.

Usage:
    python tests/check_wall_collisions.py [--base http://127.0.0.1:18195] [--count 500] [--slug integrity-2026]
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobile_probe import DevTools, start_edge  # noqa: E402

# Rasterises one signature per bubble with a unique colour, in the wall's own pixels, and reads back
# the wall's geometry so the same arrangement can be compared with the live one.
COLLECT = """(async () => {
  const slug = '%SLUG%';
  const drift = %DRIFT%;
  const rotate = %ROTATE%;
  const snapshot = await (await fetch(`/api/events/${encodeURIComponent(slug)}/display`, { cache: 'no-store' })).json();
  const items = snapshot.items || [];
  const geometry = window.wallSync ? (await window.wallSync.resolveGeometry()).geometry : null;
  const stage = document.querySelector('#wall-stage');
  const stageWidth = stage.clientWidth;
  const stageHeight = stage.clientHeight;
  const count = (geometry && geometry.count) || items.length;
  const layout = window.wallLayout.computeWallLayout(items, {
    stageWidth, stageHeight, qr: geometry ? geometry.qr : null, count,
  });
  const metrics = layout.metrics;
  const canvas = document.createElement('canvas');
  canvas.width = stageWidth;
  canvas.height = stageHeight;
  const context = canvas.getContext('2d');
  context.fillStyle = '#000000';
  context.fillRect(0, 0, stageWidth, stageHeight);
  const owner = new Int32Array(stageWidth * stageHeight).fill(-1);
  let painted = 0;
  let onTop = 0;
  layout.bubbles.forEach(({ item, position }, index) => {
    // The wall floats each signature up and down and tilts it a little, so the drawn position is not
    // quite the laid-out one. Those two decorations are applied here as well: leaving them out would
    // measure an arrangement nobody ever sees. On the page they run as a keyframe animation, so the
    // picture here is the worst case of the cycle rather than a moment of it.
    const tilt = rotate ? (position.rotation * Math.PI) / 180 : 0;
    const lift = drift ? -position.drift : 0;
    const centreX = (position.x / 100) * stageWidth;
    const centreY = (position.y / 100) * stageHeight + lift;
    const ink = document.createElement('canvas');
    window.renderSignatureInto(ink, item, {
      width: metrics.inkWidth, height: metrics.inkHeight,
      lineWidth: 3.2 * metrics.scale, resolutionRatio: 1,
    });
    if (!ink.width || !ink.height) return;
    // A unique colour per signature: green channel carries the index.
    const tinted = document.createElement('canvas');
    tinted.width = ink.width;
    tinted.height = ink.height;
    const tintedContext = tinted.getContext('2d');
    tintedContext.drawImage(ink, 0, 0);
    tintedContext.globalCompositeOperation = 'source-in';
    tintedContext.fillStyle = `rgb(${40 + (index % 7) * 30}, 255, ${90 + (index % 5) * 30})`;
    tintedContext.fillRect(0, 0, tinted.width, tinted.height);
    const left = Math.round(centreX - metrics.inkWidth / 2);
    const top = Math.round(centreY - metrics.inkHeight / 2);
    const data = tintedContext.getImageData(0, 0, tinted.width, tinted.height).data;
    for (let y = 0; y < tinted.height; y += 1) {
      for (let x = 0; x < tinted.width; x += 1) {
        if (data[(y * tinted.width + x) * 4 + 3] <= 40) continue;
        const targetX = left + x;
        const targetY = top + y;
        if (targetX < 0 || targetY < 0 || targetX >= stageWidth || targetY >= stageHeight) continue;
        const flat = targetY * stageWidth + targetX;
        if (owner[flat] !== -1 && owner[flat] !== index) onTop += 1;
        owner[flat] = index;
        painted += 1;
      }
    }
    context.drawImage(tinted, left, top);
  });
  // Count how many signatures are involved in a collision at all, from the owner map.
  const clashing = new Set();
  for (let y = 1; y < stageHeight - 1; y += 1) {
    for (let x = 1; x < stageWidth - 1; x += 1) {
      const flat = y * stageWidth + x;
      const mine = owner[flat];
      if (mine === -1) continue;
      if ((owner[flat + 1] !== -1 && owner[flat + 1] !== mine)
        || (owner[flat + stageWidth] !== -1 && owner[flat + stageWidth] !== mine)) {
        clashing.add(mine);
        clashing.add(owner[flat + 1] !== mine ? owner[flat + 1] : owner[flat + stageWidth]);
      }
    }
  }
  return JSON.stringify({
    items: items.length,
    metrics,
    strategy: layout.strategy,
    inkPixels: painted,
    inkOnTopOfInkPixels: onTop,
    signaturesInCollisions: clashing.size,
    dataUrl: canvas.toDataURL('image/png'),
  });
})()"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--out", default="tests/shots/wall-collisions.png")
    parser.add_argument("--drift", type=int, default=1, help="apply the floating animation's lift")
    parser.add_argument("--rotate", type=int, default=1, help="apply the tilt of each signature")
    parser.add_argument("--no-picture", action="store_true")
    arguments = parser.parse_args()

    port = 19361
    profile = Path(tempfile.mkdtemp(prefix="edge-collide-"))
    process = start_edge(port, profile)
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)
        devtools.call(
            "Emulation.setDeviceMetricsOverride",
            width=1920, height=1080, deviceScaleFactor=1, mobile=False,
        )
        devtools.call("Page.navigate", url=f"{arguments.base}/display?event={arguments.slug}")
        time.sleep(4)
        # The wall reports its geometry as it lays out; the raster is made from the same numbers.
        report = json.loads(devtools.evaluate(
            COLLECT.replace("%SLUG%", arguments.slug)
            .replace("%DRIFT%", "true" if arguments.drift else "false")
            .replace("%ROTATE%", "true" if arguments.rotate else "false")
        ))
        metrics = report["metrics"]
        print(
            f"wall: {report['items']} signatures, strategy {report['strategy']},"
            f" bubble {metrics['width']}x{metrics['height']}, ink {metrics['inkWidth']}x{metrics['inkHeight']}"
        )
        print(f"  ink pixels drawn: {report['inkPixels']}")
        print(f"  ink drawn on top of another signature's ink: {report['inkOnTopOfInkPixels']} pixels"
              f" ({report['inkOnTopOfInkPixels'] / max(report['inkPixels'], 1) * 100:.2f}% of the ink)")
        print(f"  signatures involved in a collision: {report['signaturesInCollisions']}"
              f" of {report['items']}"
              f" ({report['signaturesInCollisions'] / max(report['items'], 1) * 100:.0f}%)")
        target = Path(arguments.out)
        if not arguments.no_picture:
            target.parent.mkdir(parents=True, exist_ok=True)
            image = Image.open(io.BytesIO(base64.b64decode(report["dataUrl"].split(",", 1)[1])))
            image.save(target)
            print(f"  picture (each signature tinted): {target}")
        # A collision that covers a whole signature would be a real fault; a few pixels of ink
        # touching at the edges is not. The share of the ink decides.
        share = report["inkOnTopOfInkPixels"] / max(report["inkPixels"], 1)
        failures = []
        if share > 0.05:
            failures.append(f"{share * 100:.1f}% of the ink is drawn over another signature")
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
    raise SystemExit(main())
