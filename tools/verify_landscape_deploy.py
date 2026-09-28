"""Check the deployed landscape writing mode: the files are live and the page is wired for it.

Usage:
    python tools/verify_landscape_deploy.py
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
echo "--- the deployed mobile page ---"
printf 'required name field: '
curl -s http://127.0.0.1/mobile | grep -c 'id="name"'
printf 'landscape button: '
curl -s http://127.0.0.1/mobile | grep -c 'landscape-toggle'
printf 'return button: '
curl -s http://127.0.0.1/mobile | grep -c '>返回<'
printf 'vertical hint: '
curl -s http://127.0.0.1/mobile | grep -c '横向阅读 · 竖向排列'
echo "--- the deployed scripting ---"
printf 'canvas is turned (rotate(90deg)): '
curl -s http://127.0.0.1/assets/mobile.js | grep -c 'rotate(90deg)'
printf 'no fullscreen request (must be 0): '
curl -s http://127.0.0.1/assets/mobile.js | grep -c 'requestFullscreen'
printf 'no orientation lock (must be 0): '
curl -s http://127.0.0.1/assets/mobile.js | grep -c 'screen.orientation'
printf 'no page rotation left (must be 0): '
curl -s http://127.0.0.1/assets/mobile.js | grep -c 'is-rotated'
echo "--- the deployed stylesheet ---"
printf 'tall box rule: '
curl -s http://127.0.0.1/assets/styles.css | grep -c 'body.landscape-mode .canvas-wrap'
printf 'vertical writing mode: '
curl -s http://127.0.0.1/assets/styles.css | grep -c 'writing-mode: vertical-rl'
printf 'page rotation rule (must be 0): '
curl -s http://127.0.0.1/assets/styles.css | grep -c 'is-rotated'
echo "--- asset version and health ---"
printf 'asset version: '
curl -s http://127.0.0.1/mobile | grep -o 'mobile\.js?v=[0-9a-f]*'
for p in /mobile /display /monitor /admin /health; do
  printf '%s ' "$p"
  curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1$p"
done
printf 'service: '
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
