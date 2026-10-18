from __future__ import annotations

import json
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from AI.processors import response_verifier, task_runtime, tools
from AI.processors.turn_evidence import interpretation_receipt
from AI.processors.semantic_contracts import validate_business_read_arguments
from Feedback.processors.pipeline import Result


def decision(**changes):
    payload = {
        "mode": "chat", "domain": "orders", "objective": "İşletmenin mevcut durumunu değerlendir",
        "intent_kind": "conversation", "request_shape": "conversation",
        "information_source": "unspecified", "operation_policy": "allow_new_operations",
        "comparison_policy": "not_requested", "calculation_grouping": "none",
        "status_codes": [], "requested_fields": [],
        "requires_clarification": False, "clarification": "", "missing_input": "none",
    }
    payload.update(changes)
    return payload


def test_new_scope_uses_current_message_without_repeated_prior_objective():
    from AI.processors.session_state import AgentSessionState
    state = AgentSessionState(goal="Old risk objective", active_domain="orders", status="complete")
    state.record_turn(role="user", content="Old risk question", mode="inspect",
        objective="Old risk objective", intent_kind="data_read", requested_fields=["risk"],
        semantic_contract={"entity": "order", "metric": "summary", "metric_population": "fulfillment_risks",
            "period": "all", "projection": ["risk"]})
    before = state.to_dict()
    prompts = []
    message = "Bütün siparişlerimin toplamını ve durum dağılımını göster."
    payload = decision(mode="inspect", intent_kind="data_read", request_shape="focused_analysis",
        objective=message, entity="order", metric="summary", metric_population="all_orders",
        requested_fields=["count", "status"], information_source="local_business_data")
    def planner(prompt):
        prompts.append(prompt)
        return json.dumps(payload)
    result = task_runtime.interpret_agent_turn(message, planner_client=planner, session_state=state)
    assert result.success, result.message
    assert "Old risk objective" not in prompts[0]
    assert "Old risk question" not in prompts[0]
    assert '"metric_population": "fulfillment_risks"' in prompts[0]
    assert prompts[0].endswith(message)
    assert state.to_dict() == before
    assert set(result.data["requested_fields"]) == {"count", "status"}
    assert task_runtime.ORDER_TOTAL_COUNT_METRIC in result.data["semantic_contract"]["metric_requirements"]
    receipt = result.data["turn_contract_provenance"]
    assert receipt["input_sha256"] == hashlib.sha256(message.encode()).hexdigest()
    assert receipt["application_prompt_sha256"] == hashlib.sha256(prompts[0].encode()).hexdigest()
    assert receipt["initial"]["metric_population"] == "all_orders"


@pytest.mark.parametrize("repair_valid", [True, False])
def test_repeated_wrong_population_requires_model_reinterpretation(repair_valid):
    from AI.processors.session_state import AgentSessionState
    state = AgentSessionState(goal="Read risks", active_domain="orders", status="complete")
    state.record_turn(role="user", content="Read risks", mode="inspect", intent_kind="data_read",
        semantic_contract={"entity": "order", "metric_population": "fulfillment_risks"})
    message = "Risklilerle sınırlama; bütün siparişlerin toplamını göster."
    wrong = decision(mode="inspect", intent_kind="data_read", request_shape="focused_analysis",
        objective="Read risks", entity="order", metric="summary", requested_fields=["risk"],
        metric_population="fulfillment_risks")
    good = dict(wrong, objective=message, requested_fields=["count"], metric_population="all_orders")
    calls = []
    def planner(prompt):
        calls.append(prompt)
        if "Check whether this proposed interpretation" in prompt:
            return json.dumps({"aligned": False, "reason_code": "current_scope_not_honored"})
        return json.dumps(good if len(calls) > 1 and repair_valid else wrong)
    result = task_runtime.interpret_agent_turn(message, planner_client=planner, session_state=state)
    assert "CURRENT user message" in calls[1] and message in calls[1]
    assert "current_turn_population_mismatch" in calls[2]
    if repair_valid:
        assert result.success, result.message
        assert len(calls) == 3
        assert result.data["requested_fields"] == ["count"]
        assert result.data["semantic_contract"]["metric_population"] == "all_orders"
    else:
        assert not result.success and not result.data["valid"]
        assert len(calls) == 4


