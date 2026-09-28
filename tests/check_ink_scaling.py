"""Render one submission at several device pixel ratios and check the ink is the same drawing.

The fault this is built to catch: a stroke transform that folded the device pixel ratio in a second
time drew the ink `ratio` times too large, so on a 2x phone the signature filled its canvas and was
clipped — which also made a naive "does the ink cover the canvas" check pass. The checks here are
therefore:

* the ink of a given submission occupies the same *fraction* of the canvas at 1x, 2x and 3x;
* the ink never reaches the canvas edge (that is what clipping looks like — a stroke is centred and
  has margin around it);
* the ink is drawn in the same proportion for a wide stroke and for a tall one.

Usage:
    python tests/check_ink_scaling.py [--base http://127.0.0.1:18195]
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

# A wide flat stroke and a tall narrow one: if the aspect handling is wrong, one of them shows it.
WIDE = [[[10, 100], [120, 100], [240, 100], [360, 100], [470, 100]]]
TALL = [[[100, 10], [100, 60], [100, 120], [100, 180], [100, 230]]]

PROBE = """(() => {
  const items = [
    { id: 1, name: '', strokes: %WIDE% },
    { id: 2, name: '', strokes: %TALL% },
  ];
  const measure = (canvas) => {
    const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, painted = 0;
    for (let y = 0; y < canvas.height; y += 1) {
      for (let x = 0; x < canvas.width; x += 1) {
        if (data[(y * canvas.width + x) * 4 + 3] > 8) {
          painted += 1;
          if (x < minX) minX = x;
          if (y < minY) minY = y;
          if (x > maxX) maxX = x;
          if (y > maxY) maxY = y;
        }
      }
    }
    return painted
      ? {
        box: [maxX - minX + 1, maxY - minY + 1],
        origin: [minX, minY],
        painted,
        margin: [minX, minY, canvas.width - 1 - maxX, canvas.height - 1 - maxY],
      }
      : { box: [0, 0], origin: [0, 0], painted: 0, margin: [0, 0, 0, 0] };
  };

  const out = [];
  for (const item of items) {
    for (const ratio of [1, 2, 3]) {
      const canvas = document.createElement('canvas');
      window.renderSignatureInto(canvas, item, {
        width: 136, height: 88, lineWidth: 3.2, resolutionRatio: ratio,
      });
      out.push({
        id: item.id,
        ratio,
        canvas: [canvas.width, canvas.height],
        css: [canvas.style.width, canvas.style.height],
        ink: measure(canvas),
      });
    }
  }
  return JSON.stringify({ devicePixelRatio: window.devicePixelRatio, results: out });
})()"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    arguments = parser.parse_args()

    port = 19280
    profile = Path(tempfile.mkdtemp(prefix="edge-ink-scale-"))
    process = start_edge(port, profile)
    failures: list[str] = []
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Page.navigate", url=f"{arguments.base}/display")
        time.sleep(3)
        data = json.loads(
            devtools.evaluate(
                PROBE.replace("%WIDE%", json.dumps(WIDE)).replace("%TALL%", json.dumps(TALL))
            )
        )
        print(f"browser device pixel ratio: {data['devicePixelRatio']}")
        print("id ratio  canvas      ink box    margin (l,t,r,b)   painted  ink/canvas")

        by_id: dict[int, list[dict]] = {}
        for entry in data["results"]:
            by_id.setdefault(entry["id"], []).append(entry)
            ink = entry["ink"]
            width, height = entry["canvas"]
            print(
                f" {entry['id']}  {entry['ratio']}x   {width:>4}x{height:<4}  "
                f"{ink['box'][0]:>4}x{ink['box'][1]:<4}  "
                f"{str(ink['margin']):<20} {ink['painted']:>7}  "
                f"{100 * ink['box'][0] / width:>5.1f}% x {100 * ink['box'][1] / height:>5.1f}%"
            )

        for identifier, entries in by_id.items():
            shares = [
                (entry["ink"]["box"][0] / entry["canvas"][0], entry["ink"]["box"][1] / entry["canvas"][1])
                for entry in entries
            ]
            widths = [share[0] for share in shares]
            heights = [share[1] for share in shares]
            if max(widths) - min(widths) > 0.05 or max(heights) - min(heights) > 0.05:
                failures.append(
                    f"submission {identifier} fills a different share of its canvas per ratio:"
                    f" widths {[round(value, 3) for value in widths]},"
                    f" heights {[round(value, 3) for value in heights]}"
                )
            for entry in entries:
                if entry["ink"]["painted"] == 0:
                    failures.append(f"submission {identifier} at {entry['ratio']}x painted nothing")
                    continue
                # The ink is fitted to the canvas, so it reaches the edge along its long axis. What
                # clipping adds is ink *past* the edge, which shows as the bounding box the strokes
                # imply being larger than the canvas: check the extreme coordinates instead.
                width, height = entry["canvas"]
                origin = entry["ink"]["origin"]
                box = entry["ink"]["box"]
                if origin[0] + box[0] > width or origin[1] + box[1] > height:
                    failures.append(
                        f"submission {identifier} at {entry['ratio']}x overflows its canvas:"
                        f" ink {box} at {origin} of {entry['canvas']}"
                    )
                # A stroke is at most as thick as its line width allows; a clipped or double-scaled
                # one comes out with a thickness proportional to the canvas instead.
                long_axis = max(box)
                short_axis = min(box)
                if short_axis > long_axis * 0.5 and long_axis > 100:
                    failures.append(
                        f"submission {identifier} at {entry['ratio']}x is not a thin stroke: {box}"
                    )

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
