"""Provider outages preserve the actual work and expose structured status."""
from copy import deepcopy
import json
from types import SimpleNamespace

from sqlmodel import Session, select

from AI.processors import model_loop, observation_artifacts, tools
from AI.processors.session_state import AgentSessionState
from AI.processors.task_store import load_agent_task_state
from AI.runtime.contracts import AgentTool
from AI.runtime.effect_history import approved_effect_receipts
from Feedback.processors.pipeline import Result


class Model:
    runtime_name = "synthetic_provider"
    model_name = "synthetic:free"

    def __init__(self, responses, *, category="quota", quota_scope="free_tier"):
        self.responses = iter(responses)
        self.category, self.quota_scope = category, quota_scope
        self.resource_plan = {"provider_code": "synthetic", "requested_model": self.model_name,
            "capability_profile": {"native_tool_runtime_enabled": True},
            "invocation_outcome_history": []}

    def invoke_tools(self, prompt, *, tools):
        value = next(self.responses)
        self.resource_plan["model_invocation_attempted"] = True
        row = {"contract": "native_tools", "requested_model": self.model_name,
            "actual_model": self.model_name if value is not None else "",
            "response_received": value is not None, "fallback_used": False, "error_reason": ""}
        if value is None:
            reason = "http_429" if self.category == "quota" else "connection_error"
            failure = {"provider_code": "synthetic", "category": self.category, "retryable": True,
                "quota_scope": self.quota_scope, "status_code": 429 if self.category == "quota" else None,
                "safe_message": "Synthetic provider unavailable.", "model_fallback_allowed": False}
            row.update({"error_reason": reason, "error_category": self.category,
                "normalized_error_history": [failure], "quota_scope": self.quota_scope})
            self.resource_plan.update({"invocation_error_reason": reason, "normalized_error_history": [failure]})
        self.resource_plan["invocation_outcome_history"].append(row)
        if value is None:
            raise RuntimeError("private-provider-exception-must-not-be-stored")
        return json.dumps(value) if isinstance(value, dict) else value


def call(operation, **arguments):
    return {"mode": "tool", "tool": operation, "arguments": arguments}


def test_initial_quota_reaches_actual_chat_entrypoint_and_existing_ui_status(tmp_path, monkeypatch):
    from AI.views import chat_tab
    client = Model([None])
    monkeypatch.setattr(chat_tab.ai_actions, "action_get_provider_account", lambda *args: Result.ok("Synthetic", data={
        "record": {"id": 701, "provider_code": "synthetic", "default_model": client.model_name}}))
    monkeypatch.setattr(chat_tab, "build_provider_chat_client", lambda *args: client)
    monkeypatch.setattr(chat_tab, "DB_NAME", str(tmp_path / "unused.sqlite3"))

    result = chat_tab._run_chat_turn_with_runtime("Siparişleri oku", source="cloud",
        runtime_record={"id": 701}, history=[])

    assert not result.success and result.data["provider_unavailable"] is True
    assert result.data["mode"] == "provider_unavailable"
    assert result.data["provider_failure"]["category"] == "quota"
    assert result.data["provider_failure"]["quota_scope"] == "free_tier"
    assert result.data["model_invocation_attempted"] is True
    assert not result.data["model_invoked"] and not result.data["final_model_response_received"]
    assert result.data["direct_tool_calls"] == [] and result.data["state"]["completed_steps"] == []
    status = {}
    chat_tab.AITab._update_agent_state_from_result_data(
        SimpleNamespace(_set_agent_state=lambda **kwargs: status.update(kwargs)), result.data)
    assert status["status"] == "provider_unavailable" and status["tools"] == []
    assert status["detail"] == result.data["answer"]
    assert "private-provider-exception" not in json.dumps(result.data)


