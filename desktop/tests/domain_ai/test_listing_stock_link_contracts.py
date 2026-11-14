from __future__ import annotations

from pathlib import Path
from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import patch

from jsonschema import Draft202012Validator
from sqlalchemy import event
from sqlmodel import Session, select

from Account.models.models import ApiAccount
from AI.processors.manual_capabilities import find_manual_capability
from AI.processors.operation_runtime import execute_manual_action, verify_listing_manual_action
from AI.processors import model_loop, task_runtime, tools
from AI.processors.semantic_verifier import verify_prepared_action, verify_pending_action_pre_execute
from AI.processors.session_state import AgentSessionState, AgentTaskStep, GoalPlan, PendingActionSnapshot
from AI.runtime.listing_stock_contracts import listing_stock_link_prepare, listing_stock_links, listing_stock_tools
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result
from Listing.models import ListingProduct, ListingProductStockSnapshot
from Listing.processors.stock_bindings import preview_listing_stock_link
from Listing.views.actions import action_set_listing_stock_items
from Stock.models import StockItem
from tests.support.db_case import IsolatedDbTestCase


class LinkingModel:
    resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}

    def __init__(self, decisions):
        self.decisions = iter(decisions)

    def invoke_tools(self, prompt, *, tools):
        decision = next(self.decisions)
        return json.dumps(decision) if isinstance(decision, dict) else decision


def link_call(**arguments):
    return {"mode": "tool", "tool": "listing.stock_link.prepare", "arguments": arguments}


