"""Check the live deployment end to end: endpoints, the QR size setting, and page assets.

Usage:
    python tools/verify_qr_scale_live.py [--host http://127.0.0.1:18180] [--slug integrity-2026]
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

SECRETS = Path(__file__).resolve().parent.parent / ".secrets" / "deploy.env"


def admin_token() -> str:
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if line.startswith("ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("ADMIN_TOKEN not found in .secrets/deploy.env")


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def put(url: str, token: str, body: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://127.0.0.1:18180")
    parser.add_argument("--slug", default="integrity-2026")
    arguments = parser.parse_args()
    host, slug = arguments.host, arguments.slug

    failures: list[str] = []
    health = json.loads(get(f"{host}/health"))
    print(f"health: {health}")

    display = json.loads(get(f"{host}/api/events/{slug}/display"))
    print(f"display: {len(display['items'])} items, qr_scale={display['event'].get('qr_scale')}")
    if "qr_scale" not in display["event"]:
        failures.append("the display payload has no qr_scale, so the wall cannot apply the setting")

    admin_page = get(f"{host}/admin").decode("utf-8")
    for marker in ('id="qr-scale-input"', 'id="qr-scale-value"', "二维码大小"):
        if marker not in admin_page:
            failures.append(f"the admin page is missing {marker}")
    qr_control = 'has' if 'id="qr-scale-input"' in admin_page else 'MISSING'
    print(f"admin page: {qr_control} the QR size control")

    # Round-trip: save a size, read it back from the public payload, then restore.
    token = admin_token()
    original = display["event"].get("qr_scale", 1)
    try:
        for value in (1.8, original):
            saved = put(f"{host}/api/admin/events/{slug}", token, {"qr_scale": value})
            public = json.loads(get(f"{host}/api/events/{slug}/display"))["event"]["qr_scale"]
            print(f"  saved qr_scale={saved['qr_scale']} -> public payload reports {public}")
            if abs(public - value) > 0.001:
                failures.append(f"saving {value} produced {public} in the public payload")
    except Exception as error:  # noqa: BLE001
        failures.append(f"the setting could not be saved: {error}")

    # The wall script and the layout module must carry the feature.
    script = get(f"{host}/assets/display.js").decode("utf-8")
    for marker in ("--qr-scale", "qr_scale", "QR_CARD_BASE_WIDTH"):
        if marker not in script:
            failures.append(f"display.js does not mention {marker}")
    layout = get(f"{host}/assets/wallLayout.js").decode("utf-8")
    # The card must be honoured while signatures are placed, and the crowded placement must be the
    # random spread with a minimum spacing rather than a lattice.
    for marker in ("computeWallLayout", "scatterLayout", "forbidden", "overlapsCard"):
        if marker not in layout:
            failures.append(f"wallLayout.js does not mention {marker}")
    if "latticeLayout" in layout:
        failures.append("wallLayout.js still lays a crowd out on a lattice")
    version = re.findall(r"\?v=([0-9a-f]{12})", admin_page)
    print(f"asset version: {sorted(set(version))}")

    print(f"failures={len(failures)}")
    for failure in failures:
        print("FAIL:", failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
