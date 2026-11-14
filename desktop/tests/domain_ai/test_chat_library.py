from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from AI.processors import chat_session_store
from AI.processors.chat_session_store import (
    conversation_history,
    list_chat_sessions,
    load_active_chat_session,
    load_chat_session,
    save_active_chat_session,
)
from AI.processors.session_state import AgentSessionState
from AI.processors.task_store import save_agent_task_state


def _state(session_id="first-chat", *, first_message="İlk sohbetin isteği"):
    state = AgentSessionState(goal="Güncel iş hedefi", session_id=session_id, status="complete")
    if first_message:
        state.record_turn(role="user", content=first_message)
        state.record_turn(role="assistant", content="Sohbetin kayıtlı yanıtı")
    return state


def _save(state, **kwargs):
    return save_active_chat_session(state.to_dict(), conversation_history(state.to_dict()), **kwargs)


def test_two_conversations_survive_active_chat_replacement_and_empty_reset(tmp_path):
    first, second = _state(), _state("second-chat", first_message="İkinci sohbetin isteği")
    _save(first, composer_text="Birinci sohbetin taslağı")
    _save(second, composer_text="İkinci sohbetin taslağı")
    empty = _state("empty-chat", first_message="")
    _save(empty)

    rows = list_chat_sessions()
    assert {row["session_id"] for row in rows} == {first.session_id, second.session_id}
    assert load_active_chat_session(task_store_root=tmp_path / "tasks")["state"]["session_id"] == empty.session_id
    for state, draft in ((first, "Birinci sohbetin taslağı"), (second, "İkinci sohbetin taslağı")):
        recovered = load_chat_session(state.session_id, task_store_root=tmp_path / "tasks")
        assert recovered["state"] == state.to_dict()
        assert recovered["history"] == conversation_history(state.to_dict())
        assert recovered["composer_text"] == draft


def test_title_uses_first_user_turn_after_followups_and_goal_changes(tmp_path):
    first_message = "İlk istek\n  aynı başlıkta kalır " + "uzun " * 30
    state = _state(first_message=first_message)
    _save(state)
    first_title = list_chat_sessions()[0]["title"]
    state.goal = "Sonradan değişen iş hedefi"
    state.record_turn(role="user", content="Daha sonra gelen farklı istek")
    state.record_turn(role="assistant", content="Sonraki yanıt")
    _save(state)

    row = list_chat_sessions()[0]
    assert row["title"] == first_title
    assert row["title"].startswith("İlk istek aynı başlıkta kalır ")
    assert len(row["title"]) <= 80 and row["title"].endswith("…")
    assert row["goal"] == state.goal
    payload = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
    assert payload["title"] == row["title"]
    assert datetime.fromisoformat(payload["saved_at"]).utcoffset() == timedelta(0)
    assert row["updated_at"] == payload["saved_at"]


@pytest.mark.parametrize("kind", ["draft", "guidance", "state_guidance"])
def test_unsubmitted_draft_and_queued_guidance_are_archived(tmp_path, kind):
    state = _state(first_message="")
    kwargs = {}
    text = "Henüz kaybolmaması gereken talimat"
    if kind == "draft":
        kwargs["composer_text"] = text
    elif kind == "guidance":
        kwargs["queued_guidance"] = [text]
    else:
        state.active_entities["task_control"] = {"queued_user_messages": [text]}
    _save(state, **kwargs)

    rows = list_chat_sessions()
    assert len(rows) == 1
    assert rows[0]["title"] == text
    recovered = load_chat_session(state.session_id, task_store_root=tmp_path / "tasks")
    assert recovered["composer_text"] == text
    if kind == "draft":
        assert not recovered["history"]
        assert not recovered["state"]["conversation_turns"]
    else:
        assert recovered["recovered_user_messages"] == [text]


def test_library_defaults_follow_patched_active_path_and_explicit_save_is_isolated(tmp_path, monkeypatch):
    default_active = tmp_path / "first-profile" / "active_chat.json"
    monkeypatch.setattr(chat_session_store, "ACTIVE_CHAT_FILE", default_active)
    state = _state()
    _save(state)
    alternate_active = tmp_path / "second-profile" / "active.json"
    other = _state("other-chat")
    _save(other, path=alternate_active)

    assert [row["session_id"] for row in list_chat_sessions()] == [state.session_id]
    alternate_root = alternate_active.parent / "conversations"
    assert [row["session_id"] for row in list_chat_sessions(root=alternate_root)] == [other.session_id]
    assert load_chat_session(other.session_id, task_store_root=tmp_path / "tasks") is None
    assert load_chat_session(other.session_id, root=alternate_root, task_store_root=tmp_path / "tasks")["state"]["session_id"] == other.session_id
    monkeypatch.setattr(chat_session_store, "ACTIVE_CHAT_FILE", tmp_path / "third-profile" / "active.json")
    assert not list_chat_sessions()
    assert not chat_session_store.ACTIVE_CHAT_FILE.parent.exists()


