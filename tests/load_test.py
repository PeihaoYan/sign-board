"""Concurrent submission load test for the signature wall.

Fires N simultaneous submissions through the real public endpoint using the payload the phone
actually sends today — vector strokes, in the same ranges as a real handwritten signature (3–8
strokes, ~110 points each, on a bitmap of a few hundred pixels) — with a distinct device token per
submission, then reports the success rate, the latency distribution, and whether any submission
that was answered with a 2xx is missing from the event's stored rows. Losing a signature that the
server acknowledged is the one failure this test does not tolerate; added latency is acceptable.

Usage:
    python tests/load_test.py --url http://127.0.0.1 --count 500 --window 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sqlite3
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import httpx


def make_strokes(seed: int, bitmap: tuple[int, int] = (405, 265)) -> list[list[list[int]]]:
    """One handwritten-looking signature as vector strokes, in bitmap pixels.

    Coordinates are whole pixels, exactly as the phone sends them (`mobile.js` rounds every point),
    so a submission here has the same shape as a real one.
    """
    rng = random.Random(seed)
    width, height = bitmap
    strokes = []
    for _ in range(rng.randint(3, 8)):
        x = rng.uniform(20, width - 140)
        y = rng.uniform(30, height - 30)
        points = []
        for _ in range(rng.randint(80, 140)):
            x += rng.uniform(0.5, 3.2)
            y += rng.gauss(0, 5.5)
            points.append([round(min(max(x, 0), width - 1)), round(min(max(y, 0), height - 1))])
        strokes.append(points)
    return strokes


async def one_submission(client: httpx.AsyncClient, url: str, index: int, strokes, start_at: float) -> dict:
    payload = {
        "name": f"压测用户{index:03d}",
        "strokes": strokes,
        "signature_size": [405, 265],
        "device_token": f"load-test-{index}-{int(time.time() * 1000)}",
    }
    # Everyone submits inside the same short window.
    delay = start_at - time.monotonic()
    if delay > 0:
        await asyncio.sleep(delay)
    started = time.perf_counter()
    try:
        response = await client.post(f"{url}/api/events/integrity-2026/submissions", json=payload)
        elapsed = time.perf_counter() - started
        return {
            "index": index,
            "status": response.status_code,
            "elapsed": elapsed,
            "detail": response.text[:200],
        }
    except Exception as error:  # pragma: no cover - network dependent
        elapsed = time.perf_counter() - started
        return {
            "index": index,
            "status": 0,
            "elapsed": elapsed,
            "detail": f"{type(error).__name__}: {error}",
        }


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


async def count_stored(
    client: httpx.AsyncClient,
    url: str,
    slug: str,
    admin_token: str,
    database: Path | None,
) -> int | None:
    """How many submissions the event actually holds.

    The local test database is read directly when it is reachable, because the admin API caps its
    listing at 500 rows and a load test with more than that could not be counted through it.
    """
    if database and database.exists():
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
            try:
                row = connection.execute(
                    "SELECT COUNT(*) FROM submissions s JOIN events e ON e.id = s.event_id"
                    " WHERE e.slug = ?",
                    (slug,),
                ).fetchone()
                return int(row[0])
            finally:
                connection.close()
        except Exception as error:  # noqa: BLE001
            print(f"stored_count_db_unavailable {type(error).__name__}: {error}")
    if not admin_token:
        return None
    try:
        response = await client.get(
            f"{url}/api/admin/events/{slug}/submissions",
            headers={"X-Admin-Token": admin_token},
        )
        if response.status_code != 200:
            print(f"stored_count_unavailable status={response.status_code} {response.text[:120]}")
            return None
        items = response.json().get("items")
        if isinstance(items, list):
            return len(items)
    except Exception as error:  # noqa: BLE001
        print(f"stored_count_unavailable {type(error).__name__}: {error}")
    return None


async def run(
    url: str,
    count: int,
    window: float,
    timeout: float,
    concurrency: int,
    slug: str,
    admin_token: str,
    database: Path | None,
    proxy: str = "",
) -> int:
    strokes = make_strokes(seed=20260923)
    points = sum(len(stroke) for stroke in strokes)
    payload_bytes = len(
        json.dumps({"name": "压测用户001", "strokes": strokes, "signature_size": [405, 265]}).encode()
    )
    print(f"url={url}")
    print(f"concurrent_submissions={count}")
    print(f"client_concurrency={concurrency}")
    print(f"strokes_per_signature={len(strokes)} points={points}")
    print(f"payload_bytes_per_request≈{payload_bytes}")

    limits = httpx.Limits(max_connections=concurrency + 50, max_keepalive_connections=concurrency + 50)
    gate = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=timeout, limits=limits, proxy=proxy or None) as client:
        try:
            health = await client.get(f"{url}/health")
            print(f"preflight_health={health.status_code}")
        except Exception as error:
            print(f"preflight_failed={type(error).__name__}: {error}")
            return 1

        before = await count_stored(client, url, slug, admin_token, database)
        print(f"stored_before={before}")

        start_at = time.monotonic() + 1.5

        async def guarded(index: int) -> dict:
            async with gate:
                # A distinct stroke set per submitter, so no deduplication or shared body can hide
                # a lost row: every accepted submission must appear in the table.
                return await one_submission(
                    client, url, index, make_strokes(seed=1000 + index), start_at
                )

        wall_start = time.perf_counter()
        tasks = [guarded(index) for index in range(1, count + 1)]
        results = await asyncio.gather(*tasks)
        wall_elapsed = time.perf_counter() - wall_start

    elapsed = [result["elapsed"] for result in results]
    codes = Counter(result["status"] for result in results)
    accepted = sum(amount for code, amount in codes.items() if 200 <= code < 300)
    failed = [result for result in results if not 200 <= result["status"] < 300]

    print("--- results ---")
    print(f"accepted_2xx={accepted}")
    print(f"failed={len(failed)}")
    print("status_codes=" + ", ".join(f"{code}:{amount}" for code, amount in sorted(codes.items())))
    print(f"total_wall_time_s={wall_elapsed:.2f}")
    print(f"throughput_rps={count / wall_elapsed:.1f}")
    print(f"latency_p50_ms={percentile(elapsed, 0.50) * 1000:.0f}")
    print(f"latency_p90_ms={percentile(elapsed, 0.90) * 1000:.0f}")
    print(f"latency_p95_ms={percentile(elapsed, 0.95) * 1000:.0f}")
    print(f"latency_p99_ms={percentile(elapsed, 0.99) * 1000:.0f}")
    print(f"latency_max_ms={max(elapsed) * 1000:.0f}")
    if elapsed:
        print(f"latency_mean_ms={statistics.fmean(elapsed) * 1000:.0f}")

    if failed:
        print("--- first failures ---")
        for result in failed[:5]:
            print(f"status={result['status']} elapsed_ms={result['elapsed'] * 1000:.0f} detail={result['detail']}")

    within = sum(1 for value in elapsed if value <= window)
    print(f"within_{window:g}s={within}/{count}")

    # The acceptance criterion: nothing the server acknowledged may be missing.
    stored = None
    async with httpx.AsyncClient(timeout=timeout, proxy=proxy or None) as client:
        deadline = time.time() + 20
        while time.time() < deadline:
            stored = await count_stored(client, url, slug, admin_token, database)
            if stored is None or before is None or stored >= before + accepted:
                break
            await asyncio.sleep(1)
    print(f"stored_after={stored}")
    lost = None
    if stored is not None and before is not None:
        lost = accepted - (stored - before)
        print(f"accepted={accepted} stored_delta={stored - before} lost={lost}")

    if lost:
        print(f"FAIL: {lost} acknowledged signatures are not in the table")
    elif lost is None:
        print("note: the stored row count could not be read, so data loss was not checked")
    return 0 if (accepted == count and not lost) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Signature wall load test")
    parser.add_argument("--url", default="http://127.0.0.1", help="base URL of the running service")
    parser.add_argument("--count", type=int, default=500, help="number of submissions to send")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--admin-token", default="", help="admin token, to verify nothing was lost")
    parser.add_argument(
        "--database",
        default=str(Path(__file__).resolve().parent / ".probe-data" / "sign-board.sqlite3"),
        help="the local test database, read directly to count what was stored ('' to skip)",
    )
    parser.add_argument("--window", type=float, default=5.0, help="target window in seconds")
    parser.add_argument("--timeout", type=float, default=60.0, help="per-request timeout in seconds")
    parser.add_argument("--concurrency", type=int, default=0, help="max in-flight requests (0 = same as --count)")
    parser.add_argument(
        "--proxy",
        default="",
        help="send through this proxy, e.g. http://127.0.0.1:7897; the direct path to the server "
        "drops submissions larger than ~1.4 kB (see tests/probe_path_mtu.py)",
    )
    arguments = parser.parse_args()
    concurrency = arguments.concurrency or arguments.count
    return asyncio.run(
        run(
            arguments.url,
            arguments.count,
            arguments.window,
            arguments.timeout,
            concurrency,
            arguments.slug,
            arguments.admin_token,
            Path(arguments.database) if arguments.database and arguments.database != "none" else None,
            arguments.proxy,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