@pytest.mark.parametrize("omit_intent", [True, False])
def test_account_discovery_reviews_inherited_orders_even_when_intent_is_defaulted(omit_intent):
    from AI.processors.session_state import AgentSessionState
    state = AgentSessionState(goal="Evaluate orders", active_domain="orders", status="complete")
    state.record_turn(role="user", content="Evaluate orders", mode="inspect", intent_kind="data_read",
        semantic_contract={"entity": "order", "metric_population": "all_orders"})
    message = "Bu değerlendirme hangi mağazaya ait? Kayıtlı başka mağazalarım da var mı?"
    stale = decision(mode="inspect", intent_kind="data_read", objective="Evaluate orders",
        entity="order", metric="summary", metric_population="all_orders",
        request_shape="broad_analysis", requested_fields=["count", "status", "amount"])
    if omit_intent:
        stale.pop("intent_kind")
    repaired = decision(mode="inspect", intent_kind="data_read", domain="marketplaces",
        objective=message, entity="marketplace_account", metric="list", record_scope="all_matching",
        request_shape="record_list", requested_fields=["count"], information_source="local_business_data")
    prompts = []
    def planner(prompt):
        prompts.append(prompt)
        if "Check whether this proposed interpretation" in prompt:
            return '{"aligned":false,"reason_code":"current_goal_not_honored"}'
        return json.dumps(stale if len(prompts) == 1 else repaired)
    result = task_runtime.interpret_agent_turn(message, planner_client=planner, session_state=state)
    assert result.success, result.message
    assert len(prompts) == 3
    assert message in prompts[1] and '"domain": "orders"' in prompts[1]
    assert "current_turn_population_mismatch" in prompts[2]
    assert result.data["domain"] == "marketplaces"
    assert result.data["semantic_contract"]["entity"] == "marketplace_account"


def test_genuine_risk_continuation_keeps_population_after_review():
    from AI.processors.turn_evidence import review_repeated_population
    calls = []
    def reviewer(prompt):
        calls.append(prompt)
        return '{"aligned":true,"reason_code":"aligned"}'
    checked = review_repeated_population("Bunların neden riskli olduğunu açıkla.",
        {"intent_kind": "data_read", "requires_clarification": False,
         "metric_population": "fulfillment_risks", "requested_fields": ["risk"]},
        {"metric_population": "fulfillment_risks"}, reviewer)
    assert checked == {"required": True, "aligned": True, "reason_code": "aligned"}
    assert len(calls) == 1


def test_unread_data_clarification_is_repaired_by_same_model_before_any_answer():
    initial = decision(
        requires_clarification=True,
        clarification="Henüz sipariş verileriniz yok. Hangi dönemi istiyorsunuz?",
    )
    repaired = decision(
        mode="inspect", intent_kind="data_read", request_shape="broad_analysis",
        information_source="local_business_data", requested_fields=["count", "status", "amount"],
        entity="order", metric="summary", record_scope="all_matching", period="unspecified",
        freshness="current_local",
    )
    prompts = []

    def planner(prompt):
        prompts.append(prompt)
        return json.dumps(initial if len(prompts) == 1 else repaired)

    result = task_runtime.interpret_agent_turn("siparişlerim nasıl sence iyi mi", planner_client=planner)
    assert result.success, result.message
    assert len(prompts) == 2
    assert "clarification_requires_typed_user_decision" in prompts[1]
    assert result.data["mode"] == "inspect"
    assert result.data["requires_clarification"] is False
    assert result.data["turn_interpretation_repair"]["initial_decision"]["mode"] == "chat"
    assert result.data["turn_contract_provenance"]["accepted"]["mode"] == "inspect"


@pytest.mark.parametrize("domain", ["orders", "marketplaces", "stock", "finance", "listing", "logistics"])
def test_business_evidence_source_cannot_be_locked_in_conversation(domain):
    payload = decision(domain=domain, information_source="local_business_data")
    result = task_runtime.interpret_agent_turn(
        "İşletmemin bu bölümündeki mevcut durumu değerlendir", planner_client=lambda _: json.dumps(payload)
    )
    assert result.success, result.message
    assert result.data["mode"] == "inspect"
    assert result.data["intent_kind"] == "data_read"
    assert result.data["turn_contract_provenance"]["initial"]["mode"] == "chat"


def test_repeated_invalid_clarification_fails_without_publishing_absence_claim():
    payload = decision(requires_clarification=True, clarification="Kayıtlı hiçbir mağazanız yok.")
    result = task_runtime.interpret_agent_turn(
        "Bağlı hesaplarımı değerlendir", planner_client=lambda _: json.dumps(payload), _allow_safe_recovery=False
    )
    assert not result.success
    assert result.data["valid"] is False
    assert "Kayıtlı hiçbir" not in result.message
    assert result.data["turn_interpretation_repair"]["attempt_count"] == 1


def test_legitimate_clarification_asks_only_typed_decision():
    payload = decision(
        domain="general", requires_clarification=True, missing_input="goal",
        clarification="Veritabanınız boş, ne yapalım?",
    )
    result = task_runtime.interpret_agent_turn("Bir şey yapalım", planner_client=lambda _: json.dumps(payload))
    assert result.success, result.message
    assert result.data["requires_clarification"] is True
    assert result.data["clarification"] == "Neyi incelememi veya hangi işlemi yapmamı istiyorsun?"