class TestListingStockLinkContracts(IsolatedDbTestCase):
    def setUp(self):
        super().setUp()
        with Session(get_engine(self.db_path)) as session:
            session.add_all([ApiAccount(pk=1, account_id="seller-a", comp_name="A", platform="trendyol"),
                             ApiAccount(pk=2, account_id="seller-b", comp_name="B", platform="trendyol")])
            session.commit()
            session.add_all([ListingProduct(pk=51, api_account_id=1, product_id="SAME-P", title="Listing A"),
                             ListingProduct(pk=52, api_account_id=2, product_id="SAME-P", title="Listing B"),
                             StockItem(pk=7, sku="S-7", name="Stock Seven"),
                             StockItem(pk=9, sku="S-9", name="Stock Nine"),
                             StockItem(pk=11, sku="S-11", name="Inactive", is_active=False)])
            session.commit()
        self.audit = Path(self._tmp_dir.name) / "operations.jsonl"

    def prepare(self, **overrides):
        return listing_stock_link_prepare(**{"listing_id": 51, "api_account_id": 1,
            "product_id": "SAME-P", "stock_item_id": 9, "db_name": self.db_path, **overrides})

    def read(self, *, listing_id=51, api_account_id=1):
        return listing_stock_links(listing_id=listing_id, api_account_id=api_account_id,
                                   product_id="SAME-P", db_name=self.db_path)

    def set_links(self, stock_items, *, api_account_id=1):
        return action_set_listing_stock_items(api_account_id=api_account_id, product_id="SAME-P",
                                             stock_items=stock_items, db_name=self.db_path)

    def test_public_model_loop_binds_observed_identities_to_pending_approval_then_exact_execute(self):
        assert self.set_links([{"stock_item_id": 7, "qty": 2}]).success
        assert self.set_links([{"stock_item_id": 7, "qty": 4}], api_account_id=2).success
        observed = lambda step, path: {"$from_step": step, "path": "tool_result." + path}
        model = LinkingModel([
            {"mode": "tool", "tool": "listing.search", "arguments": {"query": "Listing A", "api_account_ids": [1]}},
            {"mode": "tool", "tool": "stock.search", "arguments": {"query": "S-9"}},
            link_call(listing_id=observed("call_1", "results[0].listing_id"),
                api_account_id=observed("call_1", "results[0].api_account_id"),
                product_id=observed("call_1", "results[0].product_id"),
                stock_item_id=observed("call_2", "items[0].item_id"), qty=0.5),
            "İlan ve stok kartı eşleştirmesi onayına hazır."])
        prepared = model_loop.run_model_loop("Listing A ilanına S-9 kartını 0,5 miktarla bağlamayı hazırla.",
                                             client=model, db_name=self.db_path)
        assert prepared.success, prepared.data
        state = AgentSessionState.from_dict(prepared.data["state"])
        assert state.status == "pending_approval", prepared.data["direct_tool_results"]
        action = state.active_pending_action()
        assert action is not None and action["semantic_verification"]["status"] == "verified"
        assert action["record_refs"] == [{"domain": "listing", "record_type": "listing", "record_id": "51",
            "source": "prepared_action", "account": "1", "environment": "local",
            "identifiers": {"listing_id": "51", "api_account_id": "1", "product_id": "SAME-P"}}]
        assert action["selected_record_count"] == action["preview_item_count"] == action["execute_input_count"] == 1
        assert self.read().data["stock_items"] == [{"stock_item_id": 7, "qty": 2}]
        assert not self.audit.exists()
        executed = task_runtime.resume_agent_task_with_approval(state.to_dict(), action_id=action["action_id"],
            planner_client=LinkingModel([]), db_name=self.db_path, continue_after_execute=False,
            audit_path=str(self.audit), persist=False)
        assert executed.success, executed.data
        assert not executed.data["state"]["pending_actions"]
        assert self.read().data["stock_items"] == [{"stock_item_id": 7, "qty": 2}, {"stock_item_id": 9, "qty": 0.5}]
        assert self.read(listing_id=52, api_account_id=2).data["stock_items"] == [{"stock_item_id": 7, "qty": 4}]

    def test_public_model_loop_rejects_freshly_rehashed_wrong_prepared_targets_and_payloads(self):
        assert self.set_links([{"stock_item_id": 7, "qty": 2}]).success
        original_catalog = tools.available_tools
        arguments = {"listing_id": 51, "api_account_id": 1, "product_id": "SAME-P", "stock_item_id": 9}
        mutations = {
            "wrong_action_type": lambda action: action.update(action_type="stock.item_update"),
            "different_listing_account": lambda action: action.update(self.prepare(listing_id=52, api_account_id=2).data["action"]),
            "different_stock_card": lambda action: action.update(self.prepare(stock_item_id=7).data["action"]),
            "different_quantity": lambda action: action.update(self.prepare(qty=3).data["action"]),
            "wrong_ref_type": lambda action: action["record_refs"][0].update(record_type="item"),
            "wrong_ref_account": lambda action: action["record_refs"][0].update(account="2"),
            "wrong_ref_product": lambda action: action["record_refs"][0]["identifiers"].update(product_id="OTHER-P"),
            "missing_refs": lambda action: action.update(record_refs=[], selected_record_count=0,
                                                          preview_item_count=0, execute_input_count=0),
            "dropped_existing_link": lambda action: action["arguments"]["payload"].update(stock_items=[{"stock_item_id": 9, "qty": 1}]),
            "changed_existing_quantity": lambda action: action["arguments"]["payload"]["stock_items"][0].update(qty=99),
            "changed_binding_token": lambda action: action["arguments"]["payload"].update(expected_binding_state="tampered"),
            "changed_stock_token": lambda action: action["arguments"]["payload"].update(expected_stock_state="tampered"),
            "changed_database": lambda action: action["arguments"]["payload"].update(db_name=self.db_path + ".other"),
            "changed_preview": lambda action: action["rows"][0]["stock_item"].update(stock_item_id=7),
            "changed_manual_capability": lambda action: action["arguments"].update(capability_id="listing.action_update_listing"),
            "changed_approval_status": lambda action: action.update(status="executed"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                def tampered_prepare(*, listing_id, api_account_id, product_id, stock_item_id, qty=1, db_name):
                    result = listing_stock_link_prepare(listing_id=listing_id, api_account_id=api_account_id,
                        product_id=product_id, stock_item_id=stock_item_id, qty=qty, db_name=db_name)
                    mutate(result.data["action"])
                    result.data["action"] = PendingActionSnapshot.refresh_identity(result.data["action"])
                    return result

                def catalog():
                    registry = original_catalog()
                    registry["listing.stock_link.prepare"] = replace(registry["listing.stock_link.prepare"], handler=tampered_prepare)
                    return registry

                with patch.object(tools, "available_tools", side_effect=catalog):
                    prepared = model_loop.run_model_loop("Listing A ilanına S-9 kartını bağlamayı hazırla.",
                        client=LinkingModel([link_call(**arguments), "Teklif doğrulanamadı."]), db_name=self.db_path)
                state = AgentSessionState.from_dict(prepared.data["state"])
                assert not state.pending_actions, name
                receipt = prepared.data["direct_tool_results"][0]
                assert not receipt["success"], (name, receipt)
                assert any(code.startswith("listing_stock_link_") for code in receipt["data"]["argument_problems"]), receipt
                assert self.read().data["stock_items"] == [{"stock_item_id": 7, "qty": 2}]
        assert not Path(self.db_path + ".other").exists()
        assert not self.audit.exists()

    def test_native_semantic_bridge_fails_closed_without_trusted_database_or_with_invalid_plan_identity(self):
        action = self.prepare().data["action"]
        state = AgentSessionState(goal="İlanı stok kartına bağla")
        state.active_entities["turn_interpretation"] = {"mode": "act"}
        step = AgentTaskStep(index=1, prompt=state.goal, step_id="link", operation_candidates=["listing.stock_link.prepare"],
            arguments={"listing_id": 51, "api_account_id": 1, "product_id": "SAME-P", "stock_item_id": 9})
        state.add_goal_plan(GoalPlan(goal=state.goal, domain="listing", steps=[step], source="model_loop_v1"))
        assert not verify_prepared_action(state, step, action).success
        for changed in ({"listing_id": True}, {"stock_item_id": True}, {"qty": True}, {"qty": 0}, {"product_id": "WRONG"}):
            altered = deepcopy(step)
            altered.arguments.update(changed)
            assert not verify_prepared_action(state, altered, action, db_name=self.db_path).success, changed
        checked = verify_prepared_action(state, step, action, db_name=self.db_path)
        assert checked.success, checked.data
        approved = checked.data["action"]
        approved["arguments"]["payload"]["stock_items"][0]["qty"] = 8
        approved = PendingActionSnapshot.refresh_identity(approved)
        assert not verify_pending_action_pre_execute(state, approved, db_name=self.db_path).success
        assert self.read().data["stock_items"] == []

    def test_single_prepare_preserves_other_links_and_writes_only_on_generic_execute(self):
        assert self.set_links([{"stock_item_id": 7, "qty": 2}]).success
        assert self.set_links([{"stock_item_id": 7, "qty": 4}], api_account_id=2).success
        prepared = self.prepare()
        assert prepared.success, prepared.message
        assert prepared.data["db_write_performed"] is False
        assert prepared.data["api_call_performed"] is False
        assert self.read().data["stock_items"] == [{"stock_item_id": 7, "qty": 2}]
        action = prepared.data["action"]
        assert action["tool"] == "operations.manual_action.prepare"
        assert "Stock Nine" in action["summary"] and "Listing A" in action["summary"]
        payload = action["arguments"]["payload"]
        assert payload["listing_id"] == 51
        assert payload["db_name"] == self.db_path
        assert payload["expected_binding_state"] and payload["expected_stock_state"]
        executed = execute_manual_action(action, audit_path=self.audit)
        assert executed.success, executed.message
        assert executed.data["verify"]["verified"] is True
        assert executed.data["verify"]["listing_id"] == 51
        assert self.read().data["stock_items"] == [{"stock_item_id": 7, "qty": 2}, {"stock_item_id": 9, "qty": 1}]
        assert self.read(listing_id=52, api_account_id=2).data["stock_items"] == [{"stock_item_id": 7, "qty": 4}]
        with Session(get_engine(self.db_path)) as session:
            assert session.get(ListingProduct, 51).stock_item_id == 7

    def test_one_existing_link_changes_its_quantity_without_duplicate_or_replacement(self):
        assert self.set_links([{"stock_item_id": 7, "qty": 2}, {"stock_item_id": 9, "qty": 3}]).success
        result = execute_manual_action(self.prepare(qty=0.5).data["action"], audit_path=self.audit)
        assert result.success, result.message
        assert self.read().data["stock_items"] == [{"stock_item_id": 7, "qty": 2}, {"stock_item_id": 9, "qty": 0.5}]

    def test_exact_listing_identity_and_active_stock_are_required_without_any_write(self):
        for changes in ({"api_account_id": 2}, {"listing_id": 52}, {"product_id": "missing"},
                        {"stock_item_id": 51}, {"stock_item_id": 999}, {"stock_item_id": 11},
                        {"stock_item_id": True}, {"qty": 0}, {"qty": -1}, {"qty": float("nan")},
                        {"qty": float("inf")}, {"qty": True}):
            assert not self.prepare(**changes).success, changes
        assert not self.read(api_account_id=2).success
        with Session(get_engine(self.db_path)) as session:
            assert session.exec(select(ListingProductStockSnapshot)).all() == []
            assert session.get(ListingProduct, 51).stock_item_id is None

    def test_missing_stock_rejects_entire_manual_replacement_and_preserves_prior_links(self):
        assert self.set_links([{"stock_item_id": 7, "qty": 2}]).success
        invalid = self.set_links([{"stock_item_id": 999, "qty": 1}])
        assert not invalid.success and invalid.data["invalid_stock_item_ids"] == [999]
        assert self.read().data["stock_items"] == [{"stock_item_id": 7, "qty": 2}]
        with Session(get_engine(self.db_path)) as session:
            assert session.get(ListingProduct, 51).stock_item_id == 7

    def test_nonempty_malformed_manual_inputs_never_silently_clear_current_links(self):
        assert self.set_links([{"stock_item_id": 7, "qty": 2}]).success
        invalid_rows = [None, {}, {"stock_item_id": "bad", "qty": 1},
            {"stock_item_id": True, "qty": 1}, {"stock_item_id": 9.2, "qty": 1},
            {"stock_item_id": 9, "qty": None}, {"stock_item_id": 9, "qty": True},
            {"stock_item_id": 9, "qty": -1}, {"stock_item_id": 9, "qty": 0},
            {"stock_item_id": 9, "qty": float("nan")}, {"stock_item_id": 9, "qty": float("inf")}]
        for row in invalid_rows:
            assert not self.set_links([row]).success, row
            assert self.read().data["stock_items"] == [{"stock_item_id": 7, "qty": 2}]

    def test_native_single_add_preserves_existing_primary_stock_card(self):
        assert self.set_links([{"stock_item_id": 9, "qty": 2}, {"stock_item_id": 7, "qty": 3}]).success
        prepared = self.prepare(stock_item_id=7, qty=4)
        assert prepared.success, prepared.message
        executed = execute_manual_action(prepared.data["action"], audit_path=self.audit)
        assert executed.success, executed.message
        with Session(get_engine(self.db_path)) as session:
            assert session.get(ListingProduct, 51).stock_item_id == 9

    def test_native_read_and_prepare_results_match_declared_schemas(self):
        for name, result in (("listing.stock_links", self.read()), ("listing.stock_link.prepare", self.prepare())):
            assert result.success, result.message
            Draft202012Validator(listing_stock_tools()[name].result_schema).validate(result.data)

    def test_generic_readback_rejects_primary_pointer_drift_with_unchanged_snapshots(self):
        prepared = self.prepare()
        action = prepared.data["action"]
        assert execute_manual_action(action, audit_path=self.audit).success
        with Session(get_engine(self.db_path)) as session:
            listing = session.get(ListingProduct, 51)
            listing.stock_item_id = 7
            session.add(listing)
            session.commit()
        capability = find_manual_capability("listing.action_set_listing_stock_items")
        verified = verify_listing_manual_action(capability, action, Result.ok())
        assert not verified.success
        assert self.read().data["stock_items"] == [{"stock_item_id": 9, "qty": 1}]

    def test_generic_readback_rejects_account_identity_drift_with_unchanged_snapshots(self):
        prepared = self.prepare()
        action = prepared.data["action"]
        assert execute_manual_action(action, audit_path=self.audit).success
        with Session(get_engine(self.db_path)) as session:
            listing = session.get(ListingProduct, 51)
            listing.product_id = "REPLACED-P"
            session.add(listing)
            session.commit()
        capability = find_manual_capability("listing.action_set_listing_stock_items")
        verified = verify_listing_manual_action(capability, action, Result.ok())
        assert not verified.success

    def test_mapping_drift_after_approval_blocks_without_replacing_new_binding(self):
        prepared = self.prepare()
        assert self.set_links([{"stock_item_id": 7, "qty": 8}]).success
        result = execute_manual_action(prepared.data["action"], audit_path=self.audit)
        assert not result.success
        assert self.read().data["stock_items"] == [{"stock_item_id": 7, "qty": 8}]

    def test_stock_identity_drift_and_listing_identity_drift_block_after_approval(self):
        for model, pk, field, value in ((StockItem, 9, "name", "Renamed Stock"),
                                       (ListingProduct, 51, "title", "Renamed Listing")):
            prepared = self.prepare()
            with Session(get_engine(self.db_path)) as session:
                row = session.get(model, pk)
                setattr(row, field, value)
                session.add(row)
                session.commit()
            result = execute_manual_action(prepared.data["action"], audit_path=self.audit)
            assert not result.success
            assert self.read().data["stock_items"] == []

    def test_snapshot_and_primary_pointer_are_one_transaction(self):
        def reject_listing_update(*_args):
            raise RuntimeError("synthetic_commit_failure")
        event.listen(ListingProduct, "before_update", reject_listing_update)
        try:
            result = self.set_links([{"stock_item_id": 7, "qty": 1}])
        finally:
            event.remove(ListingProduct, "before_update", reject_listing_update)
        assert not result.success
        with Session(get_engine(self.db_path)) as session:
            assert session.exec(select(ListingProductStockSnapshot)).all() == []
            assert session.get(ListingProduct, 51).stock_item_id is None

    def test_manual_full_replace_and_clear_semantics_remain_available(self):
        assert self.set_links([{"stock_item_id": 7, "qty": 1}]).success
        assert self.set_links([{"stock_item_id": 9, "qty": 2}]).success
        assert self.read().data["stock_items"] == [{"stock_item_id": 9, "qty": 2}]
        assert self.set_links([]).success
        assert self.read().data["stock_items"] == []
        with Session(get_engine(self.db_path)) as session:
            assert session.get(ListingProduct, 51).stock_item_id is None


def test_tools_offer_only_exact_identity_read_and_single_link_prepare_contracts():
    tools = listing_stock_tools()
    assert set(tools) == {"listing.stock_links", "listing.stock_link.prepare"}
    prepare = tools["listing.stock_link.prepare"]
    assert prepare.requires_approval and prepare.read_only
    assert prepare.canonical_callable == "Listing.views.actions.action_set_listing_stock_items"
    assert prepare.parameters["required"] == ["listing_id", "api_account_id", "product_id", "stock_item_id"]
    assert "stock_items" not in prepare.parameters["properties"]
