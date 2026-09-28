"""Verify the MSS hypothesis: does a clamped TCP max segment size fix large uploads?

The venue-side path MTU here is 1400 while the server advertises MSS 1460, so full-size
segments from the client are dropped. This sends the same POST twice, once with the
default MSS and once clamped, and reports which one completes.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time


def build_body(target: int) -> bytes:
    payload = {
        "name": "mss-probe",
        "organization": "",
        "message": "",
        "signature_data": "",
        "device_token": "mss-probe",
        "padding": "z" * max(0, target),
    }
    raw = json.dumps(payload).encode()
    if len(raw) > target:
        payload["padding"] = "z" * max(0, target - (len(raw) - len(payload["padding"])))
        raw = json.dumps(payload).encode()
    return raw[:target]


def send(url_host: str, port: int, path: str, body: bytes, mss: int, timeout: float) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if mss:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG, mss)
        except OSError as error:
            return f"setsockopt failed: {error}"
    sock.settimeout(timeout)
    started = time.perf_counter()
    try:
        sock.connect((url_host, port))
        request = (
            f"POST {path} HTTP/1.1\r\nHost: {url_host}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        ).encode() + body
        sock.sendall(request)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
        response = b"".join(chunks)
        elapsed = (time.perf_counter() - started) * 1000
        status = response.split(b"\r\n", 1)[0].decode(errors="replace")
        return f"{status} elapsed_ms={elapsed:.0f} reply_bytes={len(response)}"
    except Exception as error:
        elapsed = (time.perf_counter() - started) * 1000
        return f"FAILED elapsed_ms={elapsed:.0f} {type(error).__name__}: {error}"
    finally:
        sock.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18180)
    parser.add_argument("--path", default="/api/events/integrity-2026/submissions")
    parser.add_argument("--body", type=int, default=13000)
    parser.add_argument("--timeout", type=float, default=20.0)
    arguments = parser.parse_args()

    body = build_body(arguments.body)
    print(f"body_bytes={len(body)}")
    print(f"default_mss   -> {send(arguments.host, arguments.port, arguments.path, body, 0, arguments.timeout)}")
    print(f"clamped_mss1360 -> {send(arguments.host, arguments.port, arguments.path, body, 1360, arguments.timeout)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
