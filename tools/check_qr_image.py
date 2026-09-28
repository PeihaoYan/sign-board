"""Load the served QR SVG into an <img> in a browser and say whether it paints.

A QR image that "200 OK" but paints nothing is invisible to every check that only looks at HTTP, and
it is the one failure the event cannot recover from. This loads the exact URL the wall uses, into the
same kind of element the wall uses, and reports the element's natural size and how many dark pixels
the image produces when drawn to a canvas.

Usage:
    python tools/check_qr_image.py [--url http://127.0.0.1:18180/api/events/integrity-2026/qr.svg]
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

PROBE = """(async () => {
  const source = %SOURCE%;
  const result = await new Promise((resolve) => {
    const image = new Image();
    const outcome = { source, onload: false, onerror: false, naturalSize: [0, 0], dark: 0, error: null };
    image.onload = () => {
      outcome.onload = true;
      outcome.naturalSize = [image.naturalWidth, image.naturalHeight];
      try {
        const canvas = document.createElement('canvas');
        canvas.width = 256;
        canvas.height = 256;
        const context = canvas.getContext('2d');
        context.fillStyle = '#ffffff';
        context.fillRect(0, 0, 256, 256);
        context.drawImage(image, 0, 0, 256, 256);
        const data = context.getImageData(0, 0, 256, 256).data;
        let dark = 0;
        for (let index = 0; index < data.length; index += 4) if (data[index] < 128) dark += 1;
        outcome.dark = dark;
      } catch (error) {
        outcome.error = String(error);
      }
      resolve(outcome);
    };
    image.onerror = (event) => { outcome.onerror = true; resolve(outcome); };
    image.src = source;
  });
  return JSON.stringify(result);
})()"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18180/api/events/integrity-2026/qr.svg")
    parser.add_argument("--page", default="http://127.0.0.1:18180/display?event=integrity-2026")
    arguments = parser.parse_args()

    port = 19401
    profile = Path(tempfile.mkdtemp(prefix="edge-qrbitmap-"))
    process = start_edge(port, profile)
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)
        # Same-origin matters: the canvas would be tainted by a cross-origin image, so the probe runs
        # on a page served by the same host.
        devtools.call("Page.navigate", url=arguments.page)
        time.sleep(5)
        report = json.loads(devtools.evaluate(PROBE.replace("%SOURCE%", json.dumps(arguments.url))))
        print(f"image {report['source']}")
        print(f"  onload {report['onload']}  onerror {report['onerror']}"
              f"  natural size {report['naturalSize']}")
        print(f"  dark pixels in a 256x256 render: {report['dark']}")
        if report["error"]:
            print(f"  drawing raised: {report['error']}")
        ok = report["onload"] and report["naturalSize"][0] > 0 and report["dark"] > 500
        print(f"  verdict: {'renders a QR code' if ok else 'DOES NOT RENDER'}")
        return 0 if ok else 1
    finally:
        try:
            devtools.close()
        except Exception:
            pass
        process.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
