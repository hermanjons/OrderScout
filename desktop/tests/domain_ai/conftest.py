"""Keep desktop conversation recovery local to each test."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_active_chat(monkeypatch, tmp_path):
    monkeypatch.setattr("AI.processors.chat_session_store.ACTIVE_CHAT_FILE", tmp_path / "active_chat.json")
