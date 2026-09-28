"""Raise the wall's simultaneous display limit through the public admin API."""

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
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, json.load(response)


def main() -> int:
    token = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 500

    status, updated = call("PUT", f"/api/admin/events/{SLUG}", token, {"display_limit": limit})
    print("update_status", status, "display_limit", updated["display_limit"])

    status, display = call("GET", f"/api/events/{SLUG}/display", token)
    print("display_status", status)
    print("display_items", len(display["items"]))
    print("approved", display["event"]["stats"]["approved"])
    print("limit", display["event"]["display_limit"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
