"""Does the service stop quickly while a wall is connected?

Starts the app with uvicorn, opens a WebSocket to the display endpoint (the wall does exactly that
and keeps it open), sends SIGTERM, and reports how long the process takes to exit. Before
`install_shutdown_signal_handlers()` existed this hung until systemd's stop timeout killed it.

Usage:
    python tests/check_shutdown_speed.py [--port 18197]
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mobile_probe import DevTools, start_edge  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18197)
    parser.add_argument("--limit", type=float, default=20.0, help="fail above this many seconds")
    arguments = parser.parse_args()

    environment = dict(
        os.environ,
        DATA_DIR=str(ROOT / "tests" / ".shutdown-data"),
        ADMIN_TOKEN="probe-token",
        MONITOR_TOKEN="probe-monitor",
        EVENT_SLUG="integrity-2026",
        PYTHONIOENCODING="utf-8",
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(arguments.port),
            "--log-level",
            "warning",
        ],
        cwd=str(ROOT),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    browser = None
    profile = ROOT / "tests" / ".shutdown-profile"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{arguments.port}/health", timeout=3):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.4)
        else:
            print("the app never became healthy")
            return 1

        # A real wall: a browser that opens the display page and keeps its socket open.
        browser = start_edge(arguments.port + 1, profile)
        devtools = DevTools(arguments.port + 1)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Page.navigate", url=f"http://127.0.0.1:{arguments.port}/display?event=integrity-2026")
        time.sleep(4)
        status = devtools.evaluate("document.querySelector('#connection-status').textContent")
        print(f"the wall reports: {status}")

        started = time.perf_counter()
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=arguments.limit * 2)
        except subprocess.TimeoutExpired:
            print(f"FAIL: still running after {arguments.limit * 2:.0f} s")
            process.kill()
            return 1
        elapsed = time.perf_counter() - started
        print(f"stopped in {elapsed:.2f} s (limit {arguments.limit:.0f} s)")
        if elapsed > arguments.limit:
            print("FAIL: the stop is slow enough to hit systemd's timeout on a real server")
            return 1
        print("failures=0")
        return 0
    finally:
        if browser is not None:
            browser.terminate()
        if process.poll() is None:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
