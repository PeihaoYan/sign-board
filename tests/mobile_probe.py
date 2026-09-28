"""Shared driver for the mobile page layout tests.

The tests run the real `/mobile` page in a real device viewport through the Chrome DevTools
Protocol. Two behaviours of a phone cannot be reproduced by a plain headless run, so they are
injected before the page loads:

* `fallback` – fullscreen and orientation lock both fail, which is what iOS Safari does, so the
  page has to rotate itself with a CSS transform.
* `lock` – both succeed, which is what Android Chrome does, so the browser rotates the viewport
  and the page only has to refit the canvas.

The submission endpoint is stubbed as well: the layout tests send a stroke and read back the
payload the page would upload. Nothing here ever needs a mocked copy of the page markup, which is
why the layout is measured on the page participants actually use.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
MOBILE_PAGE = "http://127.0.0.1:18195/mobile?event=integrity-2026"
DEVICES = [
    ("iPhone SE", 375, 667),
    ("iPhone 14", 390, 844),
    ("Pixel 7", 412, 915),
    ("iPad mini", 744, 1133),
]
ORIENTATIONS = ("portraitPrimary", "landscapePrimary")

# Installed before every page load: the mode's stubs plus a recorder for what the page uploads.
SETUP_SCRIPT = """
(() => {
  const mode = window.__testMode || 'fallback';
  if (mode === 'fallback') {
    Object.defineProperty(Element.prototype, 'requestFullscreen', {
      configurable: true, writable: true,
      value: () => Promise.reject(new Error('fullscreen unsupported')),
    });
    Object.defineProperty(Document.prototype, 'exitFullscreen', {
      configurable: true, writable: true, value: () => Promise.resolve(),
    });
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => null });
    Object.defineProperty(window.screen, 'orientation', {
      configurable: true,
      get: () => ({ lock: () => Promise.reject(new Error('lock unsupported')), unlock: () => {} }),
    });
  } else {
    let fullscreenElement = null;
    Object.defineProperty(Element.prototype, 'requestFullscreen', {
      configurable: true, writable: true,
      value: function () { fullscreenElement = this; return Promise.resolve(); },
    });
    Object.defineProperty(Document.prototype, 'exitFullscreen', {
      configurable: true, writable: true,
      value: function () { fullscreenElement = null; return Promise.resolve(); },
    });
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => fullscreenElement });
    Object.defineProperty(window.screen, 'orientation', {
      configurable: true,
      get: () => ({ lock: () => Promise.resolve(), unlock: () => {} }),
    });
  }
  const realFetch = window.fetch.bind(window);
  window.__captured = null;
  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : input.url;
    if (init && init.method === 'POST' && url.includes('/submissions')) {
      window.__captured = init.body;
      return Promise.resolve(new Response(JSON.stringify({ ok: true, item: { id: 1 } }), {
        status: 201, headers: { 'Content-Type': 'application/json' },
      }));
    }
    return realFetch(input, init);
  };
})();
"""

# Reports the writing area, the submit button and their local (offset*) boxes side by side.
GEOMETRY_SCRIPT = """(() => {
  const box = (element) => {
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    return {
      offset: { w: element.offsetWidth, h: element.offsetHeight },
      rect: {
        l: Math.round(rect.left), t: Math.round(rect.top),
        r: Math.round(rect.right), b: Math.round(rect.bottom),
        w: Math.round(rect.width), h: Math.round(rect.height),
      },
    };
  };
  const canvas = document.querySelector('#signature-canvas');
  const viewport = { w: window.innerWidth, h: window.innerHeight };
  const c = box(canvas);
  const submit = box(document.querySelector('#submit-button'));
  const canvasRect = c ? c.rect : { l: 0, t: 0, r: 0, b: 0, w: 0, h: 0 };
  const visible = Math.max(0, Math.min(canvasRect.r, viewport.w) - Math.max(canvasRect.l, 0))
    * Math.max(0, Math.min(canvasRect.b, viewport.h) - Math.max(canvasRect.t, 0));
  const inside = (r) => r.l >= 0 && r.t >= 0 && r.r <= viewport.w && r.b <= viewport.h;
  return {
    mode: document.body.classList.contains('landscape-mode') ? 'landscape' : 'portrait',
    rotated: document.querySelector('.mobile-shell').classList.contains('is-rotated'),
    viewport,
    canvas: c,
    canvas_fully_visible: inside(canvasRect),
    canvas_visible_area: Math.round(visible),
    canvas_area: canvasRect.w * canvasRect.h,
    submit,
    submit_fully_visible: submit ? inside(submit.rect) : false,
    exit_display: getComputedStyle(document.querySelector('#landscape-exit')).display,
    toggle_display: getComputedStyle(document.querySelector('#landscape-toggle')).display,
    shell_client: {
      w: document.querySelector('.mobile-shell').clientWidth,
      h: document.querySelector('.mobile-shell').clientHeight,
      scroll_h: document.querySelector('.mobile-shell').scrollHeight,
    },
  };
})()"""


class DevTools:
    def __init__(self, port: int) -> None:
        self.port = port
        self.target = self._first_page_target()
        self.ws = connect(self.target["webSocketDebuggerUrl"], max_size=None, open_timeout=20)
        self.counter = 0

    def _first_page_target(self) -> dict:
        deadline = time.time() + 30
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=2) as response:
                    targets = json.load(response)
                for target in targets:
                    if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                        return target
            except Exception as error:  # the port is not listening yet
                last_error = error
            time.sleep(0.3)
        raise RuntimeError(f"no page target on port {self.port}: {last_error}")

    def call(self, method: str, **params):
        self.counter += 1
        message_id = self.counter
        self.ws.send(json.dumps({"id": message_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv(timeout=60))
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    def evaluate(self, expression: str):
        # `awaitPromise` lets a caller evaluate an async IIFE, which is how the export — an async
        # function — is driven from these tests. A JavaScript exception is raised here rather than
        # returned as `None`: a probe that silently yields nothing hides its own bugs.
        result = self.call(
            "Runtime.evaluate",
            expression=expression,
            returnByValue=True,
            awaitPromise=True,
        )
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            description = details.get("exception", {}).get("description") or details.get("text")
            raise RuntimeError(f"page script failed: {description}")
        return result.get("result", {}).get("value")

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def start_edge(port: int, profile: Path | str) -> subprocess.Popen:
    return subprocess.Popen(
        [
            EDGE,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def prepare_session(devtools: DevTools, width: int, height: int, orientation: str, mode: str) -> None:
    """Enable the domains, install the stubs and set the device viewport."""
    devtools.call("Page.enable")
    devtools.call("Runtime.enable")
    devtools.call("Page.addScriptToEvaluateOnNewDocument", source=f"window.__testMode = {json.dumps(mode)};")
    devtools.call("Page.addScriptToEvaluateOnNewDocument", source=SETUP_SCRIPT)
    devtools.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=True,
        screenOrientation={"type": orientation, "angle": 0 if orientation == "portraitPrimary" else 90},
    )


def load_mobile_page(devtools: DevTools, url: str = MOBILE_PAGE, settle: float = 3.0) -> None:
    devtools.call("Page.navigate", url=url)
    time.sleep(settle)


def enter_landscape(devtools: DevTools, settle: float = 1.2) -> None:
    devtools.evaluate("document.querySelector('#landscape-toggle').click()")
    time.sleep(settle)


def draw_stroke(devtools: DevTools) -> None:
    """Drag across the canvas so the page records a stroke and is ready to submit."""
    devtools.evaluate(
        """(() => {
          const canvas = document.querySelector('#signature-canvas');
          const rect = canvas.getBoundingClientRect();
          const startX = rect.left + rect.width * 0.2;
          const startY = rect.top + rect.height * 0.3;
          const fire = (type, x, y) => canvas.dispatchEvent(new PointerEvent(type, {
            pointerId: 1, clientX: x, clientY: y, bubbles: true, cancelable: true,
            isPrimary: true, pointerType: 'touch',
          }));
          fire('pointerdown', startX, startY);
          for (let step = 1; step <= 10; step += 1) {
            fire('pointermove', startX + step * (rect.width * 0.05), startY + step * (rect.height * 0.03));
          }
          fire('pointerup', startX + rect.width * 0.5, startY + rect.height * 0.3);
        })()"""
    )
    time.sleep(0.4)


def submit_form(devtools: DevTools, settle: float = 1.0) -> dict:
    devtools.evaluate(
        """(() => {
          document.querySelector('#name').value = '横屏测试';
          document.querySelector('#submission-form').dispatchEvent(
            new Event('submit', { cancelable: true, bubbles: true })
          );
        })()"""
    )
    time.sleep(settle)
    payload = devtools.evaluate("window.__captured")
    if not payload:
        return {"captured": False}
    parsed = json.loads(payload)
    points = [point for stroke in (parsed.get("strokes") or []) for point in stroke]
    if not points:
        return {"captured": True, "points": 0, "in_bounds": False}
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    canvas = devtools.evaluate(
        "JSON.stringify([document.querySelector('#signature-canvas').width, document.querySelector('#signature-canvas').height])"
    )
    bitmap_width, bitmap_height = json.loads(canvas)
    return {
        "captured": True,
        "points": len(points),
        "x": [min(xs), max(xs)],
        "y": [min(ys), max(ys)],
        "bitmap": [bitmap_width, bitmap_height],
        "spread": [max(xs) - min(xs), max(ys) - min(ys)],
        "in_bounds": min(xs) >= 0 and min(ys) >= 0 and max(xs) <= bitmap_width and max(ys) <= bitmap_height,
    }


def geometry(devtools: DevTools) -> dict:
    return devtools.evaluate(GEOMETRY_SCRIPT) or {}
