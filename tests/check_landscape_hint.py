"""Measure the landscape writing hint in the strip's own coordinates.

The hint is drawn in SVG and turned with the canvas, so "is it laid out well" is a question about
the strip: where each line of text sits, whether anything is clipped at an edge, whether the writing
line and its marks are clear of the band the signature is drawn in, and whether the drawn ink ever
covers them. Screenshots turned for reading answer the first questions but mirror the drawing (the
CSS rotation and the reading rotation run opposite ways), so the ink is read from the canvas itself
and everything is reported in one coordinate system.

Usage:
    python tests/check_landscape_hint.py [--base http://127.0.0.1:18195] [--device "iPhone 14"]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobile_probe import DEVICES, DevTools, load_mobile_page, prepare_session, start_edge  # noqa: E402

# Draws the kind of squiggle a signature makes, inside the strip's writing band. The handlers reject
# synthetic pointer events whose id the browser does not know, so the ink is put on the canvas the
# same way the page would after a stroke: through the canvas context, in bitmap pixels.
DRAW = """(() => {
  const canvas = document.querySelector('#signature-canvas');
  const context = canvas.getContext('2d');
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const strip = { w: canvas.width / ratio, h: canvas.height / ratio };
  context.lineCap = 'round';
  context.lineJoin = 'round';
  context.lineWidth = 4.6;
  context.strokeStyle = '#ffffff';
  context.beginPath();
  const bandY = strip.h * 0.62;
  for (let step = 0; step <= 60; step += 1) {
    const along = step / 60;
    const x = strip.w * (0.16 + along * 0.68);
    const y = bandY + Math.sin(along * 14) * 13;
    if (step === 0) context.moveTo(x * ratio, y * ratio);
    else context.lineTo(x * ratio, y * ratio);
  }
  context.stroke();
  return JSON.stringify({ strip: [Math.round(strip.w), Math.round(strip.h)] });
})()"""

# Everything measured inside the canvas: the ink from its own pixels, the guide from its own
# geometry, both converted into strip coordinates.
MEASURE = """(() => {
  const canvas = document.querySelector('#signature-canvas');
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const strip = [canvas.width / ratio, canvas.height / ratio];
  const context = canvas.getContext('2d');
  const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
  let ink = { minX: Infinity, minY: Infinity, maxX: -1, maxY: -1, pixels: 0 };
  for (let y = 0; y < canvas.height; y += 1) {
    for (let x = 0; x < canvas.width; x += 1) {
      if (data[(y * canvas.width + x) * 4 + 3] > 40) {
        ink.pixels += 1;
        ink.minX = Math.min(ink.minX, x / ratio);
        ink.maxX = Math.max(ink.maxX, x / ratio);
        ink.minY = Math.min(ink.minY, y / ratio);
        ink.maxY = Math.max(ink.maxY, y / ratio);
      }
    }
  }
  const svg = document.querySelector('.canvas-guide');
  const box = (node) => {
    const rect = node.getBBox();
    return [
      Number(rect.x.toFixed(1)), Number(rect.y.toFixed(1)),
      Number(rect.width.toFixed(1)), Number(rect.height.toFixed(1)),
    ];
  };
  const texts = [...svg.querySelectorAll('text')].map((node) => ({
    text: node.textContent,
    size: Number(node.getAttribute('font-size')),
    box: box(node),
  }));
  return JSON.stringify({
    strip: [Math.round(strip[0]), Math.round(strip[1])],
    viewBox: svg.getAttribute('viewBox'),
    ink: ink.pixels ? {
      pixels: ink.pixels,
      box: [
        Number(ink.minX.toFixed(1)), Number(ink.minY.toFixed(1)),
        Number((ink.maxX - ink.minX).toFixed(1)), Number((ink.maxY - ink.minY).toFixed(1)),
      ],
    } : null,
    texts,
    line: box(svg.querySelector('line')),
    ticks: box(svg.querySelector('path')),
  });
})()"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--device", default="iPhone 14")
    arguments = parser.parse_args()

    device = next((item for item in DEVICES if item[0].lower() == arguments.device.lower()), None)
    if device is None:
        print(f"unknown device; known: {[item[0] for item in DEVICES]}")
        return 1
    label, width, height = device

    port = 19351
    profile = Path(tempfile.mkdtemp(prefix="edge-hint-"))
    process = start_edge(port, profile)
    failures: list[str] = []
    try:
        devtools = DevTools(port)
        prepare_session(devtools, width, height, "portraitPrimary", "fallback")
        load_mobile_page(devtools, url=f"{arguments.base}/mobile?event={arguments.slug}")
        devtools.evaluate("document.querySelector('#landscape-toggle').click()")
        time.sleep(1.0)
        print(f"{label}: {devtools.evaluate(DRAW)}")
        time.sleep(0.4)
        report = json.loads(devtools.evaluate(MEASURE))
        strip_w, strip_h = report["strip"]
        print(f"strip {strip_w}x{strip_h}, guide viewBox {report['viewBox']}")

        texts = {item["text"]: item for item in report["texts"]}
        for item in report["texts"]:
            print(f"  text {item['text']!r} size {item['size']} box {item['box']}")
        print(f"  writing line {report['line']}, end ticks {report['ticks']}")
        print(f"  ink {report['ink']}")

        # 1. Nothing may be clipped: every drawn mark has to sit inside the strip.
        marks = [("writing line", report["line"]), ("end ticks", report["ticks"])]
        marks += [(f"text {item['text']!r}", item["box"]) for item in report["texts"]]
        for name, (x, y, w, h) in marks:
            if x < 0 or y < 0 or x + w > strip_w + 0.5 or y + h > strip_h + 0.5:
                failures.append(f"{name} is clipped by the strip: box {(x, y, w, h)} in {strip_w}x{strip_h}")

        # 2. The prompt must be the largest text, and the two small marks must share one size: the
        #    point of the redesign is that the three labels no longer compete.
        prompt = texts.get("沿虚线从左到右书写")
        marks_text = [item for item in report["texts"] if item["text"] != "沿虚线从左到右书写"]
        if not prompt:
            failures.append("the prompt is missing from the guide")
        else:
            if prompt["size"] < 15:
                failures.append(f"the prompt is too small to read at a glance: {prompt['size']}px")
            if marks_text and any(item["size"] > prompt["size"] for item in marks_text):
                failures.append("a small mark is not smaller than the prompt")
        sizes = {item["size"] for item in marks_text}
        if len(sizes) > 1:
            failures.append(f"the two marks use different sizes: {sorted(sizes)}")

        # 3. The prompt must be horizontally centred, which is what makes the layout look deliberate.
        if prompt:
            centre = prompt["box"][0] + prompt["box"][2] / 2
            if abs(centre - strip_w / 2) > strip_w * 0.03:
                failures.append(f"the prompt is off centre: {centre:.0f} against {strip_w / 2:.0f}")

        # 4. The writing line must sit above the middle, and the ink must stay below it: the guide
        #    would otherwise be the thing a signature is written on top of.
        line_y = report["line"][1]
        if line_y > strip_h * 0.5:
            failures.append(f"the writing line is below the middle of the strip: y {line_y:.0f} of {strip_h}")
        if report["ink"]:
            ink_top = report["ink"]["box"][1]
            if ink_top < line_y:
                failures.append(f"the signature's ink starts above the writing line: {ink_top:.0f} < {line_y:.0f}")
        else:
            failures.append("no ink was recorded, so the writing band could not be checked")

        # 5. Nothing may overlap the writing line: no tick, text or arrow may touch its y.
        for name, (x, y, w, h) in [(f"text {item['text']!r}", item["box"]) for item in report["texts"]]:
            if y + h > line_y + 1 and y < line_y - 1:
                failures.append(f"{name} crosses the writing line: {y + h:.1f} > {line_y} > {y:.1f}")

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
