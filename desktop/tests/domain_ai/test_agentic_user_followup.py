"""User-reported correction/cancel/failure and evidence boundaries over native tools."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from AI.processors import model_loop, task_runtime, tools, observation_artifacts
from AI.processors.session_state import AgentSessionState
from AI.processors.task_store import load_agent_task_state
from Feedback.processors.pipeline import Result
from Core.utils.model_utils import get_engine
from Testing.processors.business_agent_fixtures import seed_business_fixture


class Model:
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.prompts = []
        self.resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
    def invoke_tools(self, prompt, *, tools):
        self.prompts.append(prompt)
        value = next(self.decisions)
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    def __call__(self, *a, **k):
        pytest.fail("The native model should own this turn")


def call(operation, **arguments):
    return {"mode": "tool", "tool": operation, "arguments": arguments}


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(observation_artifacts, "OBSERVATION_ARTIFACTS_ROOT", tmp_path / "observations")
    path = str(tmp_path / "business.sqlite3")
    seed_business_fixture(path, isolation_root=tmp_path)
    return path


def prepare_card(database, **options):
    return model_loop.run_model_loop("Yeni stok kartı hazırla", client=Model([
        call("stock.item_create.prepare", **{"sku": "FOLLOWUP-NEW", "name": "Yeni Ürün"}), "Onayını bekliyorum."]),
        db_name=database, **options)


def test_native_profit_scalar_order_count_does_not_crash_observation(database):
    result = model_loop.run_model_loop("Elimizdeki verilerin kârını incele", client=Model([
        call("finance.profit_estimate", period="all"), "Maliyetler eksik olduğu için toplam kâr doğrulanamıyor."]), db_name=database)
    assert result.success, result.data
    step = result.data["state"]["completed_steps"][0]
    assert type(step["result_data"]["tool_result"]["orders"]) is int
    assert step["observation_ids"]
    assert not result.data["state"]["active_entities"]["model_loop"].get("last_error")


def test_scalar_return_count_is_not_a_record_selection():
    from AI.processors.session_state import AgentTaskStep
    state = AgentSessionState(goal="özet", active_domain="general")
    step = AgentTaskStep(index=1, prompt="summary", step_id="call_1", operation_domain="orders")
    observed = task_runtime._record_typed_step_observation(state, step=step, result=Result.ok("ok"), data={
        "tool_call": {"tool": "returns.summary"}, "tool_result": {"orders": 6, "returns": 2, "count": 2}})
    assert observed is not None and not state.active_selection("orders")


def test_cancel_revokes_current_card_and_old_id_cannot_execute(database, tmp_path, monkeypatch):
    prepared = prepare_card(database)
    old_id = prepared.data["state"]["active_pending_action_id"]
    cancelled = model_loop.run_model_loop("Yapma, iptal et ve kayıtlı veriye bak", session_state=prepared.data["state"],
        client=Model([call("approvals.cancel", action_id=old_id, reason="user_withdrew_sync"),
                      call("orders.data_freshness"), "Önceki işlemi iptal ettim, kayıtlı veriye baktım."]),
        db_name=database, persist=True, task_store_root=tmp_path / "tasks")
    assert cancelled.success and not cancelled.data["approval_required"]
    state = cancelled.data["state"]
    assert not state["active_pending_action_id"] and not state["pending_actions"]
    assert state["action_history"][-1]["phase"] == "cancel"
    stored = load_agent_task_state(state["session_id"], root=tmp_path / "tasks")
    def unexpected(*a, **k):
        pytest.fail("Cancelled card must never reach execution")
    monkeypatch.setattr("AI.processors.operation_runtime.execute_approved_operation", unexpected)
    stale = task_runtime.resume_agent_task_with_approval(stored.to_dict(), action_id=old_id, db_name=database, persist=False)
    assert not stale.success and stale.data["stale_approval"]


def test_wrong_cancel_identity_preserves_exact_current_card(database):
    prepared = prepare_card(database)
    result = model_loop.run_model_loop("İptal et", session_state=prepared.data["state"],
        client=Model([call("approvals.cancel", action_id="stale-id"), "Gönderilen iptal kimliği güncel işlemle eşleşmedi."]), db_name=database)
    assert result.success and result.data["approval_required"]
    assert not result.data["direct_tool_results"][0]["success"]
    assert result.data["state"]["pending_actions"] == prepared.data["state"]["pending_actions"]


def test_cancel_is_available_under_existing_sources_only(database):
    from AI.processors.source_policy import EXISTING_ONLY
    prepared = prepare_card(database)
    result = model_loop.run_model_loop("Yeni kaynak kullanmadan iptal et", session_state=prepared.data["state"],
        runtime_context={"source_policy": EXISTING_ONLY}, db_name=database,
        client=Model([call("approvals.cancel", action_id=prepared.data["state"]["active_pending_action_id"]), "İptal edildi."]))
    assert result.success and not result.data["approval_required"]


def test_native_execute_failure_is_explained_without_prepare_approval_loop(database, tmp_path):
    from Stock.processors.pipeline import create_item, database_scope
    prepared = prepare_card(database)
    with database_scope(database):
        conflict = create_item(sku="FOLLOWUP-NEW", name="Araya giren kart")
    assert conflict.success
    client = Model([call("stock.item_create.prepare", **{"sku": "FOLLOWUP-NEW", "name": "Tekrar"}),
                    "İşlem başarısız oldu: bu SKU artık mevcut. Yeni kart oluşturulmadı."])
    executed = task_runtime.resume_agent_task_with_approval(prepared.data["state"],
        action_id=prepared.data["state"]["active_pending_action_id"], planner_client=client,
        db_name=database, persist=False, audit_path=str(tmp_path / "audit.jsonl"))
    assert not executed.success and not executed.data["approval_required"]
    assert executed.data["state"]["status"] == "failed"
    assert not executed.data["direct_tool_calls"]
    context = executed.data["state"]["active_entities"]["model_loop"]["last_execution"]
    assert context["success"] is False and context["message"]
    assert '"success":false' in client.prompts[0] and "last_execution" in client.prompts[0]
    assert executed.data["state"]["action_history"][-1]["status"] == "failed"
    retry = model_loop.run_model_loop("Bu kez FOLLOWUP-OTHER koduyla hazırla", session_state=executed.data["state"],
        client=Model([call("stock.item_create.prepare", **{"sku": "FOLLOWUP-OTHER", "name": "Başka kart"}), "Yeni teklif hazır."]), db_name=database)
    assert retry.success and retry.data["approval_required"]


def test_native_stock_execution_and_readback_use_trusted_database(database, tmp_path, monkeypatch):
    from sqlmodel import SQLModel
    from Stock.processors import pipeline as stock
    other = str(tmp_path / "unrelated-default.sqlite3")
    SQLModel.metadata.create_all(get_engine(other))
    monkeypatch.setattr(stock, "DB_NAME", other)
    prepared = prepare_card(database)
    executed = task_runtime.resume_agent_task_with_approval(prepared.data["state"],
        action_id=prepared.data["state"]["active_pending_action_id"],
        planner_client=Model(["Stok kartı oluşturuldu ve geri okundu."]), db_name=database,
        persist=False, audit_path=str(tmp_path / "scope-audit.jsonl"))
    assert executed.success, executed.data
    assert "FOLLOWUP-NEW" in {row.sku for row in stock.list_items(db_name=database).data["records"]}
    assert not stock.list_items(db_name=other).data["records"]
    assert stock.DB_NAME == other and stock._DATABASE_SCOPE.get() is None


def test_internal_exception_is_not_reported_as_provider_failure(database, monkeypatch):
    def broken(*a, **k):
        raise TypeError("secret-value-must-not-appear")
    monkeypatch.setattr(task_runtime, "_record_typed_step_observation", broken)
    result = model_loop.run_model_loop("Kayıtlara bak", client=Model([call("orders.summary", period="all")]), db_name=database)
    assert not result.success and "uygulama hatası" in result.message
    assert result.data["runtime_error"]["phase"] == "observation"
    assert "secret-value-must-not-appear" not in json.dumps(result.data)
    assert result.data["state"]["completed_steps"][0]["result_data"]["tool_result"]["total_orders"] == 6


def test_provider_failure_after_reads_does_not_claim_nothing_ran(database):
    result = model_loop.run_model_loop("Siparişleri analiz et", client=Model([call("orders.summary", period="all")]), db_name=database)
    assert not result.success
    assert result.data["runtime_error"]["phase"] == "provider"
    assert "sonuçları saklandı" in result.message and "hiçbir" not in result.message


def test_account_health_uses_shared_manual_state_and_carries_no_live_diagnosis(database, monkeypatch):
    from Account.models.models import ApiAccount
    from Account.views import actions
    from Account.processors.local_health import local_account_status
    with Session(get_engine(database)) as session:
        account = session.get(ApiAccount, 101)
        account.token_valid = False
        account.api_key = "secret-health-key"
        account.api_secret = "secret-health-value"
        session.add(account)
        session.commit()
    manual = actions.action_load_local_account_health(api_account_ids=[101], db_name=database)
    called = []
    original = actions.action_load_local_account_health
    monkeypatch.setattr(actions, "action_load_local_account_health", lambda **kw: called.append(kw) or original(**kw))
    ai = tools.accounts_health_summary(api_account_ids=[101], db_name=database)
    assert called and ai.success
    assert {k:v for k,v in ai.data.items() if k != "tool"} == manual.data
    assert ai.data["invalid_tokens"] == 1 and not ai.data["remote_connection_verified"]
    assert ai.data["diagnosed_failure_cause"] is None
    assert "secret-health" not in json.dumps(ai.data)
    row = SimpleNamespace(is_active=True, token_valid=False)
    assert actions.account_visual_status(row) == local_account_status(row)["display_status"] == "Pasif"


def test_account_lookup_uses_account_domain_and_marks_legacy_flag_as_local(database, monkeypatch):
    from Account.models.models import ApiAccount
    from Account.views import actions
    from Account.processors.local_health import lookup_local_accounts
    with Session(get_engine(database)) as session:
        account = session.get(ApiAccount, 101)
        account.comp_name = "İŞIK Mağazası"
        account.token_valid = False
        account.api_key = "secret-lookup-key"
        session.add(account)
        session.commit()
    domain = lookup_local_accounts(query="isik magazasi", db_name=database)
    manual = actions.action_find_local_accounts(query="isik magazasi", db_name=database)
    called = []
    original = actions.action_find_local_accounts
    monkeypatch.setattr(actions, "action_find_local_accounts", lambda **kw: called.append(kw) or original(**kw))
    ai = tools.marketplaces_account_lookup(query="isik magazasi", db_name=database)
    assert ai.success and called and domain.data == manual.data
    assert {k:v for k,v in ai.data.items() if k != "tool"} == domain.data
    assert ai.data["count"] == 1 and ai.data["account_scopes"][0]["api_account_id"] == 101
    row = ai.data["accounts"][0]
    assert row["token_valid"] is False and row["stored_token_valid"] is False
    assert not row["remote_connection_verified"] and ai.data["diagnosed_failure_cause"] is None
    assert "secret-lookup" not in json.dumps(ai.data)
    summary = tools.marketplaces_summary(db_name=database)
    assert not summary.data["remote_connection_verified"] and summary.data["diagnosed_failure_cause"] is None


def test_freshness_separates_remote_event_local_write_and_unknown_fetch(database, monkeypatch):
    from Orders.models.trendyol.models import OrderData
    from Account.models.models import ApiAccount
    from Orders.views import actions
    from Orders.processors.data_freshness import read_local_order_freshness
    remote = datetime(2026, 9, 1, 20, 28, tzinfo=timezone.utc)
    with Session(get_engine(database)) as session:
        for row in session.exec(select(OrderData)).all():
            row.orderDate = int(remote.timestamp() * 1000)
            row.lastModifiedDate = int((remote - timedelta(hours=1)).timestamp() * 1000)
            row.created_at = datetime(2026, 10, 10, 10)
            row.updated_at = datetime(2026, 10, 12, 10)
            session.add(row)
        account = session.get(ApiAccount, 101)
        account.last_used_at = datetime(2026, 10, 13, 14)
        session.add(account)
        session.commit()
    native = read_local_order_freshness(api_account_ids=[101], db_name=database)
    assert native.success and native.data["order_count"] == 5
    assert native.data["latest_order_event_at"] == "2026-09-01T23:28:00+03:00"
    assert native.data["latest_remote_modified_at"] == "2026-09-01T22:28:00+03:00"
    assert native.data["latest_local_record_created_at"] == "2026-10-10T13:00:00+03:00"
    assert native.data["last_successful_retrieval_at"] is None
    assert native.data["successful_retrieval_time_known"] is False
    manual = actions.action_load_order_data_freshness(api_account_ids=[101], db_name=database)
    ai = tools.orders_data_freshness(api_account_ids=[101], db_name=database)
    assert manual.data == native.data == {k:v for k,v in ai.data.items() if k != "tool"}


def test_new_contracts_are_discoverable_and_use_native_domain_actions():
    registry = tools.available_tools()
    assert registry["orders.data_freshness"].canonical_callable == "Orders.views.actions.action_load_order_data_freshness"
    assert registry["accounts.health"].canonical_callable == "Account.views.actions.action_load_local_account_health"
    assert registry["approvals.cancel"].action_type == "control"