@pytest.mark.parametrize("domain,entity", [("marketplaces", "marketplace_account"), ("stock", "stock_item")])
def test_identified_read_goal_is_repaired_instead_of_asking_user_to_repeat(domain, entity):
    bad = decision(mode="inspect", intent_kind="data_read", request_shape="record_list",
        requested_fields=["count"], information_source="local_business_data",
        requires_clarification=True, missing_input="goal")
    repaired = dict(bad, domain=domain, entity=entity, metric="list", record_scope="all_matching",
        requires_clarification=False, missing_input="none")
    prompts = []
    def planner(prompt):
        prompts.append(prompt)
        return json.dumps(bad if len(prompts) == 1 else repaired)
    result = task_runtime.interpret_agent_turn("Bu bölümde kayıtlı başka kayıt var mı?", planner_client=planner)
    assert result.success, result.message
    assert len(prompts) == 2 and "read_goal_already_identified" in prompts[1]
    assert result.data["domain"] == domain
    assert not result.data["requires_clarification"]


@pytest.mark.parametrize("mode", ["clarify", "clarification"])
def test_clarification_does_not_reuse_previous_business_projection_receipt(mode):
    from AI.processors.session_state import AgentSessionState, AgentTaskStep
    state = AgentSessionState(goal="Previous read", active_domain="orders", status="complete")
    state.active_entities.update({
        "response_synthesis": {"final_source": "verified_model_candidate", "final_projection_verified": True},
        "task_plan": {"source": "llm_direct", "planner_invoked": True,
            "deterministic_business_steps_inserted": False, "llm_step_ids": ["read"],
            "step_specs": [{"id": "read", "operation_id": "orders.count"}]},
    })
    state.completed_steps = [AgentTaskStep(index=1, prompt="Previous read", objective="Previous read", status="completed", tool_names=["orders.count"])]
    assert task_runtime.model_authored_projection_acceptance(state, final_model_response_received=True)["verified_business_projection"]
    next_state = task_runtime.record_conversation_exchange(session_state=state, user_message="Bir şey yapalım",
        assistant_message="Neyi incelememi istiyorsun?", mode=mode, objective="Clarify")
    assert next_state.completed_steps == state.completed_steps
    assert state.active_entities["response_synthesis"]["final_projection_verified"]
    assert not next_state.active_entities["response_synthesis"]["final_projection_verified"]
    assert not task_runtime.model_authored_projection_acceptance(next_state, final_model_response_received=True)["verified_business_projection"]


def test_ui_never_renders_raw_model_clarification_even_from_old_interpretation():
    from AI.views.chat_tab import _run_chat_turn_with_runtime

    payload = decision(valid=True, requires_clarification=True, missing_input="target", clarification="Hiç sipariş yok.")
    with patch("AI.views.chat_tab.build_local_planner_client", return_value=lambda _: ""), patch(
        "AI.views.chat_tab.interpret_agent_turn", return_value=Result.ok("interpreted", data=payload)
    ), patch("AI.views.chat_tab.run_agent_task") as task, patch("AI.views.chat_tab.run_agent_turn") as legacy:
        result = _run_chat_turn_with_runtime("Bunu değiştir", source="local", runtime_record={}, history=[])
    assert result.success
    assert result.data["answer"] == "Hangi kayıt veya kayıtlar üzerinde işlem yapmamı istiyorsun?"
    task.assert_not_called()
    legacy.assert_not_called()


def test_record_list_grounding_does_not_require_numeric_count_spelling():
    from AI.processors.session_state import AgentSessionState, AgentTaskStep

    state = AgentSessionState(
        goal="Kayıtlı mağazalarımı göster",
        active_domain="marketplaces",
        status="complete",
        active_entities={
            "turn_interpretation": {
                "request_shape": "record_list",
                "requested_fields": ["count", "store", "scope"],
                "semantic_contract": {
                    "entity": "marketplace_account",
                    "projection": ["count", "store", "scope"],
                },
            }
        },
        completed_steps=[
            AgentTaskStep(
                index=1,
                step_id="account_lookup",
                prompt="Kayıtlı hesapları oku",
                status="completed",
                verification_status="observed",
                tool_names=["marketplaces.account_lookup"],
                result_data={"tool_result": {"count": 1, "accounts": [{"company": "Demo"}]}},
            )
        ],
    )
    answer = "Kayıtlı tek mağaza Demo."
    assert task_runtime._generated_task_answer_is_grounded(answer, state)

    state.active_entities["turn_interpretation"]["request_shape"] = "scalar"
    assert not task_runtime._generated_task_answer_is_grounded(answer, state)
    assert task_runtime._generated_task_answer_is_grounded("Kayıtlı 1 mağaza Demo.", state)


