"""Delete the load-test signatures from the live event.

Selects rows whose name starts with a prefix (the load test's own naming) and deletes them through
the monitor delete endpoint in batches, then reads the event back to confirm what is left. Only
rows that match the prefix are touched.

Usage:
    python tools/delete_load_rows.py [--host http://127.0.0.1:18180] [--prefix 压测用户] [--dry-run]

The delete request carries a few kilobytes of ids, which the direct path from this machine cannot
carry (see tests/probe_path_mtu.py), so it goes through the HTTP CONNECT proxy by default.
"""

from __future__ import annotations

import argparse
import http.client
import json
import socket
import urllib.parse
from pathlib import Path

SECRETS = Path(__file__).resolve().parent.parent / ".secrets" / "deploy.env"
DEFAULT_PROXY = "http://127.0.0.1:7897"


def admin_token() -> str:
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if line.startswith("ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("ADMIN_TOKEN not found in .secrets/deploy.env")


def request_json(url: str, token: str, body: dict | None = None, proxy: str = "") -> dict:
    data = json.dumps(body).encode() if body is not None else None
    parsed = urllib.parse.urlsplit(url)
    headers = {
        "Authorization": f"Bearer {token}",
        "Host": parsed.netloc,
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(data))
    if proxy:
        address = proxy.split("://")[-1].rstrip("/")
        proxy_host, _, proxy_port = address.partition(":")
        connection = http.client.HTTPConnection(proxy_host or "127.0.0.1", int(proxy_port or 7897), timeout=120)
        connection.set_tunnel(parsed.netloc, parsed.port or (443 if parsed.scheme == "https" else 80))
    else:
        connection = http.client.HTTPConnection(parsed.netloc, timeout=120)
    connection.connect()
    try:
        connection.request("POST" if data is not None else "GET", parsed.path, body=data, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        if response.status >= 400:
            raise SystemExit(f"{response.status} {response.reason}: {payload[:300]!r}")
        return json.loads(payload)
    finally:
        connection.close()


def list_rows(host: str, slug: str, token: str, proxy: str) -> list[dict]:
    payload = request_json(
        f"{host}/api/admin/events/{urllib.parse.quote(slug)}/submissions", token, proxy=proxy
    )
    return payload.get("items", [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://127.0.0.1:18180")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--prefix", default="压测用户")
    parser.add_argument("--batch", type=int, default=300)
    parser.add_argument("--proxy", default=DEFAULT_PROXY, help="'' to go direct")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    token = admin_token()
    deleted = 0
    round_number = 0
    # The listing is capped, so repeat: each pass reveals the rows that were hidden behind it.
    while True:
        round_number += 1
        before = list_rows(arguments.host, arguments.slug, token, arguments.proxy)
        targets = [
            row["id"] for row in before if str(row.get("name", "")).startswith(arguments.prefix)
        ]
        print(f"pass {round_number}: listing holds {len(before)} rows; {len(targets)} match {arguments.prefix}")
        if arguments.dry_run:
            print("dry run: nothing deleted")
            return 0
        if not targets:
            break
        for start in range(0, len(targets), arguments.batch):
            chunk = targets[start : start + arguments.batch]
            result = request_json(
                f"{arguments.host}/api/monitor/events/{urllib.parse.quote(arguments.slug)}/submissions/delete",
                token,
                {"ids": chunk},
                proxy=arguments.proxy,
            )
            deleted += int(result.get("deleted", 0))
            print(f"  deleted {result.get('deleted')} of {result.get('requested')} requested")

    print(f"deleted {deleted} matching rows in {round_number - 1} passes")
    after = list_rows(arguments.host, arguments.slug, token, arguments.proxy)
    remaining = [row for row in after if str(row.get("name", "")).startswith(arguments.prefix)]
    print(f"listing now holds {len(after)} rows; {len(remaining)} still match {arguments.prefix}")
    survivors = [row.get("name") for row in after if not str(row.get("name", "")).startswith(arguments.prefix)]
    print(f"non-matching names still present: {survivors[:10]}{' ...' if len(survivors) > 10 else ''}")
    return 0 if not remaining else 1


if __name__ == "__main__":
    raise SystemExit(main())