@pytest.mark.parametrize("session_id", ["../elsewhere", "..\\elsewhere", "CON", "con", "UpperCase", "", "x/y", "a" * 97])
def test_library_rejects_invalid_session_identity(tmp_path, session_id):
    with pytest.raises(ValueError):
        load_chat_session(session_id, root=tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("contents", ["{", "[]", '{"version":2}',
                                      '{"version":1,"session_state":{"session_id":"../other"}}'])
def test_malformed_library_entries_do_not_hide_valid_chats(tmp_path, contents):
    state = _state()
    _save(state)
    root = chat_session_store.ACTIVE_CHAT_FILE.parent / "conversations"
    broken = root / "broken-chat.json"
    broken.write_text(contents, encoding="utf-8")

    assert [row["session_id"] for row in list_chat_sessions()] == [state.session_id]
    with pytest.raises((ValueError, TypeError)):
        load_chat_session("broken-chat", task_store_root=tmp_path / "tasks")
    assert broken.read_text(encoding="utf-8") == contents


def test_renamed_entry_cannot_open_another_chat_and_invalid_filenames_are_skipped(tmp_path):
    _save(_state())
    root = chat_session_store.ACTIVE_CHAT_FILE.parent / "conversations"
    payload = (root / "first-chat.json").read_text(encoding="utf-8")
    (root / "renamed-chat.json").write_text(payload, encoding="utf-8")
    (root / "UPPERCASE.json").write_text(payload, encoding="utf-8")

    assert [row["session_id"] for row in list_chat_sessions()] == ["first-chat"]
    with pytest.raises(ValueError, match="does not match"):
        load_chat_session("renamed-chat", task_store_root=tmp_path / "tasks")


def test_archive_recovery_prefers_newer_checkpoint_without_writing_or_executing(tmp_path):
    state = _state()
    state.add_pending_action({
        "action_type": "orders.change_cargo_provider", "title": "Kargo değişikliği",
        "summary": "ORD-1 için hazırlanmış işlem", "order_numbers": ["ORD-1"],
        "_agent_task_session_id": state.session_id,
    })
    state.status = "pending_approval"
    state.updated_at = "2026-10-01T10:00:00+00:00"
    _save(state)
    state.cancel_active_pending_action(reason="user_cancelled", cancelled_by="user")
    state.record_turn(role="user", content="Vazgeç")
    state.record_turn(role="assistant", content="İşlem iptal edildi.")
    state.updated_at = "2026-10-02T10:00:00+00:00"
    task_root = tmp_path / "tasks"
    checkpoint_path = save_agent_task_state(state, root=task_root)
    archive = Path(list_chat_sessions()[0]["path"])
    before = {path: path.read_bytes() for path in (checkpoint_path, archive, chat_session_store.ACTIVE_CHAT_FILE)}

    with patch("AI.processors.task_store.save_agent_task_state") as checkpoint_save, patch(
        "AI.processors.operation_runtime.execute_approved_operation"
    ) as execute:
        recovered = load_chat_session(state.session_id, task_store_root=task_root)
        list_chat_sessions()

    assert recovered["checkpoint_recovered"]
    assert not recovered["state"]["pending_actions"]
    assert not recovered["state"]["active_pending_action_id"]
    assert recovered["history"][-1]["content"] == "İşlem iptal edildi."
    checkpoint_save.assert_not_called()
    execute.assert_not_called()
    assert {path: path.read_bytes() for path in before} == before


def test_library_listing_orders_by_snapshot_save_time_and_honors_limit(tmp_path):
    first, second = _state(), _state("second-chat")
    _save(first)
    _save(second)
    root = chat_session_store.ACTIVE_CHAT_FILE.parent / "conversations"
    for session_id, saved_at in ((first.session_id, "2026-10-02T10:00:00+00:00"),
                                 (second.session_id, "2026-10-01T10:00:00+00:00")):
        path = root / f"{session_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["saved_at"] = saved_at
        path.write_text(json.dumps(payload), encoding="utf-8")

    assert [row["session_id"] for row in list_chat_sessions(limit=1)] == [first.session_id]
    assert not list_chat_sessions(limit=0)


def test_failed_library_commit_preserves_active_snapshot_and_reports_failure(tmp_path):
    first, second = _state(), _state("second-chat")
    _save(first)
    previous = chat_session_store.ACTIVE_CHAT_FILE.read_bytes()
    original_replace = chat_session_store._replace_checkpoint

    def replace(source, destination):
        if destination.parent.name == "conversations" and destination.stem == second.session_id:
            raise OSError("archive unavailable")
        original_replace(source, destination)

    with patch.object(chat_session_store, "_replace_checkpoint", side_effect=replace):
        with pytest.raises(OSError, match="archive unavailable"):
            _save(second)

    assert chat_session_store.ACTIVE_CHAT_FILE.read_bytes() == previous
    assert [row["session_id"] for row in list_chat_sessions()] == [first.session_id]
    assert not list(tmp_path.rglob("*.tmp"))


def test_failed_active_commit_reports_failure_but_keeps_library_backup(tmp_path):
    _save(_state())
    second = _state("second-chat")
    previous = chat_session_store.ACTIVE_CHAT_FILE.read_bytes()
    original_replace = chat_session_store._replace_checkpoint

    def replace(source, destination):
        if destination == chat_session_store.ACTIVE_CHAT_FILE:
            raise OSError("active snapshot unavailable")
        original_replace(source, destination)

    with patch.object(chat_session_store, "_replace_checkpoint", side_effect=replace):
        with pytest.raises(OSError, match="active snapshot unavailable"):
            _save(second)

    assert chat_session_store.ACTIVE_CHAT_FILE.read_bytes() == previous
    assert load_chat_session(second.session_id, task_store_root=tmp_path / "tasks")["state"]["session_id"] == second.session_id
    assert load_active_chat_session(task_store_root=tmp_path / "tasks")["state"]["session_id"] == "first-chat"
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize("explicit_path", [False, True])
def test_restart_after_active_commit_failure_preserves_latest_same_chat_draft_on_save(tmp_path, explicit_path):
    state = _state()
    active = tmp_path / "alternate-profile" / "active.json" if explicit_path else chat_session_store.ACTIVE_CHAT_FILE
    original_replace = chat_session_store._replace_checkpoint

    def replace(source, destination):
        if destination == active:
            raise OSError("active snapshot unavailable")
        original_replace(source, destination)

    with patch.object(chat_session_store, "datetime", wraps=datetime) as clock:
        clock.now.return_value = datetime(2026, 10, 20, 10, tzinfo=timezone.utc)
        _save(state, composer_text="Eski taslak", path=active)
        previous_active = active.read_bytes()
        clock.now.return_value += timedelta(seconds=1)
        with patch.object(chat_session_store, "_replace_checkpoint", side_effect=replace):
            with pytest.raises(OSError, match="active snapshot unavailable"):
                _save(state, composer_text="Son düzenlenen taslak", path=active)

        archive = active.parent / "conversations" / f"{state.session_id}.json"
        previous_archive = archive.read_bytes()
        assert active.read_bytes() == previous_active
        restarted = load_active_chat_session(path=active, task_store_root=tmp_path / "tasks")
        assert restarted["composer_text"] == "Son düzenlenen taslak"
        assert restarted["state"]["session_id"] == state.session_id
        assert active.read_bytes() == previous_active
        assert archive.read_bytes() == previous_archive

        # Startup's normal persistence must keep the recovered UI data instead
        # of replacing the archive with the stale active-file draft.
        clock.now.return_value += timedelta(seconds=1)
        save_active_chat_session(restarted["state"], restarted["history"],
                                 composer_text=restarted["composer_text"], path=active)

    for path in (active, archive):
        assert json.loads(path.read_text(encoding="utf-8"))["composer_text"] == "Son düzenlenen taslak"
    assert load_active_chat_session(path=active, task_store_root=tmp_path / "tasks")["composer_text"] == "Son düzenlenen taslak"


@pytest.mark.parametrize("archive_kind", ["malformed", "wrong_identity", "invalid_timestamp", "older"])
def test_unusable_or_older_archive_does_not_block_active_recovery(tmp_path, archive_kind):
    state = _state()
    _save(state, composer_text="Sağlam etkin sohbet taslağı")
    active = chat_session_store.ACTIVE_CHAT_FILE
    archive = active.parent / "conversations" / f"{state.session_id}.json"
    payload = json.loads(archive.read_text(encoding="utf-8"))
    payload["composer_text"] = "Seçilmemesi gereken yedek"
    payload["saved_at"] = "2099-01-01T00:00:00+00:00"
    if archive_kind == "wrong_identity":
        payload["session_state"]["session_id"] = "another-chat"
    elif archive_kind == "invalid_timestamp":
        payload["saved_at"] = "invalid timestamp"
    elif archive_kind == "older":
        payload["saved_at"] = "2020-01-01T00:00:00+00:00"
    contents = "{" if archive_kind == "malformed" else json.dumps(payload, ensure_ascii=False)
    archive.write_text(contents, encoding="utf-8")
    before = {path: path.read_bytes() for path in (active, archive)}

    restarted = load_active_chat_session(task_store_root=tmp_path / "tasks")

    assert restarted["composer_text"] == "Sağlam etkin sohbet taslağı"
    assert restarted["state"]["session_id"] == state.session_id
    assert {path: path.read_bytes() for path in before} == before


def test_library_load_reconciles_selected_archive_without_reopening_active_or_nested_archive(tmp_path):
    state = _state()
    _save(state, composer_text="Seçilen arşivin taslağı")
    archive = chat_session_store.ACTIVE_CHAT_FILE.parent / "conversations" / f"{state.session_id}.json"
    nested = archive.parent / "conversations" / archive.name
    nested.parent.mkdir()
    payload = json.loads(archive.read_text(encoding="utf-8"))
    payload.update(saved_at="2099-01-01T00:00:00+00:00", composer_text="Seçilmemesi gereken iç içe yedek")
    nested.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    before = {path: path.read_bytes() for path in (archive, nested, chat_session_store.ACTIVE_CHAT_FILE)}

    recovered = load_chat_session(state.session_id, task_store_root=tmp_path / "tasks")

    assert recovered["composer_text"] == "Seçilen arşivin taslağı"
    assert {path: path.read_bytes() for path in before} == before
