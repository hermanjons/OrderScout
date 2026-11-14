"""Legacy primary-only bindings survive the shared manual/native link editor."""
from pathlib import Path

from sqlmodel import Session, select

from Account.models.models import ApiAccount
from AI.processors.operation_runtime import execute_manual_action
from AI.runtime.listing_stock_contracts import listing_stock_link_prepare, listing_stock_links
from Core.utils.model_utils import get_engine
from Listing.models import ListingProduct, ListingProductStockSnapshot
from Listing.processors.pipeline import get_listings_from_db
from Listing.processors.stock_bindings import preview_listing_stock_link
from Listing.views.actions import action_set_listing_stock_items
from Stock.models import StockItem
from tests.support.db_case import IsolatedDbTestCase


class TestLegacyStockBindings(IsolatedDbTestCase):
    def setUp(self):
        super().setUp()
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="isolated", comp_name="Synthetic", platform="trendyol"))
            session.add_all([StockItem(pk=7, sku="S-7", name="Legacy"),
                             StockItem(pk=9, sku="S-9", name="Selected")])
            session.commit()
            session.add(ListingProduct(pk=51, api_account_id=1, product_id="LEGACY", stock_item_id=7))
            session.commit()
        self.audit = Path(self._tmp_dir.name) / "approved.jsonl"

    def native(self):
        result = listing_stock_links(listing_id=51, api_account_id=1, product_id="LEGACY", db_name=self.db_path)
        assert result.success, result.message
        return result.data["stock_items"]

    def manual(self):
        result = get_listings_from_db(api_account_ids=[1], product_id="LEGACY", db_name=self.db_path)
        assert result.success, result.message
        return result.data["items"][0]

    def prepare(self, **changes):
        return listing_stock_link_prepare(**{"listing_id": 51, "api_account_id": 1,
            "product_id": "LEGACY", "stock_item_id": 9, "qty": 0.5, "db_name": self.db_path, **changes})

    def database_state(self):
        with Session(get_engine(self.db_path)) as session:
            primary = session.get(ListingProduct, 51).stock_item_id
            rows = session.exec(select(ListingProductStockSnapshot).where(
                ListingProductStockSnapshot.listing_id == 51).order_by(ListingProductStockSnapshot.pk)).all()
            return primary, [(row.pk, row.stock_item_id, row.qty, row.status) for row in rows]

    def add_history(self, *rows):
        with Session(get_engine(self.db_path)) as session:
            session.add_all([ListingProductStockSnapshot(listing_id=51, stock_item_id=stock_id, qty=qty, status=status)
                             for stock_id, qty, status in rows])
            session.commit()

    def test_primary_only_read_prepare_and_approved_execute_preserve_primary_and_manual_parity(self):
        expected = [{"stock_item_id": 7, "qty": 1.0}]
        assert self.native() == self.manual()["stock_items"] == expected
        assert self.database_state() == (7, [])
        prepared = self.prepare()
        assert prepared.success, prepared.message
        assert prepared.data["current_stock_items"] == expected
        desired = [*expected, {"stock_item_id": 9, "qty": 0.5}]
        assert prepared.data["desired_stock_items"] == desired
        assert prepared.data["action"]["arguments"]["payload"]["stock_items"] == desired
        assert prepared.data["db_write_performed"] is False and prepared.data["api_call_performed"] is False
        assert self.database_state() == (7, []) and not self.audit.exists()
        executed = execute_manual_action(prepared.data["action"], audit_path=self.audit)
        assert executed.success and executed.data["verify"]["verified"], executed.message
        assert executed.data["verify"]["primary_stock_item_id"] == 7
        assert self.native() == self.manual()["stock_items"] == desired
        assert self.database_state()[0] == 7
        assert [(stock_id, qty, status) for _, stock_id, qty, status in self.database_state()[1]] == [
            (7, 1.0, "append"), (9, 0.5, "append")]

    def test_missing_legacy_primary_stock_fails_prepare_without_replacing_it(self):
        # Simulate an imported legacy database whose dangling pointer predates
        # the current foreign key. No application write may hide that problem.
        with get_engine(self.db_path).connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.exec_driver_sql("UPDATE trendyol_listing_product SET stock_item_id=999 WHERE pk=51")
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        before = self.database_state()
        assert self.native() == self.manual()["stock_items"] == [{"stock_item_id": 999, "qty": 1.0}]
        prepared = self.prepare()
        assert not prepared.success and prepared.data["reason"] == "missing_existing_stock_item"
        assert self.database_state() == before and not self.audit.exists()

    def test_removed_history_does_not_resurrect_a_stale_primary_pointer(self):
        self.add_history((7, 2.0, "remove"))
        before = self.database_state()
        assert self.native() == self.manual()["stock_items"] == []
        prepared = self.prepare()
        assert prepared.success, prepared.message
        assert prepared.data["current_stock_items"] == []
        assert prepared.data["desired_stock_items"] == [{"stock_item_id": 9, "qty": 0.5}]
        assert self.database_state() == before

    def test_explicit_clear_of_primary_only_and_snapshot_bindings_stays_empty(self):
        cleared = action_set_listing_stock_items(api_account_id=1, product_id="LEGACY", stock_items=[], db_name=self.db_path)
        assert cleared.success, cleared.message
        assert self.native() == self.manual()["stock_items"] == []
        assert self.database_state() == (None, [])
        linked = action_set_listing_stock_items(api_account_id=1, product_id="LEGACY",
            stock_items=[{"stock_item_id": 7, "qty": 2}], db_name=self.db_path)
        assert linked.success, linked.message
        assert action_set_listing_stock_items(api_account_id=1, product_id="LEGACY", stock_items=[], db_name=self.db_path).success
        assert self.native() == self.manual()["stock_items"] == []
        assert self.database_state()[0] is None
        assert self.database_state()[1][-1][-1] == "remove"

    def test_modern_history_stays_authoritative_and_normal_payload_primary_order_is_shared(self):
        self.add_history((9, 0.5, "append"))
        # A primary pointer absent from modern history is drift, not a legacy
        # binding to silently add back to the complete snapshot representation.
        assert self.native() == self.manual()["stock_items"] == [{"stock_item_id": 9, "qty": 0.5}]
        preview = preview_listing_stock_link(listing_id=51, api_account_id=1, product_id="LEGACY",
            stock_item_id=9, qty=2, db_name=self.db_path)
        assert preview.success and preview.data["desired_stock_items"] == [{"stock_item_id": 9, "qty": 2.0}]
        self.add_history((7, 3.25, "append"))
        expected = [{"stock_item_id": 7, "qty": 3.25}, {"stock_item_id": 9, "qty": 0.5}]
        assert self.native() == self.manual()["stock_items"] == expected
        assert all(set(row) == {"stock_item_id", "qty"} for row in self.manual()["stock_items"])
        with Session(get_engine(self.db_path)) as session:
            listing = session.get(ListingProduct, 51)
            listing.stock_item_id = 9
            session.add(listing)
            session.commit()
        assert self.native() == self.manual()["stock_items"] == list(reversed(expected))
