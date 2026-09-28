"""Check that the display reconnects after a browser network interruption."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobile_probe import DevTools, start_edge  # noqa: E402


def wait_for(devtools: DevTools, expression: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if devtools.evaluate(f"Boolean({expression})"):
            return True
        time.sleep(0.25)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--container", default="", help="Docker container to stop/start for a real WebSocket interruption")
    arguments = parser.parse_args()

    edge_port = 19411
    profile = Path(tempfile.mkdtemp(prefix="edge-reconnect-"))
    process = start_edge(edge_port, profile)
    failures: list[str] = []
    try:
        devtools = DevTools(edge_port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)
        devtools.call("Page.navigate", url=f"{arguments.base}/display?event={arguments.slug}")

        live = "document.querySelector('#connection-status')?.textContent === '实时连接'"
        if not wait_for(devtools, live):
            failures.append("display did not establish its initial WebSocket connection")
        initial = devtools.evaluate("document.querySelector('#connection-status')?.textContent || ''")

        if arguments.container:
            subprocess.run(["docker", "stop", "--time", "1", arguments.container], check=True)
        else:
            devtools.call(
                "Network.emulateNetworkConditions",
                offline=True,
                latency=0,
                downloadThroughput=0,
                uploadThroughput=0,
            )
        offline = wait_for(
            devtools,
            "document.querySelector('#connection-status')?.textContent !== '实时连接'",
            timeout=8.0,
        )
        offline_status = devtools.evaluate("document.querySelector('#connection-status')?.textContent || ''")
        if not offline:
            failures.append("display did not leave the live state while offline")

        if arguments.container:
            subprocess.run(["docker", "start", arguments.container], check=True)
        else:
            devtools.call(
                "Network.emulateNetworkConditions",
                offline=False,
                latency=0,
                downloadThroughput=-1,
                uploadThroughput=-1,
            )
        reconnected = wait_for(devtools, live, timeout=12.0)
        final = devtools.evaluate("document.querySelector('#connection-status')?.textContent || ''")
        if not reconnected:
            failures.append("display did not reconnect after network recovery")

        print(f"initial={initial} offline={offline_status} final={final}")
        print(f"failures={len(failures)}")
        for failure in failures:
            print(f"failure: {failure}")
        return 1 if failures else 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:  # noqa: BLE001
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
