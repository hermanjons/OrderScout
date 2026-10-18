from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

from AI.constants.paths import AI_DOMAIN_ROOT, ensure_ai_paths
from AI.processors.session_state import AgentSessionState


TASK_STORE_DIR = AI_DOMAIN_ROOT / "tasks"
_TASK_ID_PATTERN = re.compile(r"[a-z0-9_-]{1,96}\Z", re.ASCII)
_RESERVED_TASK_IDS = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}
_CHECKPOINT_IO_LOCK = threading.RLock()


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_task_id(value: Any) -> str:
    # Reject aliases instead of silently stripping/truncating identifiers. The
    # lowercase contract also avoids distinct identities sharing a Windows path.
    if not isinstance(value, str) or _TASK_ID_PATTERN.fullmatch(value) is None or value in _RESERVED_TASK_IDS:
        raise ValueError("Agent task session_id must be 1-96 lowercase ASCII letters, digits, '-' or '_', and not a reserved device name.")
    return value


def _task_dir(root: str | Path | None = None) -> Path:
    if root is None:
        ensure_ai_paths()
        base = TASK_STORE_DIR
    else:
        base = Path(root)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _task_path(session_id: str, *, root: str | Path | None = None) -> Path:
    safe_id = _safe_task_id(session_id)
    return _task_dir(root) / f"{safe_id}.json"


def _verified_payload(payload: Any, session_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Agent task state payload is not an object.")
    stored_id = _safe_task_id(payload.get("session_id"))
    if stored_id != session_id:
        raise ValueError("Agent task state session_id does not match the requested task.")
    return payload


def _read_task_payload(path: Path, session_id: str) -> dict[str, Any]:
    with _CHECKPOINT_IO_LOCK:
        return _verified_payload(json.loads(path.read_text(encoding="utf-8")), session_id)


def _replace_checkpoint(source: Path, destination: Path) -> None:
    # Windows file opens and concurrent renames can deny a replacement. Keep
    # local reads and commits short and serialized; temporary writes stay parallel.
    with _CHECKPOINT_IO_LOCK:
        _replace_checkpoint_unlocked(source, destination)


def _replace_checkpoint_unlocked(source: Path, destination: Path) -> None:
    if os.name != "nt":
        os.replace(source, destination)
        return
    import ctypes
    from ctypes import wintypes

    def windows_path(path: Path) -> str:
        # Normalize relative components without following a final file symlink.
        absolute = os.path.abspath(os.fspath(path))
        if absolute.startswith("\\\\?\\"):
            return absolute
        return "\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\") else "\\\\?\\" + absolute

    move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
    move.restype = wintypes.BOOL
    # Same-directory replacement; WRITE_THROUGH requests disk completion on
    # Windows, where POSIX directory fsync is unavailable.
    if not move(windows_path(source), windows_path(destination), 0x1 | 0x8):
        raise ctypes.WinError(ctypes.get_last_error())


def _sync_checkpoint_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_agent_task_state(state: AgentSessionState, *, root: str | Path | None = None) -> Path:
    path = _task_path(state.session_id, root=root)
    payload = _verified_payload(state.to_dict(), state.session_id)
    if path.exists():
        _read_task_payload(path, state.session_id)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as output:
            tmp_path = Path(output.name)
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        _replace_checkpoint(tmp_path, path)
        _sync_checkpoint_directory(path.parent)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return path


def load_agent_task_state(session_id: str, *, root: str | Path | None = None) -> AgentSessionState:
    path = _task_path(session_id, root=root)
    payload = _read_task_payload(path, session_id)
    return AgentSessionState.from_dict(payload)


def delete_agent_task_state(session_id: str, *, root: str | Path | None = None) -> bool:
    path = _task_path(session_id, root=root)
    if not path.exists():
        return False
    with _CHECKPOINT_IO_LOCK:
        _read_task_payload(path, session_id)
        path.unlink()
    return True


def list_agent_task_states(*, root: str | Path | None = None, limit: int = 50) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(_task_dir(root).glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            requested_id = _safe_task_id(path.stem)
            payload = _read_task_payload(path, requested_id)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(
                {
                    "session_id": _compact_text(payload.get("session_id")),
                    "goal": _compact_text(payload.get("goal")),
                    "status": _compact_text(payload.get("status")),
                    "active_domain": _compact_text(payload.get("active_domain")),
                    "pending_count": len(list(payload.get("pending_actions") or [])),
                    "completed_step_count": len(list(payload.get("completed_steps") or [])),
                    "updated_at": _compact_text(payload.get("updated_at")),
                    "path": str(path),
                }
            )
        if len(rows) >= max(1, int(limit or 50)):
            break
    return rows
