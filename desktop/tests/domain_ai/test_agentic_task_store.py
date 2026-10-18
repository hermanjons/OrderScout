from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import threading
from unittest.mock import patch

import pytest

from AI.processors import task_store
from AI.processors.session_state import AgentSessionState


@pytest.mark.parametrize("invalid_id", [
    "", " ", " task-a", "task-a ", "task/a", "task\\a", "../task-a", "task.a", "task:a", "task\x00a",
    "Task-a", "task-İ", "任务", "a" * 97, "con", "prn", "aux", "nul", "com1", "com9", "lpt1", "lpt9",
    None, 123,
])
def test_invalid_ids_cannot_alias_or_modify_an_existing_task(tmp_path, invalid_id):
    good = AgentSessionState(session_id="task-a", goal="Keep this task")
    path = task_store.save_agent_task_state(good, root=tmp_path)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        task_store.save_agent_task_state(AgentSessionState(session_id=invalid_id, goal="Rejected alias"), root=tmp_path)
    with pytest.raises(ValueError):
        task_store.load_agent_task_state(invalid_id, root=tmp_path)
    with pytest.raises(ValueError):
        task_store.delete_agent_task_state(invalid_id, root=tmp_path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("session_id", ["0123456789abcdef0123456789abcdef", "task_2026-10-08", "a" * 96])
def test_canonical_ids_and_full_unicode_state_roundtrip(tmp_path, session_id):
    state = AgentSessionState(session_id=session_id, goal="Sipariş ve ödeme incelemesi", status="interrupted")
    state.active_entities = {"execution_budget": {"max_steps": 20, "started_steps": 8},
                             "task_checkpoint": {"version": 1, "phase": "step_observed"},
                             "authority": {"pending_action_id": "immutable-action", "approved": False}}
    path = task_store.save_agent_task_state(state, root=tmp_path)
    assert path.name == f"{session_id}.json"
    assert task_store.load_agent_task_state(session_id, root=tmp_path).to_dict() == state.to_dict()
    assert task_store.list_agent_task_states(root=tmp_path)[0]["session_id"] == session_id


@pytest.mark.parametrize("payload_id", ["another-task", "Task-a", " task-a", None])
def test_payload_identity_mismatch_cannot_load_overwrite_or_appear_in_picker(tmp_path, payload_id):
    state = AgentSessionState(session_id="task-a", goal="Original")
    payload = state.to_dict()
    payload["session_id"] = payload_id
    path = tmp_path / "task-a.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ValueError):
        task_store.load_agent_task_state("task-a", root=tmp_path)
    with pytest.raises(ValueError):
        task_store.save_agent_task_state(state, root=tmp_path)
    with pytest.raises(ValueError):
        task_store.delete_agent_task_state("task-a", root=tmp_path)
    assert task_store.list_agent_task_states(root=tmp_path) == []
    assert path.read_bytes() == original


def test_missing_payload_identity_does_not_generate_a_fresh_task(tmp_path):
    path = tmp_path / "task-a.json"
    path.write_text(json.dumps({"goal": "Foreign pending authority", "status": "pending_approval"}), encoding="utf-8")
    with pytest.raises(ValueError):
        task_store.load_agent_task_state("task-a", root=tmp_path)
    assert task_store.list_agent_task_states(root=tmp_path) == []


@pytest.mark.parametrize("payload", [[], None, "task-a"])
def test_nonobject_payload_cannot_be_used_as_a_resume_target(tmp_path, payload):
    (tmp_path / "task-a.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        task_store.load_agent_task_state("task-a", root=tmp_path)
    assert task_store.list_agent_task_states(root=tmp_path) == []


def test_alias_prone_historical_filename_is_not_exposed_as_a_resume_target(tmp_path):
    state = AgentSessionState(session_id="task-a", goal="Valid payload in invalid file name")
    (tmp_path / "task.a.json").write_text(json.dumps(state.to_dict()), encoding="utf-8")
    assert task_store.list_agent_task_states(root=tmp_path) == []


@pytest.mark.parametrize("failure_point", ["file_fsync", "atomic_replace"])
def test_failed_save_preserves_previous_checkpoint_and_removes_uncommitted_temp(tmp_path, failure_point):
    state = AgentSessionState(session_id="task-a", goal="Before interruption")
    path = task_store.save_agent_task_state(state, root=tmp_path)
    original = path.read_bytes()
    state.goal = "Uncommitted update"
    target = "os.fsync" if failure_point == "file_fsync" else "_replace_checkpoint"
    with patch.object(task_store.os, "fsync", side_effect=OSError("Cannot flush checkpoint")) if target == "os.fsync" \
            else patch.object(task_store, target, side_effect=OSError("Cannot replace checkpoint")):
        with pytest.raises(OSError):
            task_store.save_agent_task_state(state, root=tmp_path)
    assert path.read_bytes() == original
    assert task_store.load_agent_task_state("task-a", root=tmp_path).goal == "Before interruption"
    assert list(tmp_path.iterdir()) == [path]


def test_process_interruption_before_replace_keeps_committed_authority(tmp_path):
    class ProcessLoss(BaseException):
        pass
    state = AgentSessionState(session_id="task-a", goal="Approved source receipt")
    state.active_entities["immutable_receipt"] = {"approved": False, "source_hash": "source-v1"}
    path = task_store.save_agent_task_state(state, root=tmp_path)
    original = path.read_bytes()
    state.active_entities["immutable_receipt"] = {"approved": True, "source_hash": "uncommitted-v2"}
    with patch.object(task_store, "_replace_checkpoint", side_effect=ProcessLoss()), pytest.raises(ProcessLoss):
        task_store.save_agent_task_state(state, root=tmp_path)
    assert path.read_bytes() == original
    assert task_store.load_agent_task_state("task-a", root=tmp_path).active_entities["immutable_receipt"]["approved"] is False


def test_posix_directory_sync_releases_descriptor_even_when_sync_fails(tmp_path):
    with patch.object(task_store.os, "name", "posix"), \
            patch.object(task_store.os, "open", return_value=123) as opened, \
            patch.object(task_store.os, "fsync", side_effect=OSError("Directory sync failed")) as synced, \
            patch.object(task_store.os, "close") as closed:
        with pytest.raises(OSError):
            task_store._sync_checkpoint_directory(tmp_path)
    opened.assert_called_once_with(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    synced.assert_called_once_with(123)
    closed.assert_called_once_with(123)


def test_replace_observes_a_complete_flushed_same_directory_temp(tmp_path):
    state = AgentSessionState(session_id="task-a", goal="Durable checkpoint")
    events = []
    actual_fsync = os.fsync
    actual_replace = task_store._replace_checkpoint
    def flushed(descriptor):
        events.append("fsync")
        return actual_fsync(descriptor)
    def replace(source, destination):
        assert source.parent == destination.parent == tmp_path
        assert json.loads(source.read_text(encoding="utf-8")) == state.to_dict()
        assert events == ["fsync"]
        events.append("replace")
        return actual_replace(source, destination)
    with patch.object(task_store.os, "fsync", side_effect=flushed), \
            patch.object(task_store, "_replace_checkpoint", side_effect=replace):
        task_store.save_agent_task_state(state, root=tmp_path)
    assert events == (["fsync", "replace"] if os.name == "nt" else ["fsync", "replace", "fsync"])
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("commit_round", range(4))
def test_simultaneous_saves_use_distinct_temps_and_never_publish_a_partial_payload(tmp_path, commit_round):
    state = AgentSessionState(session_id="task-a", goal=f"Initial {commit_round}")
    task_store.save_agent_task_state(state, root=tmp_path)
    initial = state.to_dict()
    before_replace = threading.Barrier(2, timeout=10)
    temporary_paths = []
    complete_payloads = []
    actual_replace = task_store._replace_checkpoint
    def replace(source, destination):
        temporary_paths.append(source)
        complete_payloads.append(json.loads(source.read_text(encoding="utf-8")))
        before_replace.wait()
        actual_replace(source, destination)
    def save(number):
        payload = deepcopy(initial)
        payload["goal"] = f"Writer {number}: " + "tam gözlem " * 1000
        task_store.save_agent_task_state(AgentSessionState.from_dict(payload), root=tmp_path)
    with patch.object(task_store, "_replace_checkpoint", side_effect=replace), ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, n) for n in (1, 2)]
        for future in futures:
            future.result(timeout=15)
    assert len(set(temporary_paths)) == 2
    assert json.loads((tmp_path / "task-a.json").read_text(encoding="utf-8")) in complete_payloads
    assert len(list(tmp_path.iterdir())) == 1


def test_atomic_replace_replaces_the_named_file_link_without_overwriting_its_target(tmp_path):
    target = tmp_path / "independent-source.json"
    source = tmp_path / "checkpoint.tmp"
    destination = tmp_path / "task-a.json"
    target.write_text("Independent source", encoding="utf-8")
    source.write_text("New checkpoint", encoding="utf-8")
    try:
        destination.symlink_to(target)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows user lacks symbolic-link creation privilege")
        raise
    task_store._replace_checkpoint(source, destination)
    assert not destination.is_symlink()
    assert destination.read_text(encoding="utf-8") == "New checkpoint"
    assert target.read_text(encoding="utf-8") == "Independent source"


def test_deletion_is_exact_and_does_not_remove_a_similar_task(tmp_path):
    first = task_store.save_agent_task_state(AgentSessionState(session_id="task-a", goal="First"), root=tmp_path)
    second = task_store.save_agent_task_state(AgentSessionState(session_id="task_a", goal="Second"), root=tmp_path)
    assert task_store.delete_agent_task_state("task-a", root=tmp_path) is True
    assert not first.exists() and second.exists()
    assert task_store.delete_agent_task_state("task-a", root=tmp_path) is False
