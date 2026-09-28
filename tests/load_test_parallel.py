"""Run two independent load-test processes at once against the same service.

If the service is the limit, both processes report roughly the throughput one process alone gets;
if the client machine was the limit, the combined throughput rises.

Usage:
    python tests/load_test_parallel.py --url http://127.0.0.1:18195 --count 200 --processes 2
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

FIELDS = (
    "accepted_2xx",
    "latency_p50_ms",
    "latency_p99_ms",
    "latency_max_ms",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18195")
    parser.add_argument("--count", type=int, default=200, help="requests per process")
    parser.add_argument("--processes", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=0, help="per process (0 = all at once)")
    arguments = parser.parse_args()

    command = [
        sys.executable,
        str(HERE / "load_test.py"),
        "--url",
        arguments.url,
        "--count",
        str(arguments.count),
        "--database",
        "none",
    ]
    if arguments.concurrency:
        command += ["--concurrency", str(arguments.concurrency)]

    started = time.perf_counter()
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    processes = [
        subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        for _ in range(arguments.processes)
    ]
    outputs = [process.communicate()[0] for process in processes]
    elapsed = time.perf_counter() - started

    accepted = 0
    for index, output in enumerate(outputs, start=1):
        match = re.search(r"accepted_2xx=(\d+)", output)
        total = re.search(r"total_wall_time_s=([\d.]+)", output)
        lines = []
        for field in FIELDS:
            found = re.search(rf"{field}=([\d.]+)", output)
            if found:
                lines.append(f"{field}={found.group(1)}")
        if match:
            accepted += int(match.group(1))
        print(f"process {index}: {match.group(1) if match else '?'} accepted, wall {total.group(1) if total else '?'}s, " + " ".join(lines))

    total_requests = arguments.count * arguments.processes
    print(f"combined: {total_requests} requests, {accepted} accepted, {elapsed:.2f} s wall, {total_requests / elapsed:.1f} rps")
    return 0 if accepted == total_requests else 2


if __name__ == "__main__":
    raise SystemExit(main())
