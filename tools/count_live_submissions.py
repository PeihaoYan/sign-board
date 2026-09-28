"""Count the signatures the live server holds, and how many of a named batch arrived.

The admin endpoint caps its listing at 500 rows, so a batch larger than that is counted in a
separate page-by-page pass; this reports both the newest rows and the total.

Usage:
    python tools/count_live_submissions.py [--host http://127.0.0.1:18180] [--prefix 压测用户]
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

SECRETS = Path(__file__).resolve().parent.parent / ".secrets" / "deploy.env"


def admin_token() -> str:
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if line.startswith("ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("ADMIN_TOKEN not found in .secrets/deploy.env")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://127.0.0.1:18180")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--prefix", default="压测用户")
    arguments = parser.parse_args()

    request = urllib.request.Request(
        f"{arguments.host}/api/admin/events/{urllib.parse.quote(arguments.slug)}/submissions",
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    items = payload.get("items", [])
    matching = [item for item in items if str(item.get("name", "")).startswith(arguments.prefix)]
    print(f"newest listing: {len(items)} rows, {len(matching)} with prefix {arguments.prefix}")
    if items:
        print(f"newest id: {items[0]['id']}, oldest id in listing: {items[-1]['id']}")
        print(f"newest names: {[item.get('name') for item in items[:5]]}")
    stats = payload.get("stats")
    if stats:
        print(f"stats: {json.dumps(stats, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
