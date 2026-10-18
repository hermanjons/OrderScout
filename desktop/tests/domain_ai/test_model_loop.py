"""Model-owned turns over actual canonical tools, without the legacy intent/router."""
from copy import deepcopy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from AI.processors import model_loop, tools, task_runtime, observation_artifacts
from AI.processors.session_state import AgentSessionState
from AI.processors.task_store import load_agent_task_state
from Testing.processors.order_snapshot_fixture import seed_order_snapshot_fixture


class ScriptedModel:
    def __init__(self, decisions, reviews=None):
        self.decisions = iter(decisions)
        self.reviews = iter(reviews) if reviews is not None else None
        self.prompts = []
        self.resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
    def __call__(self, prompt):
        raise AssertionError("Use the native tools contract")
    def invoke_tools(self, prompt, *, tools):
        self.prompts.append(prompt)
        decision = next(self.decisions)
        return decision["answer"] if set(decision) == {"answer"} else json.dumps(decision, ensure_ascii=False)
    def invoke_json_text(self, prompt, *, schema=None):
        assert "factual review" in prompt
        return json.dumps(next(self.reviews) if self.reviews is not None else {"supported": True, "issues": []})


def call(operation, **args):
    return {"mode": "tool", "tool": operation, "arguments": args}


@pytest.fixture
def population(tmp_path, monkeypatch):
    monkeypatch.setattr(observation_artifacts, "OBSERVATION_ARTIFACTS_ROOT", tmp_path / "observations")
    db = str(tmp_path / "business.sqlite3")
    seed_order_snapshot_fixture(db, isolation_root=tmp_path)
    return db


def test_native_snapshot_uses_manual_action_and_reads_all_570_sorted_records(population, monkeypatch):
    from Orders.views import actions
    original = actions.action_load_order_snapshot
    calls = []
    monkeypatch.setattr(actions, "action_load_order_snapshot", lambda **kwargs: calls.append(kwargs) or original(**kwargs))
    end = datetime.now().date()
    result = tools.orders_snapshot(start_date=str(end - timedelta(days=365)), end_date=str(end), db_name=population)
    assert result.success, result.message
    assert len(calls) == 1
    assert result.data["complete"] and len(result.data["orders"]) == result.data["total_count"] == 570
    assert not result.data["truncated"]
    assert "SNAPSHOT-OUTSIDE" not in {row["order_number"] for row in result.data["orders"]}
    dates = [row["order_date_ms"] for row in result.data["orders"]]
    assert dates == sorted(dates)


def test_model_writes_its_own_answer_and_legacy_interpretation_never_runs(tmp_path, monkeypatch):
    def legacy(*args, **kwargs):
        raise AssertionError("Legacy business interpretation must not run")
    monkeypatch.setattr(task_runtime, "interpret_agent_turn", legacy)
    monkeypatch.setattr(task_runtime, "_finalize_task_answer", legacy)
    text = "Buradayım başkan. Ne üzerinde çalışalım?"
    result = model_loop.run_model_loop("selam", client=ScriptedModel([{"answer": text}]), db_name=str(tmp_path / "unused.db"))
    assert result.success and result.data["answer"] == text
    assert result.data["direct_tool_calls"] == []
    assert result.data["response_synthesis"]["fallback_used"] is False


