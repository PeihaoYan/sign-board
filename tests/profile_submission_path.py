"""Where does the throughput of a submission actually go?

Runs the whole application in-process (httpx ASGI transport, no sockets) in several configurations
and reports requests per second for each, so the limit can be attributed:

* the real endpoint with a realistic stroke payload — the baseline;
* the same payload with an invalid body (no name), which skips the store and the broadcast and
  therefore isolates the request-validation cost;
* the store alone, called directly in a loop, which isolates the SQLite writer.

Usage:
    python tests/profile_submission_path.py [--count 500] [--data-dir tests/.probe-data]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from load_test import make_strokes  # noqa: E402


async def timed(coro_factory, count: int) -> tuple[float, list[float]]:
    started = time.perf_counter()
    latencies = await asyncio.gather(*(coro_factory(index) for index in range(count)))
    return time.perf_counter() - started, list(latencies)


def report(label: str, elapsed: float, latencies: list[float], failures: int) -> None:
    ordered = sorted(latencies)
    print(
        f"{label:<28} {len(latencies) / elapsed:>7.1f} rps  p50 {ordered[len(ordered) // 2] * 1000:>7.0f} ms"
        f"  p99 {ordered[int(0.99 * (len(ordered) - 1))] * 1000:>7.0f} ms  failures {failures}"
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--data-dir", default="tests/.probe-data")
    arguments = parser.parse_args()

    os.environ["DATA_DIR"] = arguments.data_dir
    os.environ["ADMIN_TOKEN"] = "probe-token"
    os.environ["MONITOR_TOKEN"] = "probe-monitor"

    import httpx

    from app import main as app_module

    app_module.init_db()
    transport = httpx.ASGITransport(app=app_module.app)
    strokes = make_strokes(seed=7)
    endpoint = "/api/events/integrity-2026/submissions"

    async with httpx.AsyncClient(transport=transport, base_url="http://probe", timeout=60) as client:
        async def real(index: int) -> float:
            body = {
                "name": f"剖析{index:04d}",
                "strokes": make_strokes(seed=2000 + index),
                "device_token": f"profile-{index}-{time.time_ns()}",
            }
            started = time.perf_counter()
            response = await client.post(endpoint, json=body)
            elapsed = time.perf_counter() - started
            if response.status_code != 201:
                raise RuntimeError(f"{response.status_code} {response.text[:120]}")
            return elapsed

        async def body_only(index: int) -> float:
            # A 422 reply: the JSON is parsed and validated, nothing is stored or broadcast.
            started = time.perf_counter()
            await client.post(endpoint, json={"strokes": make_strokes(seed=3000 + index)})
            return time.perf_counter() - started

        async def tiny_body(index: int) -> float:
            # Same endpoint and the same failure, but a three-field body instead of a signature.
            started = time.perf_counter()
            await client.post(endpoint, json={"strokes": [[[1, 2]]]})
            return time.perf_counter() - started

        async def broadcast_only(index: int) -> float:
            started = time.perf_counter()
            await app_module.broadcast(
                "integrity-2026", {"type": "submission", "item": {"id": index, "name": "x"}}
            )
            return time.perf_counter() - started

        async def health_only(index: int) -> float:
            started = time.perf_counter()
            await client.get("/health")
            return time.perf_counter() - started

        async def health_post(index: int) -> float:
            started = time.perf_counter()
            await client.post("/health")
            return time.perf_counter() - started

        async def display_only(index: int) -> float:
            started = time.perf_counter()
            await client.get("/api/events/integrity-2026/display")
            return time.perf_counter() - started

        async def wrong_slug(index: int) -> float:
            # A submission-shaped POST that 404s in `event_or_404`, before any payload work.
            started = time.perf_counter()
            await client.post("/api/events/nope/submissions", json={"name": "x"})
            return time.perf_counter() - started

        for label, factory in (
            ("full submission", real),
            ("validate only (422)", body_only),
            ("tiny body (422)", tiny_body),
            ("broadcast only", broadcast_only),
            ("health only", health_only),
            ("health POST", health_post),
            ("missing event (404)", wrong_slug),
            ("display payload", display_only),
        ):
            failures = 0
            try:
                elapsed, latencies = await timed(factory, arguments.count)
            except RuntimeError as error:
                print(f"{label}: {error}")
                continue
            report(label, elapsed, latencies, failures)

    # The store on its own, with no HTTP in the way.
    rows = [
        {
            "name": f"存储{i}",
            "organization": "",
            "message": "",
            "signature_data": "",
            "stroke_data": json.dumps(strokes),
            "device_hash": f"{i:064d}",
            "created_at": "2026-09-23T00:00:00+00:00",
        }
        for i in range(arguments.count)
    ]
    started = time.perf_counter()
    latencies = await asyncio.gather(
        *(app_module.store_submission(1, row) for row in rows)
    )
    elapsed = time.perf_counter() - started
    print(
        f"{'store only':<28} {arguments.count / elapsed:>7.1f} rps"
        f"  total {elapsed:.2f} s  rows {len(latencies)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
