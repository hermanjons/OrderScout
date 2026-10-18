from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def serve(
    *,
    host: str,
    port: int,
    token: str,
    provider_id: int,
    provider_label: str,
    provider_code: str,
    model: str,
    artifact_path: Path,
    timeout: float,
    minimum_turns: int,
) -> None:
    command = [
        sys.executable,
        "-m",
        "AI.processors.orders_source_ui_human_recheck_cli",
        "--provider-id",
        str(provider_id),
        "--provider-label",
        provider_label,
        "--provider-code",
        provider_code,
        "--model",
        model,
        "--artifact-path",
        str(artifact_path),
        "--timeout",
        str(timeout),
        "--minimum-turns",
        str(max(1, int(minimum_turns or 20))),
    ]
    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"
    child = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        bufsize=1,
        env=child_env,
    )
    if child.stdin is None or child.stdout is None:
        raise RuntimeError("Source-UI acceptance child pipe acilamadi.")
    ready_line = child.stdout.readline()
    ready = json.loads(ready_line)
    if not isinstance(ready, dict) or ready.get("ready") is not True:
        raise RuntimeError(f"Source-UI acceptance child hazir degil: {ready_line}")
    command_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _authorized(self) -> bool:
            return self.headers.get("X-OrderScout-Token", "") == token

        def _write(self, status: int, payload: dict[str, Any]) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if not self._authorized():
                self._write(403, {"success": False, "error": "forbidden"})
                return
            if self.path == "/health":
                self._write(
                    200,
                    {
                        "success": child.poll() is None,
                        "provider": provider_code,
                        "model": model,
                        "artifact_path": str(artifact_path),
                    },
                )
                return
            self._write(404, {"success": False, "error": "not_found"})

        def do_POST(self) -> None:
            if not self._authorized():
                self._write(403, {"success": False, "error": "forbidden"})
                return
            if self.path != "/command":
                self._write(404, {"success": False, "error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON object gerekir.")
                with command_lock:
                    if child.poll() is not None:
                        raise RuntimeError(f"Acceptance child kapandi: {child.returncode}")
                    child.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    child.stdin.flush()
                    response_line = child.stdout.readline()
                    if not response_line:
                        raise RuntimeError("Acceptance child cevap vermeden kapandi.")
                    response = json.loads(response_line)
                self._write(200, response if isinstance(response, dict) else {"value": response})
                if str(payload.get("action") or "").casefold() == "quit":
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
            except Exception as exc:
                self._write(
                    500,
                    {"success": False, "error": type(exc).__name__, "message": str(exc)},
                )

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if child.poll() is None:
            try:
                child.stdin.write('{"action":"quit"}\n')
                child.stdin.flush()
                child.wait(timeout=10)
            except Exception:
                child.terminate()
        if child.poll() is None:
            child.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Control one offscreen full-source-app acceptance session turn by turn.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--provider-id", type=int, required=True)
    parser.add_argument("--provider-label", required=True)
    parser.add_argument("--provider-code", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--minimum-turns", type=int, default=20)
    args = parser.parse_args(argv)
    serve(
        host=args.host,
        port=args.port,
        token=args.token,
        provider_id=args.provider_id,
        provider_label=args.provider_label,
        provider_code=args.provider_code,
        model=args.model,
        artifact_path=Path(args.artifact_path),
        timeout=args.timeout,
        minimum_turns=max(1, int(args.minimum_turns or 20)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
