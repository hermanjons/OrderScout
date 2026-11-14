"""A provider stream failure must not discard a real domain read or its task."""
from collections import Counter
import json

import pytest
from sqlmodel import Session, select

from AI.processors import cloud_runtime, model_loop, tools
from AI.processors.task_store import load_agent_task_state
from AI.runtime.response_stream import response_stream
from Core.utils.model_utils import get_engine
from Orders.models.trendyol.models import OrderData
from Testing.processors.order_snapshot_fixture import seed_order_snapshot_fixture


def frame(payload):
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode()


class Stream:
    ok = True
    status_code = 200
    headers = {"Content-Type": "text/event-stream"}
    url = "https://synthetic.test/v1/chat/completions"
    def __init__(self, frames): self.frames = frames
    def iter_content(self, chunk_size=1): yield from self.frames
    def raise_for_status(self): pass
    def close(self): pass


def text_stream(answer, *, terminal=True):
    return Stream([frame({"model": "synthetic-model", "choices": [{"index": 0,
        "delta": {"content": answer}, "finish_reason": "stop" if terminal else None}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20}})])


def tool_stream():
    return Stream([frame({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0,
        "id": "synthetic-call", "type": "function", "function": {"name": "orders_status_counts",
        "arguments": '{"period":"all"}'}}]}, "finish_reason": "tool_calls"}]}), b"data: [DONE]\n\n"])


@pytest.fixture
def classification(tmp_path, monkeypatch):
    db = str(tmp_path / "business.sqlite3")
    seed_order_snapshot_fixture(db, isolation_root=tmp_path)
    with Session(get_engine(db)) as session:
        outside = session.exec(select(OrderData).where(OrderData.orderNumber == "SNAPSHOT-OUTSIDE")).one()
        session.delete(outside)
        session.commit()
        rows = list(session.exec(select(OrderData)).all())
        counts = Counter(row.status for row in rows)
    assert sum(counts.values()) == 570
    registry = tools.available_tools()
    monkeypatch.setattr(tools, "available_tools", lambda: {"orders.status_counts": registry["orders.status_counts"]})
    answer = "570 siparişi durumlarına göre sınıflandırdım: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    return db, counts, answer


def client():
    value = cloud_runtime.build_openai_compatible_client(base_url="https://synthetic.test/v1", api_key="synthetic",
        model="synthetic-model", provider_code="openrouter", timeout=2, native_tool_runtime_enabled=True,
        model_metadata={"supported_parameters": ["tools"]})
    value.resource_plan = {"provider_code": "openrouter", "capability_profile": {"native_tool_runtime_enabled": True}}
    return value


@pytest.mark.parametrize("transient", [False, True])
def test_real_domain_classification_finishes_after_stream_recovery(classification, tmp_path, monkeypatch, transient):
    db, expected, answer = classification
    replies = [tool_stream()]
    if transient:
        replies.append(text_stream("Tamamlanmamış taslak", terminal=False))
    replies.append(text_stream(answer))  # valid finish, clean EOF, no redundant DONE marker
    requests = []
    def post(url, **kwargs):
        requests.append(kwargs["json"])
        return replies.pop(0)
    monkeypatch.setattr(cloud_runtime.requests, "post", post)
    events = []
    with response_stream(events.append):
        result = model_loop.run_model_loop("570 siparişi sınıflandır", client=client(), db_name=db,
            persist=True, task_store_root=str(tmp_path / "tasks"))
    assert result.success, result.data
    assert result.data["answer"] == answer
    assert [r["tool"] for r in result.data["direct_tool_calls"]] == ["orders.status_counts"]
    payload = result.data["direct_tool_results"][0]["data"]
    assert payload["total_orders"] == 570 and payload["status_counts"] == dict(expected)
    assert len(requests) == (3 if transient else 2)
    stored = load_agent_task_state(result.data["state"]["session_id"], root=tmp_path / "tasks")
    assert stored.status == "complete" and stored.goal == "570 siparişi sınıflandır"
    assert "last_error" not in stored.active_entities["model_loop"]
    assert stored.conversation_turns[-1].content == answer


def test_exhausted_provider_failure_can_resume_without_repeating_domain_read(classification, tmp_path, monkeypatch):
    db, expected, answer = classification
    replies = [tool_stream(), text_stream("Eksik", terminal=False), text_stream("Eksik", terminal=False)]
    monkeypatch.setattr(cloud_runtime.requests, "post", lambda *a, **kw: replies.pop(0))
    first_client = client()
    with response_stream(lambda event: None):
        failed = model_loop.run_model_loop("570 siparişi sınıflandır", client=first_client, db_name=db,
            persist=True, task_store_root=str(tmp_path / "tasks"))
    assert not failed.success
    state = load_agent_task_state(failed.data["state"]["session_id"], root=tmp_path / "tasks")
    assert state.status == "paused" and len(state.completed_steps) == 1
    assert state.completed_steps[0].result_data["tool_result"]["status_counts"] == dict(expected)
    diagnostic = state.active_entities["model_loop"]["last_error"]
    assert diagnostic["phase"] == "provider" and diagnostic.get("reason")
    monkeypatch.setattr(cloud_runtime.requests, "post", lambda *a, **kw: text_stream(answer))
    with response_stream(lambda event: None):
        completed = model_loop.run_model_loop(state.goal, session_state=state, continuing=True, client=client(),
            db_name=db, persist=True, task_store_root=str(tmp_path / "tasks"))
    assert completed.success and completed.data["answer"] == answer
    assert completed.data["direct_tool_calls"] == []
    loop = completed.data["state"]["active_entities"]["model_loop"]
    assert "last_error" not in loop and loop["failure_history"][-1] == diagnostic
