"""Actual approval outcomes remain visible beside historical prepare receipts."""
from copy import deepcopy
import json
from pathlib import Path
import time
from unittest.mock import patch

from sqlmodel import Session

from Account.models.models import ApiAccount
from AI.processors import model_loop, observation_artifacts
from AI.processors import operation_runtime
from AI.processors.conversation_runtime import run_contextual_conversation_turn
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.runtime.answer_review import review_answer
from AI.runtime.context_window import json_bytes
from AI.runtime.effect_history import approved_effect_receipts, observation_effect_timing
from AI.runtime.listing_stock_contracts import listing_stock_links
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result
from Listing.models import ListingProduct
from Stock.models import StockItem
from tests.support.db_case import IsolatedDbTestCase


class Model:
    def __init__(self, decisions, *, reviewed=None):
        self.decisions, self.reviewed = iter(decisions), reviewed
        self.prompts, self.review_prompts = [], []
        self.resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True},
                              "final_answer_review_enabled": reviewed is not None}

    def invoke_tools(self, prompt, *, tools):
        self.prompts.append(prompt)
        decision = next(self.decisions)
        return json.dumps(decision) if isinstance(decision, dict) else decision

    def invoke_final_text(self, prompt, *, exact_model=False):
        assert exact_model
        self.review_prompts.append(prompt)
        return self.reviewed


def call(name, **arguments):
    return {"mode": "tool", "tool": name, "arguments": arguments}


def packet(prompt):
    return json.loads(prompt._context.split(": ", 1)[1])


def assert_actual_link_receipt(context, action_id):
    effects = context["effect_receipts"]
    assert len(effects) == 1
    effect = effects[0]
    assert effect["action_id"] == action_id
    assert effect["operation"] == "listing.action_set_listing_stock_items"
    assert effect["success"] and effect["status"] == "executed" and effect["business_completion_verified"]
    assert effect["verify"] == {"listing_id": 502, "primary_stock_item_id": 401,
                                "stock_item_ids": [401], "verified": True, "verified_by": "db"}
    assert {source["collection"] for source in effect["sources"]} == {
        "action_history", "last_tool_results", "model_loop.last_execution"}
    assert effect["approved_record_refs"][0]["account"] == "101"
    assert effect["approved_record_refs"][0]["environment"] == "local"
    assert "arguments" not in effect and "action" not in effect
    return effect


