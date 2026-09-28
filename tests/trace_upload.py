"""Follow one real submission to the live server, phase by phase.

Uses a raw socket so the phases can be seen separately: connecting, sending the headers, sending the
body, waiting for the response headers, and reading the body. A stall that shows up between two of
these phases says where the path is broken (a small request that lands instantly but a larger one
that hangs points at the network path, not at the application).

Usage:
    python tests/trace_upload.py [--host 127.0.0.1] [--count 3] [--strokes 520]
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_test import make_strokes  # noqa: E402


def one(host: str, port: int, payload: bytes, timeout: float) -> None:
    started = time.perf_counter()
    connection = socket.create_connection((host, port), timeout=timeout)
    connected = time.perf_counter()
    request = (
        b"POST /api/events/integrity-2026/submissions HTTP/1.1\r\n"
        + f"Host: {host}\r\n".encode()
        + b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(payload)}\r\n".encode()
        + b"Connection: close\r\n\r\n"
    )
    connection.sendall(request)
    headers_sent = time.perf_counter()
    connection.sendall(payload)
    body_sent = time.perf_counter()
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = connection.recv(4096)
        if not chunk:
            break
        response += chunk
    headers_back = time.perf_counter()
    while True:
        chunk = connection.recv(65536)
        if not chunk:
            break
        response += chunk
    done = time.perf_counter()
    connection.close()
    status = response.split(b"\r\n", 1)[0].decode("latin-1") if response else "(no response)"
    print(
        f"  payload {len(payload):>6} B  connect {(connected - started) * 1000:>7.0f} ms"
        f"  headers {(headers_sent - connected) * 1000:>7.0f} ms"
        f"  body {(body_sent - headers_sent) * 1000:>7.0f} ms"
        f"  wait {(headers_back - body_sent) * 1000:>7.0f} ms"
        f"  read {(done - headers_back) * 1000:>6.0f} ms  {status}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18180)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=45.0)
    arguments = parser.parse_args()

    small = json.dumps({"name": "trace-small", "strokes": [[[10, 10], [11, 11]]], "device_token": f"trace-{time.time_ns()}"}).encode()
    full = json.dumps(
        {
            "name": "trace-full",
            "strokes": make_strokes(seed=4242),
            "device_token": f"trace-{time.time_ns()}",
        }
    ).encode()
    print(f"host={arguments.host} small={len(small)} B full={len(full)} B")
    for index in range(arguments.count):
        print(f"round {index + 1}: small")
        one(arguments.host, arguments.port, small, arguments.timeout)
        print(f"round {index + 1}: full")
        one(arguments.host, arguments.port, full, arguments.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
