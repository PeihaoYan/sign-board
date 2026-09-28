"""Find the largest submission the live path will carry, and how it fails above that.

Sends the same submission at growing sizes through a raw socket and reports, for each size, how far
the exchange got: did the body go out, did the response come back, and what did the server say. The
size at which it breaks, together with the phase that stalled, says whether the limit is the network
path (a stall in the middle of sending) or the application (an immediate 4xx).

Usage:
    python tests/probe_path_mtu.py [--host 127.0.0.1] [--sizes 100,500,1000,2000,3000,4000,6000,8000]
"""

from __future__ import annotations

import argparse
import json
import socket
import time

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_test import make_strokes  # noqa: E402


def build_payload(target: int) -> bytes:
    """A submission whose JSON body is about `target` bytes."""
    strokes = make_strokes(seed=99)
    while True:
        body = json.dumps(
            {"name": "mtu-probe", "strokes": strokes, "device_token": f"mtu-{time.time_ns()}"}
        ).encode()
        if abs(len(body) - target) <= 120:
            return body
        if len(body) < target:
            strokes.append([[0, 0], [1, 1]])
        else:
            strokes = strokes[:-1] if len(strokes) > 1 else strokes
            strokes = [[point for point in stroke[: max(2, len(stroke) - 20)]] or [[0, 0], [1, 1]] for stroke in strokes]


def open_through_proxy(host: str, port: int, proxy: str, timeout: float) -> socket.socket:
    """A socket to `host:port` tunnelled through an HTTP CONNECT proxy."""
    import http.client

    address = proxy.split("://")[-1].rstrip("/")
    proxy_host, _, proxy_port = address.partition(":")
    connection = http.client.HTTPConnection(proxy_host, int(proxy_port or 7897), timeout=timeout)
    connection.set_tunnel(host, port)
    connection.connect()
    assert connection.sock is not None
    return connection.sock


def attempt(host: str, port: int, payload: bytes, timeout: float, proxy: str = "") -> str:
    started = time.perf_counter()
    try:
        connection = (
            open_through_proxy(host, port, proxy, timeout)
            if proxy
            else socket.create_connection((host, port), timeout=timeout)
        )
    except Exception as error:  # noqa: BLE001
        return f"connect failed: {error}"
    try:
        request = (
            b"POST /api/events/integrity-2026/submissions HTTP/1.1\r\n"
            + f"Host: {host}\r\n".encode()
            + b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(payload)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
        )
        connection.sendall(request)
        try:
            connection.sendall(payload)
        except Exception as error:  # noqa: BLE001
            return f"body send failed after {(time.perf_counter() - started) * 1000:.0f} ms: {type(error).__name__}"
        sent = time.perf_counter()
        response = b""
        try:
            while b"\r\n\r\n" not in response:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                response += chunk
        except Exception as error:  # noqa: BLE001
            return f"response read failed after {(time.perf_counter() - started) * 1000:.0f} ms: {type(error).__name__}"
        status = response.split(b"\r\n", 1)[0].decode("latin-1") if response else "(connection closed with no response)"
        return f"{(sent - started) * 1000:>7.0f} ms to send  {(time.perf_counter() - sent) * 1000:>7.0f} ms to answer  {status}"
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18180)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--sizes", default="100,500,1000,1400,2000,3000,4000,6000,8000")
    parser.add_argument(
        "--proxy",
        default="",
        help="an HTTP CONNECT proxy, e.g. http://127.0.0.1:7897, to try the path through it",
    )
    arguments = parser.parse_args()

    if arguments.proxy:
        print(f"through proxy {arguments.proxy}")
    for text in arguments.sizes.split(","):
        target = int(text)
        payload = build_payload(target)
        print(
            f"{len(payload):>6} B:"
            f" {attempt(arguments.host, arguments.port, payload, arguments.timeout, arguments.proxy)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
