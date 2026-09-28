"""Check that the deployed instance requires a name for every signature.

Reads the mobile page markup and posts name-free submissions to the live API; refusals must not
store anything, so the wall is untouched by this check.

Usage:
    python tools/verify_required_name.py
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
echo "--- mobile page markup ---"
curl -s http://127.0.0.1/mobile | grep -c 'required'
curl -s http://127.0.0.1/mobile | grep -c '必填'
echo "--- server response to a nameless submission ---"
for body in '{"name":"","strokes":[[[1,2],[3,4]]],"device_token":"verify-empty"}' \
            '{"name":"   ","strokes":[[[1,2],[3,4]]],"device_token":"verify-blank"}' \
            '{"strokes":[[[1,2],[3,4]]],"device_token":"verify-missing"}'; do
  curl -s -w ' status=%{http_code} ' -o /tmp/nameless.json \
    -X POST http://127.0.0.1/api/events/integrity-2026/submissions \
    -H 'Content-Type: application/json' -d "$body"
  tr -d '\n' < /tmp/nameless.json
  echo
done
echo "--- endpoint health ---"
for p in /display /monitor /mobile /admin /health; do
  printf '%s ' "$p"
  curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1$p"
done
echo "--- service ---"
systemctl is-active sign-board
"""


def main() -> int:
    result = subprocess.run(
        [
            "ssh",
            "-i", KEY,
            "-o", f"ProxyCommand={PYTHON} {ROOT / 'tools' / 'connect_tunnel.py'} %h %p",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=20",
            HOST,
            REMOTE,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
