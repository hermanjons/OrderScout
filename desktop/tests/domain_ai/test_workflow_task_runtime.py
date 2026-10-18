from copy import deepcopy
import json

from AI.processors import tools, workflow_store
from AI.processors.task_runtime import run_agent_task
from AI.processors.turn_service import run_typed_control_turn


def test_model_planned_save_workflow_reaches_exact_current_approval_and_independent_sqlite_readback(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_store, "AI_DOMAIN_ROOT", tmp_path)
    spec = {"schema_version": 1, "name": "Stok incelemesi",
            "instructions": "Güncel stoku oku ve para birimlerini ayrı göster.",
            "objective_template": "Son {{days}} günü incele.", "parameter_schema": {
                "type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 31}},
                "required": ["days"], "additionalProperties": False},
            "source_policy": {"description": "Her çalışmada kaynakları yeniden oku.", "requires_current_sources": True},
            "effect_policy": {"description": "Dosya oluşturmayı o çalışmanın onayına sun.", "requires_current_approval": True}}
    plan = {"steps": [{"id": "save_instructions", "operation_id": "workflows.save.prepare",
                       "arguments": {"spec": deepcopy(spec), "workflow_id": "stock-review"}, "depends_on": [],
                       "objective": "Prepare these exact reusable instructions for saving", "expected_evidence": ["action", "spec_hash"]}]}
    prompts = []
    def planner(prompt):
        prompts.append(prompt)
        if prompt.startswith("OrderScout semantic action verifier"):
            return json.dumps({"verdict": "allow", "objective_aligned": True, "domain_aligned": True,
                               "unwanted_effect": False, "reason": "The user requested saving these reusable instructions",
                               "configuration_schema_reviews": [{"argument_path": "/spec/parameter_schema",
                                   "requested_schema_json": json.dumps(spec["parameter_schema"]),
                                   "requirement_quotes": ["gün sayısını zorunlu tamsayı ve 1 ile 31 arasında parametre yap"]}]})
        return json.dumps(plan)
    started = run_agent_task(
        "Bu talimatları Stok incelemesi olarak kaydet: Güncel stoku oku ve para birimlerini ayrı göster; gün sayısını zorunlu tamsayı ve 1 ile 31 arasında parametre yap.",
        domain="general", planner_client=planner, persist=False, db_name=str(tmp_path / "business.sqlite3"),
        turn_interpretation={"mode": "act", "domain": "general", "intent_kind": "action", "valid": True,
                             "requested_fields": ["action_result"], "requires_clarification": False},
    )
    assert started.success, started.message
    state = started.data["state"]
    assert state["status"] == "pending_approval", [(s["step_id"], s["status"], s["result_message"]) for s in state["completed_steps"]]
    assert not workflow_store.workflow_store_path().exists()
    assert state["completed_steps"][0]["tool_names"] == ["workflows.save.prepare"]
    assert "workflows.save.prepare" in prompts[0]
    pending = state["pending_actions"][0]
    assert pending["action_type"] == "ai.action_save_workflow_spec"
    assert pending["domain"] == "workflows"
    assert pending["arguments"]["payload"]["proposal"]["spec"] == spec
    assert "db_name" not in pending["arguments"]["payload"]
    semantic = state["active_entities"]["semantic_verifications"]
    assert any(row["allowed"] is True and row["phase"] == "prepared_action" for row in semantic)
    assert pending["semantic_verification"]["required"] is True
    assert pending["semantic_verification"]["operation_id"] == "workflows.save.prepare"
    completed = run_typed_control_turn("Onaylıyorum.", mode="approve", session_state=state, client=None,
                                      db_name=str(tmp_path / "business.sqlite3"), allow_approval_execute=True)
    assert completed.success, completed.message
    verify = completed.data["execute"]["verify"]
    assert verify["verified"] and verify["verified_by"] == "workflow_exact_revision_sqlite_readback"
    assert verify["current_head_matches_approved_revision"] is True
    stored = tools.available_tools()["workflows.read"].handler(workflow_id="stock-review")
    assert stored.success and stored.data["spec"] == spec
    assert stored.data["revision_id"] == pending["arguments"]["payload"]["proposal"]["revision_id"]
    assert completed.data["state"]["pending_actions"] == []
