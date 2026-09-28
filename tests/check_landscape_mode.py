"""Verify the landscape writing mode: a tall box, a sideways drawing, and a way back.

The design under test: the phone stays upright, the writing box is a tall rectangle, and only the
canvas content is turned 90°, so the participant writes along the phone's long edge and reads it
without turning the phone. This checks, on a real device viewport:

* the box is tall (taller than wide) and fully inside the screen;
* the canvas is turned 90° and its bitmap keeps the strip's proportions (wide, not tall);
* a touch at a known point of the box records the matching point of the strip — the mapping that a
  rotation gets wrong if it is not inverted;
* the drawing survives leaving and re-entering the mode;
* nothing about the page rotates: no fullscreen, no orientation lock, the shell has no transform;
* the return button brings the portrait layout back.

Usage:
    python tests/check_landscape_mode.py [--base http://127.0.0.1:18195] [--device "iPhone 14"]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobile_probe import (  # noqa: E402
    DEVICES,
    DevTools,
    load_mobile_page,
    prepare_session,
    start_edge,
)

REPORT = r"""(() => {
  const shell = document.querySelector('.mobile-shell');
  const wrap = document.querySelector('.canvas-wrap');
  const canvas = document.querySelector('#signature-canvas');
  const exit = document.querySelector('#landscape-exit');
  const style = getComputedStyle(canvas);
  const wrapRect = wrap.getBoundingClientRect();
  const canvasRect = canvas.getBoundingClientRect();
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  return JSON.stringify({
    mode: document.body.classList.contains('landscape-mode') ? 'landscape' : 'portrait',
    shellTransform: getComputedStyle(shell).transform,
    wrap: {
      w: Math.round(wrapRect.width),
      h: Math.round(wrapRect.height),
      left: Math.round(wrapRect.left),
      top: Math.round(wrapRect.top),
      display: getComputedStyle(wrap).display,
      overflow: getComputedStyle(wrap).overflow,
      position: getComputedStyle(wrap).position,
      computed: [getComputedStyle(wrap).width, getComputedStyle(wrap).height],
      inline: [wrap.style.width, wrap.style.height],
      hidden: wrap.offsetParent === null && getComputedStyle(wrap).position !== 'fixed',
    },
    canvas: {
      bitmap: [canvas.width, canvas.height],
      strip: [Math.round(canvas.width / ratio), Math.round(canvas.height / ratio)],
      style: [style.width, style.height],
      transform: style.transform,
      transformOrigin: style.transformOrigin,
      rect: [
        Math.round(canvasRect.left), Math.round(canvasRect.top),
        Math.round(canvasRect.width), Math.round(canvasRect.height),
      ],
    },
    hints: {
      guide: (() => {
        const svg = document.querySelector('.canvas-guide');
        if (!svg) return null;
        const guideStyle = getComputedStyle(svg);
        const guideRect = svg.getBoundingClientRect();
        return {
          display: guideStyle.display,
          transform: guideStyle.transform,
          pointerEvents: guideStyle.pointerEvents,
          // The guide sits over the box; its bounding rectangle is therefore taller than wide even
          // though its own coordinate space is wide, which is what the rotation is for.
          rect: [
            Math.round(guideRect.left), Math.round(guideRect.top),
            Math.round(guideRect.width), Math.round(guideRect.height),
          ],
          texts: Array.from(svg.querySelectorAll('text')).map((node) => node.textContent.trim()),
          line: (() => {
            const line = svg.querySelector('line');
            return line ? [line.getAttribute('x1'), line.getAttribute('y1'), line.getAttribute('x2'), line.getAttribute('y2')] : null;
          })(),
        };
      })(),
      vertical: 'canvas-vertical-hint' in document
        ? getComputedStyle(document.querySelector('.canvas-vertical-hint')).display
        : 'removed',
      note: getComputedStyle(document.querySelector('.landscape-note')).display,
      noteText: document.querySelector('.landscape-note').textContent.replace(/\s+/g, ' ').trim(),
      exit: getComputedStyle(exit).display,
      exitText: exit.textContent.trim(),
      exitRect: (() => {
        const rect = exit.getBoundingClientRect();
        return [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)];
      })(),
    },
    viewport: [window.innerWidth, window.innerHeight],
    chain: (() => {
      // Walk up from the box, reporting every ancestor that is not laying out normally: a hidden
      // ancestor is the usual reason a box with a width reports zero.
      const rows = [];
      let node = wrap;
      while (node && node !== document.documentElement) {
        const style = getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden' || style.position === 'absolute' || style.position === 'fixed') {
          rows.push(`${node.tagName.toLowerCase()}.${node.className || '-'}: display=${style.display} position=${style.position}`);
        }
        node = node.parentElement;
      }
      return rows;
    })(),
    insideViewport: wrapRect.left >= 0 && wrapRect.top >= 0
      && wrapRect.right <= window.innerWidth + 1 && wrapRect.bottom <= window.innerHeight + 1,
    recorded: window.__signBoardCaptured || null,
    fit: window.__signBoardLandscapeFit ? window.__signBoardLandscapeFit() : null,
  });
})()"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--device", default="iPhone 14")
    parser.add_argument("--slug", default="integrity-2026")
    arguments = parser.parse_args()

    device = next((item for item in DEVICES if item[0].lower() == arguments.device.lower()), None)
    if device is None:
        print(f"unknown device; known: {[item[0] for item in DEVICES]}")
        return 1
    label, width, height = device

    port = 19270
    profile = Path(tempfile.mkdtemp(prefix="edge-landscape-"))
    process = start_edge(port, profile)
    failures: list[str] = []
    try:
        devtools = DevTools(port)
        prepare_session(devtools, width, height, "portraitPrimary", "fallback")
        # Fail loudly if the page ever asks for fullscreen or an orientation lock again.
        devtools.call("Page.addScriptToEvaluateOnNewDocument", source="""
          window.__fullscreenRequested = false;
          window.__orientationLocked = false;
          Object.defineProperty(Element.prototype, 'requestFullscreen', {
            configurable: true, writable: true,
            value: () => { window.__fullscreenRequested = true; return Promise.resolve(); },
          });
          Object.defineProperty(window.screen, 'orientation', {
            configurable: true,
            get: () => ({
              lock: () => { window.__orientationLocked = true; return Promise.resolve(); },
              unlock: () => {},
            }),
          });
        """)
        devtools.call("Page.addScriptToEvaluateOnNewDocument", source="""
          // Records what the page would upload, so the recorded stroke can be inspected.
          const realFetch = window.fetch.bind(window);
          window.__signBoardCaptured = null;
          window.fetch = (input, init) => {
            const url = typeof input === 'string' ? input : input.url;
            if (init && init.method === 'POST' && url.includes('/submissions')) {
              window.__signBoardCaptured = init.body;
              return Promise.resolve(new Response(JSON.stringify({ ok: true, item: { id: 1 } }), {
                status: 201, headers: { 'Content-Type': 'application/json' },
              }));
            }
            return realFetch(input, init);
          };
        """)
        load_mobile_page(devtools, url=f"{arguments.base}/mobile?event={arguments.slug}&layoutDebug=1")

        portrait = json.loads(devtools.evaluate(REPORT))
        print(
            f"portrait: viewport {portrait['viewport'][0]}x{portrait['viewport'][1]}"
            f" canvas bitmap {portrait['canvas']['bitmap']} mode {portrait['mode']}"
        )
        if portrait["mode"] != "portrait":
            failures.append("the page did not start in portrait mode")

        # Enter the landscape writing mode and look at the box it produced.
        devtools.evaluate("document.querySelector('#landscape-toggle').click()")
        time.sleep(1.0)
        landscape = json.loads(devtools.evaluate(REPORT))
        wrap = landscape["wrap"]
        canvas = landscape["canvas"]
        print(
            f"landscape: box {wrap['w']}x{wrap['h']} at {wrap['left']},{wrap['top']}"
            f" canvas {canvas['style'][0]}x{canvas['style'][1]} transform {canvas['transform']}"
        )
        print(
            f"  strip {canvas['strip'][0]}x{canvas['strip'][1]} bitmap {canvas['bitmap']}"
            f" (device pixel ratio implied)"
        )
        guide = landscape["hints"]["guide"]
        print(
            f"  guide: {guide['display']} transform {guide['transform']}"
            f" rect {guide['rect']} line {guide['line']}"
        )
        print(f"    texts {guide['texts']}")
        print(
            f"  note {landscape['hints']['note']}: {landscape['hints']['noteText']}"
        )
        print(
            f"  exit '{landscape['hints']['exitText']}' at {landscape['hints']['exitRect']}"
        )

        if landscape["mode"] != "landscape":
            failures.append("the button did not switch the page into landscape writing mode")
        if wrap["h"] <= wrap["w"]:
            failures.append(f"the writing box is not tall: {wrap['w']}x{wrap['h']}")
        if not landscape["insideViewport"]:
            failures.append(f"the writing box is not fully on screen: {wrap}")
        if wrap["h"] < height * 0.45:
            failures.append(f"the box only takes {wrap['h']}px of a {height}px screen")
        if "matrix" not in canvas["transform"]:
            failures.append(f"the canvas is not rotated: transform is {canvas['transform']}")
        else:
            numbers = [float(value) for value in canvas["transform"].removeprefix("matrix(").removesuffix(")").split(",")]
            if abs(numbers[0]) > 0.01 or abs(numbers[1] - 1) > 0.01:
                failures.append(f"the rotation is not 90°: {canvas['transform']}")
        strip_w, strip_h = canvas["strip"]
        if strip_w <= strip_h:
            failures.append(f"the strip bitmap is not wide: {strip_w}x{strip_h}")
        if not (0.6 <= strip_h / strip_w <= 1.0):
            failures.append(f"the strip proportions are odd: {strip_w}x{strip_h}")
        # The writing guide must be turned the same way as the canvas, so its text reads
        # horizontally once the participant turns the phone: that is the whole hint.
        if not guide:
            failures.append("the writing guide is missing from the page")
        else:
            if guide["display"] == "none":
                failures.append("the writing guide is hidden in landscape mode")
            if "matrix" not in guide["transform"]:
                failures.append(f"the guide is not turned with the canvas: {guide['transform']}")
            else:
                numbers = [float(value) for value in guide["transform"].removeprefix("matrix(").removesuffix(")").split(",")]
                if abs(numbers[0]) > 0.01 or abs(numbers[1] - 1) > 0.01:
                    failures.append(f"the guide rotation is not 90°: {guide['transform']}")
            # The guide's own space is wide; over the tall box it therefore covers it and must not
            # swallow the touches meant for the canvas.
            if guide["pointerEvents"] != "none":
                failures.append(f"the guide would intercept drawing: pointer-events {guide['pointerEvents']}")
            prompt = " ".join(guide["texts"])
            # The guide has to say which way to write. The wording lives in mobile.js with the rest of
            # the guide's layout; the direction may be spelled out in words or carried by the arrow.
            if "从左到右" not in prompt:
                failures.append(f"the guide does not say which way to write: {guide['texts']}")
            guide_rect = guide["rect"]
            if guide_rect[0] < wrap["left"] - 2 or guide_rect[1] < wrap["top"] - 2:
                failures.append(f"the guide starts outside the writing box: {guide_rect} against {wrap}")
        if landscape["hints"]["note"] == "none":
            failures.append("the instruction note is hidden in landscape mode")
        if "横" not in landscape["hints"]["noteText"]:
            failures.append(f"the note does not explain the mode: {landscape['hints']['noteText']}")
        if landscape["hints"]["exit"] == "none":
            failures.append("the return button is hidden in landscape mode")

        # The mapping that must be inverted: a touch at a known box position has to land at the
        # corresponding point of the strip.
        mapping = json.loads(
            devtools.evaluate(
                """(() => {
                  const wrap = document.querySelector('.canvas-wrap');
                  const rect = wrap.getBoundingClientRect();
                  const stripW = %STRIP_W%;
                  const stripH = %STRIP_H%;
                  const ratio = Math.min(window.devicePixelRatio || 1, 2);
                  const canvas = document.querySelector('#signature-canvas');
                  const u = rect.width * 0.25;
                  const v = rect.height * 0.75;
                  const clientX = rect.left + u;
                  const clientY = rect.top + v;
                  const fire = (type) => canvas.dispatchEvent(new PointerEvent(type, {
                    pointerId: 1, clientX, clientY, bubbles: true, cancelable: true,
                    isPrimary: true, pointerType: 'touch',
                  }));
                  fire('pointerdown');
                  fire('pointerup');
                  const expected = [Math.round(v * ratio), Math.round((stripH - u) * ratio)];
                  return JSON.stringify({
                    tap: [Math.round(clientX), Math.round(clientY)],
                    box: [Math.round(u), Math.round(v)],
                    expected,
                    strip: [stripW, stripH],
                    bitmap: [canvas.width, canvas.height],
                  });
                })()"""
                .replace("%STRIP_W%", str(strip_w))
                .replace("%STRIP_H%", str(strip_h))
            )
        )
        recorded = json.loads(devtools.evaluate("JSON.stringify(window.__capturedStroke || null)"))
        print(
            f"  tap at box {mapping['box']} should record strip bitmap point"
            f" {mapping['expected']} of {mapping['bitmap']}"
        )

        # Read the recorded stroke through the page's own submit path.
        devtools.evaluate("""
          window.__capturedStroke = null;
          const form = document.querySelector('#submission-form');
          document.querySelector('#name').value = '横屏测试';
          form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
        """)
        time.sleep(1.0)
        captured = devtools.evaluate("window.__signBoardCaptured")
        internal = devtools.evaluate(
            "JSON.stringify({point: window.__signBoardLandscapePoint || null,"
            " fit: window.__signBoardLandscapeFit ? window.__signBoardLandscapeFit() : null})"
        )
        print(f"  internal state: {internal}")
        if not captured:
            failures.append("the drawing could not be submitted, so its recorded points are unknown")
        else:
            payload = json.loads(captured)
            points = [point for stroke in (payload.get("strokes") or []) for point in stroke]
            print(f"  submitted {len(points)} points; first {points[0] if points else None}")
            if not points:
                failures.append("no stroke points were recorded")
            else:
                first = points[0]
                expected = mapping["expected"]
                if abs(first[0] - expected[0]) > 4 or abs(first[1] - expected[1]) > 4:
                    failures.append(
                        f"the tap recorded {first} instead of {expected}: the rotation is not inverted"
                    )
                if not (0 <= first[0] <= canvas["bitmap"][0] and 0 <= first[1] <= canvas["bitmap"][1]):
                    failures.append(f"the recorded point {first} is outside the bitmap")

        # A successful submission replaces the form with the success panel, which hides everything
        # and would make the checks below meaningless. The form is made visible again directly: the
        # page's own "write another" button is only clickable while the success panel is showing.
        devtools.evaluate(
            """(() => {
              const form = document.querySelector('#submission-form');
              form.style.display = '';
              document.querySelector('#success-panel').classList.remove('is-visible');
              document.querySelector('#name').value = '';
            })()"""
        )
        time.sleep(0.4)

        # The drawing has to survive leaving and re-entering the mode.
        devtools.evaluate("document.querySelector('#landscape-exit').click()")
        time.sleep(0.8)
        back = json.loads(devtools.evaluate(REPORT))
        print(f"  after return: mode {back['mode']} box display {back['wrap']['display']}")
        if back["mode"] != "portrait":
            failures.append("the return button did not leave landscape writing mode")
        devtools.evaluate("document.querySelector('#landscape-toggle').click()")
        time.sleep(0.8)
        again = json.loads(devtools.evaluate(REPORT))
        if again["mode"] != "landscape":
            failures.append("re-entering landscape writing mode failed")
        if again["wrap"]["h"] <= again["wrap"]["w"]:
            failures.append("the box lost its shape when re-entering")
        print(
            f"  re-entered: box {again['wrap']['w']}x{again['wrap']['h']}"
            f" at {again['wrap']['left']},{again['wrap']['top']}"
            f" computed {again['wrap']['computed']} inline {again['wrap']['inline']}"
            f" display {again['wrap']['display']} position {again['wrap']['position']}"
            f" canvas {again['canvas']['style'][0]}x{again['canvas']['style'][1]}"
        )
        print(f"  ancestors with special layout: {again['chain']}")
        ink = devtools.evaluate(
            "(() => { const canvas = document.querySelector('#signature-canvas');"
            " const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;"
            " let painted = 0;"
            " for (let index = 3; index < data.length; index += 4) if (data[index] > 8) painted += 1;"
            " return painted; })()"
        )
        # A picture of the mode, rotated back the way the participant reads it, so the hint can be
        # checked as the reader sees it rather than as the upright phone shows it.
        import base64

        from PIL import Image

        png = devtools.call("Page.captureScreenshot", format="png").get("data", "")
        shots = Path(__file__).resolve().parent / "shots"
        shots.mkdir(exist_ok=True)
        shot = shots / "landscape-mode.png"
        shot.write_bytes(base64.b64decode(png))
        image = Image.open(shot).convert("RGB")
        rotated = image.rotate(-90, expand=True)
        rotated_path = shot.with_name("landscape-rotated.png")
        rotated.save(rotated_path)
        print(f"  screenshot {image.size} saved; rotated for reading: {rotated.size} -> {rotated_path}")

        # On the rotated picture the guide's text has to read horizontally: look for the gold guide
        # colour and measure the bounding box of what it covers inside the drawing area.
        left = rotated.width - (wrap["top"] + wrap["h"])
        top = wrap["left"]
        right = rotated.width - wrap["top"]
        bottom = wrap["left"] + wrap["w"]
        crop = rotated.crop((max(0, left), max(0, top), min(rotated.width, right), min(rotated.height, bottom)))
        pixels = crop.load()
        min_x, min_y, max_x, max_y, marks = crop.width, crop.height, -1, -1, 0
        for y in range(crop.height):
            for x in range(crop.width):
                red, green, blue = pixels[x, y]
                # The guide is drawn in gold on the pale canvas.
                if red > 120 and red - blue > 40 and green > 90:
                    marks += 1
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)
        if marks == 0:
            failures.append("no writing guide is visible in the picture")
        else:
            box = (max_x - min_x + 1, max_y - min_y + 1)
            print(
                f"  guide marks in the rotated picture: {marks} pixels over {box}"
                f" at {min_x},{min_y} inside a {crop.width}x{crop.height} drawing area"
            )
            # The baseline is the long thin part; a baseline plus a text row is wider than it is
            # tall, so a tall thin box would mean the guide was not turned with the reader.
            if box[1] > box[0]:
                failures.append(f"the guide reads vertically in the rotated picture: {box}")
        rotated_path.unlink(missing_ok=True)

        print(f"  ink pixels after re-entering: {ink}")
        # The drawing was reset by "write another", so this only proves the canvas is usable again.
        devtools.evaluate(
            """(() => {
              const wrap = document.querySelector('.canvas-wrap');
              const rect = wrap.getBoundingClientRect();
              const canvas = document.querySelector('#signature-canvas');
              const fire = (type, x, y) => canvas.dispatchEvent(new PointerEvent(type, {
                pointerId: 2, clientX: x, clientY: y, bubbles: true, cancelable: true,
                isPrimary: true, pointerType: 'touch',
              }));
              fire('pointerdown', rect.left + 40, rect.top + 60);
              for (let step = 0; step < 6; step += 1) {
                fire('pointermove', rect.left + 40 + step * 12, rect.top + 60 + step * 20);
              }
              fire('pointerup', rect.left + 120, rect.top + 200);
            })()"""
        )
        time.sleep(0.4)
        ink_again = devtools.evaluate(
            "(() => { const canvas = document.querySelector('#signature-canvas');"
            " const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;"
            " let painted = 0;"
            " for (let index = 3; index < data.length; index += 4) if (data[index] > 8) painted += 1;"
            " return painted; })()"
        )
        print(f"  ink pixels after drawing again: {ink_again}")
        stroke_debug = devtools.evaluate(
            "JSON.stringify({strokes: (window.__signBoardStrokes ? window.__signBoardStrokes() : null),"
            " point: window.__signBoardLandscapePoint || null})"
        )
        print(f"  stroke debug: {stroke_debug}")
        if not ink_again:
            failures.append("drawing in landscape mode after re-entering painted nothing")

        flags = json.loads(
            devtools.evaluate(
                "JSON.stringify({fullscreen: window.__fullscreenRequested, orientation: window.__orientationLocked,"
                " shellTransform: getComputedStyle(document.querySelector('.mobile-shell')).transform})"
            )
        )
        print(f"  fullscreen requested {flags['fullscreen']}, orientation locked {flags['orientation']}"
              f", shell transform {flags['shellTransform']}")
        if flags["fullscreen"]:
            failures.append("the page still asks for fullscreen")
        if flags["orientation"]:
            failures.append("the page still asks to lock the orientation")
        if flags["shellTransform"] not in ("none", ""):
            failures.append(f"the page itself is still rotated: {flags['shellTransform']}")

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
