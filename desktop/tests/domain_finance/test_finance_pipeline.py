from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlmodel import Session, select

from Account.models.models import ApiAccount
from Feedback.processors.pipeline import Result
from Finance.models.trendyol.models import FinanceCostItem, FinanceCostItemMarketplaceLink
from Logistics.models.models import LogisticsCargoProvider, LogisticsCargoTariff
from Logistics.views.actions import accept_logistics_cargo_provider_record, load_logistics_cargo_providers
from Listing.models.models import ListingProduct, ListingProductCostSnapshot
from Marketplaces.views.actions import accept_marketplace_record
from Finance.processors.trendyol import pipeline as finance_pipeline
from Finance.views import actions as finance_actions
from Core.utils.model_utils import get_engine
from Finance.processors.trendyol.pipeline import (
    get_finance_cargo_invoice_items_from_db,
    get_finance_cargo_invoice_transactions_from_db,
    get_finance_transactions_from_db,
    save_finance_cargo_items_to_db,
    save_finance_transactions_to_db,
    split_finance_date_range,
)
from Finance.views.actions import (
    FINANCE_INCREMENTAL_OVERLAP_MINUTES,
    accept_finance_cargo_tariff,
    accept_finance_cargo_tariffs,
    accept_finance_cost_item,
    delete_finance_cargo_tariff,
    delete_finance_cost_item,
    load_finance_cost_items,
    load_finance_cargo_tariffs,
    load_finance_cargo_invoices_from_db,
    load_finance_transactions_from_db,
    save_finance_cargo_tariff,
    load_finance_invoice_documents_from_db,
    load_finance_dashboard_from_db,
    resolve_finance_sync_plan,
    save_finance_invoice_document,
    save_finance_cost_item,
    save_manual_finance_transaction,
)
from Core.db.models import SOURCE_TYPE_BUILTIN
from tests.support.db_case import IsolatedDbTestCase


