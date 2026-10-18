from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from AI.processors.local_runtime import shutdown_managed_llama_servers
from AI.processors.orders_live_human_eval_cli import (
    _build_exact_client,
    finalize_conversation,
    run_turn,
)
from settings import DB_NAME


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def serve(
    *,
    host: str,
    port: int,
    token: str,
    state_path: Path,
    artifact_path: Path,
    provider: str,
    model: str,
    db_name: str,
    timeout: float,
    minimum_turns: int = 0,
    target_message_count: int = 0,
    required_domains: str = "",
) -> None:
    client, _record, is_local = _build_exact_client(
        provider,
        model,
        timeout=timeout,
    )
    turn_lock = threading.Lock()

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
                        "success": True,
                        "provider": provider,
                        "model": model,
                        "state_path": str(state_path),
                    },
                )
                return
            self._write(404, {"success": False, "error": "not_found"})

        def do_POST(self) -> None:
            if not self._authorized():
                self._write(403, {"success": False, "error": "forbidden"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON object gerekir.")
                with turn_lock:
                    if self.path == "/turn":
                        result = run_turn(
                            state_path=state_path,
                            artifact_path=artifact_path,
                            provider_code=provider,
                            model=model,
                            prompt=str(payload.get("prompt") or ""),
                            selection_reason=str(payload.get("reason") or ""),
                            review_previous_status=str(
                                payload.get("review_previous_status") or ""
                            ),
                            review_previous_notes=str(
                                payload.get("review_previous_notes") or ""
                            ),
                            db_name=db_name,
                            timeout=timeout,
                            target_message_count=max(
                                0,
                                int(target_message_count or 0),
                            ),
                            minimum_turns=max(0, int(minimum_turns or 0)),
                            required_domains=required_domains,
                            switch_runtime=payload.get("switch_runtime") is True,
                            switch_reason=str(payload.get("switch_reason") or ""),
                            client_override=client,
                            is_local_override=is_local,
                            shutdown_local_after=False,
                        )
                        self._write(200, result)
                        return
                    if self.path == "/finalize":
                        result = finalize_conversation(
                            state_path=state_path,
                            artifact_path=artifact_path,
                            status=str(payload.get("status") or ""),
                            notes=str(payload.get("notes") or ""),
                        )
                        self._write(200, result)
                        threading.Thread(
                            target=self.server.shutdown,
                            daemon=True,
                        ).start()
                        return
                    if self.path == "/shutdown":
                        self._write(200, {"success": True})
                        threading.Thread(
                            target=self.server.shutdown,
                            daemon=True,
                        ).start()
                        return
                self._write(404, {"success": False, "error": "not_found"})
            except Exception as exc:
                self._write(
                    500,
                    {
                        "success": False,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    },
                )

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if is_local:
            shutdown_managed_llama_servers()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Keep one exact provider/model runtime while a human reviews every turn."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--state-path", required=True)
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument(
        "--provider",
        required=True,
        choices=("gemini", "openrouter", "local-best", "local-weak", "local"),
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--db-name", default=DB_NAME)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument(
        "--minimum-turns",
        type=int,
        default=0,
        help=(
            "Persist a focused campaign minimum-turn contract; omit to retain "
            "the 20-turn long-campaign default."
        ),
    )
    parser.add_argument("--target-message-count", type=int, default=0)
    parser.add_argument("--required-domains", default="")
    args = parser.parse_args()
    serve(
        host=args.host,
        port=args.port,
        token=args.token,
        state_path=Path(args.state_path),
        artifact_path=Path(args.artifact_path),
        provider=args.provider,
        model=args.model,
        db_name=args.db_name,
        timeout=args.timeout,
        minimum_turns=max(0, int(args.minimum_turns or 0)),
        target_message_count=max(0, int(args.target_message_count or 0)),
        required_domains=args.required_domains,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