def test_account_lookup_store_evidence_uses_canonical_scope_name():
    from AI.processors.session_state import AgentTaskStep, Observation

    step = AgentTaskStep(
        index=1,
        step_id="account_lookup",
        prompt="Kayıtlı mağazaları göster",
        expected_evidence=["count", "store", "scope"],
        result_data={
            "tool_result": {
                "count": 1,
                "accounts": [{"company": "Demo"}],
                "account_scopes": [{"store_name": "Demo", "platform": "TRENDYOL"}],
            }
        },
    )
    observation = Observation.create(
        domain="marketplaces",
        operation_name="marketplaces.account_lookup",
        success=True,
        source="local_db",
        facts={"scope": "all_registered_accounts"},
    )

    status = task_runtime._expected_evidence_status(step, observation)

    assert all(status[name]["present"] for name in ("count", "store", "scope"))
    assert status["store"]["source"] == "step_result"


def test_complete_account_lookup_answers_other_store_question_from_full_population():
    from AI.processors.session_state import AgentSessionState, AgentTaskStep

    state = AgentSessionState(
        goal="Bu değerlendirme hangi mağazaya ait? Kayıtlı başka mağazam var mı?",
        active_domain="marketplaces",
        status="complete",
        active_entities={"turn_interpretation": {
            "request_shape": "record_list",
            "requested_fields": ["count", "store", "scope"],
            "semantic_contract": {"entity": "marketplace_account", "metric": "list"},
        }},
        completed_steps=[AgentTaskStep(
            index=1, step_id="lookup", prompt="Mağazaları oku",
            status="completed", verification_status="observed",
            tool_names=["marketplaces.account_lookup"],
            result_data={"tool_result": {
                "count": 1, "total_matching": 1, "truncated": False,
                "accounts": [{"company": "Demo"}],
                "account_scopes": [{"store_name": "Demo", "platform": "TRENDYOL", "environment": "stage"}],
                "read_evidence": {"source": "local_database", "scope": "all_accounts", "status": "nonempty"},
            }},
        )],
    )
    projection = response_verifier.response_evidence_projection(state)
    assert projection["registered_account_population"]["complete"] is True
    fallback = response_verifier.project_fallback_response(state, "")
    assert "Kayıtlı başka mağaza yok." in fallback
    assert response_verifier.verify_response_projection(fallback, state).success

    uncertain = (
        "1 mağaza bulundu: Demo (TRENDYOL / stage). "
        "Başka mağazalar olup olmadığı bu veriyle doğrulanamaz."
    )
    checked = response_verifier.verify_response_projection(uncertain, state)
    assert not checked.success
    assert "complete_account_population_misrepresented_as_unknown" in (
        checked.data["response_verification"]["reason_codes"]
    )

    result = state.completed_steps[0].result_data["tool_result"]
    result["truncated"] = True
    result["total_matching"] = 2
    partial = response_verifier.project_fallback_response(state, "")
    assert "Kayıtlı başka mağaza yok." not in partial
    assert response_verifier.response_evidence_projection(state)["registered_account_population"]["complete"] is False


def test_interpretation_receipt_has_no_free_text_or_private_values():
    payload = decision(domain="private-secret", objective="private-customer", clarification="private-account")
    receipt = interpretation_receipt(payload, response=json.dumps(payload))
    assert "private" not in json.dumps(receipt)
    assert receipt["domain"] == "missing_or_invalid"
    assert len(receipt["response_sha256"]) == 64


def test_account_discovery_distinguishes_empty_failed_and_truncated_without_credentials():
    with patch.object(tools.account_repo, "list_accounts", return_value=Result.ok("read", data={"records": []})):
        empty = tools.marketplaces_account_lookup()
    assert empty.success and empty.data["read_evidence"]["status"] == "empty"
    with patch.object(tools.account_repo, "list_accounts", return_value=Result.fail("read denied")):
        failed = tools.marketplaces_account_lookup()
    assert not failed.success
    assert not (failed.data or {}).get("read_evidence")
    rows = [SimpleNamespace(comp_name="Demo", platform="TRENDYOL", account_id=str(i), integration_code="private-secret") for i in range(2)]
    with patch.object(tools.account_repo, "list_accounts", return_value=Result.ok("read", data={"records": rows})):
        found = tools.marketplaces_account_lookup(limit=1)
    assert found.success and found.data["total_matching"] == 2
    assert found.data["count"] == 1 and found.data["truncated"] is True
    assert found.data["read_evidence"]["status"] == "nonempty"
    assert "private-secret" not in json.dumps(found.data)
    assert "integration_code" not in found.data["accounts"][0]
    from AI.processors.session_state import AgentSessionState, AgentTaskStep

    state = AgentSessionState(goal="Mağazalarım", active_domain="marketplaces")
    observation = task_runtime._record_typed_step_observation(
        state,
        step=AgentTaskStep(index=1, step_id="lookup", prompt=state.goal, operation_domain="marketplaces"),
        data={
            "tool_call": {"tool": "marketplaces.account_lookup", "arguments": {}},
            "tool_result": found.data,
        },
        result=found,
    )
    assert observation is not None
    assert observation.facts["population"] == "partial_registered_accounts"
    assert observation.facts["truncated"] is True
    assert observation.facts["total_matching"] == 2


