from __future__ import annotations

from datetime import datetime
import time
from unittest.mock import patch

from Core.utils.model_utils import get_records
from Account.models.models import ApiAccount
from Finance.models.trendyol.models import Brand, Company
from Listing.models import ListingProduct, ListingProductStockSnapshot
from Orders.models.trendyol.models import OrderHeader
from Stock.models import StockItem, StockTx
import Stock.processors.pipeline as stock_pipeline
from sqlmodel import Session

from tests.support.db_case import IsolatedDbTestCase


class TestStockPipeline(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._db_patch = patch.object(stock_pipeline, "DB_NAME", self.db_path)
        self._db_patch.start()

    def tearDown(self) -> None:
        self._db_patch.stop()
        super().tearDown()

    def _seed_item_and_warehouse(self, *, vat_rate: float | None) -> tuple[int, int]:
        item_res = stock_pipeline.create_item(
            sku="SKU-100",
            name="Test Item",
            vat_rate=vat_rate,
        )
        self.assertTrue(item_res.success, item_res.message)

        warehouse_res = stock_pipeline.create_warehouse(name="Ana Depo")
        self.assertTrue(warehouse_res.success, warehouse_res.message)

        items_res = stock_pipeline.list_items(only_active=True)
        self.assertTrue(items_res.success, items_res.message)
        warehouses_res = stock_pipeline.list_warehouses(only_active=True)
        self.assertTrue(warehouses_res.success, warehouses_res.message)

        item_id = int(getattr((items_res.data or {}).get("records", [])[0], "pk"))
        warehouse_id = int(getattr((warehouses_res.data or {}).get("records", [])[0], "pk"))
        return item_id, warehouse_id

    def test_manual_in_normalizes_net_cost_to_gross_and_exposes_mode(self) -> None:
        item_id, warehouse_id = self._seed_item_and_warehouse(vat_rate=20.0)

        tx_res = stock_pipeline.manual_in(
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=2,
            unit_cost=100.0,
            unit_cost_input_mode="net",
            currency="TRY",
        )
        self.assertTrue(tx_res.success, tx_res.message)

        rows_res = get_records(model=StockTx, db_name=self.db_path)
        self.assertTrue(rows_res.success, rows_res.message)
        rows = (rows_res.data or {}).get("records", []) or []
        self.assertEqual(len(rows), 1)
        tx = rows[0]
        self.assertAlmostEqual(float(getattr(tx, "unit_cost", 0.0) or 0.0), 120.0)
        self.assertEqual(getattr(tx, "unit_cost_input_mode", None), "net")
        self.assertAlmostEqual(float(getattr(tx, "unit_cost_vat_rate", 0.0) or 0.0), 20.0)

        balances_res = stock_pipeline.list_item_balances(warehouse_id=warehouse_id, only_active=True)
        self.assertTrue(balances_res.success, balances_res.message)
        balance_row = ((balances_res.data or {}).get("records", []) or [])[0]
        self.assertAlmostEqual(float(balance_row.get("avg_unit_cost") or 0.0), 120.0)
        self.assertEqual(balance_row.get("avg_cost_input_mode"), "net")

    def test_manual_in_rejects_net_cost_without_item_vat_rate(self) -> None:
        item_id, warehouse_id = self._seed_item_and_warehouse(vat_rate=None)

        tx_res = stock_pipeline.manual_in(
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=1,
            unit_cost=100.0,
            unit_cost_input_mode="net",
            currency="TRY",
        )
        self.assertFalse(tx_res.success)
        self.assertIn("kdv hari", str(tx_res.message or "").casefold())

    def test_manual_out_inherits_active_cost_input_mode(self) -> None:
        item_id, warehouse_id = self._seed_item_and_warehouse(vat_rate=20.0)

        in_res = stock_pipeline.manual_in(
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=2,
            unit_cost=100.0,
            unit_cost_input_mode="net",
            currency="TRY",
        )
        self.assertTrue(in_res.success, in_res.message)

        out_res = stock_pipeline.manual_out(
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=1,
            currency="TRY",
        )
        self.assertTrue(out_res.success, out_res.message)

        rows_res = get_records(model=StockTx, db_name=self.db_path)
        self.assertTrue(rows_res.success, rows_res.message)
        rows = sorted((rows_res.data or {}).get("records", []) or [], key=lambda row: int(getattr(row, "pk", 0) or 0))
        self.assertEqual(len(rows), 2)
        out_tx = rows[-1]
        self.assertEqual(getattr(out_tx, "unit_cost_input_mode", None), "net")
        self.assertAlmostEqual(float(getattr(out_tx, "unit_cost_vat_rate", 0.0) or 0.0), 20.0)

    def test_update_tx_edit_fields_updates_attachments_and_cost_mode(self) -> None:
        item_id, warehouse_id = self._seed_item_and_warehouse(vat_rate=20.0)

        tx_res = stock_pipeline.manual_in(
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=1,
            unit_cost=100.0,
            unit_cost_input_mode="gross",
            currency="TRY",
        )
        self.assertTrue(tx_res.success, tx_res.message)

        edit_res = stock_pipeline.update_tx_edit_fields(
            tx_id=int((tx_res.data or {}).get("tx_id") or 0),
            attachments='["invoice.png"]',
            unit_cost_input_mode="net",
        )
        self.assertTrue(edit_res.success, edit_res.message)

        rows_res = get_records(model=StockTx, db_name=self.db_path)
        self.assertTrue(rows_res.success, rows_res.message)
        tx = ((rows_res.data or {}).get("records", []) or [])[0]
        self.assertEqual(getattr(tx, "attachments", None), '["invoice.png"]')
        self.assertEqual(getattr(tx, "unit_cost_input_mode", None), "net")
        self.assertAlmostEqual(float(getattr(tx, "unit_cost_vat_rate", 0.0) or 0.0), 20.0)

    def test_manual_in_emits_tx_created_signal(self) -> None:
        item_id, warehouse_id = self._seed_item_and_warehouse(vat_rate=20.0)
        captured: list[int] = []

        def _capture(tx_id: int) -> None:
            captured.append(int(tx_id))

        stock_pipeline.stock_signals.tx_created.connect(_capture)
        try:
            tx_res = stock_pipeline.manual_in(
                item_id=item_id,
                warehouse_id=warehouse_id,
                qty=1,
                unit_cost=120.0,
                unit_cost_input_mode="gross",
                currency="TRY",
            )
            self.assertTrue(tx_res.success, tx_res.message)
        finally:
            try:
                stock_pipeline.stock_signals.tx_created.disconnect(_capture)
            except Exception:
                pass

        expected_tx_id = int((tx_res.data or {}).get("tx_id") or 0)
        self.assertEqual(captured, [expected_tx_id])

    def test_quick_access_change_is_debounced_for_duplicate_payloads(self) -> None:
        captured: list[tuple[str, int]] = []

        def _capture(section: str, delta: int) -> None:
            captured.append((str(section), int(delta)))

        stock_pipeline.stock_signals.quick_access_changed.connect(_capture)
        try:
            stock_pipeline._last_quick_access_emit.clear()
            stock_pipeline._emit_quick_access_change("items", 1)
            stock_pipeline._emit_quick_access_change("items", 1)
            time.sleep(0.06)
            stock_pipeline._emit_quick_access_change("items", 1)
        finally:
            try:
                stock_pipeline.stock_signals.quick_access_changed.disconnect(_capture)
            except Exception:
                pass

        self.assertEqual(captured, [("items", 1), ("items", 1)])

    def test_auto_deduct_order_items_only_processes_created_status_and_links_order_header(self) -> None:
        item_id, warehouse_id = self._seed_item_and_warehouse(vat_rate=20.0)

        engine = stock_pipeline._engine()
        with Session(engine) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="TRENDYOL"))
            session.add(OrderHeader(pk=11, orderNumber="ORD-CREATED", api_account_id=1))
            session.add(OrderHeader(pk=12, orderNumber="ORD-SHIPPED", api_account_id=1))
            listing = ListingProduct(
                pk=301,
                api_account_id=1,
                product_id="P-301",
                product_code="9001",
                stock_item_id=item_id,
                title="Demo Listing",
            )
            session.add(listing)
            session.add(
                ListingProductStockSnapshot(
                    listing_id=301,
                    stock_item_id=item_id,
                    qty=2,
                    status="append",
                )
            )
            session.commit()

        stock_pipeline.manual_in(
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=20,
            unit_cost=100.0,
            unit_cost_input_mode="gross",
            currency="TRY",
        )

        res = stock_pipeline.auto_deduct_order_items(
            [
                {
                    "api_account_id": 1,
                    "orderNumber": "ORD-CREATED",
                    "quantity": 3,
                    "productCode": "9001",
                    "orderLineItemStatusName": "Created",
                },
                {
                    "api_account_id": 1,
                    "orderNumber": "ORD-SHIPPED",
                    "quantity": 4,
                    "productCode": "9001",
                    "orderLineItemStatusName": "Shipped",
                },
            ],
            created_by="orders:auto",
        )
        self.assertTrue(res.success, res.message)
        self.assertEqual((res.data or {}).get("tx_created"), 1)

        rows_res = get_records(model=StockTx, db_name=self.db_path)
        self.assertTrue(rows_res.success, rows_res.message)
        rows = sorted((rows_res.data or {}).get("records", []) or [], key=lambda row: int(getattr(row, "pk", 0) or 0))
        order_out_rows = [
            row
            for row in rows
            if str(getattr(row, "reason", "") or "").strip().casefold().endswith("order_out")
        ]
        self.assertEqual(len(order_out_rows), 1)
        tx = order_out_rows[0]
        self.assertAlmostEqual(float(getattr(tx, "qty", 0.0) or 0.0), 6.0)
        self.assertEqual(int(getattr(tx, "order_header_id", 0) or 0), 11)
        self.assertEqual(str(getattr(tx, "order_ref", "") or ""), "ORD-CREATED")

    def test_create_item_links_brand_by_name(self) -> None:
        brand_res = stock_pipeline.create_brand(name="ACME")
        self.assertTrue(brand_res.success, brand_res.message)

        item_res = stock_pipeline.create_item(
            sku="SKU-BRAND-1",
            name="Brand Linked Item",
            brand="ACME",
        )
        self.assertTrue(item_res.success, item_res.message)

        rows_res = get_records(model=StockItem, db_name=self.db_path)
        self.assertTrue(rows_res.success, rows_res.message)
        item = ((rows_res.data or {}).get("records", []) or [])[0]

        self.assertEqual(str(getattr(item, "brand", "") or ""), "ACME")
        self.assertGreater(int(getattr(item, "brand_id", 0) or 0), 0)

    def test_update_brand_syncs_linked_stock_item_label_and_blocks_delete(self) -> None:
        brand_res = stock_pipeline.create_brand(name="ACME")
        self.assertTrue(brand_res.success, brand_res.message)

        brands_res = get_records(model=Brand, db_name=self.db_path)
        self.assertTrue(brands_res.success, brands_res.message)
        brand = ((brands_res.data or {}).get("records", []) or [])[0]
        brand_id = int(getattr(brand, "pk", 0) or 0)

        item_res = stock_pipeline.create_item(
            sku="SKU-BRAND-2",
            name="Linked Brand Item",
            brand="ACME",
        )
        self.assertTrue(item_res.success, item_res.message)

        update_res = stock_pipeline.update_brand(brand_id, {"name": "ACME 2"})
        self.assertTrue(update_res.success, update_res.message)

        rows_res = get_records(model=StockItem, db_name=self.db_path)
        self.assertTrue(rows_res.success, rows_res.message)
        item = ((rows_res.data or {}).get("records", []) or [])[0]
        self.assertEqual(str(getattr(item, "brand", "") or ""), "ACME 2")
        self.assertEqual(int(getattr(item, "brand_id", 0) or 0), brand_id)

        delete_res = stock_pipeline.delete_brand(brand_id)
        self.assertFalse(delete_res.success)
        self.assertIn("stok kart", str(delete_res.message or "").casefold())

    def test_create_tx_links_company_by_counterparty_name(self) -> None:
        item_id, warehouse_id = self._seed_item_and_warehouse(vat_rate=20.0)
        company_res = stock_pipeline.create_company(name="Demo Muhatap")
        self.assertTrue(company_res.success, company_res.message)

        tx_res = stock_pipeline.manual_in(
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=1,
            unit_cost=100.0,
            unit_cost_input_mode="gross",
            currency="TRY",
            counterparty="Demo Muhatap",
        )
        self.assertTrue(tx_res.success, tx_res.message)

        rows_res = get_records(model=StockTx, db_name=self.db_path)
        self.assertTrue(rows_res.success, rows_res.message)
        tx = ((rows_res.data or {}).get("records", []) or [])[0]

        self.assertEqual(str(getattr(tx, "counterparty", "") or ""), "Demo Muhatap")
        self.assertGreater(int(getattr(tx, "company_id", 0) or 0), 0)

    def test_update_company_syncs_linked_stock_tx_label_and_blocks_delete(self) -> None:
        item_id, warehouse_id = self._seed_item_and_warehouse(vat_rate=20.0)
        company_res = stock_pipeline.create_company(name="Demo Muhatap")
        self.assertTrue(company_res.success, company_res.message)

        companies_res = get_records(model=Company, db_name=self.db_path)
        self.assertTrue(companies_res.success, companies_res.message)
        company = ((companies_res.data or {}).get("records", []) or [])[0]
        company_id = int(getattr(company, "pk", 0) or 0)

        tx_res = stock_pipeline.manual_in(
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=1,
            unit_cost=100.0,
            unit_cost_input_mode="gross",
            currency="TRY",
            counterparty="Demo Muhatap",
        )
        self.assertTrue(tx_res.success, tx_res.message)

        update_res = stock_pipeline.update_company(company_id, {"name": "Demo Muhatap 2"})
        self.assertTrue(update_res.success, update_res.message)

        rows_res = get_records(model=StockTx, db_name=self.db_path)
        self.assertTrue(rows_res.success, rows_res.message)
        tx = ((rows_res.data or {}).get("records", []) or [])[0]
        self.assertEqual(str(getattr(tx, "counterparty", "") or ""), "Demo Muhatap 2")
        self.assertEqual(int(getattr(tx, "company_id", 0) or 0), company_id)

        delete_res = stock_pipeline.delete_company(company_id)
        self.assertFalse(delete_res.success)
        self.assertIn("stok hareket", str(delete_res.message or "").casefold())

    def test_get_on_hand_and_balances_respect_warehouse_scope(self) -> None:
        item_id, warehouse_one_id = self._seed_item_and_warehouse(vat_rate=20.0)
        warehouse_two_res = stock_pipeline.create_warehouse(name="Yedek Depo")
        self.assertTrue(warehouse_two_res.success, warehouse_two_res.message)

        warehouses_res = stock_pipeline.list_warehouses(only_active=True)
        self.assertTrue(warehouses_res.success, warehouses_res.message)
        warehouse_ids = [int(getattr(row, "pk", 0) or 0) for row in ((warehouses_res.data or {}).get("records", []) or [])]
        warehouse_two_id = next(wid for wid in warehouse_ids if wid != warehouse_one_id)

        for warehouse_id, qty, unit_cost in (
            (warehouse_one_id, 3, 50.0),
            (warehouse_two_id, 2, 80.0),
        ):
            tx_res = stock_pipeline.manual_in(
                item_id=item_id,
                warehouse_id=warehouse_id,
                qty=qty,
                unit_cost=unit_cost,
                unit_cost_input_mode="gross",
                currency="TRY",
                occurred_at=datetime.utcnow(),
            )
            self.assertTrue(tx_res.success, tx_res.message)

        out_res = stock_pipeline.manual_out(
            item_id=item_id,
            warehouse_id=warehouse_one_id,
            qty=1,
            currency="TRY",
            occurred_at=datetime.utcnow(),
        )
        self.assertTrue(out_res.success, out_res.message)

        overall_res = stock_pipeline.get_on_hand(item_id=item_id)
        self.assertTrue(overall_res.success, overall_res.message)
        self.assertAlmostEqual(float((overall_res.data or {}).get("on_hand") or 0.0), 4.0)

        warehouse_one_res = stock_pipeline.get_on_hand(item_id=item_id, warehouse_id=warehouse_one_id)
        self.assertTrue(warehouse_one_res.success, warehouse_one_res.message)
        self.assertAlmostEqual(float((warehouse_one_res.data or {}).get("on_hand") or 0.0), 2.0)

        balances_one_res = stock_pipeline.list_item_balances(warehouse_id=warehouse_one_id, only_active=True)
        self.assertTrue(balances_one_res.success, balances_one_res.message)
        balance_one = ((balances_one_res.data or {}).get("records", []) or [])[0]
        self.assertAlmostEqual(float(balance_one.get("on_hand") or 0.0), 2.0)
        self.assertAlmostEqual(float(balance_one.get("avg_unit_cost") or 0.0), 50.0)

        balances_all_res = stock_pipeline.list_item_balances(warehouse_id=None, only_active=True)
        self.assertTrue(balances_all_res.success, balances_all_res.message)
        balance_all = ((balances_all_res.data or {}).get("records", []) or [])[0]
        self.assertAlmostEqual(float(balance_all.get("on_hand") or 0.0), 4.0)

    def test_mixed_warehouse_currencies_are_not_combined_into_one_average(self) -> None:
        from AI.processors.tools import stock_inventory_overview

        item_id, warehouse_one_id = self._seed_item_and_warehouse(vat_rate=20.0)
        created = stock_pipeline.create_warehouse(name="Döviz Deposu")
        self.assertTrue(created.success, created.message)
        warehouses = stock_pipeline.list_warehouses(only_active=True)
        self.assertTrue(warehouses.success, warehouses.message)
        warehouse_two_id = next(
            int(row.pk) for row in warehouses.data["records"]
            if int(row.pk) != warehouse_one_id
        )
        for warehouse_id, cost, currency in (
            (warehouse_one_id, 100, "TRY"),
            (warehouse_two_id, 10, "USD"),
        ):
            created = stock_pipeline.manual_in(
                item_id=item_id, warehouse_id=warehouse_id, qty=1,
                unit_cost=cost, unit_cost_input_mode="gross", currency=currency,
            )
            self.assertTrue(created.success, created.message)
        balances = stock_pipeline.list_item_balances(only_active=True)
        self.assertTrue(balances.success, balances.message)
        row = balances.data["records"][0]
        self.assertIsNone(row["avg_unit_cost"])
        self.assertEqual(row["stock_value_by_currency"], {"TRY": 100, "USD": 10})
        overview = stock_inventory_overview(db_name=self.db_path)
        self.assertTrue(overview.success, overview.message)
        self.assertEqual(
            {part["currency"]: part["amount"] for part in overview.data["stock_value_by_currency"]},
            {"TRY": 100, "USD": 10},
        )

    def test_missing_cost_warehouse_does_not_inflate_known_stock_value(self) -> None:
        from AI.processors.tools import stock_inventory_overview

        item_id, warehouse_one_id = self._seed_item_and_warehouse(vat_rate=20.0)
        created = stock_pipeline.create_warehouse(name="Maliyeti Bilinmeyen Depo")
        self.assertTrue(created.success, created.message)
        warehouses = stock_pipeline.list_warehouses(only_active=True)
        warehouse_two_id = next(
            int(row.pk) for row in warehouses.data["records"]
            if int(row.pk) != warehouse_one_id
        )
        for warehouse_id, cost in ((warehouse_one_id, 100), (warehouse_two_id, None)):
            created = stock_pipeline.manual_in(
                item_id=item_id, warehouse_id=warehouse_id, qty=1,
                unit_cost=cost, currency="TRY",
            )
            self.assertTrue(created.success, created.message)
        balances = stock_pipeline.list_item_balances(only_active=True)
        self.assertTrue(balances.success, balances.message)
        row = balances.data["records"][0]
        self.assertIsNone(row["avg_unit_cost"])
        self.assertEqual(row["stock_value_by_currency"], {"TRY": 100})
        self.assertEqual(row["valuation_missing_quantity"], 1)
        overview = stock_inventory_overview(db_name=self.db_path)
        self.assertTrue(overview.success, overview.message)
        self.assertEqual(overview.data["stock_value_by_currency"], [{"currency": "TRY", "amount": 100}])
        self.assertFalse(overview.data["stock_valuation_complete"])
        self.assertEqual(overview.data["valuation_missing_items"], 1)

    def test_update_item_noop_skips_write_and_refresh(self) -> None:
        item_id, _warehouse_id = self._seed_item_and_warehouse(vat_rate=20.0)

        with patch.object(stock_pipeline, "update_records") as update_records, patch.object(
            stock_pipeline, "_emit_refresh"
        ) as emit_refresh:
            res = stock_pipeline.update_item(item_id, {"name": "  Test Item  "})

        self.assertTrue(res.success, res.message)
        self.assertTrue(bool((res.data or {}).get("noop")))
        update_records.assert_not_called()
        emit_refresh.assert_not_called()

    def test_update_brand_noop_skips_write(self) -> None:
        create_res = stock_pipeline.create_brand(name="Acme")
        self.assertTrue(create_res.success, create_res.message)

        brands_res = stock_pipeline.list_brands(only_active=True)
        self.assertTrue(brands_res.success, brands_res.message)
        brand_id = int(getattr((brands_res.data or {}).get("records", [])[0], "pk"))

        with patch.object(stock_pipeline, "update_records") as update_records:
            res = stock_pipeline.update_brand(brand_id, {"name": "  Acme  "})

        self.assertTrue(res.success, res.message)
        self.assertTrue(bool((res.data or {}).get("noop")))
        update_records.assert_not_called()

    def test_list_txs_filtered_returns_empty_for_invalid_direction(self) -> None:
        item_id, warehouse_id = self._seed_item_and_warehouse(vat_rate=20.0)
        tx_res = stock_pipeline.manual_in(
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=1,
            unit_cost=120.0,
            unit_cost_input_mode="gross",
            currency="TRY",
        )
        self.assertTrue(tx_res.success, tx_res.message)

        rows_res = stock_pipeline.list_txs_filtered(direction="sideways")
        self.assertTrue(rows_res.success, rows_res.message)
        self.assertEqual((rows_res.data or {}).get("records"), [])

    def test_create_tx_rejects_missing_item_and_warehouse_early(self) -> None:
        missing_item_res = stock_pipeline.manual_in(
            item_id=999,
            warehouse_id=1,
            qty=1,
            unit_cost=10.0,
            currency="TRY",
        )
        self.assertFalse(missing_item_res.success)
        self.assertIn("stok karti", str(missing_item_res.message or "").casefold())

        item_id, _warehouse_id = self._seed_item_and_warehouse(vat_rate=20.0)
        missing_warehouse_res = stock_pipeline.manual_in(
            item_id=item_id,
            warehouse_id=999,
            qty=1,
            unit_cost=10.0,
            currency="TRY",
        )
        self.assertFalse(missing_warehouse_res.success)
        self.assertIn("depo", str(missing_warehouse_res.message or "").casefold())

    def test_list_txs_returns_latest_rows_with_limit(self) -> None:
        item_id, warehouse_id = self._seed_item_and_warehouse(vat_rate=20.0)

        first_res = stock_pipeline.manual_in(
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=1,
            unit_cost=10.0,
            currency="TRY",
            occurred_at=datetime(2026, 4, 1, 10, 0, 0),
        )
        second_res = stock_pipeline.manual_in(
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=1,
            unit_cost=11.0,
            currency="TRY",
            occurred_at=datetime(2026, 4, 1, 11, 0, 0),
        )
        third_res = stock_pipeline.manual_out(
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=1,
            currency="TRY",
            occurred_at=datetime(2026, 4, 1, 12, 0, 0),
        )
        self.assertTrue(first_res.success, first_res.message)
        self.assertTrue(second_res.success, second_res.message)
        self.assertTrue(third_res.success, third_res.message)

        rows_res = stock_pipeline.list_txs(item_id=item_id, warehouse_id=warehouse_id, limit=2)
        self.assertTrue(rows_res.success, rows_res.message)
        rows = (rows_res.data or {}).get("records", []) or []
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [int(getattr(row, "pk", 0) or 0) for row in rows],
            [
                int((third_res.data or {}).get("tx_id") or 0),
                int((second_res.data or {}).get("tx_id") or 0),
            ],
        )
