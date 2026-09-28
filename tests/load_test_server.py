"""Server-side load test: measures the submission path without the wide-area network.

Run this ON the host that serves the app so that client bandwidth does not hide the
server's own capacity:

    /opt/sign-board/.venv/bin/python load_test_server.py --url http://127.0.0.1 --count 500

It uses asyncio-only sockets (no external packages) and a payload shaped like a real
participant signature, with one device token per submission.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import statistics
import sys
import time
import zlib
from collections import Counter


def make_signature_png(width: int = 405, height: int = 265) -> str:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            on_stroke = abs(y - (height // 2 + int(18 * ((x % 60) / 60 - 0.5)))) < 3 and 40 < x < width - 40
            raw.extend((255, 255, 255, 255) if on_stroke else (0, 0, 0, 0))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return len(payload).to_bytes(4, "big") + tag + payload + zlib.crc32(tag + payload).to_bytes(4, "big")

    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes((8, 6, 0, 0, 0))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


async def read_response(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    status_line = await reader.readline()
    parts = status_line.split()
    status = int(parts[1]) if len(parts) > 1 else 0
    length = 0
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            length = int(value.strip() or 0)
    body = await reader.readexactly(length) if length else b""
    return status, body


async def one(host: str, port: int, path: str, payload: bytes, start_at: float, timeout: float) -> dict:
    delay = start_at - time.monotonic()
    if delay > 0:
        await asyncio.sleep(delay)
    started = time.perf_counter()
    writer = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        request = (
            f"POST {path} HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n"
        ).encode() + payload
        writer.write(request)
        await writer.drain()
        status, body = await asyncio.wait_for(read_response(reader), timeout=timeout)
        return {"status": status, "elapsed": time.perf_counter() - started, "detail": body[:160].decode(errors="replace")}
    except Exception as error:
        return {"status": 0, "elapsed": time.perf_counter() - started, "detail": f"{type(error).__name__}: {error}"}
    finally:
        if writer is not None:
            writer.close()


async def pooled(host: str, port: int, path: str, payload: bytes, start_at: float, timeout: float) -> dict:
    """Same as one(), but reuses one connection per submission through keep-alive."""
    delay = start_at - time.monotonic()
    if delay > 0:
        await asyncio.sleep(delay)
    started = time.perf_counter()
    writer = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        request = (
            f"POST {path} HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n"
        ).encode() + payload
        writer.write(request)
        await writer.drain()
        status, body = await asyncio.wait_for(read_response(reader), timeout=timeout)
        return {"status": status, "elapsed": time.perf_counter() - started, "detail": body[:160].decode(errors="replace")}
    except Exception as error:
        return {"status": 0, "elapsed": time.perf_counter() - started, "detail": f"{type(error).__name__}: {error}"}
    finally:
        if writer is not None:
            writer.close()


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]


async def run(host: str, port: int, slug: str, count: int, window: float, timeout: float, concurrency: int) -> int:
    signature = make_signature_png()
    body = json.dumps(
        {
            "name": "压测",
            "organization": "压测",
            "message": "",
            "signature_data": signature,
            "device_token": "placeholder",
        }
    )
    path = f"/api/events/{slug}/submissions"
    print(f"target=http://{host}:{port}{path}")
    print(f"count={count} concurrency={concurrency} target_window={window:g}s")
    print(f"payload_bytes≈{len(body.encode()) + 60}")

    start_at = time.monotonic() + 1.5
    wall_start = time.perf_counter()
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(index: int) -> dict:
        payload = json.dumps(
            {
                "name": f"压测{index:03d}",
                "organization": "压测",
                "message": "",
                "signature_data": signature,
                "device_token": f"load-{index}-{int(time.time() * 1000)}",
            }
        ).encode()
        async with semaphore:
            return await one(host, port, path, payload, start_at, timeout)

    results = await asyncio.gather(*(guarded(index) for index in range(1, count + 1)))
    wall_elapsed = time.perf_counter() - wall_start

    elapsed = [result["elapsed"] for result in results]
    codes = Counter(result["status"] for result in results)
    failed = [result for result in results if result["status"] != 201]

    print("--- results ---")
    print("status_codes=" + ", ".join(f"{code}:{amount}" for code, amount in sorted(codes.items())))
    print(f"success_201={codes.get(201, 0)} failed={len(failed)}")
    print(f"total_wall_time_s={wall_elapsed:.2f}")
    print(f"throughput_rps={count / wall_elapsed:.1f}")
    print(f"latency_p50_ms={percentile(elapsed, 0.50) * 1000:.0f}")
    print(f"latency_p90_ms={percentile(elapsed, 0.90) * 1000:.0f}")
    print(f"latency_p95_ms={percentile(elapsed, 0.95) * 1000:.0f}")
    print(f"latency_p99_ms={percentile(elapsed, 0.99) * 1000:.0f}")
    print(f"latency_max_ms={max(elapsed) * 1000:.0f}")
    print(f"latency_mean_ms={statistics.fmean(elapsed) * 1000:.0f}")
    print(f"within_{window:g}s={sum(1 for value in elapsed if value <= window)}/{count}")
    for result in failed[:5]:
        print(f"failed status={result['status']} elapsed_ms={result['elapsed'] * 1000:.0f} detail={result['detail']}")
    return 0 if not failed else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--window", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=500)
    arguments = parser.parse_args()
    return asyncio.run(
        run(arguments.host, arguments.port, arguments.slug, arguments.count, arguments.window, arguments.timeout, arguments.concurrency)
    )


if __name__ == "__main__":
    sys.exit(main())