class TestApprovedEffectContext(IsolatedDbTestCase):
    def setUp(self):
        super().setUp()
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=101, account_id="isolated", comp_name="Synthetic", platform="trendyol"))
            session.commit()
            session.add_all([ListingProduct(pk=502, api_account_id=101, product_id="REMOTE-502", title="Pilot Filtre"),
                             StockItem(pk=401, sku="PILOT-KUPA", name="Pilot Kupa")])
            session.commit()
        self.observation_patch = patch.object(observation_artifacts, "OBSERVATION_ARTIFACTS_ROOT",
                                               Path(self._tmp_dir.name) / "observations")
        self.observation_patch.start()
        self.addCleanup(self.observation_patch.stop)

    def turn(self, message, client, history, state=None):
        return run_contextual_conversation_turn(message, client=client, provider_code="synthetic",
            model_name="synthetic-exact", db_name=self.db_path, history=history, session_state=state,
            allow_approval_execute=True, persist=False)

    def prepare_link(self, history):
        preparing = Model([
            call("operations.discover", query="listing.stock_links", limit=1),
            call("listing.stock_links", listing_id=502, api_account_id=101, product_id="REMOTE-502"),
            call("operations.discover", query="stock.search", limit=1),
            call("stock.search", query="PILOT-KUPA"),
            call("operations.discover", query="listing.stock_link.prepare", limit=1),
            call("listing.stock_link.prepare", listing_id=502, api_account_id=101,
                 product_id="REMOTE-502", stock_item_id=401, qty=1),
            "Eşleştirme önerisi onayına hazır."])
        preparing.resource_plan["native_tool_history_enabled"] = True
        prepared = self.turn("Pilot Filtre ilanına Pilot Kupa stok kartını bağla.", preparing, history)
        assert prepared["success"] and prepared["approval_required"], prepared
        assert preparing.prompts[-1]._tool_exchanges  # Reproduce a preceding native prepare receipt.
        return prepared["session_state"]

    def test_turkish_button_label_executes_exact_local_action_once_and_does_not_reissue_original_task(self):
        history = []
        state = self.prepare_link(history)
        action_id = state["active_pending_action_id"]
        answer = "Eşleştirme yerel kayıtta doğrulandı."
        approving = Model([answer])
        approving.resource_plan["native_tool_history_enabled"] = True
        with patch.object(operation_runtime, "execute_approved_operation",
                          wraps=operation_runtime.execute_approved_operation) as execute:
            approved = self.turn("Onayla ve çalıştır", approving, history, state)
            assert approved["success"] and approved["answer"] == answer, approved
            assert execute.call_count == 1
            assert execute.call_args.args[0]["action_id"] == action_id
            replayed = self.turn("Onayla ve çalıştır", Model([]), history, approved["session_state"])
            assert replayed["mode"] == "no_pending_action"
            assert execute.call_count == 1
        prompt = approving.prompts[0]
        context = packet(prompt)
        assert prompt._request is None  # The original action request must not become a new user message.
        assert "\nCurrent user request:" not in str(prompt)
        assert "\nConversation:" in str(prompt)  # String-only local transports retain the earlier conversation.
        assert context["original_task"] == state["goal"]
        assert context["approval_continuation"]["action_id"] == action_id
        assert context["approval_continuation"]["approval_consumed"]
        assert not prompt._tool_exchanges  # The latest receipt is execution, not the preceding prepare.
        assert_actual_link_receipt(context, action_id)
        assert not approved["session_state"]["pending_actions"]
        assert listing_stock_links(listing_id=502, api_account_id=101, product_id="REMOTE-502",
                                   db_name=self.db_path).data["stock_items"] == [{"stock_item_id": 401, "qty": 1.0}]

    def test_failed_approval_continuation_exposes_error_without_replaying_preparation_or_reviving_approval(self):
        history = []
        state = self.prepare_link(history)
        action_id = state["active_pending_action_id"]
        error = "Yerel kayıt güncellemesi başarısız: sentetik işlem kilidi."
        answer = "Eşleştirme çalıştırılamadı; yerel kayıt güncellemesinde sentetik işlem kilidi oluştu."
        approving = Model([answer], reviewed=answer)
        approving.resource_plan["native_tool_history_enabled"] = True
        with patch.object(operation_runtime, "execute_approved_operation",
                          return_value=Result.fail(error, close_dialog=False,
                              data={"api_call_performed": False, "db_write_performed": False})) as execute:
            approved = self.turn("Onayla ve çalıştır", approving, history, state)
        assert execute.call_count == 1 and execute.call_args.args[0]["action_id"] == action_id
        assert not approved["success"] and approved["answer"] == answer
        assert approved["session_state"]["status"] == "failed"
        assert not approved["approval_required"] and not approved["session_state"]["pending_actions"]
        prompt = approving.prompts[0]
        context = packet(prompt)
        assert prompt._request is None and not prompt._tool_exchanges
        assert not context["approval_continuation"]["execution_success"]
        assert context["approval_continuation"]["execution_message"] == error
        effect = context["effect_receipts"][0]
        assert effect["action_id"] == action_id and effect["status"] == "failed"
        assert effect["message"] == error and not effect["business_completion_verified"]
        review = packet(approving.review_prompts[0])
        assert review["active_pending_action_id"] is None
        assert review["approval_continuation"]["execution_message"] == error
        assert listing_stock_links(listing_id=502, api_account_id=101, product_id="REMOTE-502",
                                   db_name=self.db_path).data["stock_items"] == []

    def test_explicit_stale_or_malformed_approval_never_executes_the_current_local_action(self):
        history = []
        state = self.prepare_link(history)
        with patch.object(operation_runtime, "execute_approved_operation") as execute:
            stale = self.turn("eski action_id 0a461f4c7c6adef0369cfa633fb955a7 onayla ve çalıştır",
                              Model([]), history, state)
            assert stale["mode"] == "stale_approval"
            assert stale["session_state"]["active_pending_action_id"] == state["active_pending_action_id"]
            from AI.processors.turn_service import run_typed_control_turn
            malformed = run_typed_control_turn("action_id : onayla ve çalıştır", mode="approve",
                session_state=state, client=Model([]), db_name=self.db_path, allow_approval_execute=True)
            assert malformed.data["mode"] == "invalid_approval"
            assert malformed.data["state"]["active_pending_action_id"] == state["active_pending_action_id"]
        execute.assert_not_called()

    def test_actual_ui_approval_card_surfaces_failed_execution_and_cannot_replay_the_old_button(self):
        from PyQt6.QtCore import QUrl
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from AI.processors.task_store import save_agent_task_state
        from AI.views import chat_tab
        history = []
        state = self.prepare_link(history)
        runtime = {"source": "cloud", "provider_id": 701, "provider_code": "synthetic",
                   "model_name": "synthetic-exact", "allow_model_fallback": False}
        state["active_entities"]["runtime_context"] = runtime
        state["pending_actions"][0]["_agent_task_runtime"] = runtime
        saved = save_agent_task_state(AgentSessionState.from_dict(state), root=Path(self._tmp_dir.name) / "tasks")
        state["pending_actions"][0]["_agent_task_store_root"] = str(saved.parent)
        error = "Yerel kayıt güncellemesi başarısız: sentetik işlem kilidi."
        answer = "Eşleştirme çalıştırılamadı; sentetik işlem kilidi oluştu."
        approving = Model([answer])
        approving.resource_plan["native_tool_history_enabled"] = True
        with patch.object(chat_tab.AITab, "_refresh_current_source"), \
             patch.object(chat_tab.AITab, "_refresh_task_sessions"), \
             patch.object(chat_tab, "DB_NAME", self.db_path), \
             patch.object(chat_tab.ai_actions, "action_get_provider_account", return_value=Result.ok(
                 "Synthetic runtime", data={"record": {"provider_code": "synthetic", "default_model": "synthetic-exact"}})), \
             patch.object(chat_tab, "build_provider_chat_client", return_value=approving), \
             patch.object(operation_runtime, "execute_approved_operation", return_value=Result.fail(error)) as execute:
            tab = chat_tab.AITab()
            tab._schedule_timer.stop()
            try:
                tab._restore_task_chat_context({"state": state, "state_path": str(saved)})
                token = tab._latest_approval_card_token
                assert token and "Onayla ve çalıştır" in tab.transcript.toPlainText()
                url = QUrl("orderscout://approval/approve/" + token)
                tab._on_transcript_anchor_clicked(url)
                deadline = time.monotonic() + 5
                while tab._action_worker is not None and time.monotonic() < deadline:
                    QApplication.processEvents()
                    QTest.qWait(5)
                assert tab._action_worker is None, "Approval worker did not finish"
                assert execute.call_count == 1
                assert tab._conversation_state["status"] == "failed"
                assert not tab._pending_action_from_state()
                assert answer in tab.transcript.toPlainText()
                assert tab._chat_history[-2:] == [{"role": "user", "content": "Onayla ve çalıştır"},
                                                  {"role": "assistant", "content": answer}]
                tab._on_transcript_anchor_clicked(url)
                assert execute.call_count == 1
                assert packet(approving.prompts[0])["approval_continuation"]["execution_message"] == error
                assert approving.prompts[0]._request is None and not approving.prompts[0]._tool_exchanges
            finally:
                tab.close()
                tab.deleteLater()
                QApplication.processEvents()

    def test_native_prepare_public_approval_and_followup_share_exact_effect_and_historical_readback(self):
        history = []
        preparing = Model([
            call("listing.stock_links", listing_id=502, api_account_id=101, product_id="REMOTE-502"),
            call("stock.search", query="PILOT-KUPA"),
            call("listing.stock_link.prepare", listing_id=502, api_account_id=101,
                 product_id="REMOTE-502", stock_item_id=401, qty=1),
            "Eşleştirme önerisi onayına hazır."])
        prepared = self.turn("Pilot Filtre ilanına Pilot Kupa stok kartını bağla.", preparing, history)
        assert prepared["success"], prepared
        state = prepared["session_state"]
        action_id = state["active_pending_action_id"]
        assert approved_effect_receipts(AgentSessionState.from_dict(state), model_loop._preview) == []
        assert listing_stock_links(listing_id=502, api_account_id=101, product_id="REMOTE-502",
                                   db_name=self.db_path).data["stock_items"] == []

        model_answer = "Eşleştirme tamamlandı ve yerel kayıt okumasıyla doğrulandı."
        approving = Model([model_answer], reviewed=model_answer)
        approved = self.turn("Onaylıyorum.", approving, history, state)
        assert approved["success"] and approved["answer"] == model_answer, approved
        assert listing_stock_links(listing_id=502, api_account_id=101, product_id="REMOTE-502",
                                   db_name=self.db_path).data["stock_items"] == [
            {"stock_item_id": 401, "qty": 1.0}]
        assert_actual_link_receipt(packet(approving.prompts[0]), action_id)
        review = packet(approving.review_prompts[0])
        assert_actual_link_receipt(review, action_id)
        earlier_prepare = next(row for row in review["source_receipts"] if row["operation"] == "listing.stock_link.prepare")
        assert earlier_prepare["compact_facts"]["db_write_performed"] is False
        assert earlier_prepare["historical_before_approved_execution"][0]["action_id"] == action_id
        earlier_read = next(row for row in packet(approving.prompts[0])["observations"]
                            if row["operation"] == "listing.stock_links")
        assert earlier_read["historical_before_approved_execution"][0]["action_id"] == action_id
        assert "later verified execution" in approving.review_prompts[0]._instructions

        following = Model([model_answer], reviewed=model_answer)
        followup = self.turn("Eşleştirme yapıldı mı?", following, history, approved["session_state"])
        assert followup["success"] and followup["answer"] == model_answer
        assert_actual_link_receipt(packet(following.prompts[0]), action_id)
        assert_actual_link_receipt(packet(following.review_prompts[0]), action_id)


