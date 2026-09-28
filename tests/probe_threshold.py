"""Find the exact request-body size where uploads stop completing from this client.

Reports status and time for each size, and marks whether the request even reached the
application (HTTP status present) or the connection stalled and was reset.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx


def body_of_size(target: int) -> bytes:
    padding = "x" * 4000
    payload = {
        "name": "size-probe",
        "organization": "",
        "message": "",
        "signature_data": "",
        "device_token": f"sz-{target}-{int(time.time() * 1000)}",
        "padding": padding,
    }
    raw = json.dumps(payload).encode()
    # Trim the padding so the total encoded body is exactly `target` bytes.
    excess = len(raw) - target
    if excess > 0:
        payload["padding"] = padding[: len(padding) - excess]
        raw = json.dumps(payload).encode()
    if len(raw) < target:
        payload["padding"] = padding + ("y" * (target - len(raw)))
        raw = json.dumps(payload).encode()
    return raw[:target]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18180")
    parser.add_argument("--sizes", default="300,700,1000,1300,1600,2000,3000,5000")
    parser.add_argument("--timeout", type=float, default=20.0)
    arguments = parser.parse_args()

    with httpx.Client(timeout=arguments.timeout) as client:
        for size in [int(value) for value in arguments.sizes.split(",")]:
            raw = body_of_size(size)
            started = time.perf_counter()
            try:
                response = client.post(
                    f"{arguments.url}/api/events/integrity-2026/submissions",
                    content=raw,
                    headers={"Content-Type": "application/json"},
                )
                elapsed = (time.perf_counter() - started) * 1000
                print(f"body={len(raw):5d} -> status={response.status_code} elapsed_ms={elapsed:7.0f}")
            except Exception as error:
                elapsed = (time.perf_counter() - started) * 1000
                print(f"body={len(raw):5d} -> STALLED elapsed_ms={elapsed:7.0f} {type(error).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
