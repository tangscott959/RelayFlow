"""Threading HTTP sink that sleeps before 200 OK to inject subscriber latency."""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HEALTH_BODY = b'{"status":"ok","service":"relayflow-sink"}'
OK_BODY = b'{"ok":true}'


def delay_seconds(delay_ms: int) -> float:
    """Convert a non-negative millisecond delay to seconds."""

    return max(int(delay_ms), 0) / 1000.0


def sink_settings(
    environ: dict[str, str] | None = None,
) -> tuple[str, int, int]:
    env = os.environ if environ is None else environ
    host = env.get("SINK_HOST", "0.0.0.0")
    port = int(env.get("SINK_PORT", "8089"))
    delay_ms = int(env.get("SINK_DELAY_MS", "200"))
    return host, port, delay_ms


def make_handler(delay_ms: int, sleeper: Any = None) -> type[BaseHTTPRequestHandler]:
    """Build a POST handler that waits ``delay_ms`` then returns 200."""

    import time as time_module

    sleep = time_module.sleep if sleeper is None else sleeper
    wait = delay_seconds(delay_ms)

    class DelayedSinkHandler(BaseHTTPRequestHandler):
        def _write(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] in {"/", "/health"}:
                self._write(200, HEALTH_BODY, "application/json")
                return
            self._write(404, b'{"detail":"not found"}', "application/json")

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length:
                self.rfile.read(length)
            sleep(wait)
            self._write(200, OK_BODY, "application/json")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    return DelayedSinkHandler


def serve(host: str, port: int, delay_ms: int) -> None:
    handler = make_handler(delay_ms)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"relayflow sink listening on {host}:{port} delay_ms={delay_ms}", flush=True)
    server.serve_forever()


def main() -> None:
    host, port, delay_ms = sink_settings()
    serve(host, port, delay_ms)


if __name__ == "__main__":
    main()
