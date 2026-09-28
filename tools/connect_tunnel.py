#!/usr/bin/env python3
"""HTTP CONNECT tunnel for SSH ProxyCommand.

OpenSSH has no native HTTP proxy support, so route the TCP stream through a
local HTTP proxy instead of relying on direct connectivity to port 22:

    ssh -o "ProxyCommand=python tools/connect_tunnel.py %h %p" user@host
    scp -o "ProxyCommand=python tools/connect_tunnel.py %h %p" file user@host:/path

Proxy address comes from DSH_CONNECT_PROXY, then HTTPS_PROXY/HTTP_PROXY, and
finally defaults to http://127.0.0.1:7897.

stdin and stdout are pumped by separate daemon threads because select() cannot
be used on stdin pipes on Windows; the main thread only waits for stdin to end.
"""

from __future__ import annotations

import http.client
import os
import socket
import sys
import threading


def proxy_address() -> tuple[str, int]:
    raw = (
        os.environ.get("DSH_CONNECT_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or "http://127.0.0.1:7897"
    )
    raw = raw.split("://")[-1].rstrip("/")
    host, _, port = raw.partition(":")
    return host or "127.0.0.1", int(port or 7897)


def open_remote(target_host: str, target_port: int) -> socket.socket:
    proxy_host, proxy_port = proxy_address()
    connection = http.client.HTTPConnection(proxy_host, proxy_port, timeout=20)
    connection.set_tunnel(target_host, target_port)
    connection.connect()
    assert connection.sock is not None
    return connection.sock


def pump_stdin_to_remote(remote: socket.socket) -> None:
    source = getattr(sys.stdin, "buffer", sys.stdin)
    # Read from the unbuffered stream so that the buffer layer cannot swallow bytes
    # that belong to a later SSH exchange.
    raw = getattr(source, "raw", source)
    try:
        while True:
            chunk = raw.read(1) if hasattr(raw, "read") else os.read(0, 1)
            if not chunk:
                break
            remote.sendall(chunk)
    except Exception:
        pass
    finally:
        try:
            remote.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def pump_remote_to_stdout(remote: socket.socket) -> None:
    sink = getattr(sys.stdout, "buffer", sys.stdout)
    try:
        while True:
            data = remote.recv(65536)
            if not data:
                break
            sink.write(data)
            sink.flush()
    except Exception:
        pass
    finally:
        try:
            os._exit(0)
        except Exception:
            pass


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    target_host, target_port = sys.argv[1], int(sys.argv[2])
    try:
        remote = open_remote(target_host, target_port)
    except Exception as error:  # pragma: no cover - network dependent
        print(f"tunnel failed via {proxy_address()}: {error}", file=sys.stderr)
        return 1

    threading.Thread(target=pump_stdin_to_remote, args=(remote,), daemon=True).start()
    threading.Thread(target=pump_remote_to_stdout, args=(remote,), daemon=True).start()

    # Wait until stdin closes, then let the daemon threads drain and exit.
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            remote.close()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