def test_registered_store_population_is_reinterpreted_without_order_context_narrowing():
    bad = decision(
        mode="inspect", intent_kind="data_read", request_shape="record_list",
        information_source="local_business_data", entity="order", metric="list",
        record_scope="all_matching", requested_fields=["store", "scope"],
    )
    corrected = dict(bad, domain="marketplaces", entity="marketplace_account", population_basis="entity_records")
    calls = []

    def planner(prompt):
        calls.append(prompt)
        return json.dumps(bad if len(calls) == 1 else corrected)

    result = task_runtime.interpret_agent_turn("hangi mağazarlar var", planner_client=planner)
    assert result.success, result.message
    assert len(calls) == 2 and "related_entity_population_ambiguous" in calls[1]
    assert result.data["domain"] == "marketplaces"
    assert result.data["semantic_contract"]["entity"] == "marketplace_account"


def test_explicit_stores_represented_in_orders_keep_the_relation_population():
    payload = decision(
        mode="inspect", intent_kind="data_read", request_shape="record_list",
        information_source="local_business_data", entity="order", metric="list",
        record_scope="all_matching", requested_fields=["store", "scope"], population_basis="related_records",
    )
    result = task_runtime.interpret_agent_turn("Siparişlerin geldiği mağazaları göster", planner_client=lambda _: json.dumps(payload))
    assert result.success, result.message
    assert result.data["domain"] == "orders"
    assert result.data["population_basis"] == "related_records"


def test_account_population_requires_account_repository_operation():
    contract = {"entity": "marketplace_account", "metric": "list", "record_scope": "all_matching"}
    for operation in ("orders.query", "marketplaces.catalog", "marketplaces.active_count", "marketplaces.summary"):
        assert validate_business_read_arguments(contract, operation, {}) == ("registered_account_population_source_mismatch",)
    assert validate_business_read_arguments(contract, "marketplaces.account_lookup", {}) == ()


def test_business_read_provenance_question_does_not_become_policy_explanation():
    message = "Kayıtlı mağazalarımın tamamını listele. Başka mağazam var mı? Hangi veri kaynağından kontrol ettin?"
    payload = decision(
        mode="inspect", domain="marketplaces", intent_kind="data_read",
        request_shape="record_list", objective=message,
        entity="marketplace_account", metric="list", record_scope="all_matching",
        requested_fields=["count", "store", "scope"],
        direct_output_fields=["count", "store"],
        explanation_topics=["data_source"],
        information_source="local_business_data",
    )
    prompts = []
    def planner(prompt):
        prompts.append(prompt)
        return json.dumps(payload, ensure_ascii=False)
    result = task_runtime.interpret_agent_turn(message, planner_client=planner)
    assert result.success, result.message
    assert len(prompts) == 1
    assert result.data["intent_kind"] == "data_read"
    assert result.data["explanation_topics"] == []
    assert result.data["semantic_contract"]["entity"] == "marketplace_account"
    assert "business_provenance_topic_kept_as_read_evidence" in result.data["semantic_corrections"]


def test_explicit_business_read_can_plan_across_orders_stock_and_finance():
    goal = "Siparişlerimle stok durumunu ve nakit akışını birlikte incele."
    interpretation = {"mode": "inspect", "intent_kind": "data_read"}
    domains = task_runtime._explicit_business_read_domains("stock", goal, interpretation)
    assert domains == {"orders", "stock", "finance"}
    candidates = task_runtime._planner_operation_candidates(
        "stock", goal, read_domains=domains, limit=24,
    )
    for operation in ("orders.summary", "stock.inventory_overview", "finance.cashflow_summary"):
        assert operation in candidates
    specs = [
        {"id": operation, "operation_id": operation, "arguments": {},
         "depends_on": [], "objective": goal, "expected_evidence": []}
        for operation in ("orders.summary", "stock.inventory_overview", "finance.cashflow_summary")
    ]
    accepted, rejected = task_runtime._validate_direct_plan_specs(
        "stock", specs, goal, allowed_operations=candidates, max_steps=8,
        read_domains=domains,
    )
    assert not rejected
    assert {row["operation_domain"] for row in accepted} == domains
    accepted_without_scope, rejected_without_scope = task_runtime._validate_direct_plan_specs(
        "stock", specs, goal, allowed_operations=candidates, max_steps=8,
    )
    assert {row["operation_domain"] for row in accepted_without_scope} == {"stock"}
    assert set(rejected_without_scope) == {"orders.summary", "finance.cashflow_summary"}
    assert task_runtime._explicit_business_read_domains(
        "stock", goal, {"mode": "act", "intent_kind": "action"},
    ) == {"stock"}
    order_candidates = task_runtime._planner_operation_candidates(
        "orders", goal, read_domains=domains, limit=24,
    )
    assert "stock.inventory_overview" in order_candidates
    contextual_goal = (
        "Bu mağazanın siparişlerini stok ve finansla birlikte değerlendir; "
        "stokta bağlı tutar, satış hızı ve nakit baskısı için kapsamlar eşleşmiyorsa belirt."
    )
    contextual_candidates = task_runtime._planner_operation_candidates(
        "orders", contextual_goal, read_domains=domains, limit=24,
    )
    assert "stock.inventory_overview" in contextual_candidates
    assert "stock.manual_write.prepare" not in contextual_candidates
    assert task_runtime._missing_business_read_domains(
        [row for row in accepted if row["operation_domain"] != "stock"], domains,
    ) == ["cross_business_read_domain_missing:stock"]


