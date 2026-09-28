"""Compare every local static asset with the copy the live server is serving.

Usage:
    python tools/diff_static.py [--host http://127.0.0.1:18180]
"""

from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "/assets/"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def combined_digest(files: list[tuple[str, bytes]]) -> str:
    """The same digest app/main.py computes for `__ASSET_VERSION__`: names then bytes."""
    digest = hashlib.sha256()
    for name, data in sorted(files):
        digest.update(name.encode())
        digest.update(data)
    return digest.hexdigest()[:12]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://127.0.0.1:18180")
    arguments = parser.parse_args()

    names = sorted(
        path.name
        for pattern in ("*.js", "*.css", "*.html")
        for path in (ROOT / "static").glob(pattern)
    )
    differences = []
    for_assets: list[tuple[str, bytes]] = []
    remote_assets: list[tuple[str, bytes]] = []
    for name in names:
        local = (ROOT / "static" / name).read_bytes()
        if name.endswith((".js", ".css")):
            for_assets.append((name, local))
        try:
            request = urllib.request.Request(
                f"{arguments.host}{PREFIX}{name}", headers={"Cache-Control": "no-cache"}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                remote = response.read()
        except Exception as error:  # noqa: BLE001
            print(f"  ERR  {name}: {error}")
            differences.append(name)
            continue
        same = digest(local) == digest(remote)
        print(f"  {'same' if same else 'DIFF'} {name}: local {digest(local)} live {digest(remote)}")
        if same and name.endswith((".js", ".css")):
            remote_assets.append((name, remote))
        if not same:
            differences.append(name)
    print(f"local asset version (from these bytes): {combined_digest(for_assets)}")
    if len(remote_assets) == len(for_assets):
        print(f"live asset version (from served bytes): {combined_digest(remote_assets)}")
    else:
        print("live asset version: not computed, some assets differ")
    print(f"different: {len(differences)} -> {' '.join(differences) if differences else '(none)'}")
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