def test_prepare_flags_arguments_and_semantic_verification_never_become_execution_evidence():
    state = AgentSessionState(goal="Hazırla")
    action = {"action_id": "pending", "action_type": "example.write", "success": True,
              "verify": {"verified": True}, "arguments": {"phase": "execute", "db_write_performed": True},
              "semantic_verification": {"status": "verified"}}
    state.add_pending_action(action)
    state.action_history = [{"phase": "prepare", "status": "pending_approval", "success": True,
                             "verify": {"verified": True}, "action": action}]
    state.last_tool_results = [{"step": 1, "tool_names": ["example.prepare"], "data": action}]
    assert approved_effect_receipts(state, model_loop._preview) == []


def test_real_failure_envelope_is_not_verified_completion_and_prewrite_fields_do_not_leak():
    state = AgentSessionState(goal="Çalıştır")
    state.action_history = [{"phase": "execute", "status": "failed", "success": False,
        "action_type": "example.write", "result_message": "Write failed", "verify": {"verified": False},
        "action": {"action_id": "failed", "arguments": {"db_write_performed": True, "secret": "not-outcome"},
                   "semantic_verification": {"status": "verified"}, "summary": "pretend completed"}}]
    receipts = approved_effect_receipts(state, model_loop._preview)
    assert len(receipts) == 1
    assert receipts[0]["status"] == "failed" and receipts[0]["success"] is False
    assert receipts[0]["business_completion_verified"] is False
    assert "not-outcome" not in json.dumps(receipts) and "pretend completed" not in json.dumps(receipts)
    reviewer = Model([], reviewed="İşlem başarısız oldu.")
    answer, marker = review_answer(reviewer, state, "İşlem tamamlandı.", sanitize=model_loop._preview)
    assert answer == reviewer.reviewed and marker["review_effect_count"] == 1
    assert packet(reviewer.review_prompts[0])["effect_receipts"] == receipts