def test_transport_failure_after_successful_read_retains_observation_and_saved_failure(tmp_path, monkeypatch):
    read = AgentTool(name="example.count", description="Read a synthetic count.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda: Result.ok("Observed", data={"count": 7}))
    monkeypatch.setattr(tools, "available_tools", lambda: {read.name: read})
    client = Model([call(read.name), None], category="transport", quota_scope="")
    result = model_loop.run_model_loop("Oku", client=client, db_name=str(tmp_path / "unused.sqlite3"),
        persist=True, task_store_root=tmp_path / "tasks")
    before = deepcopy(result.data["direct_tool_results"])
    model_loop.project_runtime_result(result, client)

    assert not result.success and result.data["provider_unavailable"]
    assert result.data["mode"] == "task" and result.data["provider_failure"]["category"] == "transport"
    assert result.data["direct_tool_results"] == before and before[0]["data"]["count"] == 7
    assert result.data["model_response_received"] and not result.data["final_model_response_received"]
    assert result.data["runtime"]["model_response_received"] and result.data["model_invocation_attempted"]
    assert "hiçbir business tool" not in result.data["answer"]
    saved = load_agent_task_state(result.data["state"]["session_id"], root=tmp_path / "tasks")
    assert saved.completed_steps[0].result_data["tool_result"]["count"] == 7
    assert saved.active_entities["model_loop"]["last_error"]["provider_failure"] == result.data["provider_failure"]
    assert "private-provider-exception" not in json.dumps(saved.to_dict())


def test_provider_failure_after_approved_real_write_keeps_execution_and_readback(tmp_path, monkeypatch):
    from Core.utils.model_utils import get_engine
    from Stock.models.models import StockItem
    from Testing.processors.business_agent_fixtures import seed_business_fixture
    database = str(tmp_path / "business.sqlite3")
    seed_business_fixture(database, isolation_root=tmp_path)
    monkeypatch.setattr(observation_artifacts, "OBSERVATION_ARTIFACTS_ROOT", tmp_path / "observations")
    preparing = Model([
        call("operations.discover", query="stock.item_create.prepare", limit=1),
        call("stock.item_create.prepare", sku="PROVIDER-FAILURE-CREATED", name="Synthetic Item"),
        "Stok kartının bilgileri onayına hazır."])
    prepared = model_loop.run_model_loop("Stok kartı hazırla", client=preparing, db_name=database)
    assert prepared.success and prepared.data["approval_required"], prepared.data
    client = Model([None], category="transport", quota_scope="")

    result = model_loop.resume_model_loop_approval(prepared.data["state"],
        action_id=prepared.data["state"]["active_pending_action_id"], planner_client=client,
        db_name=database, persist=True, task_store_root=tmp_path / "tasks",
        audit_path=str(tmp_path / "audit.jsonl"))

    assert not result.success and result.data["provider_unavailable"]
    assert result.data["provider_failure"]["category"] == "transport" and result.data["approval_granted"]
    assert result.data["execute"]["verify"]["verified"] is True
    state = AgentSessionState.from_dict(result.data["state"])
    receipts = approved_effect_receipts(state, model_loop._preview)
    assert len(receipts) == 1 and receipts[0]["success"] and receipts[0]["business_completion_verified"]
    assert not state.pending_actions and len(state.completed_steps) == len(prepared.data["state"]["completed_steps"])
    assert receipts[0]["message"] in result.data["answer"]
    assert "hiçbir business tool" not in result.data["answer"] and "İstek çalıştırılmadı" not in result.data["answer"]
    saved = load_agent_task_state(state.session_id, root=tmp_path / "tasks")
    assert approved_effect_receipts(saved, model_loop._preview) == receipts
    with Session(get_engine(database)) as session:
        created = session.exec(select(StockItem).where(StockItem.sku == "PROVIDER-FAILURE-CREATED")).all()
        assert len(created) == 1


def test_recovered_turn_does_not_inherit_the_previous_quota_flag(tmp_path):
    database = str(tmp_path / "unused.sqlite3")
    failed = model_loop.run_model_loop("Oku", client=Model([None]), db_name=database)
    client = Model(["Bağlantı yeniden çalışıyor."])
    recovered = model_loop.run_model_loop("Yeniden dene", client=client,
        session_state=failed.data["state"], db_name=database)
    model_loop.project_runtime_result(recovered, client)

    assert recovered.success and not recovered.data.get("provider_unavailable")
    assert not recovered.data.get("provider_failure") and not recovered.data.get("runtime_error")
    assert recovered.data["model_response_received"] and recovered.data["final_model_response_received"]
    assert recovered.data["state"]["active_entities"]["model_loop"]["failure_history"][-1]["provider_failure"]