def test_failed_step_replan_keeps_authorized_cross_business_read_scope():
    from AI.processors.session_state import AgentSessionState, AgentTaskStep
    goal = "Siparişlerimle stok durumunu ve nakit akışını birlikte incele."
    state = AgentSessionState(goal=goal, active_domain="orders", status="running")
    state.active_entities["business_read_domains"] = ["orders", "stock", "finance"]
    state.active_entities["turn_interpretation"] = {
        "mode": "inspect", "intent_kind": "data_read", "requested_fields": [],
        "semantic_contract": {},
    }
    failed = AgentTaskStep(
        index=1, prompt=goal, step_id="failed_read", operation_domain="orders",
        status="failed", result_message="geçici okuma hatası",
    )
    state.completed_steps.append(failed)
    candidate = {
        "id": "stock_read_new", "operation_id": "stock.inventory_overview",
        "arguments": {}, "depends_on": [], "objective": goal,
        "expected_evidence": [],
    }
    applied = task_runtime._replan_after_failed_step(
        state, failed, planner_client=lambda _prompt: json.dumps({"steps": [candidate]}),
        max_replans=2, max_steps=8,
    )
    assert applied
    assert state.active_entities["replans"][-1]["accepted_step_ids"] == ["stock_read_new"]
    assert not state.active_entities["replans"][-1]["rejected_step_ids"]


def test_cross_business_final_cannot_omit_observed_stock_value():
    from AI.processors.session_state import AgentSessionState, AgentTaskStep
    state = AgentSessionState(goal="Sipariş, stok ve nakit durumunu incele", active_domain="orders", status="complete")
    state.active_entities["business_read_domains"] = ["orders", "stock", "finance"]
    state.active_entities["turn_interpretation"] = {
        "mode": "inspect", "intent_kind": "data_read", "requested_fields": [],
        "semantic_contract": {},
    }
    for index, (operation, domain, data) in enumerate((
        ("orders.summary", "orders", {"total_orders": 10, "period": "all"}),
        ("stock.inventory_overview", "stock", {"active_items": 2, "total_balance": 5,
            "stock_value_by_currency": [{"amount": 125.0, "currency": "TRY"}],
            "stock_valuation_complete": True, "valuation_missing_items": 0}),
        ("finance.cashflow_summary", "finance", {"period": "all", "currency_totals": [
            {"currency": "TRY", "combined_net": 0.0}], "transaction_type_counts": {}}),
    ), start=1):
        state.completed_steps.append(AgentTaskStep(
            index=index, prompt=state.goal, step_id=f"step_{index}", operation_domain=domain,
            status="completed", tool_names=[operation],
            result_data={"tool_result": data, "answer": "read"},
        ))
    projection = response_verifier.response_evidence_projection(state)
    assert projection["cross_business_read"]["stock"]["stock_value_by_currency"] == [
        {"amount": 125.0, "currency": "TRY"}
    ]
    assert "125.00 TRY" in task_runtime._cross_business_safe_summary(projection)
    rejected = response_verifier.verify_response_projection(
        "10 sipariş var; stok değeri verisi yok. Nakit baskısını belirleyemem.", state,
    )
    assert not rejected.success
    codes = (rejected.data or {}).get("response_verification", {}).get("reason_codes") or []
    assert "cross_stock_value_omitted" in codes
    state.completed_steps = [step for step in state.completed_steps if step.operation_domain != "stock"]
    missing_read = response_verifier.verify_response_projection(
        "10 sipariş var; finans hareketi 0 TRY. Stok verisi yok.", state,
    )
    assert not missing_read.success
    missing_codes = (missing_read.data or {}).get("response_verification", {}).get("reason_codes") or []
    assert "cross_business_read_domain_unobserved:stock" in missing_codes