def test_large_proposal_never_displaces_readback_and_postwrite_observation_is_not_historical():
    state = AgentSessionState(goal="Kontrol et")
    state.completed_steps = [AgentTaskStep(index=1, step_id="before", prompt="read"),
                             AgentTaskStep(index=2, step_id="after", prompt="read")]
    state.action_history = [{"phase": "execute", "status": "executed", "success": True,
        "action_type": "example.write", "verify": {"verified": True, "verified_by": "db", "record_id": 9},
        "action": {"action_id": "real", "arguments": {"rows": [{"noise": "x" * 5000}] * 100}}}]
    state.last_tool_results = [{"step": 1}, {"step": "approval", "tool_names": ["execute_approved_operation"],
        "data": {"audit": {"action": {"action_id": "real"}, "operation": "example.write", "execute_success": True},
                 "verify": deepcopy(state.action_history[0]["verify"]), "result": {"changed": True}}}, {"step": 2}]
    receipts = approved_effect_receipts(state, model_loop._preview)
    assert json_bytes(receipts) < 2000 and receipts[0]["verify"]["record_id"] == 9
    assert receipts[0]["result"] == {"changed": True} and receipts[0]["business_completion_verified"]
    assert "noise" not in json.dumps(receipts)
    timing = observation_effect_timing(state, receipts)
    assert timing["before"]["historical_before_approved_execution"][0]["action_id"] == "real"
    assert "after" not in timing


def test_last_execution_summary_cannot_claim_completion_without_actual_readback():
    state = AgentSessionState(goal="Kontrol et")
    state.active_entities["model_loop"] = {"last_execution": {"action_id": "unverified",
        "operation": "example.write", "success": True, "business_completion_verified": True,
        "result": {"changed": True}}}
    receipt = approved_effect_receipts(state, model_loop._preview)[0]
    assert receipt["success"] is True and receipt["business_completion_verified"] is False
    assert receipt["result"] == {"changed": True} and "verify" not in receipt