class FinancePipelineTests(IsolatedDbTestCase):
    def _accept_trendyol_marketplace(self) -> None:
        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)

    def _seed_account(self) -> None:
        engine = get_engine(self.db_path)
        with Session(engine) as session:
            session.add(
                ApiAccount(
                    account_id="784195",
                    comp_name="MDB",
                    platform="trendyol",
                    api_key="key",
                    api_secret="secret",
                    is_active=True,
                )
            )
            session.commit()

    def _missing_cost_items_default_path(self) -> Path:
        return Path(self._tmp_dir.name) / "__missing_finance_cost_items.default.json"

    def test_finance_transactions_are_saved_and_read_from_db(self):
        self._seed_account()

        res = save_finance_transactions_to_db(
            [
                {
                    "_finance_service": "settlements",
                    "_api_account_id": 1,
                    "_seller_id": "784195",
                    "id": "tx-1",
                    "transactionType": "Sale",
                    "description": "Satis",
                    "transactionDate": 1700000000000,
                    "credit": 100.0,
                    "debt": 0.0,
                    "orderNumber": "1001",
                    "currency": "TRY",
                },
                {
                    "_finance_service": "otherfinancials",
                    "_api_account_id": 1,
                    "_seller_id": "784195",
                    "id": "tx-2",
                    "transactionType": "PaymentOrder",
                    "description": "Odeme",
                    "transactionDate": 1700003600000,
                    "credit": 0.0,
                    "debt": 25.0,
                    "paymentOrderId": "PO-1",
                    "currency": "TRY",
                },
            ],
            db_name=self.db_path,
        )

        self.assertTrue(res.success, msg=res.message)

        rows_res = get_finance_transactions_from_db(db_name=self.db_path)
        self.assertTrue(rows_res.success, msg=rows_res.message)
        rows = rows_res.data["records"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["companyName"], "MDB")
        self.assertEqual({row["serviceKey"] for row in rows}, {"settlements", "otherfinancials"})

        dashboard_res = load_finance_dashboard_from_db(limit=20, db_name=self.db_path)
        self.assertTrue(dashboard_res.success, msg=dashboard_res.message)
        self.assertEqual(len(dashboard_res.data["transaction_table_rows"]), 2)

    def test_finance_cargo_items_are_saved_and_filtered(self):
        self._seed_account()

        tx_res = save_finance_transactions_to_db(
            [
                {
                    "_finance_service": "otherfinancials",
                    "_api_account_id": 1,
                    "_seller_id": "784195",
                    "id": "tx-3",
                    "transactionType": "Kargo Fatura",
                    "description": "Kargo Fatura",
                    "transactionDate": 1700007200000,
                    "debt": 12.5,
                    "credit": 0.0,
                    "commissionInvoiceSerialNumber": "DDF2026001",
                    "currency": "TRY",
                }
            ],
            db_name=self.db_path,
        )
        self.assertTrue(tx_res.success, msg=tx_res.message)

        cargo_res = save_finance_cargo_items_to_db(
            [
                {
                    "_api_account_id": 1,
                    "_seller_id": "784195",
                    "_invoice_serial_number": "DDF2026001",
                    "parcelUniqueId": 555,
                    "orderNumber": "1001",
                    "shipmentPackageType": "Box",
                    "amount": 12.5,
                    "desi": 3.0,
                }
            ],
            db_name=self.db_path,
        )
        self.assertTrue(cargo_res.success, msg=cargo_res.message)

        rows_res = get_finance_cargo_invoice_items_from_db(
            invoice_serial_numbers=["DDF2026001"],
            db_name=self.db_path,
        )
        self.assertTrue(rows_res.success, msg=rows_res.message)
        rows = rows_res.data["records"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["companyName"], "MDB")
        self.assertEqual(rows[0]["invoiceSerialNumber"], "DDF2026001")

        tx_rows_res = get_finance_cargo_invoice_transactions_from_db(db_name=self.db_path)
        self.assertTrue(tx_rows_res.success, msg=tx_rows_res.message)
        tx_rows = tx_rows_res.data["records"]
        self.assertEqual(len(tx_rows), 1)
        self.assertEqual(tx_rows[0]["commissionInvoiceSerialNumber"], "DDF2026001")

        cargo_window_res = load_finance_cargo_invoices_from_db(db_name=self.db_path)
        self.assertTrue(cargo_window_res.success, msg=cargo_window_res.message)
        records = cargo_window_res.data["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["invoiceSerialNumber"], "DDF2026001")
        self.assertEqual(records[0]["itemCount"], 1)
        self.assertEqual(records[0]["orderCount"], 1)

    def test_manual_finance_transactions_are_merged_into_transactions_window(self):
        self._seed_account()

        api_res = save_finance_transactions_to_db(
            [
                {
                    "_finance_service": "settlements",
                    "_api_account_id": 1,
                    "_seller_id": "784195",
                    "id": "tx-api-1",
                    "transactionType": "Sale",
                    "description": "Satis",
                    "transactionDate": 1_700_000_000_000,
                    "credit": 100.0,
                    "debt": 0.0,
                    "currency": "TRY",
                }
            ],
            db_name=self.db_path,
        )
        self.assertTrue(api_res.success, msg=api_res.message)

        manual_res = save_manual_finance_transaction(
            {
                "direction": "expense",
                "transactionDate": 1_700_000_100_000,
                "amount": 2500,
                "currency": "TRY",
                "categoryName": "Dükkan Kirası",
                "counterparty": "Mülk Sahibi",
                "referenceNo": "KIRA-2026-01",
            },
            db_name=self.db_path,
        )
        self.assertTrue(manual_res.success, msg=manual_res.message)

        merged = load_finance_transactions_from_db(db_name=self.db_path)
        self.assertTrue(merged.success, msg=merged.message)
        records = list((merged.data or {}).get("records") or [])
        self.assertEqual(len(records), 2)
        manual = next(row for row in records if row["serviceKey"] == "manual")
        self.assertEqual(manual["transactionType"], "Dükkan Kirası")
        self.assertEqual(manual["debt"], 2500)
        self.assertEqual(manual["netAmount"], -2500)
        service_values = [value for _label, value in (merged.data["metadata"]["service_options"] or [])]
        self.assertIn("manual", service_values)

    def test_invoice_documents_are_separate_from_cargo_invoice_groups(self):
        invoice_file = Path(self._tmp_dir.name) / "official-invoice.pdf"
        invoice_file.write_bytes(b"%PDF-1.4\n%test\n")
        unsupported_file = Path(self._tmp_dir.name) / "not-an-invoice.txt"
        unsupported_file.write_text("not official invoice copy", encoding="utf-8")

        save_res = save_finance_invoice_document(
            {
                "invoiceNumber": "INV-2026-0001",
                "invoiceType": "expense",
                "invoiceDate": 1_700_000_000_000,
                "totalAmount": 1250.5,
                "currency": "TRY",
                "counterparty": "Tedarikçi A",
                "filePath": str(invoice_file),
            },
            db_name=self.db_path,
        )
        self.assertTrue(save_res.success, msg=save_res.message)

        invalid_res = save_finance_invoice_document(
            {
                "invoiceNumber": "INV-2026-0002",
                "invoiceType": "expense",
                "invoiceDate": 1_700_000_000_000,
                "filePath": str(unsupported_file),
            },
            db_name=self.db_path,
        )
        self.assertFalse(invalid_res.success)

        docs = load_finance_invoice_documents_from_db(db_name=self.db_path)
        self.assertTrue(docs.success, msg=docs.message)
        records = list((docs.data or {}).get("records") or [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["invoiceNumber"], "INV-2026-0001")
        self.assertEqual(records[0]["fileName"], "official-invoice.pdf")

        cargo_window_res = load_finance_cargo_invoices_from_db(db_name=self.db_path)
        self.assertTrue(cargo_window_res.success, msg=cargo_window_res.message)
        self.assertEqual(list((cargo_window_res.data or {}).get("records") or []), [])

    def test_finance_date_range_is_split_into_safe_windows(self):
        tz = timezone(timedelta(hours=3))
        start = datetime(2026, 1, 1, tzinfo=tz)
        end = datetime(2026, 2, 1, tzinfo=tz)
        windows = split_finance_date_range(
            int(start.timestamp() * 1000),
            int(end.timestamp() * 1000),
        )

        self.assertGreaterEqual(len(windows), 3)
        for left, right in windows:
            self.assertLessEqual(right - left, int(timedelta(days=14).total_seconds() * 1000))
        self.assertEqual(windows[0][0], int(start.timestamp() * 1000))
        self.assertEqual(windows[-1][1], int(end.timestamp() * 1000))

    def test_finance_sync_plan_starts_with_backfill_when_state_is_empty(self):
        self._seed_account()
        now_ms = 1_770_000_000_000
        state_path = Path(self._tmp_dir.name) / "finance_runtime_state.json"

        plan_res = resolve_finance_sync_plan(
            [{"pk": 1, "seller_id": "784195", "comp_name": "MDB"}],
            now_ms=now_ms,
            state_path=state_path,
            db_name=self.db_path,
        )

        self.assertTrue(plan_res.success, msg=plan_res.message)
        jobs = plan_res.data["jobs"]
        self.assertGreater(len(jobs), 1)
        self.assertEqual(jobs[0]["mode"], "backfill")
        self.assertEqual(jobs[0]["end_ms"], now_ms)
        self.assertTrue(all(job["mode"] == "backfill" for job in jobs))

    def test_finance_sync_plan_uses_incremental_window_after_successful_sync_state(self):
        self._seed_account()
        now_ms = 1_770_000_000_000
        latest_sync_ms = now_ms - 3_600_000
        state_path = Path(self._tmp_dir.name) / "finance_runtime_state.json"
        state_path.write_text(
            json.dumps(
                {
                    "accounts": {
                        "1": {
                            "pk": 1,
                            "seller_id": "784195",
                            "comp_name": "MDB",
                            "latest_sync_ms": latest_sync_ms,
                            "backfill_complete": True,
                            "backfill_cursor_ms": latest_sync_ms,
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        plan_res = resolve_finance_sync_plan(
            [{"pk": 1, "seller_id": "784195", "comp_name": "MDB"}],
            now_ms=now_ms,
            state_path=state_path,
            db_name=self.db_path,
        )

        self.assertTrue(plan_res.success, msg=plan_res.message)
        jobs = plan_res.data["jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["mode"], "incremental")
        self.assertEqual(
            jobs[0]["start_ms"],
            latest_sync_ms - (FINANCE_INCREMENTAL_OVERLAP_MINUTES * 60 * 1000),
        )
        self.assertEqual(jobs[0]["end_ms"], now_ms)

    def test_sync_finance_returns_compact_result_payload(self):
        account = {"pk": 1, "seller_id": "784195", "comp_name": "MDB"}
        settlement_result = Result.ok(
            "ok",
            close_dialog=False,
            data={"records": [], "errors": [], "account_summaries": []},
        )
        other_result = Result.ok(
            "ok",
            close_dialog=False,
            data={
                "records": [
                    {
                        "_finance_service": "otherfinancials",
                        "_api_account_id": 1,
                        "id": "tx-1",
                        "transactionType": "Kargo Fatura",
                        "description": "Kargo Fatura",
                        "transactionDate": 1_700_000_000_000,
                        "commissionInvoiceSerialNumber": "INV-1",
                    }
                ],
                "errors": [],
                "account_summaries": [],
            },
        )
        cargo_result = Result.ok(
            "ok",
            close_dialog=False,
            data={
                "records": [
                    {
                        "_api_account_id": 1,
                        "invoiceSerialNumber": "INV-1",
                        "parcelUniqueId": 42,
                        "shipmentPackageType": "Box",
                    }
                ],
                "errors": [],
                "account_summaries": [],
            },
        )

        with patch.object(finance_pipeline, "fetch_settlements_for_accounts", AsyncMock(return_value=settlement_result)), \
             patch.object(finance_pipeline, "fetch_other_financials_for_accounts", AsyncMock(return_value=other_result)), \
             patch.object(finance_pipeline, "fetch_cargo_invoice_items_for_accounts", AsyncMock(return_value=cargo_result)), \
             patch.object(finance_pipeline, "save_finance_transactions_to_db", return_value=Result.ok("ok", close_dialog=False, data={"counts": {"transactions": 1}})), \
             patch.object(finance_pipeline, "save_finance_cargo_items_to_db", return_value=Result.ok("ok", close_dialog=False, data={"counts": {"cargo_items": 1}})):
            result = asyncio.run(
                finance_pipeline.sync_finance_for_accounts(
                    [account],
                    transaction_date_start=1_700_000_000_000,
                    transaction_date_end=1_700_000_000_001,
                )
            )

        self.assertTrue(result.success, msg=result.message)
        data = result.data or {}
        self.assertNotIn("transaction_records", data)
        self.assertNotIn("cargo_invoice_items", data)
        self.assertEqual(data["counts"]["transactions"], 1)
        self.assertEqual(data["counts"]["cargo_items"], 1)
        self.assertEqual(data["counts"]["cargo_invoices"], 1)

    def test_stage_finance_fetch_preserves_credential_reference_and_environment(self):
        captured_client_kwargs: list[dict] = []

        class _FakeStageFinanceApi:
            def __init__(self, **kwargs):
                captured_client_kwargs.append(dict(kwargs))

            async def get_settlements(self, **_kwargs):
                return Result.ok(
                    "ok",
                    close_dialog=False,
                    data={
                        "content": [{"id": "stage-finance-row-1"}],
                        "page": 0,
                        "totalPages": 1,
                    },
                )

        account = {
            "pk": 1,
            "seller_id": "2738",
            "comp_name": "Stage Finance",
            "api_key": "credential://marketplaces/finance-stage-test",
            "api_secret": "",
            "extra_config": {"environment": "stage"},
        }
        with patch.object(finance_pipeline, "TrendyolFinanceApi", _FakeStageFinanceApi):
            result = asyncio.run(
                finance_pipeline.fetch_settlements_for_accounts(
                    [account],
                    transaction_date_start=1_700_000_000_000,
                    transaction_date_end=1_700_000_000_001,
                    max_pages=1,
                )
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual(len(captured_client_kwargs), 1)
        self.assertEqual(
            captured_client_kwargs[0],
            {
                "api_key_id": None,
                "api_key_secret": None,
                "supplier_id": "2738",
                "environment": "stage",
                "credential_reference": "credential://marketplaces/finance-stage-test",
            },
        )
        data = result.data or {}
        self.assertEqual((data.get("records") or [])[0].get("_environment"), "stage")
        self.assertEqual((data.get("account_summaries") or [])[0].get("environment"), "stage")
        self.assertNotIn(
            "credential://marketplaces/finance-stage-test",
            str(data),
        )

    def test_finance_company_payload_preserves_account_extra_config(self):
        account_record = SimpleNamespace(
            pk=1,
            comp_name="Stage Finance",
            extra_config={
                "environment": "stage",
                "credential_reference": "credential://marketplaces/finance-stage-test",
            },
        )
        account_result = Result.ok(
            "ok",
            close_dialog=False,
            data={
                "records": [account_record],
                "accounts": [
                    [
                        1,
                        "credential://marketplaces/finance-stage-test",
                        None,
                        "2738",
                        None,
                        dict(account_record.extra_config),
                    ]
                ],
            },
        )
        with patch.object(
            finance_actions,
            "get_company_by_id",
            return_value=account_result,
        ):
            result = finance_actions._collect_account_payload_for_company_pks([1])

        self.assertTrue(result.success, result.message)
        account = ((result.data or {}).get("accounts") or [])[0]
        self.assertEqual(account.get("seller_id"), "2738")
        self.assertEqual(account.get("extra_config"), account_record.extra_config)

    def test_finance_cost_item_can_be_saved_loaded_and_deleted(self):
        self._accept_trendyol_marketplace()
        save_res = save_finance_cost_item(
            {
                "name": "Paketleme",
                "description": "Kutu ve ambalaj maliyeti",
                "valueType": "numeric",
                "defaultAmount": 12.5,
                "supportedPlatforms": ["TRENDYOL"],
                "isVatIncluded": False,
                "vatRate": 20,
                "isActive": True,
            },
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertTrue(save_res.success, msg=save_res.message)
        record = dict((save_res.data or {}).get("record") or {})
        self.assertEqual(record["name"], "Paketleme")
        self.assertEqual(record["valueType"], "numeric")
        self.assertEqual(record["defaultMatchMode"], "manual")
        self.assertEqual(record["defaultSourceType"], "manual_value")
        self.assertEqual(record["supportedSourceTypes"], ["manual_value"])
        self.assertEqual(record["supportedPlatforms"], ["TRENDYOL"])
        self.assertEqual(record["currency"], "TRY")
        self.assertFalse(record["isVatIncluded"])
        self.assertEqual(record["vatRate"], 20)

        load_res = load_finance_cost_items(
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertTrue(load_res.success, msg=load_res.message)
        records = list((load_res.data or {}).get("records") or [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "Paketleme")
        self.assertEqual(records[0]["currency"], "TRY")
        engine = get_engine(self.db_path)
        with Session(engine) as session:
            db_rows = session.exec(select(FinanceCostItem)).all()
            link_rows = session.exec(select(FinanceCostItemMarketplaceLink)).all()
        self.assertEqual(len(db_rows), 1)
        self.assertEqual(db_rows[0].supportedPlatformsJson, '["TRENDYOL"]')
        self.assertEqual(db_rows[0].supportedPlatformSourceIdsJson, "[1]")
        self.assertEqual(len(link_rows), 1)
        self.assertGreater(int(link_rows[0].sourceId or 0), 0)

        delete_res = delete_finance_cost_item(
            int(record["pk"]),
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertTrue(delete_res.success, msg=delete_res.message)

        post_delete = load_finance_cost_items(
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertTrue(post_delete.success, msg=post_delete.message)
        self.assertEqual(len((post_delete.data or {}).get("records") or []), 0)

    def test_finance_cost_item_db_save_requires_accepted_platform(self):
        save_res = save_finance_cost_item(
            {
                "name": "Paketleme",
                "description": "Kutu ve ambalaj maliyeti",
                "valueType": "numeric",
                "defaultAmount": 12.5,
                "supportedPlatforms": ["TRENDYOL"],
                "isVatIncluded": False,
                "vatRate": 20,
                "isActive": True,
            },
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertFalse(save_res.success)
        self.assertIn("pazaryerlerini", save_res.message)

    def test_finance_cost_item_user_cards_are_forced_to_manual_source(self):
        self._accept_trendyol_marketplace()
        save_res = save_finance_cost_item(
            {
                "name": "Paketleme",
                "description": "Kutu ve ambalaj maliyeti",
                "valueType": "numeric",
                "defaultAmount": 12.5,
                "supportedPlatforms": ["TRENDYOL"],
                "isVatIncluded": False,
                "vatRate": 20,
                "supportedSourceTypes": ["manual_value", "db_field"],
                "defaultSourceType": "db_field",
                "isActive": True,
            },
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertTrue(save_res.success, msg=save_res.message)
        record = dict((save_res.data or {}).get("record") or {})
        self.assertEqual(record["supportedSourceTypes"], ["manual_value"])
        self.assertEqual(record["defaultSourceType"], "manual_value")
        self.assertIsNone(record["defaultSourceConfig"])

    def test_finance_cost_item_persists_explicit_currency(self):
        self._accept_trendyol_marketplace()
        save_res = save_finance_cost_item(
            {
                "name": "Yurtdisi Paketleme",
                "description": "USD bazli paketleme",
                "valueType": "numeric",
                "defaultAmount": 3.5,
                "supportedPlatforms": ["TRENDYOL"],
                "currency": "USD",
                "isVatIncluded": True,
                "vatRate": 20,
                "isActive": True,
            },
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertTrue(save_res.success, msg=save_res.message)
        record = dict((save_res.data or {}).get("record") or {})
        self.assertEqual(record["currency"], "USD")

        load_res = load_finance_cost_items(
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertTrue(load_res.success, msg=load_res.message)
        loaded = list((load_res.data or {}).get("records") or [])
        self.assertEqual(loaded[0]["currency"], "USD")

    def test_finance_cost_item_rejects_user_selected_builtin_resolver(self):
        self._accept_trendyol_marketplace()
        save_res = save_finance_cost_item(
            {
                "name": "Paketleme",
                "description": "Kutu ve ambalaj maliyeti",
                "valueType": "numeric",
                "defaultAmount": 12.5,
                "supportedPlatforms": ["TRENDYOL"],
                "isVatIncluded": False,
                "vatRate": 20,
                "supportedSourceTypes": ["manual_value", "builtin_resolver"],
                "defaultSourceType": "builtin_resolver",
                "isActive": True,
            },
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertFalse(save_res.success)
        self.assertIn("sistem", save_res.message.casefold())

    def test_finance_cost_item_filters_accept_switch_select_all_value(self):
        self._accept_trendyol_marketplace()
        save_res = save_finance_cost_item(
            {
                "name": "Balonlu Naylon",
                "description": "Koruyucu ambalaj",
                "valueType": "numeric",
                "defaultAmount": 4.5,
                "supportedPlatforms": ["TRENDYOL"],
                "isVatIncluded": True,
                "vatRate": 20,
                "isActive": True,
            },
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertTrue(save_res.success, msg=save_res.message)

        load_res = load_finance_cost_items(
            db_name=self.db_path,
            calculation_type="all",
            active_state="all",
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertTrue(load_res.success, msg=load_res.message)
        records = list((load_res.data or {}).get("records") or [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "Balonlu Naylon")

    def test_finance_cost_item_requires_vat_rate_for_any_price_mode(self):
        self._accept_trendyol_marketplace()
        save_res = save_finance_cost_item(
            {
                "name": "Komisyon",
                "description": "Yüzdesel komisyon",
                "valueType": "numeric",
                "defaultAmount": 21,
                "supportedPlatforms": ["TRENDYOL"],
                "isVatIncluded": False,
                "vatRate": "",
                "isActive": True,
            },
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertFalse(save_res.success)
        self.assertIn("KDV", save_res.message)

        save_res_included = save_finance_cost_item(
            {
                "name": "Paketleme",
                "description": "KDV dahil fiyat",
                "valueType": "numeric",
                "defaultAmount": 21,
                "supportedPlatforms": ["TRENDYOL"],
                "isVatIncluded": True,
                "vatRate": "",
                "isActive": True,
            },
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertFalse(save_res_included.success)
        self.assertIn("KDV", save_res_included.message)

    def test_finance_cost_item_builtin_rule_card_is_loaded_from_defaults(self):
        default_path = Path(self._tmp_dir.name) / "finance_cost_items.default.json"
        default_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "source_id": 1,
                            "costKey": "kargo",
                            "name": "Kargo",
                            "description": "Tarifeden hesaplanan kargo maliyeti",
                            "valueType": "numeric",
                            "defaultMatchMode": "automatic",
                            "supportedPlatforms": ["TRENDYOL"],
                            "supportedSourceTypes": ["manual_value", "builtin_resolver"],
                            "defaultSourceType": "builtin_resolver",
                            "defaultSourceConfig": {"ruleKey": "cargo_amount_matcher"},
                            "defaultAmount": None,
                            "currency": "TRY",
                            "isVatIncluded": True,
                            "vatRate": 20,
                            "isActive": True
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        load_res = load_finance_cost_items(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(load_res.success, msg=load_res.message)
        self.assertEqual(list((load_res.data or {}).get("records") or []), [])

        self._accept_trendyol_marketplace()

        load_res = load_finance_cost_items(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(load_res.success, msg=load_res.message)
        record = list((load_res.data or {}).get("records") or [])[0]
        self.assertEqual(record["valueType"], "numeric")
        self.assertEqual(record["defaultMatchMode"], "automatic")
        self.assertEqual(record["defaultSourceType"], "builtin_resolver")
        self.assertEqual(record["defaultSourceConfig"], {"ruleKey": "cargo_amount_matcher"})
        self.assertEqual(record["supportedSourceTypes"], ["manual_value", "builtin_resolver"])
        self.assertTrue(record["isSystemRuleCard"])
        self.assertEqual(record["supportedPlatforms"], ["TRENDYOL"])
        self.assertIsNone(record["defaultAmount"])
        self.assertTrue(record["isVatIncluded"])
        self.assertEqual(record["vatRate"], 20)

    def test_finance_cost_item_percentage_keeps_vat_fields_when_excluded(self):
        self._accept_trendyol_marketplace()
        save_res = save_finance_cost_item(
            {
                "name": "Komisyon",
                "description": "Satıştan yüzdesel komisyon",
                "valueType": "percentage",
                "defaultAmount": 10,
                "supportedPlatforms": ["TRENDYOL"],
                "isVatIncluded": False,
                "vatRate": 20,
                "isActive": True,
            },
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertTrue(save_res.success, msg=save_res.message)
        record = dict((save_res.data or {}).get("record") or {})
        self.assertEqual(record["valueType"], "percentage")
        self.assertEqual(record["defaultAmount"], 10.0)
        self.assertFalse(record["isVatIncluded"])
        self.assertEqual(record["vatRate"], 20.0)
        self.assertEqual(record["amountModeText"], "KDV hariç")

    def test_finance_cost_item_percentage_keeps_vat_fields_when_included(self):
        self._accept_trendyol_marketplace()
        save_res = save_finance_cost_item(
            {
                "name": "Komisyon Dahil",
                "description": "Satıştan yüzdesel komisyon",
                "valueType": "percentage",
                "defaultAmount": 12,
                "supportedPlatforms": ["TRENDYOL"],
                "isVatIncluded": True,
                "vatRate": 20,
                "isActive": True,
            },
            db_name=self.db_path,
            default_storage_path=self._missing_cost_items_default_path(),
        )
        self.assertTrue(save_res.success, msg=save_res.message)
        record = dict((save_res.data or {}).get("record") or {})
        self.assertTrue(record["isVatIncluded"])
        self.assertEqual(record["vatRate"], 20.0)
        self.assertEqual(record["amountModeText"], "KDV dahil")

    def test_finance_cost_items_merge_defaults_allow_declared_field_overrides(self):
        self._accept_trendyol_marketplace()
        default_path = Path(self._tmp_dir.name) / "finance_cost_items.default.json"
        default_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "source_id": 1,
                            "costKey": "paketleme",
                            "name": "Paketleme",
                            "description": "Varsayılan kayıt",
                            "valueType": "numeric",
                            "defaultMatchMode": "manual",
                            "supportedPlatforms": ["TRENDYOL"],
                            "editableFields": ["name", "description", "defaultAmount", "isVatIncluded", "isActive"],
                            "defaultAmount": None,
                            "isVatIncluded": False,
                            "vatRate": 20,
                            "isActive": True,
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        initial = load_finance_cost_items(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(initial.success, msg=initial.message)
        initial_records = list((initial.data or {}).get("records") or [])
        self.assertEqual(len(initial_records), 1)
        self.assertTrue(initial_records[0]["isBuiltin"])
        self.assertFalse(initial_records[0]["isBuiltinAccepted"])
        self.assertEqual(initial_records[0]["pk"], 1)
        self.assertEqual(initial_records[0]["defaultSourceType"], "manual_value")
        self.assertEqual(initial_records[0]["currency"], "TRY")

        save_res = save_finance_cost_item(
            {
                "pk": 1,
                "costKey": "paketleme",
                "name": "Paketleme Güncel",
                "description": "Kullanıcı override",
                "valueType": "numeric",
                "defaultMatchMode": "manual",
                "defaultAmount": 18.75,
                "supportedPlatforms": ["TRENDYOL"],
                "isVatIncluded": True,
                "vatRate": 20,
                "isActive": False,
            },
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(save_res.success, msg=save_res.message)

        merged = load_finance_cost_items(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(merged.success, msg=merged.message)
        merged_records = list((merged.data or {}).get("records") or [])
        self.assertEqual(len(merged_records), 1)
        self.assertEqual(merged_records[0]["name"], "Paketleme Güncel")
        self.assertEqual(merged_records[0]["description"], "Kullanıcı override")
        self.assertEqual(merged_records[0]["defaultAmount"], 18.75)
        self.assertTrue(merged_records[0]["isVatIncluded"])
        self.assertFalse(merged_records[0]["isActive"])
        self.assertEqual(merged_records[0]["currency"], "TRY")
        self.assertTrue(merged_records[0]["isBuiltinAccepted"])

        delete_res = delete_finance_cost_item(
            1,
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertFalse(delete_res.success)
        self.assertIn("silinemez", delete_res.message.lower())

        after_delete = load_finance_cost_items(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(after_delete.success, msg=after_delete.message)
        after_delete_records = list((after_delete.data or {}).get("records") or [])
        self.assertEqual(len(after_delete_records), 1)
        self.assertEqual(after_delete_records[0]["name"], "Paketleme Güncel")
        self.assertTrue(after_delete_records[0]["isBuiltin"])

        engine = get_engine(self.db_path)
        with Session(engine) as session:
            deleted_rows = session.exec(select(FinanceCostItem).where(FinanceCostItem.isDeleted == True)).all()
        self.assertNotIn("paketleme", [row.costKey for row in deleted_rows])

    def test_finance_cost_items_merge_builtin_json_with_db_user_records(self):
        self._accept_trendyol_marketplace()
        default_path = Path(self._tmp_dir.name) / "finance_cost_items.default.json"
        default_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "source_id": 1,
                            "costKey": "kargo",
                            "name": "Kargo",
                            "description": "Varsayılan kural tabanlı kart",
                            "valueType": "numeric",
                            "defaultMatchMode": "automatic",
                            "supportedPlatforms": ["TRENDYOL"],
                            "supportedSourceTypes": ["manual_value", "builtin_resolver"],
                            "defaultSourceType": "builtin_resolver",
                            "defaultSourceConfig": {"ruleKey": "cargo_amount_matcher"},
                            "defaultAmount": None,
                            "currency": "TRY",
                            "isVatIncluded": True,
                            "vatRate": 20,
                            "isActive": True,
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        save_res = save_finance_cost_item(
            {
                "name": "Paketleme",
                "description": "DB user kartı",
                "valueType": "numeric",
                "defaultAmount": 3,
                "supportedPlatforms": ["TRENDYOL"],
                "currency": "TRY",
                "isVatIncluded": False,
                "vatRate": 20,
                "isActive": True,
            },
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(save_res.success, msg=save_res.message)

        engine = get_engine(self.db_path)
        with Session(engine) as session:
            db_rows = session.exec(select(FinanceCostItem).order_by(FinanceCostItem.pk.asc())).all()
        self.assertEqual(len(db_rows), 1)
        self.assertEqual(db_rows[0].costKey, "paketleme")

        load_res = load_finance_cost_items(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(load_res.success, msg=load_res.message)
        records = list((load_res.data or {}).get("records") or [])
        self.assertEqual({row["costKey"] for row in records}, {"kargo", "paketleme"})
        cargo = next(row for row in records if row["costKey"] == "kargo")
        package = next(row for row in records if row["costKey"] == "paketleme")
        self.assertTrue(cargo["isBuiltin"])
        self.assertFalse(cargo["isBuiltinAccepted"])
        self.assertEqual(cargo["defaultSourceConfig"], {"ruleKey": "cargo_amount_matcher"})
        self.assertFalse(package["isBuiltin"])
        self.assertEqual(package["defaultAmount"], 3.0)

    def test_accept_finance_cost_item_persists_builtin_template_to_db(self):
        self._accept_trendyol_marketplace()
        default_path = Path(self._tmp_dir.name) / "finance_cost_items.default.json"
        default_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "source_id": 1,
                            "costKey": "komisyon",
                            "name": "Komisyon",
                            "description": "Önerilen kart",
                            "valueType": "percentage",
                            "defaultMatchMode": "manual",
                            "supportedPlatforms": ["TRENDYOL"],
                            "supportedSourceTypes": ["manual_value"],
                            "defaultSourceType": "manual_value",
                            "defaultAmount": 12,
                            "currency": "TRY",
                            "isVatIncluded": True,
                            "vatRate": 20,
                            "isActive": True,
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        initial = load_finance_cost_items(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(initial.success, msg=initial.message)
        initial_record = list((initial.data or {}).get("records") or [])[0]
        self.assertTrue(initial_record["isBuiltin"])
        self.assertFalse(initial_record["isBuiltinAccepted"])

        accept_res = accept_finance_cost_item(
            1,
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(accept_res.success, msg=accept_res.message)

        engine = get_engine(self.db_path)
        with Session(engine) as session:
            db_rows = session.exec(select(FinanceCostItem).order_by(FinanceCostItem.pk.asc())).all()
            link_rows = session.exec(select(FinanceCostItemMarketplaceLink).order_by(FinanceCostItemMarketplaceLink.pk.asc())).all()
        self.assertEqual(len(db_rows), 1)
        self.assertEqual(db_rows[0].costKey, "komisyon")
        self.assertEqual(db_rows[0].supportedPlatformsJson, '["TRENDYOL"]')
        self.assertEqual(db_rows[0].supportedPlatformSourceIdsJson, "[1]")
        self.assertEqual(db_rows[0].sourceType, SOURCE_TYPE_BUILTIN)
        self.assertEqual(
            db_rows[0].sourceId,
            1,
        )
        self.assertEqual(len(link_rows), 1)
        self.assertGreater(int(link_rows[0].sourceId or 0), 0)

        after = load_finance_cost_items(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(after.success, msg=after.message)
        after_record = list((after.data or {}).get("records") or [])[0]
        self.assertTrue(after_record["isBuiltin"])
        self.assertTrue(after_record["isBuiltinAccepted"])

    def test_accept_finance_cost_item_does_not_delete_referenced_cost_items(self):
        self._accept_trendyol_marketplace()
        default_path = Path(self._tmp_dir.name) / "finance_cost_items.default.json"
        default_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "source_id": 1,
                            "costKey": "komisyon",
                            "name": "Komisyon",
                            "description": "Önerilen kart",
                            "valueType": "percentage",
                            "defaultMatchMode": "manual",
                            "supportedPlatforms": ["TRENDYOL"],
                            "supportedSourceTypes": ["manual_value"],
                            "defaultSourceType": "manual_value",
                            "defaultAmount": 12,
                            "currency": "TRY",
                            "isVatIncluded": True,
                            "vatRate": 20,
                            "isActive": True,
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self._seed_account()
        engine = get_engine(self.db_path)
        with Session(engine) as session:
            session.add(
                FinanceCostItem(
                    pk=1004,
                    costKey="paketleme",
                    name="Paketleme",
                    description="Mevcut kart",
                    valueType="numeric",
                    defaultMatchMode="manual",
                    defaultAmount=3.0,
                    currency="TRY",
                    isVatIncluded=True,
                    vatRate=20,
                    supportedSourceTypesJson='["manual_value"]',
                    supportedPlatformsJson='["TRENDYOL"]',
                    defaultSourceType="manual_value",
                    defaultSourceConfigJson=None,
                    isActive=True,
                    isDeleted=False,
                    createdAt="2026-04-07T00:00:00",
                    updatedAt="2026-04-07T00:00:00",
                )
            )
            session.add(
                ListingProduct(
                    pk=624,
                    api_account_id=1,
                    product_id="listing-624",
                    title="Test Ilan",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            session.add(
                ListingProductCostSnapshot(
                    cost_item_id=1004,
                    listing_id=624,
                    cost_key="paketleme",
                    source_type="manual_value",
                    source_config={"amount": 3.0},
                    resolved_amount=3.0,
                    currency="TRY",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            session.commit()

        accept_res = accept_finance_cost_item(
            1,
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(accept_res.success, msg=accept_res.message)

        with Session(engine) as session:
            db_rows = session.exec(select(FinanceCostItem).order_by(FinanceCostItem.pk.asc())).all()
            snapshot = session.exec(select(ListingProductCostSnapshot)).one()
        self.assertEqual([row.costKey for row in db_rows], ["komisyon", "paketleme"])
        self.assertEqual(snapshot.cost_item_id, 1004)

    def test_accepting_multiple_builtin_cost_items_on_same_marketplace_keeps_link_source_ids_unique(self):
        self._accept_trendyol_marketplace()
        default_path = Path(self._tmp_dir.name) / "finance_cost_items.default.json"
        default_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "source_id": 1,
                            "costKey": "komisyon",
                            "name": "Komisyon",
                            "description": "Önerilen kart",
                            "valueType": "percentage",
                            "defaultMatchMode": "manual",
                            "supportedPlatformSourceIds": [1],
                            "supportedSourceTypes": ["manual_value"],
                            "defaultSourceType": "manual_value",
                            "defaultAmount": 12,
                            "currency": "TRY",
                            "isVatIncluded": True,
                            "vatRate": 20,
                            "isActive": True,
                        },
                        {
                            "source_id": 2,
                            "costKey": "paketleme",
                            "name": "Paketleme",
                            "description": "İkinci önerilen kart",
                            "valueType": "numeric",
                            "defaultMatchMode": "manual",
                            "supportedPlatformSourceIds": [1],
                            "supportedSourceTypes": ["manual_value"],
                            "defaultSourceType": "manual_value",
                            "defaultAmount": 4,
                            "currency": "TRY",
                            "isVatIncluded": True,
                            "vatRate": 20,
                            "isActive": True,
                        },
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        first_accept = accept_finance_cost_item(1, db_name=self.db_path, default_storage_path=default_path)
        second_accept = accept_finance_cost_item(2, db_name=self.db_path, default_storage_path=default_path)
        self.assertTrue(first_accept.success, msg=first_accept.message)
        self.assertTrue(second_accept.success, msg=second_accept.message)

        engine = get_engine(self.db_path)
        with Session(engine) as session:
            link_rows = session.exec(
                select(FinanceCostItemMarketplaceLink).order_by(FinanceCostItemMarketplaceLink.pk.asc())
            ).all()
        self.assertEqual(len(link_rows), 2)
        self.assertEqual(len({int(row.sourceId or 0) for row in link_rows}), 2)

    def test_finance_cargo_tariff_can_be_saved_loaded_and_deleted(self):
        storage_path = Path(self._tmp_dir.name) / "finance_cargo_tariffs.json"
        save_res = save_finance_cargo_tariff(
            {
                "name": "Trendyol Express 0-5 Desi",
                "description": "Standart ilk barem",
                "platform": "TRENDYOL",
                "cargoProviderCode": "TEXMP",
                "minDesi": 0,
                "maxDesi": 5,
                "minSalePrice": 0,
                "maxSalePrice": 300,
                "amount": 54.9,
                "currency": "TRY",
                "isVatIncluded": False,
                "vatRate": 20,
                "isActive": True,
            },
            storage_path=storage_path,
        )
        self.assertTrue(save_res.success, msg=save_res.message)
        record = dict((save_res.data or {}).get("record") or {})
        self.assertEqual(record["name"], "Trendyol Express 0-5 Desi")
        self.assertEqual(record["cargoProviderCode"], "TEXMP")
        self.assertFalse(record["isVatIncluded"])
        self.assertEqual(record["vatRate"], 20)

        load_res = load_finance_cargo_tariffs(storage_path=storage_path)
        self.assertTrue(load_res.success, msg=load_res.message)
        records = list((load_res.data or {}).get("records") or [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["platform"], "Trendyol")
        self.assertEqual(records[0]["amount"], 54.9)
        self.assertEqual(records[0]["amountModeText"], "KDV hariç (%20)")

        delete_res = delete_finance_cargo_tariff(int(record["pk"]), storage_path=storage_path)
        self.assertTrue(delete_res.success, msg=delete_res.message)

        post_delete = load_finance_cargo_tariffs(storage_path=storage_path)
        self.assertTrue(post_delete.success, msg=post_delete.message)
        self.assertEqual(len((post_delete.data or {}).get("records") or []), 0)

    def test_finance_cargo_tariff_db_save_materializes_provider_and_sets_fk(self):
        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)

        provider_rows = load_logistics_cargo_providers(platform_code="TRENDYOL", search="texmp", db_name=self.db_path)
        self.assertTrue(provider_rows.success, provider_rows.message)
        builtin_provider = next(
            (
                row
                for row in list((provider_rows.data or {}).get("records") or [])
                if str(row.get("cargoProviderCode") or "") == "TEXMP"
            ),
            None,
        )
        self.assertIsNotNone(builtin_provider)
        accept_provider = accept_logistics_cargo_provider_record(dict(builtin_provider or {}), db_name=self.db_path)
        self.assertTrue(accept_provider.success, accept_provider.message)

        save_res = save_finance_cargo_tariff(
            {
                "name": "Trendyol Express 0-5 Desi",
                "description": "Standart ilk barem",
                "platform": "TRENDYOL",
                "cargoProviderCode": "TEXMP",
                "cargoProviderName": "Trendyol Express Marketplace",
                "minDesi": 0,
                "maxDesi": 5,
                "minSalePrice": 0,
                "maxSalePrice": 300,
                "amount": 54.9,
                "currency": "TRY",
                "isVatIncluded": False,
                "vatRate": 20,
                "isActive": True,
            },
            db_name=self.db_path,
        )
        self.assertTrue(save_res.success, msg=save_res.message)

        engine = get_engine(self.db_path)
        with Session(engine) as session:
            provider_rows = session.exec(select(LogisticsCargoProvider).order_by(LogisticsCargoProvider.pk.asc())).all()
            tariff_rows = session.exec(select(LogisticsCargoTariff).order_by(LogisticsCargoTariff.pk.asc())).all()
        self.assertEqual(len(provider_rows), 1)
        self.assertEqual(provider_rows[0].cargoProviderCode, "TEXMP")
        self.assertEqual(len(tariff_rows), 1)
        self.assertEqual(tariff_rows[0].cargo_provider_id, provider_rows[0].pk)

    def test_finance_cargo_tariff_ignores_hidden_sale_price_fields_for_platform(self):
        storage_path = Path(self._tmp_dir.name) / "finance_cargo_tariffs.json"
        save_res = save_finance_cargo_tariff(
            {
                "name": "HB 0-5 Desi",
                "platform": "HEPSIBURADA",
                "cargoProviderCode": "TEXMP",
                "minDesi": 0,
                "maxDesi": 5,
                "minSalePrice": 0,
                "maxSalePrice": 300,
                "amount": 54.9,
                "currency": "TRY",
                "isVatIncluded": True,
                "isActive": True,
            },
            storage_path=storage_path,
        )
        self.assertTrue(save_res.success, msg=save_res.message)
        record = dict((save_res.data or {}).get("record") or {})
        self.assertIsNone(record["minSalePrice"])
        self.assertIsNone(record["maxSalePrice"])

    def test_finance_cargo_tariffs_merge_defaults_override_and_delete(self):
        storage_path = Path(self._tmp_dir.name) / "finance_cargo_tariffs.json"
        default_path = Path(self._tmp_dir.name) / "finance_cargo_tariffs.default.json"
        default_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "source_id": 1,
                            "tariffKey": "trendyol-express-0-5-desi",
                            "name": "Trendyol Express 0-5 Desi",
                            "description": "Varsayılan tarife",
                            "platform": "TRENDYOL",
                            "cargoProviderCode": "TEXMP",
                            "cargoProviderName": "Trendyol Express Marketplace",
                            "minDesi": 0,
                            "maxDesi": 5,
                            "minSalePrice": 0,
                            "maxSalePrice": 300,
                            "amount": None,
                            "currency": "TRY",
                            "isVatIncluded": True,
                            "vatRate": None,
                            "isActive": False,
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        initial = load_finance_cargo_tariffs(
            storage_path=storage_path,
            default_storage_path=default_path,
        )
        self.assertTrue(initial.success, msg=initial.message)
        initial_records = list((initial.data or {}).get("records") or [])
        self.assertEqual(len(initial_records), 1)
        self.assertTrue(initial_records[0]["isBuiltin"])
        self.assertFalse(initial_records[0]["isBuiltinAccepted"])
        self.assertEqual(initial_records[0]["pk"], 1)

        save_res = save_finance_cargo_tariff(
            {
                "pk": 1,
                "tariffKey": "trendyol-express-0-5-desi",
                "name": "Trendyol Express 0-5 Desi Güncel",
                "description": "Kullanıcı override",
                "platform": "TRENDYOL",
                "cargoProviderCode": "TEXMP",
                "minDesi": 0,
                "maxDesi": 5,
                "minSalePrice": 0,
                "maxSalePrice": 300,
                "amount": 49.9,
                "currency": "TRY",
                "isVatIncluded": True,
                "vatRate": None,
                "isActive": True,
            },
            storage_path=storage_path,
            default_storage_path=default_path,
        )
        self.assertTrue(save_res.success, msg=save_res.message)

        merged = load_finance_cargo_tariffs(
            storage_path=storage_path,
            default_storage_path=default_path,
        )
        self.assertTrue(merged.success, msg=merged.message)
        merged_records = list((merged.data or {}).get("records") or [])
        self.assertEqual(len(merged_records), 1)
        self.assertEqual(merged_records[0]["name"], "Trendyol Express 0-5 Desi Güncel")
        self.assertEqual(merged_records[0]["amount"], 49.9)
        self.assertTrue(merged_records[0]["isActive"])
        self.assertTrue(merged_records[0]["isBuiltinAccepted"])

        delete_res = delete_finance_cargo_tariff(
            1,
            storage_path=storage_path,
            default_storage_path=default_path,
        )
        self.assertTrue(delete_res.success, msg=delete_res.message)

        after_delete = load_finance_cargo_tariffs(
            storage_path=storage_path,
            default_storage_path=default_path,
        )
        self.assertTrue(after_delete.success, msg=after_delete.message)
        self.assertEqual(len((after_delete.data or {}).get("records") or []), 0)

        user_payload = json.loads(storage_path.read_text(encoding="utf-8"))
        self.assertIn("trendyol-express-0-5-desi", list(user_payload.get("deletedKeys") or []))

    def test_accept_finance_cargo_tariff_persists_builtin_template_to_db(self):
        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)

        default_path = Path(self._tmp_dir.name) / "finance_cargo_tariffs.default.json"
        default_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "source_id": 1,
                            "tariffKey": "trendyol-express-0-5-desi",
                            "name": "Trendyol Express 0-5 Desi",
                            "description": "Önerilen tarife",
                            "platform": "TRENDYOL",
                            "cargoProviderCode": "TEXMP",
                            "cargoProviderName": "Trendyol Express Marketplace",
                            "minDesi": 0,
                            "maxDesi": 5,
                            "minSalePrice": 0,
                            "maxSalePrice": 300,
                            "amount": 54.9,
                            "currency": "TRY",
                            "isVatIncluded": False,
                            "vatRate": 20,
                            "isActive": True,
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        initial = load_finance_cargo_tariffs(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(initial.success, msg=initial.message)
        self.assertEqual(list((initial.data or {}).get("records") or []), [])

        provider_rows = load_logistics_cargo_providers(platform_code="TRENDYOL", search="texmp", db_name=self.db_path)
        self.assertTrue(provider_rows.success, provider_rows.message)
        builtin_provider = next(
            (
                row
                for row in list((provider_rows.data or {}).get("records") or [])
                if str(row.get("cargoProviderCode") or "") == "TEXMP"
            ),
            None,
        )
        self.assertIsNotNone(builtin_provider)
        accept_provider = accept_logistics_cargo_provider_record(dict(builtin_provider or {}), db_name=self.db_path)
        self.assertTrue(accept_provider.success, accept_provider.message)

        initial = load_finance_cargo_tariffs(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(initial.success, msg=initial.message)
        initial_record = list((initial.data or {}).get("records") or [])[0]
        self.assertTrue(initial_record["isBuiltin"])
        self.assertFalse(initial_record["isBuiltinAccepted"])

        accept_res = accept_finance_cargo_tariff(
            1,
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(accept_res.success, msg=accept_res.message)

        engine = get_engine(self.db_path)
        with Session(engine) as session:
            provider_rows = session.exec(select(LogisticsCargoProvider).order_by(LogisticsCargoProvider.pk.asc())).all()
            db_rows = session.exec(select(LogisticsCargoTariff).order_by(LogisticsCargoTariff.pk.asc())).all()
        self.assertEqual(len(provider_rows), 1)
        self.assertEqual(len(db_rows), 1)
        self.assertEqual(db_rows[0].tariffKey, "trendyol-express-0-5-desi")
        self.assertEqual(db_rows[0].cargo_provider_id, provider_rows[0].pk)
        self.assertEqual(db_rows[0].sourceType, SOURCE_TYPE_BUILTIN)
        self.assertEqual(
            db_rows[0].sourceId,
            1,
        )

        after = load_finance_cargo_tariffs(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(after.success, msg=after.message)
        after_record = list((after.data or {}).get("records") or [])[0]
        self.assertTrue(after_record["isBuiltin"])
        self.assertTrue(after_record["isBuiltinAccepted"])

    def test_accept_finance_cargo_tariffs_persists_multiple_builtin_templates_to_db(self):
        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)

        default_path = Path(self._tmp_dir.name) / "finance_cargo_tariffs.default.json"
        default_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "source_id": 1,
                            "tariffKey": "trendyol-express-0-5-desi",
                            "name": "Trendyol Express 0-5 Desi",
                            "description": "Önerilen tarife 1",
                            "platform": "TRENDYOL",
                            "cargoProviderCode": "TEXMP",
                            "cargoProviderName": "Trendyol Express Marketplace",
                            "minDesi": 0,
                            "maxDesi": 5,
                            "minSalePrice": 0,
                            "maxSalePrice": 300,
                            "amount": 54.9,
                            "currency": "TRY",
                            "isVatIncluded": False,
                            "vatRate": 20,
                            "isActive": True,
                        },
                        {
                            "source_id": 2,
                            "tariffKey": "trendyol-express-6-10-desi",
                            "name": "Trendyol Express 6-10 Desi",
                            "description": "Önerilen tarife 2",
                            "platform": "TRENDYOL",
                            "cargoProviderCode": "TEXMP",
                            "cargoProviderName": "Trendyol Express Marketplace",
                            "minDesi": 6,
                            "maxDesi": 10,
                            "minSalePrice": 0,
                            "maxSalePrice": 300,
                            "amount": 64.9,
                            "currency": "TRY",
                            "isVatIncluded": False,
                            "vatRate": 20,
                            "isActive": True,
                        },
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        provider_rows = load_logistics_cargo_providers(platform_code="TRENDYOL", search="texmp", db_name=self.db_path)
        self.assertTrue(provider_rows.success, provider_rows.message)
        builtin_provider = next(
            (
                row
                for row in list((provider_rows.data or {}).get("records") or [])
                if str(row.get("cargoProviderCode") or "") == "TEXMP"
            ),
            None,
        )
        self.assertIsNotNone(builtin_provider)
        accept_provider = accept_logistics_cargo_provider_record(dict(builtin_provider or {}), db_name=self.db_path)
        self.assertTrue(accept_provider.success, accept_provider.message)

        accept_res = accept_finance_cargo_tariffs(
            [1, 2],
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(accept_res.success, msg=accept_res.message)
        self.assertEqual(int((accept_res.data or {}).get("accepted_count") or 0), 2)

        engine = get_engine(self.db_path)
        with Session(engine) as session:
            provider_rows = session.exec(select(LogisticsCargoProvider).order_by(LogisticsCargoProvider.pk.asc())).all()
            db_rows = session.exec(select(LogisticsCargoTariff).order_by(LogisticsCargoTariff.pk.asc())).all()
        self.assertEqual(len(provider_rows), 1)
        self.assertEqual(len(db_rows), 2)
        self.assertTrue(all(int(row.cargo_provider_id or 0) == int(provider_rows[0].pk or 0) for row in db_rows))

    def test_finance_cargo_tariff_builtin_defaults_require_accepted_platform_and_provider(self):
        default_path = Path(self._tmp_dir.name) / "finance_cargo_tariffs.default.json"
        default_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "source_id": 1,
                            "tariffKey": "trendyol-express-0-5-desi",
                            "name": "Trendyol Express 0-5 Desi",
                            "description": "Önerilen tarife",
                            "platform": "TRENDYOL",
                            "cargoProviderCode": "TEXMP",
                            "cargoProviderName": "Trendyol Express Marketplace",
                            "minDesi": 0,
                            "maxDesi": 5,
                            "minSalePrice": 0,
                            "maxSalePrice": 300,
                            "amount": 54.9,
                            "currency": "TRY",
                            "isVatIncluded": False,
                            "vatRate": 20,
                            "isActive": True,
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        no_platform = load_finance_cargo_tariffs(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(no_platform.success, msg=no_platform.message)
        self.assertEqual(list((no_platform.data or {}).get("records") or []), [])

        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)

        no_provider = load_finance_cargo_tariffs(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(no_provider.success, msg=no_provider.message)
        self.assertEqual(list((no_provider.data or {}).get("records") or []), [])

        provider_rows = load_logistics_cargo_providers(platform_code="TRENDYOL", search="texmp", db_name=self.db_path)
        self.assertTrue(provider_rows.success, provider_rows.message)
        builtin_provider = next(
            (
                row
                for row in list((provider_rows.data or {}).get("records") or [])
                if str(row.get("cargoProviderCode") or "") == "TEXMP"
            ),
            None,
        )
        self.assertIsNotNone(builtin_provider)
        accept_provider = accept_logistics_cargo_provider_record(dict(builtin_provider or {}), db_name=self.db_path)
        self.assertTrue(accept_provider.success, accept_provider.message)

        visible = load_finance_cargo_tariffs(
            db_name=self.db_path,
            default_storage_path=default_path,
        )
        self.assertTrue(visible.success, msg=visible.message)
        records = list((visible.data or {}).get("records") or [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["tariffKey"], "trendyol-express-0-5-desi")

    def test_finance_cargo_tariff_db_save_requires_accepted_provider(self):
        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)

        save_res = save_finance_cargo_tariff(
            {
                "name": "Trendyol Express 0-5 Desi",
                "description": "Standart ilk barem",
                "platform": "TRENDYOL",
                "cargoProviderCode": "TEXMP",
                "cargoProviderName": "Trendyol Express Marketplace",
                "minDesi": 0,
                "maxDesi": 5,
                "minSalePrice": 0,
                "maxSalePrice": 300,
                "amount": 54.9,
                "currency": "TRY",
                "isVatIncluded": False,
                "vatRate": 20,
                "isActive": True,
            },
            db_name=self.db_path,
        )
        self.assertFalse(save_res.success)
        self.assertIn("kargo firmasını", save_res.message)
