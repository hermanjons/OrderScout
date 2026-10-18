"""Human control signal shared with a running worker; never model authority."""
from __future__ import annotations

from threading import Event, Lock


class AgentTaskControl:
    def __init__(self) -> None:
        self._pause = Event()
        self._lock = Lock()
        self._reason = "user_pause"
        self._queued_user_messages: list[str] = []

    @property
    def pause_requested(self) -> bool:
        return self._pause.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    @property
    def queued_user_messages(self) -> list[str]:
        with self._lock:
            return list(self._queued_user_messages)

    def request_pause(self, *, reason: str = "user_pause", user_message: str | None = None) -> None:
        if reason not in {"user_pause", "user_revision"}:
            raise ValueError("task_control_reason_invalid")
        if user_message is not None and (reason != "user_revision" or not isinstance(user_message, str) or not user_message.strip()):
            raise ValueError("task_control_revision_message_invalid")
        with self._lock:
            if user_message is not None:
                self._queued_user_messages.append(user_message)
            if reason == "user_revision" or not self._pause.is_set():
                self._reason = reason
            self._pause.set()