def test_full_year_report_binds_all_rows_then_exact_approval_creates_verified_xlsx(population, tmp_path, monkeypatch):
    from openpyxl import load_workbook
    end = datetime.now().date()
    output = tmp_path / "orders.xlsx"
    model = ScriptedModel([
        call("orders.snapshot", start_date=str(end - timedelta(days=365)), end_date=str(end), sort="order_date_asc"),
        call("reports.build_snapshot", title="Son yıl siparişleri", sources=[{
            "source_id": "orders", "source_step_id": "call_1", "operation_id": "orders.snapshot",
            "result": {"$from_step": "call_1", "path": "tool_result"}}], sheets=[{
            "name": "Siparişler", "source_id": "orders", "rows_path": "orders", "columns": [
                {"key": "number", "label": "Sipariş", "source_path": "order_number", "data_type": "string"},
                {"key": "date", "label": "Tarih", "source_path": "order_date", "data_type": "string"},
                {"key": "amount", "label": "Tutar", "source_path": "total_price", "data_type": "number"},
                {"key": "currency", "label": "Döviz", "source_path": "currency", "data_type": "string"}]}]),
        call("reports.xlsx.prepare", report_snapshot={"$from_step": "call_2", "path": "tool_result.report_snapshot"}, output_path=str(output)),
        {"answer": "Son bir yıldaki 570 siparişini eskiden yeniye sıraladım. Excel'i kaydetmek için onayını bekliyorum."}])
    prepared = model_loop.run_model_loop("Son bir yılın siparişlerini sıralayıp Excel hazırla", client=model,
        db_name=population, persist=True, task_store_root=tmp_path / "tasks")
    assert prepared.success, prepared.data
    state = AgentSessionState.from_dict(prepared.data["state"])
    assert state.status == "pending_approval", [(s.tool_names, s.status, s.result_message, s.result_data) for s in state.completed_steps if s.status != "completed"]
    assert len(state.completed_steps) == 3 and not output.exists()
    stored = load_agent_task_state(state.session_id, root=tmp_path / "tasks")
    snapshot = stored.completed_steps[1].result_data["tool_result"]["report_snapshot"]
    assert len(snapshot["sheets"][0]["rows"]) == 570
    assert '"stored_row_count":570' in model.prompts[-1] and '"preview_only":true' in model.prompts[-1]
    stale = task_runtime.resume_agent_task_with_approval(stored.to_dict(), action_id="old-action", planner_client=model,
        db_name=population, persist=False)
    assert not stale.success and not output.exists()
    inquiry = model_loop.run_model_loop("Kaç sipariş var; dosya oluştu mu?", session_state=stored.to_dict(),
        client=ScriptedModel([{"answer": "570 sipariş var, dosya henüz onay bekliyor."}]), db_name=population)
    assert inquiry.data["state"]["active_pending_action_id"] == stored.active_pending_action_id
    assert inquiry.data["state"]["pending_actions"] == stored.to_dict()["pending_actions"]
    assert not inquiry.data["direct_tool_calls"] and not output.exists()
    revision = stored.to_dict()
    revision["active_entities"]["task_control"] = {"reason": "user_revision", "queued_user_messages": ["Dönemi daralt"]}
    blocked = task_runtime.resume_agent_task_with_approval(revision, action_id=stored.active_pending_action_id,
        planner_client=model, db_name=population, persist=False)
    assert not blocked.success and blocked.data["requires_user_revision_turn"] and not output.exists()
    approved = task_runtime.resume_agent_task_with_approval(stored.to_dict(), action_id=stored.active_pending_action_id,
        planner_client=ScriptedModel([{"answer": "Excel oluştu; 570 siparişin tamamı dosyada ve okuma doğrulaması başarılı."}]),
        db_name=population, persist=False, audit_path=str(tmp_path / "audit.jsonl"))
    assert approved.success, approved.data
    assert approved.data["execute"]["verify"]["verified"] is True
    assert approved.data["state"]["observations"][-1]["facts"]["verified"] is True
    from AI.views.chat_tab import AITab
    assert AITab._format_execute_result_answer(None, "Old boilerplate prefix", approved) == approved.data["answer"]
    book = load_workbook(output, read_only=True, data_only=True)
    try:
        assert len(list(book["Siparişler"].values)) == 571
    finally:
        book.close()
    from PyQt6.QtCore import QUrl
    from PyQt6.QtWidgets import QApplication
    from AI.views import chat_tab
    app = QApplication.instance() or QApplication([])
    widget = AITab()
    opened = []
    monkeypatch.setattr(chat_tab.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    try:
        widget._append_verified_artifact_links(prepared.data)
        assert not widget._delivered_artifacts
        widget._append_verified_artifact_links(approved.data)
        assert len(widget._delivered_artifacts) == 1
        token, receipt = next(iter(widget._delivered_artifacts.items()))
        assert receipt["output_path"] == str(output)
        assert str(output) in widget.transcript.toPlainText()
        widget._append_verified_artifact_links(approved.data)
        assert len(widget._delivered_artifacts) == 1
        widget._on_transcript_anchor_clicked(QUrl("orderscout://artifact/open/unknown"))
        assert opened == []
        widget._on_transcript_anchor_clicked(QUrl("orderscout://artifact/open/" + token))
        assert [Path(path) for path in opened] == [output]
        tampered = deepcopy(approved.data)
        native = tampered["state"]["last_tool_results"][-1]["data"]
        native["verify"]["output_path"] = str(tmp_path / "not-approved.xlsx")
        widget._append_verified_artifact_links(tampered)
        assert len(widget._delivered_artifacts) == 1
        widget._reset_chat()
        assert not widget._delivered_artifacts
        widget._restore_task_chat_context(approved.data)
        assert widget._conversation_state["completed_steps"] == approved.data["state"]["completed_steps"]
        assert widget._conversation_state["conversation_turns"] == approved.data["state"]["conversation_turns"]
        assert len(widget._delivered_artifacts) == 1
        output.unlink()
        widget._on_transcript_anchor_clicked(QUrl("orderscout://artifact/open/" + token))
        assert [Path(path) for path in opened] == [output]
        assert "Dosya bu konumda bulunamadı" in widget.transcript.toPlainText()
    finally:
        widget.close()
        widget.deleteLater()
        assert app is not None


def test_duplicate_successful_read_is_reused_without_dispatch(population):
    query = call("orders.snapshot")
    client = ScriptedModel([query, query, {"answer": "Mevcut kayıtları okudum."}])
    result = model_loop.run_model_loop("Siparişlerime bak", client=client, db_name=population)
    assert result.success and len(result.data["direct_tool_calls"]) == 1
    assert "duplicate_not_executed" in client.prompts[-1]


def test_literal_report_and_wrong_report_family_are_returned_as_tool_errors(population):
    client = ScriptedModel([
        call("reports.xlsx.prepare", report_snapshot={"snapshot_id": "fake"}),
        {"answer": "Geçerli bir kaynak raporu hazırlanmadığından dosya oluşturulmadı."}])
    result = model_loop.run_model_loop("Raporu oluştur", client=client, db_name=population)
    assert result.success and not result.data["approval_required"]
    error = result.data["direct_tool_results"][0]
    assert not error["success"] and "exact_declared_producer_required" in json.dumps(error["data"])


def test_model_answer_has_no_second_model_veto_or_template_replacement(tmp_path):
    model = ScriptedModel([{"answer": "Henüz bir dosya oluşturmadım."}])
    model.invoke_json_text = lambda *a, **k: pytest.fail("No second model may veto the ordinary answer")
    result = model_loop.run_model_loop("Dosya oluştu mu?", client=model, db_name=str(tmp_path / "unused.db"))
    assert result.success and result.data["answer"] == "Henüz bir dosya oluşturmadım."
    assert len(model.prompts) == 1
    assert result.data["response_synthesis"]["prose_reviewed"] is False
    assert result.data["response_synthesis"]["final_projection_verified"] is False


@pytest.mark.parametrize("answer", ['{"orders":[],"total":0}', '```json\n{"x":1}\n```', '[1,2,3]'])
def test_native_answer_may_be_json_or_code_without_becoming_a_control(answer, tmp_path):
    result = model_loop.run_model_loop("JSON olarak yanıtla", client=ScriptedModel([{"answer": answer}]),
                                       db_name=str(tmp_path / "unused.db"))
    assert result.success and result.data["answer"] == answer


def test_wrong_export_family_is_rejected_before_prepare_dispatch(population):
    client = ScriptedModel([
        call("orders.snapshot"),
        call("orders.item_sales_report_xlsx.prepare", report_snapshot={"$from_step": "call_1", "path": "tool_result"}),
        {"answer": "Sipariş listesi ürün satış raporu olmadığı için bu aktarım hazırlanmadı."}])
    result = model_loop.run_model_loop("Siparişlerimi Excel yap", client=client, db_name=population)
    assert result.success and not result.data["approval_required"]
    assert not result.data["direct_tool_results"][1]["success"]
    assert "exact_declared_producer_required" in json.dumps(result.data["direct_tool_results"][1])


def test_provider_failure_keeps_original_request_for_retry(population):
    failed = model_loop.run_model_loop("Son bir yılın siparişlerini sırala", client=ScriptedModel([]), db_name=population)
    assert not failed.success and failed.data["state"]["status"] == "paused"
    client = ScriptedModel([call("orders.snapshot"), {"answer": "Sipariş kayıtlarını okuyabildim."}])
    retried = model_loop.run_model_loop("tekrar dene", client=client, session_state=failed.data["state"], db_name=population)
    assert retried.success and "Son bir yılın siparişlerini sırala" in client.prompts[0]


def test_old_conversation_sources_and_pending_identity_survive_engine_migration(population):
    client = ScriptedModel([call("orders.snapshot"), {"answer": "Siparişleri okudum."}])
    original = model_loop.run_model_loop("siparişlere bak", client=client, db_name=population)
    state = original.data["state"]
    state["active_entities"].pop("model_loop")
    old_id = state["session_id"]
    reader = ScriptedModel([{"answer": "Önceki sipariş gözlemi burada; yeniden sorgulamadım."}])
    continued = model_loop.run_model_loop("Mevcut bilgi burada mı?", client=reader, session_state=state, db_name=population)
    assert continued.success and continued.data["state"]["session_id"] == old_id
    assert len(continued.data["state"]["completed_steps"]) == 1
    assert "orders.snapshot" in reader.prompts[0]


def test_host_source_restriction_blocks_reads_even_if_model_requests_one(population):
    from AI.processors.source_policy import EXISTING_ONLY
    client = ScriptedModel([call("orders.snapshot"), {"answer": "Yeni sorgu çalıştırılmadı."}])
    result = model_loop.run_model_loop("Yalnız mevcut bilgi", client=client, db_name=population,
                                      runtime_context={"source_policy": EXISTING_ONLY})
    assert result.success and not result.data["direct_tool_calls"]
    assert "invalid_tool" in client.prompts[-1]


def test_actual_ui_entrypoint_bypasses_legacy_interpreter(population, monkeypatch):
    from AI.views import chat_tab
    from Feedback.processors.pipeline import Result
    def legacy(*args, **kwargs):
        raise AssertionError("Legacy intent interpreter must not run")
    client = ScriptedModel([{"answer": "Buradayım, siparişlerine birlikte bakabiliriz."}])
    monkeypatch.setattr(chat_tab, "interpret_agent_turn", legacy)
    monkeypatch.setattr(chat_tab, "_task_domain_requested", legacy)
    monkeypatch.setattr(chat_tab, "DB_NAME", population)
    monkeypatch.setattr(chat_tab.ai_actions, "action_get_provider_account", lambda *a: Result.ok("ok", data={"record": {
        "id": 1, "provider_code": "openrouter", "default_model": "unit-model"}}))
    monkeypatch.setattr(chat_tab, "build_provider_chat_client", lambda *a, **k: client)
    result = chat_tab._run_chat_turn_with_runtime("selam", source="cloud", runtime_record={"id": 1}, history=[])
    assert result.success and result.data["decision_path"] == model_loop.ENGINE
    assert result.data["answer"] == "Buradayım, siparişlerine birlikte bakabiliriz."


def test_headless_entrypoint_uses_same_loop(population, monkeypatch):
    from AI.processors import conversation_runtime
    monkeypatch.setattr(conversation_runtime, "interpret_agent_turn", lambda *a, **k: pytest.fail("Legacy intent invoked"))
    history = []
    turn = conversation_runtime.run_contextual_conversation_turn("selam", client=ScriptedModel([{"answer": "Merhaba başkan."}]),
        history=history, db_name=population, provider_code="test", model_name="unit-model", session_state=None)
    assert turn["success"] and turn["decision_path"] == model_loop.ENGINE
    assert history[-1]["content"] == turn["answer"] == "Merhaba başkan."


def test_plain_conversation_history_is_given_to_model_when_no_state_exists(tmp_path):
    client = ScriptedModel([{"answer": "Önceki mesajını görüyorum."}])
    result = model_loop.run_model_loop("hatırlıyor musun", client=client, db_name=str(tmp_path / "unused.db"),
        history=[{"role": "user", "content": "Mağazamın adı Pilot"}, {"role": "assistant", "content": "Pilot olarak hatırlayacağım."}])
    assert result.success and "Mağazamın adı Pilot" in client.prompts[0]


def test_model_child_uses_same_loop_and_cannot_prepare_writes(population, tmp_path, monkeypatch):
    def legacy(*args, **kwargs):
        raise AssertionError("New parent must not delegate to the legacy graph planner")
    monkeypatch.setattr(task_runtime, "run_agent_task", legacy)
    model = ScriptedModel([
        call("agent.delegate", objective="Stokları oku", max_steps=3, max_replans=1),
        call("stock.inventory_overview"), {"answer": "Stok kaynağını okudum."},
        {"answer": "Alt çalışma stok kaynağını okudu; kaynak kaydı hazır."}])
    result = model_loop.run_model_loop("Stok okumasını alt çalışmaya devret", client=model, db_name=population,
        persist=True, task_store_root=tmp_path / "tasks")
    assert result.success
    receipt = result.data["direct_tool_results"][0]
    assert receipt["success"], receipt
    child_id = receipt["data"]["child_task_id"]
    child = load_agent_task_state(child_id, root=tmp_path / "tasks")
    assert model_loop.is_model_loop(child) and child.status == "complete"
    assert not child.pending_actions
    assert child.active_entities["execution_budget"]["started_steps"] == 1
    parent = result.data["state"]["active_entities"]
    assert parent["child_task_reservations"]["call_1"]["child_task_id"] == child_id
    assert parent["execution_budget"]["started_steps"] == 4


def test_stock_create_prepares_registered_native_action_without_writing(population):
    from sqlmodel import Session, select
    from Core.utils.model_utils import get_engine
    from Stock.models.models import StockItem
    model = ScriptedModel([call("stock.item_create.prepare", sku="NEW-SKU", name="Yeni Ürün"),
                           {"answer": "Yeni stok kartının bilgileri onayına hazır."}])
    result = model_loop.run_model_loop("NEW-SKU koduyla Yeni Ürün stok kartı hazırla", client=model, db_name=population)
    assert result.success and result.data["approval_required"], result.data["direct_tool_results"]
    with Session(get_engine(population)) as session:
        assert session.exec(select(StockItem).where(StockItem.sku == "NEW-SKU")).first() is None


def test_same_native_approval_can_execute_without_forcing_a_model_continuation(population, tmp_path):
    client = ScriptedModel([call("stock.item_create.prepare", sku="APPROVED-SKU", name="Onaylı Ürün"),
                            {"answer": "Stok kartını onayına hazırladım."}])
    prepared = model_loop.run_model_loop("Stok kartını hazırla", client=client, db_name=population)
    state = prepared.data["state"]
    executed = task_runtime.resume_agent_task_with_approval(state, action_id=state["active_pending_action_id"],
        planner_client=ScriptedModel([]), db_name=population, continue_after_execute=False,
        audit_path=str(tmp_path / "stock-audit.jsonl"))
    assert executed.success and executed.data["approval_granted"]
    assert executed.data["state"]["status"] == "paused"
    assert not executed.data["state"]["pending_actions"]
