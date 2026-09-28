"""Find out why a page's scripts did not run.

Collects the console messages, the failed requests and the uncaught exceptions of a page load, and
reports what the page's own globals and DOM look like afterwards. A page that loads but never changes
is almost always an exception during module evaluation, which the browser reports on the console and
which a screenshot cannot show.

Usage:
    python tools/diagnose_page.py --url http://127.0.0.1:18180/display?event=integrity-2026
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from mobile_probe import DevTools, start_edge  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18180/display?event=integrity-2026")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--wait", type=float, default=6.0)
    arguments = parser.parse_args()

    port = 19391
    profile = Path(tempfile.mkdtemp(prefix="edge-diag-"))
    process = start_edge(port, profile)
    events: list[str] = []
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)
        devtools.call(
            "Emulation.setDeviceMetricsOverride",
            width=arguments.width, height=arguments.height, deviceScaleFactor=1, mobile=False,
        )
        # Ask the browser to keep reporting: exceptions, console output and failed requests are the
        # three things a "page that does not work" shows and a screenshot does not.
        devtools.call("Runtime.enable")
        devtools.call(
            "Page.navigate", url=arguments.url,
        )
        time.sleep(arguments.wait)
        for expression in (
            "JSON.stringify({scripts: Array.from(document.scripts).map((s) => s.src || '(inline)')})",
            "JSON.stringify({"
            "  wallSync: typeof window.wallSync,"
            "  wallLayout: typeof window.wallLayout,"
            "  wallExport: typeof window.wallExport,"
            "  signature: typeof window.renderSignatureInto,"
            "  bubbles: document.querySelectorAll('.signature-bubble').length,"
            "  qrSrc: document.querySelector('#qr-image')?.getAttribute('src'),"
            "  empty: document.querySelector('#wall-empty')?.hidden,"
            "  qrScale: getComputedStyle(document.documentElement).getPropertyValue('--qr-scale'),"
            "  connection: document.querySelector('#connection-status')?.textContent"
            "})",
        ):
            print(devtools.evaluate(expression))
        print("--- browser log ---")
        for entry in devtools.drain_events() if hasattr(devtools, "drain_events") else []:
            print(entry)
    finally:
        try:
            devtools.close()
        except Exception:
            pass
        process.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