def test_cross_business_amounts_must_keep_their_currencies():
    from AI.processors.session_state import AgentSessionState, AgentTaskStep
    state = AgentSessionState(goal="Sipariş, stok ve finansı incele", active_domain="orders", status="complete")
    state.active_entities["business_read_domains"] = ["orders", "stock", "finance"]
    state.active_entities["turn_interpretation"] = {
        "mode": "inspect", "intent_kind": "data_read", "requested_fields": [],
        "semantic_contract": {},
    }
    for index, (operation, domain, data) in enumerate((
        ("orders.summary", "orders", {"total_orders": 10, "period": "all"}),
        ("stock.inventory_overview", "stock", {"active_items": 1,
            "stock_value_by_currency": [{"amount": 125, "currency": "TRY"}],
            "stock_valuation_complete": True, "valuation_missing_items": 0}),
        ("finance.cashflow_summary", "finance", {"period": "all", "currency_totals": [
            {"currency": "USD", "combined_net": 50}], "transaction_type_counts": {}}),
    ), start=1):
        state.completed_steps.append(AgentTaskStep(
            index=index, prompt=state.goal, step_id=f"step_{index}", operation_domain=domain,
            status="completed", tool_names=[operation],
            result_data={"tool_result": data, "answer": "read"},
        ))
    correct = response_verifier.verify_response_projection(
        "10 sipariş var. Stok değeri 125 TRY. Finans hareketi 50 USD.", state,
    )
    assert correct.success, (correct.data or {}).get("response_verification")
    swapped = response_verifier.verify_response_projection(
        "10 sipariş var. Stok değeri 125 USD. Finans hareketi 50 TRY.", state,
    )
    assert not swapped.success
    codes = (swapped.data or {}).get("response_verification", {}).get("reason_codes") or []
    assert "cross_stock_value_currency_pair_missing" in codes
    assert "cross_finance_amount_currency_mismatch" in codes


def test_finance_currency_totals_supply_currency_evidence():
    from AI.processors.session_state import AgentSessionState, AgentTaskStep
    state = AgentSessionState(goal="Nakit hareketlerinin dövizlerini göster", active_domain="finance", status="complete")
    state.active_entities["turn_interpretation"] = {
        "mode": "inspect", "intent_kind": "data_read", "requested_fields": ["currency"],
        "semantic_contract": {},
    }
    state.completed_steps.append(AgentTaskStep(
        index=1, prompt=state.goal, step_id="finance_read", operation_domain="finance",
        status="completed", tool_names=["finance.cashflow_summary"],
        result_data={"tool_result": {"currency": None, "currency_totals": [
            {"currency": "TRY", "combined_net": 100},
            {"currency": "USD", "combined_net": 10},
        ]}, "answer": "read"},
    ))
    assert response_verifier._currency_values(state) == ["TRY", "USD"]
    verified = response_verifier.verify_response_projection(
        "Nakit hareketleri 100 TRY ve 10 USD.", state,
    )
    assert verified.success, (verified.data or {}).get("response_verification")
    swapped = response_verifier.verify_response_projection(
        "Nakit hareketleri 100 USD ve 10 TRY.", state,
    )
    assert not swapped.success
    assert "finance_amount_currency_mismatch" in (
        (swapped.data or {}).get("response_verification", {}).get("reason_codes") or []
    )


def test_pending_work_mention_is_not_a_global_no_pending_claim():
    from AI.processors.session_state import AgentSessionState
    state = AgentSessionState(goal="Siparişleri değerlendir", active_domain="orders")
    assert response_verifier.unsupported_operational_clearance_reason_codes(
        "Picking durumundaki bekleyen işleri ve sipariş yaşını incele.", state,
    ) == []
    assert "unsupported_global_pending_clearance" in (
        response_verifier.unsupported_operational_clearance_reason_codes(
            "Kritik bekleyen iş görünmüyor.", state,
        )
    )
    assert response_verifier.unsupported_operational_clearance_reason_codes(
        "İade nedenlerine dair veri yok; risk oranını yorumlayamam.", state,
    ) == []
    assert "unsupported_return_clearance" in (
        response_verifier.unsupported_operational_clearance_reason_codes(
            "İade kaydı görünmüyor.", state,
        )
    )
    assert "unsupported_fulfillment_risk_clearance" in (
        response_verifier.unsupported_operational_clearance_reason_codes(
            "Fulfillment risk kaydı yok.", state,
        )
    )


