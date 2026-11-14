"""Durable UI conversation recovery, separate from in-flight task checkpoints."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import os
import tempfile
import threading
from typing import Any

from AI.constants.paths import AI_DOMAIN_ROOT
from AI.processors.session_state import AgentSessionState
from AI.processors.task_store import (
    _replace_checkpoint,
    _safe_task_id,
    _sync_checkpoint_directory,
    load_agent_task_state,
)


ACTIVE_CHAT_FILE = AI_DOMAIN_ROOT / "active_chat.json"
_CHAT_IO_LOCK = threading.RLock()


def _chat_library_root(root: str | Path | None = None) -> Path:
    return Path(root) if root is not None else ACTIVE_CHAT_FILE.parent / "conversations"


def _chat_path(session_id: str, *, root: str | Path | None = None) -> Path:
    return _chat_library_root(root) / f"{_safe_task_id(session_id)}.json"


def _read_chat_snapshot(source: Path, *, session_id: str | None = None) -> dict[str, Any]:
    with _CHAT_IO_LOCK:
        payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Unsupported saved chat format.")
    raw_state = payload.get("session_state")
    if not isinstance(raw_state, dict) or not isinstance(raw_state.get("session_id"), str) or not raw_state["session_id"]:
        raise ValueError("Saved chat has no session identity.")
    stored_id = _safe_task_id(raw_state["session_id"])
    if session_id is not None and stored_id != session_id:
        raise ValueError("Saved chat session_id does not match the requested conversation.")
    payload["session_state"] = AgentSessionState.from_dict(raw_state).to_dict()
    payload["history"] = _history(payload.get("history", []))
    if not isinstance(payload.get("composer_text", ""), str):
        raise ValueError("Saved chat draft must be text.")
    _snapshot_guidance(payload)
    return payload


def _snapshot_guidance(payload: dict[str, Any]) -> list[str]:
    control = (payload["session_state"].get("active_entities") or {}).get("task_control") or {}
    guidance = payload.get("queued_guidance") or (control.get("queued_user_messages") if isinstance(control, dict) else []) or []
    if not isinstance(guidance, list):
        raise ValueError("Saved chat guidance must be a list.")
    return [message for message in guidance if isinstance(message, str) and message.strip()]


def _snapshot_title(payload: dict[str, Any]) -> str:
    history = [*payload["history"], *conversation_history(payload["session_state"])]
    text = next((row["content"] for row in history if row["role"] == "user"), "")
    if not text:
        candidates = [payload.get("composer_text", ""), *_snapshot_guidance(payload), payload["session_state"].get("goal", "")]
        text = next((value for value in candidates if value.strip()), "Yeni sohbet")
    compact = " ".join(text.split())
    return compact if len(compact) <= 80 else compact[:79].rstrip() + "…"


def _has_snapshot_content(payload: dict[str, Any]) -> bool:
    return bool(
        payload["history"] or conversation_history(payload["session_state"])
        or payload.get("composer_text", "").strip() or _snapshot_guidance(payload)
    )


def _write_chat_snapshot(destination: Path, serialized: str) -> None:
    """Replace one complete snapshot using the task store's durability contract."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=f".{destination.name}.", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        _replace_checkpoint(temporary, destination)
        _sync_checkpoint_directory(destination.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def conversation_history(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Project complete recorded turns without deduplicating repeated messages."""
    entities = state.get("active_entities") or {}
    return _history(
        state.get("conversation_turns")
        or (entities.get("conversation_history") if isinstance(entities, dict) else [])
        or []
    )


def _history(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError("Saved chat history must be a list.")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        role, content = row.get("role"), row.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        item = {"role": role, "content": content}
        if isinstance(row.get("context"), dict):
            item["context"] = deepcopy(row["context"])
        result.append(item)
    return result


def _timestamp(value: Any) -> float:
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _message_key(row: dict[str, Any]) -> tuple[str, str]:
    return row["role"], row["content"]


def _has_history_prefix(history: list[dict[str, Any]], prefix: list[dict[str, Any]]) -> bool:
    return len(history) >= len(prefix) and all(
        _message_key(left) == _message_key(right) for left, right in zip(history, prefix)
    )


def _reconcile_submitted_messages(
    snapshot_state: dict[str, Any], state: dict[str, Any], history: list[dict[str, Any]],
    guidance: list[str], *, checkpoint_recovered: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
    """Recover submitted UI messages only across a proven same-session prefix.

    The UI saves before the worker creates its first checkpoint. Those user
    messages already happened; recording them is data recovery, never a new
    approval or permission to execute. Match occurrences in order rather than
    comparing sets, because identical user requests can be separate turns.
    """
    baseline = conversation_history(snapshot_state)
    recorded = conversation_history(state)
    ui_has_prefix = _has_history_prefix(history, baseline)
    suffix = history[len(baseline):] if ui_has_prefix else []
    pending = suffix if suffix and all(row["role"] == "user" for row in suffix) else []
    recorded_guidance = (snapshot_state.get("conversation_turns") or [])[-len(guidance):] if guidance else []
    guidance_already_recorded = bool(guidance) and len(recorded_guidance) == len(guidance) and all(
        row.get("mode") == "recovered_submission" and row.get("content") == message
        for row, message in zip(recorded_guidance, guidance)
    )
    from_guidance = False
    if not pending and guidance and not guidance_already_recorded:
        # Explicitly queued UI guidance remains authoritative even when the
        # latest assistant response was displayed after the queued user row.
        pending = [{"role": "user", "content": text} for text in guidance]
        from_guidance = True
    elif not pending and not ui_has_prefix:
        # Divergent transcripts cannot establish where a submitted turn belongs.
        # Preserve its exact trailing text for explicit resubmission instead.
        for row in reversed(history):
            if row["role"] != "user":
                break
            pending.insert(0, row)
        if pending:
            return state, history, [], [row["content"] for row in pending]
    if not pending:
        return state, recorded if checkpoint_recovered and recorded else history, [], []
    if not _has_history_prefix(recorded, baseline):
        return state, recorded if checkpoint_recovered and recorded else history, [], [row["content"] for row in pending]

    consumed = 0
    for row in recorded[len(baseline):]:
        if consumed < len(pending) and _message_key(row) == _message_key(pending[consumed]):
            consumed += 1
    missing = pending[consumed:]
    if not missing:
        return state, recorded if checkpoint_recovered and recorded else history, [], []
    recovered = AgentSessionState.from_dict(state)
    for row in missing:
        recovered.record_turn(role="user", content=row["content"], mode="recovered_submission", objective=recovered.goal)
    if recovered.active_pending_action() is not None:
        from AI.processors.turn_service import approval_reply_protocol
        revisions = [row["content"] for row in missing if approval_reply_protocol(row["content"], recovered) != "approve"]
        if revisions:
            # An unprocessed revision/withdrawal cannot leave the older proposal
            # executable. The normal next model turn consumes this saved input.
            control = dict(recovered.active_entities.get("task_control") or {})
            control.update(reason="user_revision", queued_user_messages=revisions)
            recovered.active_entities["task_control"] = control
    if recovered.status in {"complete", "running"} and recovered.active_pending_action() is None:
        recovered.status = "interrupted"
    if checkpoint_recovered or from_guidance:
        history = [*recorded, *[deepcopy(row) for row in missing]]
    return recovered.to_dict(), history, [row["content"] for row in missing], []


def save_active_chat_session(
    state: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    composer_text: str = "",
    queued_guidance: list[str] | None = None,
    path: str | Path | None = None,
) -> Path:
    """Save a UI snapshot without ever overwriting an executing task's state."""
    if not isinstance(state, dict) or not isinstance(state.get("session_id"), str) or not state["session_id"]:
        raise ValueError("Saved chat must have a session identity.")
    # Verify typed state before replacing the last usable snapshot.
    _safe_task_id(state["session_id"])
    normalized_state = AgentSessionState.from_dict(state).to_dict()
    payload = {
        "version": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "session_state": deepcopy(normalized_state),
        "history": _history(history),
        "composer_text": str(composer_text),
        "queued_guidance": [message for message in (queued_guidance or []) if isinstance(message, str) and message.strip()],
    }
    payload["title"] = _snapshot_title(payload)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    destination = Path(path) if path is not None else ACTIVE_CHAT_FILE
    with _CHAT_IO_LOCK:
        if _has_snapshot_content(payload):
            # Commit the library first. A failed archive must not report an
            # active-chat save as successful and then lose this chat on reset.
            archive = _chat_path(normalized_state["session_id"], root=destination.parent / "conversations")
            _write_chat_snapshot(archive, serialized)
        _write_chat_snapshot(destination, serialized)
    return destination


def load_active_chat_session(
    *,
    path: str | Path | None = None,
    task_store_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Recover the selected chat's newest UI snapshot and task checkpoint.

    Recovery is read-only. Pending actions and interrupted work still require a
    new user command through the normal execution and approval boundaries.
    """
    source = Path(path) if path is not None else ACTIVE_CHAT_FILE
    if not source.exists():
        return None
    payload = _read_chat_snapshot(source)
    archive = _chat_path(payload["session_state"]["session_id"], root=source.parent / "conversations")
    if archive != source:
        try:
            archived_payload = _read_chat_snapshot(archive, session_id=payload["session_state"]["session_id"])
        except (ValueError, TypeError, KeyError, OSError, AttributeError):
            # A failed second commit can leave a newer library backup, but a
            # damaged backup must never block the usable active snapshot.
            archived_payload = None
        if archived_payload is not None and _timestamp(archived_payload.get("saved_at")) > _timestamp(payload.get("saved_at")):
            payload = archived_payload
    return _recover_chat_snapshot(payload, task_store_root=task_store_root)


def _recover_chat_snapshot(
    payload: dict[str, Any], *, task_store_root: str | Path | None = None,
) -> dict[str, Any]:
    """Reconcile an already selected, identity-checked UI snapshot read-only."""
    state = payload["session_state"]
    snapshot_state = deepcopy(state)
    history = _history(payload.get("history", []))
    checkpoint_recovered = False
    checkpoint_error = ""
    try:
        checkpoint = load_agent_task_state(state["session_id"], root=task_store_root).to_dict()
    except FileNotFoundError:
        checkpoint = None
    except (ValueError, TypeError, KeyError, OSError) as exc:
        # A usable UI backup must survive a malformed or unreadable checkpoint.
        checkpoint = None
        checkpoint_error = str(exc)
    if checkpoint is not None and _timestamp(checkpoint.get("updated_at")) > _timestamp(state.get("updated_at")):
        state = checkpoint
        checkpoint_recovered = True
    if not history:
        history = conversation_history(state)
    guidance = _snapshot_guidance(payload)
    state, history, recovered_messages, resubmit_messages = _reconcile_submitted_messages(
        snapshot_state, state, history, guidance, checkpoint_recovered=checkpoint_recovered,
    )
    draft = payload.get("composer_text", "")
    if not isinstance(draft, str):
        raise ValueError("Saved chat draft must be text.")
    if history and state.get("status") == "running":
        state["status"] = "interrupted"
    return {
        "state": state,
        "history": history,
        "composer_text": draft or "\n".join(resubmit_messages or (guidance if not checkpoint_recovered else [])),
        "recovered_user_messages": recovered_messages,
        "resubmit_user_messages": resubmit_messages,
        "checkpoint_recovered": checkpoint_recovered,
        "checkpoint_error": checkpoint_error,
    }


@lru_cache(maxsize=256)
def _chat_summary(path: Path, revision: tuple[int, ...]) -> dict[str, Any] | None:
    # The file version keys the summary across atomic saves. Opening a chat
    # still reads and validates the full snapshot.
    session_id = _safe_task_id(path.stem)
    payload = _read_chat_snapshot(path, session_id=session_id)
    if not _has_snapshot_content(payload):
        return None
    state = payload["session_state"]
    updated_at = payload.get("saved_at") or state.get("updated_at", "")
    if not isinstance(updated_at, str):
        raise ValueError("Saved chat timestamp must be text.")
    return {
        "session_id": session_id,
        "title": _snapshot_title(payload),
        "goal": state["goal"],
        "status": state["status"],
        "pending_count": int(AgentSessionState.from_dict(state).active_pending_action() is not None),
        "completed_step_count": len(state.get("completed_steps") or []),
        "updated_at": updated_at,
        "path": str(path),
    }


def list_chat_sessions(*, root: str | Path | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """List durable conversation snapshots without reading or writing tasks."""
    count = max(0, int(limit))
    if not count:
        return []
    rows = []
    for path in _chat_library_root(root).glob("*.json"):
        try:
            stat = path.stat()
            revision = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            summary = _chat_summary(path, revision)
            if summary is not None:
                rows.append(dict(summary))
        except (ValueError, TypeError, KeyError, OSError, AttributeError):
            # A broken entry cannot hide other usable conversations.
            continue
    rows.sort(key=lambda row: (_timestamp(row["updated_at"]), row["session_id"]), reverse=True)
    return rows[:count]


def load_chat_session(
    session_id: str,
    *,
    root: str | Path | None = None,
    task_store_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Open one chat through the same read-only recovery boundary as startup."""
    source = _chat_path(session_id, root=root)
    if not source.exists():
        return None
    # Bind the requested file identity before checkpoint reconciliation can
    # select a task. A renamed or damaged entry must not open a different chat.
    with _CHAT_IO_LOCK:
        payload = _read_chat_snapshot(source, session_id=session_id)
        return _recover_chat_snapshot(payload, task_store_root=task_store_root)
