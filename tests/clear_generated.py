"""Delete the generated load-test signatures.

Reading the event listing needs the admin credential, while the monitor delete endpoint
needs the monitor credential, so both are passed in.

    python tests/clear_generated.py <admin-token> <monitor-token>
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:18180"
SLUG = "integrity-2026"


def call(method: str, path: str, token: str, payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.status, json.load(response)


def main() -> int:
    admin = sys.argv[1]
    monitor = sys.argv[2]

    status, listing = call("GET", f"/api/admin/events/{SLUG}/submissions", admin)
    ids = [item["id"] for item in listing["items"]]
    print("found", len(ids))

    removed = 0
    for start in range(0, len(ids), 100):
        chunk = ids[start : start + 100]
        status, result = call(
            "POST", f"/api/monitor/events/{SLUG}/submissions/delete", monitor, {"ids": chunk}
        )
        removed += result["deleted"]
    print("deleted_total", removed)

    status, display = call("GET", f"/api/events/{SLUG}/display", admin)
    print("remaining_items", len(display["items"]))
    print("display_limit", display["event"]["display_limit"])
    print("approved", display["event"]["stats"]["approved"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