def test_account_lookup_returns_accounts_without_reading_orders_and_carries_environment():
    from AI.processors.session_state import AgentSessionState, AgentTaskStep

    account = SimpleNamespace(pk=7, comp_name="Henüz siparişi olmayan mağaza", platform="TRENDYOL", account_id="test", extra_config={"environment": "stage"})
    with patch.object(tools.account_repo, "list_accounts", return_value=Result.ok("read", data={"records": [account]})), patch.object(
        tools.orders_repo, "query_orders", side_effect=AssertionError("Store discovery must not depend on orders")
    ) as order_read:
        result = tools.marketplaces_account_lookup()
    assert result.success
    assert result.data["count"] == 1
    assert result.data["account_scopes"][0]["environment"] == "stage"
    assert result.data["account_scopes"][0]["store_name"] == account.comp_name
    order_read.assert_not_called()
    state = AgentSessionState(goal="Kayıtlı mağazalarım", active_domain="marketplaces")
    observation = task_runtime._record_typed_step_observation(
        state,
        step=AgentTaskStep(
            index=1, step_id="account_lookup", prompt=state.goal,
            operation_domain="marketplaces", status="completed",
        ),
        data={
            "tool_call": {"tool": "marketplaces.account_lookup", "arguments": {}},
            "tool_result": result.data,
        },
        result=result,
    )
    assert observation is not None
    assert observation.facts["population"] == "all_registered_accounts"
    assert observation.facts["truncated"] is False
    assert state.active_scopes == {}


def test_aggregate_read_scope_survives_as_typed_followup_context():
    from AI.processors.session_state import AgentSessionState, AgentTaskStep

    state = AgentSessionState(goal="Siparişlerimi değerlendir", active_domain="orders")
    step = AgentTaskStep(
        index=1,
        step_id="summary",
        prompt=state.goal,
        operation_domain="orders",
        tool_names=["orders.summary"],
        status="completed",
    )
    data = {
        "tool_call": {"tool": "orders.summary", "arguments": {}},
        "tool_result": {
            "truncated": True,  # A row projection limit is not account coverage.
            "account_scopes": [{
                "api_account_id": 7,
                "account_id": "2738",
                "store_name": "Stage QA",
                "platform": "TRENDYOL",
                "environment": "stage",
                "integration_code": "private-secret",
            }],
        },
    }
    observation = task_runtime._record_typed_step_observation(
        state, step=step, data=data, result=Result.ok("Okundu")
    )
    assert observation is not None
    assert observation.scope_id == ""
    assert state.active_scopes == {}
    assert observation.facts["account_scopes"][0]["store_name"] == "Stage QA"
    assert observation.facts["population"] == "accounts_in_read_result"
    assert observation.facts["truncated"] is False
    assert "private-secret" not in json.dumps(state.to_dict())

    followup = task_runtime._fresh_task_state_from_conversation(
        goal="Bu değerlendirme hangi mağazaya ait?",
        domain="marketplaces",
        session_state=state,
    )
    assert followup.active_scopes == {}
    references = task_runtime._typed_turn_prompt_context(followup, references_only=True)
    assert references["active_scope"] == {}
    assert references["recent_read_scopes"][0]["account_scopes"][0]["store_name"] == "Stage QA"
    assert references["recent_read_scopes"][0]["source"] == "orders.summary"
    assert references["recent_read_scopes"][0]["population"] == "accounts_in_read_result"
    planner_context = task_runtime._planner_typed_context(followup)
    assert planner_context[0]["source_tool"] == "orders.summary"
    assert planner_context[0]["account_scopes"][0]["environment"] == "stage"


@pytest.mark.parametrize("repair_valid", [True, False])
def test_rejected_account_plan_is_repaired_or_stopped_without_legacy_template(repair_valid):
    interpretation = decision(
        domain="marketplaces", mode="inspect", intent_kind="data_read", request_shape="record_list",
        requested_fields=["store", "scope"], semantic_contract={
            "entity": "marketplace_account", "metric": "list", "record_scope": "all_matching",
            "projection": ["store", "scope"],
        },
    )
    calls = []

    def planner(prompt):
        calls.append(prompt)
        operation = "marketplaces.account_lookup" if repair_valid and len(calls) > 1 else "marketplaces.summary"
        return json.dumps({"steps": [{"id": "accounts", "operation_id": operation, "arguments_json": "{}", "depends_on": [], "objective": "Kayıtlı mağazaları göster", "expected_evidence": ["accounts"]}]})

    ids, meta = task_runtime._domain_task_plan(
        "marketplaces", "hangi mağazalar var", planner_client=planner, max_steps=3, turn_interpretation=interpretation
    )
    assert len(calls) == 2 and calls[1].startswith("Domain read plan contract repair")
    assert meta["domain_plan_repair"]["applied"] is repair_valid, meta
    if repair_valid:
        assert ids == ["accounts"]
        assert meta["step_specs"][0]["operation_id"] == "marketplaces.account_lookup"
    else:
        assert ids == [] and meta["source"] == "model_plan_invalid"
        assert meta["requires_clarification"] is True
        assert "marketplaces.summary" not in meta["step_ids"]
