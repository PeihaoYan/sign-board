"""Check the deployed instance: schema, endpoints and the monitor page wiring.

Run from the project root with the SSH details in .secrets/:
    python tools/verify_deployment.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")
KEY = str(ROOT / ".secrets" / "deploy_key.pem")
HOST = "user@example.com"

REMOTE = r"""
echo "--- approved signatures on the wall ---"
curl -s http://127.0.0.1/api/events/integrity-2026/display | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['items']), 'items, display_limit =', d['event']['display_limit'])"
echo "--- stored wall geometry ---"
curl -s http://127.0.0.1/api/events/integrity-2026/wall-geometry
echo
echo "--- endpoints ---"
for p in /display /monitor /mobile /admin /health /api/events/integrity-2026/wall-geometry; do
  printf '%s ' "$p"
  curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1$p"
done
echo "--- the deployed renderer and export ---"
printf 'compose outer transform: '
curl -s http://127.0.0.1/assets/signature.js | grep -c 'context.transform(outer.a'
printf 'device-pixel ratio option: '
curl -s http://127.0.0.1/assets/signature.js | grep -c 'settings.dpr'
printf 'double ratio in the ink transform (must be 0): '
curl -s http://127.0.0.1/assets/signature.js | grep -c 'scale \* ratio'
printf 'QR card drawing code in the export (must be 0): '
curl -s http://127.0.0.1/assets/wallExport.js | grep -c 'qr.svg'
printf 'monitor page assets: '
curl -s http://127.0.0.1/monitor | grep -oE 'src="/assets/[A-Za-z]+\.js' | tr '\n' ' '
echo
printf 'asset version: '
curl -s http://127.0.0.1/monitor | grep -o 'monitor\.js?v=[0-9a-f]*'
printf 'service: '
systemctl is-active sign-board
"""


def ssh(arguments: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    """Run a command on the host, trying a direct connection first and the tunnel second.

    Direct SSH to this host is intermittent, and so is the HTTP proxy the tunnel needs; trying both
    means a check does not have to be repeated by hand when one of them is having a bad minute.
    """
    direct = [
        "ssh",
        "-i", KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15",
        HOST,
        *arguments,
    ]
    tunnelled = [
        "ssh",
        "-i", KEY,
        "-o", f"ProxyCommand={PYTHON} {ROOT / 'tools' / 'connect_tunnel.py'} %h %p",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=20",
        HOST,
        *arguments,
    ]
    last: subprocess.CompletedProcess | None = None
    for command in (direct, tunnelled):
        last = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if last.returncode == 0:
            return last
    assert last is not None
    return last


def main() -> int:
    result = ssh([REMOTE])
    sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
