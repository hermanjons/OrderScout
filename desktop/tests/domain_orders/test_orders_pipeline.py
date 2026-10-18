from __future__ import annotations

import asyncio
import copy
import inspect
import json
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from Account.models.models import ApiAccount
from Core.utils.model_utils import create_records, get_records
from Feedback.processors.pipeline import Result
from Marketplaces.constants.catalog_constants import platform_select_options
from Orders.models.trendyol.models import OrderItem, ReturnClaim
from Orders.processors import agentic_repository as orders_agentic_repo
import Orders.processors.trendyol.pipeline as orders_pipeline
import Orders.views.actions as orders_actions
import Orders.views.returns_manager_window as returns_views
import Orders.views.views as orders_views

from tests.support.db_case import IsolatedDbTestCase


class TestOrdersPipeline(IsolatedDbTestCase):
    class _DummyProgress:
        def __init__(self) -> None:
            self.value = None
            self.enabled = True
            self.running_text = ""

        def setProgress(self, v: int) -> None:
            self.value = int(v)

        def setEnabled(self, v: bool) -> None:
            self.enabled = bool(v)

        def setRunningText(self, text: str) -> None:
            self.running_text = str(text or "")

    def _seed_account(self, pk: int = 1) -> None:
        res = create_records(
            model=ApiAccount,
            data_list=[
                {
                    "pk": pk,
                    "account_id": f"ACC-{pk}",
                    "comp_name": f"Company {pk}",
                    "platform": "trendyol",
                }
            ],
            db_name=self.db_path,
            mode="plain",
        )
        self.assertTrue(res.success, res.message)

    def _sample_payload(self, account_pk: int = 1) -> dict:
        return {
            "order_data_list": [
                {
                    "id": 1001,
                    "shipmentPackageId": 1001,
                    "orderNumber": "ORD-1001",
                    "api_account_id": account_pk,
                    "lastModifiedDate": 1700000000000,
                    "orderDate": 1700000000000,
                    "status": "Picking",
                    "shipmentPackageStatus": "ReadyToShip",
                    "cargoTrackingNumber": "TRK-1001",
                    "customerFirstName": "Jane",
                    "customerLastName": "Doe",
                }
            ],
            "order_item_list": [
                {
                    "orderNumber": "ORD-1001",
                    "api_account_id": account_pk,
                    "order_data_id": 1001,
                    "snapshotLastModifiedDate": 1700000000000,
                    "quantity": 1,
                    "productCode": 501,
                    "id": 1501,
                    "lineId": 1501,
                    "orderLineItemStatusName": "Picking",
                    "merchantSku": "SKU-501",
                    "productName": "Product 501",
                }
            ],
        }

    def test_save_orders_to_db_is_idempotent(self) -> None:
        self._seed_account()
        payload = self._sample_payload()

        first_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(first_res.success, first_res.message)
        self.assertTrue((first_res.data or {}).get("changed"))

        second_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(second_res.success, second_res.message)
        self.assertFalse((second_res.data or {}).get("changed"))

    def test_agentic_order_children_are_filterable_by_account(self) -> None:
        self._seed_account(1)
        self._seed_account(2)
        first_payload = self._sample_payload(account_pk=1)
        second_payload = self._sample_payload(account_pk=2)
        second_payload["order_item_list"][0]["productName"] = "Other account product"

        for payload in (first_payload, second_payload):
            saved = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
            self.assertTrue(saved.success, saved.message)

        headers = orders_agentic_repo.list_order_headers(
            ["ORD-1001"],
            api_account_ids=[2],
            db_name=self.db_path,
        )
        items = orders_agentic_repo.list_order_items(
            ["ORD-1001"],
            api_account_ids=[2],
            db_name=self.db_path,
        )

        self.assertTrue(headers.success, headers.message)
        self.assertTrue(items.success, items.message)
        self.assertEqual(
            {getattr(row, "api_account_id", None) for row in (headers.data or {}).get("records", [])},
            {2},
        )
        item_rows = list((items.data or {}).get("records", []) or [])
        self.assertEqual({getattr(row, "api_account_id", None) for row in item_rows}, {2})
        self.assertEqual({getattr(row, "productName", None) for row in item_rows}, {"Other account product"})
        resolved = orders_agentic_repo.resolve_order_record(
            "ORD-1001",
            api_account_id=2,
            db_name=self.db_path,
        )
        self.assertTrue(resolved.success, resolved.message)
        self.assertEqual(getattr((resolved.data or {}).get("record"), "api_account_id", None), 2)

    def test_ready_selection_is_one_account_scoped_authoritative_set(self) -> None:
        self._seed_account(1)
        self._seed_account(2)
        first = self._sample_payload(account_pk=1)
        second = self._sample_payload(account_pk=2)
        second["order_data_list"][0].update(
            {
                "id": 2001,
                "shipmentPackageId": 2001,
                "orderNumber": "ORD-2001",
            }
        )
        second["order_item_list"][0].update(
            {
                "id": 2501,
                "lineId": 2501,
                "order_data_id": 2001,
                "orderNumber": "ORD-2001",
            }
        )
        delivered = copy.deepcopy(first)
        delivered["order_data_list"][0].update(
            {
                "id": 1002,
                "shipmentPackageId": 1002,
                "orderNumber": "ORD-DELIVERED",
                "status": "Delivered",
                "shipmentPackageStatus": "Delivered",
            }
        )
        delivered["order_item_list"][0].update(
            {
                "id": 1502,
                "lineId": 1502,
                "order_data_id": 1002,
                "orderNumber": "ORD-DELIVERED",
            }
        )
        for payload in (first, second, delivered):
            saved = orders_pipeline.save_orders_to_db(
                Result.ok(data=payload),
                db_name=self.db_path,
            )
            self.assertTrue(saved.success, saved.message)

        selection = orders_agentic_repo.select_ready_to_ship_orders(
            api_account_ids=[1],
            limit=500,
            db_name=self.db_path,
        )

        self.assertTrue(selection.success, selection.message)
        data = selection.data or {}
        self.assertEqual(data.get("ready_to_ship"), 1)
        self.assertEqual(data.get("selected_count"), 1)
        self.assertEqual(data.get("order_numbers"), ["ORD-1001"])
        self.assertEqual(data.get("listed_count"), data.get("ready_to_ship"))
        self.assertFalse(data.get("truncated"))
        self.assertEqual(
            {row.get("api_account_id") for row in data.get("orders") or []},
            {1},
        )

    def test_order_summary_uses_latest_account_scope_and_excludes_cancelled_revenue(self) -> None:
        self._seed_account(1)
        self._seed_account(2)
        ready = self._sample_payload(account_pk=1)
        ready["order_data_list"][0]["packageTotalPrice"] = 125.5
        ready["order_data_list"][0]["currencyCode"] = "TRY"
        cancelled = copy.deepcopy(ready)
        cancelled["order_data_list"][0].update(
            {
                "id": 1002,
                "shipmentPackageId": 1002,
                "orderNumber": "ORD-CANCELLED",
                "status": "Cancelled",
                "shipmentPackageStatus": "Cancelled",
                "packageTotalPrice": 999.0,
            }
        )
        cancelled["order_item_list"][0].update(
            {
                "id": 1502,
                "lineId": 1502,
                "order_data_id": 1002,
                "orderNumber": "ORD-CANCELLED",
            }
        )
        other_account = copy.deepcopy(ready)
        other_account["order_data_list"][0].update(
            {
                "id": 2001,
                "shipmentPackageId": 2001,
                "orderNumber": "ORD-OTHER",
                "api_account_id": 2,
                "packageTotalPrice": 500.0,
            }
        )
        other_account["order_item_list"][0].update(
            {
                "id": 2501,
                "lineId": 2501,
                "order_data_id": 2001,
                "orderNumber": "ORD-OTHER",
                "api_account_id": 2,
            }
        )
        for payload in (ready, cancelled, other_account):
            saved = orders_pipeline.save_orders_to_db(
                Result.ok(data=payload),
                db_name=self.db_path,
            )
            self.assertTrue(saved.success, saved.message)

        summary = orders_agentic_repo.summarize_orders(
            api_account_ids=[1],
            db_name=self.db_path,
        )

        self.assertTrue(summary.success, summary.message)
        data = summary.data or {}
        self.assertEqual(data.get("total_orders"), 2)
        self.assertEqual(data.get("cancelled_orders"), 1)
        self.assertEqual(data.get("estimated_revenue"), 125.5)
        self.assertEqual(data.get("currency"), "TRY")
        self.assertEqual(data.get("currencies"), ["TRY"])
        self.assertEqual(data.get("revenue_by_currency"), {"TRY": 125.5})
        self.assertEqual(data.get("status_counts"), {"ReadyToShip": 1, "Cancelled": 1})
        self.assertEqual(data.get("status_rates"), {"ReadyToShip": 50.0, "Cancelled": 50.0})
        self.assertEqual(data.get("dominant_status"), "ReadyToShip")
        self.assertEqual(data.get("dominant_status_count"), 1)
        self.assertEqual(data.get("dominant_status_rate"), 50.0)
        self.assertEqual(data.get("cancellation_rate"), 50.0)
        self.assertEqual(data.get("revenue_order_count"), 1)
        self.assertEqual(data.get("average_revenue_per_order"), 125.5)
        self.assertEqual(
            data.get("scope_account_ids"),
            [1],
        )
        self.assertNotIn("scope_rows", data)
        self.assertTrue(data.get("source_snapshot_hash"))
        self.assertGreater(int(data.get("source_revision") or 0), 0)

    def test_agentic_order_query_preserves_exact_identifier_boundary(self) -> None:
        self._seed_account(1)
        ready = self._sample_payload(account_pk=1)
        delivered = copy.deepcopy(ready)
        delivered["order_data_list"][0].update(
            {
                "id": 1002,
                "shipmentPackageId": 1002,
                "orderNumber": "ORD-DELIVERED",
                "orderDate": 1700000010000,
                "lastModifiedDate": 1700000010000,
                "status": "Delivered",
                "shipmentPackageStatus": "Delivered",
                "customerFirstName": "Berat",
                "customerLastName": "Baskan",
            }
        )
        delivered["order_item_list"][0].update(
            {
                "id": 1502,
                "lineId": 1502,
                "order_data_id": 1002,
                "orderNumber": "ORD-DELIVERED",
                "snapshotLastModifiedDate": 1700000010000,
            }
        )
        for payload in (ready, delivered):
            saved = orders_pipeline.save_orders_to_db(
                Result.ok(data=payload),
                db_name=self.db_path,
            )
            self.assertTrue(saved.success, saved.message)

        exact = orders_agentic_repo.query_orders(
            query="Bu ne, ORD-1001 kimin siparisi?",
            db_name=self.db_path,
        )
        objection = orders_agentic_repo.query_orders(
            query="Teslim edilmis eski bir siparisi gosterdin bana su an.",
            db_name=self.db_path,
        )

        self.assertTrue(exact.success, exact.message)
        self.assertEqual(
            [row.get("order_number") for row in (exact.data or {}).get("orders") or []],
            ["ORD-1001"],
        )
        self.assertTrue(objection.success, objection.message)
        self.assertEqual((objection.data or {}).get("count"), 0)
        self.assertEqual((objection.data or {}).get("orders"), [])

    def test_agentic_order_query_filters_account_customer_status_and_sort_in_domain(self) -> None:
        self._seed_account(1)
        self._seed_account(2)
        jane = self._sample_payload(account_pk=1)
        jane["order_data_list"][0]["packageTotalPrice"] = 90.0
        jane_high = copy.deepcopy(jane)
        jane_high["order_data_list"][0].update(
            {
                "id": 1002,
                "shipmentPackageId": 1002,
                "orderNumber": "ORD-1002",
                "orderDate": 1700000010000,
                "lastModifiedDate": 1700000010000,
                "packageTotalPrice": 250.0,
            }
        )
        jane_high["order_item_list"][0].update(
            {
                "id": 1502,
                "lineId": 1502,
                "order_data_id": 1002,
                "orderNumber": "ORD-1002",
                "snapshotLastModifiedDate": 1700000010000,
            }
        )
        other = copy.deepcopy(jane_high)
        other["order_data_list"][0].update(
            {
                "id": 2001,
                "shipmentPackageId": 2001,
                "orderNumber": "ORD-OTHER",
                "api_account_id": 2,
                "packageTotalPrice": 999.0,
            }
        )
        other["order_item_list"][0].update(
            {
                "id": 2501,
                "lineId": 2501,
                "order_data_id": 2001,
                "orderNumber": "ORD-OTHER",
                "api_account_id": 2,
            }
        )
        for payload in (jane, jane_high, other):
            saved = orders_pipeline.save_orders_to_db(
                Result.ok(data=payload),
                db_name=self.db_path,
            )
            self.assertTrue(saved.success, saved.message)

        result = orders_agentic_repo.query_orders(
            api_account_ids=[1],
            filters={"customer": "Jane Doe", "status": "ReadyToShip"},
            sort="total_price_desc",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertEqual(data.get("count"), 2)
        self.assertEqual(
            [row.get("order_number") for row in data.get("orders") or []],
            ["ORD-1002", "ORD-1001"],
        )
        self.assertEqual(
            {row.get("api_account_id") for row in data.get("orders") or []},
            {1},
        )

    def test_agentic_order_query_normalizes_canonical_snake_case_status(self) -> None:
        self._seed_account(1)
        statuses = (
            ("UnDeliveredAndReturned", "ORD-RETURNED"),
            ("UnDelivered", "ORD-UNDELIVERED"),
        )
        for offset, (status, order_number) in enumerate(statuses, start=1):
            payload = copy.deepcopy(self._sample_payload(account_pk=1))
            order_data_id = 7_000 + offset
            payload["order_data_list"][0].update(
                {
                    "id": order_data_id,
                    "shipmentPackageId": order_data_id,
                    "orderNumber": order_number,
                    "orderDate": 1700000000000 + offset,
                    "lastModifiedDate": 1700000000000 + offset,
                    "status": status,
                    "shipmentPackageStatus": status,
                }
            )
            payload["order_item_list"][0].update(
                {
                    "id": 7_500 + offset,
                    "lineId": 7_500 + offset,
                    "order_data_id": order_data_id,
                    "orderNumber": order_number,
                    "snapshotLastModifiedDate": 1700000000000 + offset,
                }
            )
            saved = orders_pipeline.save_orders_to_db(
                Result.ok(data=payload),
                db_name=self.db_path,
            )
            self.assertTrue(saved.success, saved.message)

        result = orders_agentic_repo.query_orders(
            api_account_ids=[1],
            filters={"statuses": ["undelivered_and_returned"]},
            sort="order_date_desc",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertEqual(data.get("count"), 1)
        self.assertEqual(
            [row.get("order_number") for row in data.get("orders") or []],
            ["ORD-RETURNED"],
        )

    def test_nonfinal_summary_reuses_canonical_terminal_status_boundary(self) -> None:
        self._seed_account(1)
        statuses = (
            ("ReadyToShip", "ORD-NONFINAL-READY"),
            ("Shipped", "ORD-NONFINAL-SHIPPED"),
            ("Delivered", "ORD-FINAL-DELIVERED"),
            ("Cancelled", "ORD-FINAL-CANCELLED"),
            ("UnDeliveredAndReturned", "ORD-FINAL-RETURNED"),
        )
        for offset, (status, order_number) in enumerate(statuses, start=1):
            payload = copy.deepcopy(self._sample_payload(account_pk=1))
            order_data_id = 8_000 + offset
            payload["order_data_list"][0].update(
                {
                    "id": order_data_id,
                    "shipmentPackageId": order_data_id,
                    "orderNumber": order_number,
                    "lastModifiedDate": 1700000000000 + offset,
                    "status": status,
                    "shipmentPackageStatus": status,
                }
            )
            payload["order_item_list"][0].update(
                {
                    "id": 9_000 + offset,
                    "lineId": 9_000 + offset,
                    "order_data_id": order_data_id,
                    "orderNumber": order_number,
                    "snapshotLastModifiedDate": 1700000000000 + offset,
                }
            )
            saved = orders_pipeline.save_orders_to_db(
                Result.ok(data=payload),
                db_name=self.db_path,
            )
            self.assertTrue(saved.success, saved.message)

        result = orders_agentic_repo.summarize_nonfinal_orders(
            api_account_ids=[1],
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        data = dict(result.data or {})
        self.assertEqual(data.get("total_count"), 2)
        self.assertEqual(
            data.get("status_counts"),
            {"ReadyToShip": 1, "Shipped": 1},
        )
        self.assertTrue(data.get("status_counts_complete"))
        self.assertEqual(
            set(data.get("order_numbers") or []),
            {"ORD-NONFINAL-READY", "ORD-NONFINAL-SHIPPED"},
        )
        self.assertNotIn(
            "customer",
            (data.get("sample_orders") or [{}])[0],
        )

    def test_agentic_fulfillment_risk_excludes_delivered_orders(self) -> None:
        self._seed_account(1)
        ready = self._sample_payload(account_pk=1)
        ready["order_data_list"][0].update(
            {
                "cargoTrackingNumber": "",
                "cargoProviderName": "",
            }
        )
        delivered = copy.deepcopy(ready)
        delivered["order_data_list"][0].update(
            {
                "id": 1002,
                "shipmentPackageId": 1002,
                "orderNumber": "ORD-DELIVERED",
                "status": "Delivered",
                "shipmentPackageStatus": "Delivered",
            }
        )
        delivered["order_item_list"][0].update(
            {
                "id": 1502,
                "lineId": 1502,
                "order_data_id": 1002,
                "orderNumber": "ORD-DELIVERED",
            }
        )
        for payload in (ready, delivered):
            saved = orders_pipeline.save_orders_to_db(
                Result.ok(data=payload),
                db_name=self.db_path,
            )
            self.assertTrue(saved.success, saved.message)

        result = orders_agentic_repo.analyze_fulfillment_risks(
            api_account_ids=[1],
            now_ms=1700000000000 + (48 * 3_600_000),
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertEqual(data.get("risk_count"), 1)
        self.assertEqual(
            [row.get("order_number") for row in data.get("orders") or []],
            ["ORD-1001"],
        )
        self.assertEqual(
            set((data.get("orders") or [])[0].get("reasons") or []),
            {"tracking_missing", "cargo_provider_missing", "order_age_over_threshold_while_ready"},
        )

    def test_order_item_sales_summary_uses_latest_snapshot_and_excludes_cancelled(self) -> None:
        self._seed_account(1)
        first = self._sample_payload(account_pk=1)
        first["order_item_list"][0].update(
            {"quantity": 1, "lineGrossAmount": 100.0, "barcode": "BAR-501"}
        )
        updated = copy.deepcopy(first)
        updated["order_data_list"][0]["lastModifiedDate"] = 1700000005000
        updated["order_item_list"][0].update(
            {
                "snapshotLastModifiedDate": 1700000005000,
                "quantity": 3,
                "lineGrossAmount": 300.0,
            }
        )
        second = copy.deepcopy(first)
        second["order_data_list"][0].update(
            {
                "id": 1002,
                "shipmentPackageId": 1002,
                "orderNumber": "ORD-1002",
                "lastModifiedDate": 1700000010000,
            }
        )
        second["order_item_list"][0].update(
            {
                "orderNumber": "ORD-1002",
                "order_data_id": 1002,
                "snapshotLastModifiedDate": 1700000010000,
                "quantity": 2,
                "lineGrossAmount": 200.0,
            }
        )
        cancelled = copy.deepcopy(first)
        cancelled["order_data_list"][0].update(
            {
                "id": 1003,
                "shipmentPackageId": 1003,
                "orderNumber": "ORD-1003",
                "lastModifiedDate": 1700000020000,
                "status": "Cancelled",
            }
        )
        cancelled["order_item_list"][0].update(
            {
                "orderNumber": "ORD-1003",
                "order_data_id": 1003,
                "snapshotLastModifiedDate": 1700000020000,
                "quantity": 10,
                "lineGrossAmount": 1000.0,
            }
        )
        for payload in (first, updated, second, cancelled):
            saved = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
            self.assertTrue(saved.success, saved.message)

        summary = orders_agentic_repo.summarize_order_item_sales(
            start_date_ms=1699999999000,
            end_date_ms=1700000030000,
            db_name=self.db_path,
        )

        self.assertTrue(summary.success, summary.message)
        data = summary.data or {}
        self.assertEqual(data.get("order_count"), 2)
        self.assertEqual(data.get("total_quantity"), 5)
        self.assertEqual(data.get("gross_amount_by_currency"), {"TRY": 500.0})
        self.assertEqual(data.get("total_gross_amount"), 500.0)
        self.assertEqual(data.get("currency"), "TRY")
        self.assertEqual(data.get("product_count"), 1)
        self.assertEqual((data.get("rows") or [])[0].get("quantity"), 5)
        self.assertEqual((data.get("rows") or [])[0].get("gross_amount"), 500.0)
        self.assertEqual(data.get("leading_five_quantity"), 5)
        self.assertEqual(data.get("leading_five_quantity_share"), 100.0)
        self.assertGreater(data.get("source_revision") or 0, 0)
        self.assertEqual(len(str(data.get("source_snapshot_hash") or "")), 64)

        filtered = orders_agentic_repo.summarize_order_item_sales(
            start_date_ms=1699999999000,
            end_date_ms=1700000030000,
            product_identities=[{"barcode": "BAR-501"}],
            db_name=self.db_path,
        )
        self.assertTrue(filtered.success, filtered.message)
        filtered_data = filtered.data or {}
        self.assertEqual(filtered_data.get("identity_filter_count"), 1)
        self.assertEqual(filtered_data.get("order_count"), 2)
        self.assertEqual(filtered_data.get("matched_order_count"), 2)
        self.assertEqual(filtered_data.get("population_order_count"), 2)
        self.assertEqual(filtered_data.get("total_quantity"), 5)
        self.assertEqual(
            filtered_data.get("gross_amount_by_currency"),
            {"TRY": 500.0},
        )
        self.assertEqual(filtered_data.get("total_gross_amount"), 500.0)
        self.assertEqual(filtered_data.get("currency"), "TRY")
        self.assertEqual(len(filtered_data.get("rows") or []), 1)

        missing = orders_agentic_repo.summarize_order_item_sales(
            start_date_ms=1699999999000,
            end_date_ms=1700000030000,
            product_identities=[{"barcode": "BAR-NOT-PRESENT"}],
            db_name=self.db_path,
        )
        self.assertTrue(missing.success, missing.message)
        missing_data = missing.data or {}
        self.assertEqual(missing_data.get("identity_filter_count"), 1)
        self.assertEqual(missing_data.get("order_count"), 0)
        self.assertEqual(missing_data.get("matched_order_count"), 0)
        self.assertEqual(missing_data.get("population_order_count"), 2)
        self.assertEqual(missing_data.get("total_quantity"), 0)
        self.assertEqual(missing_data.get("rows"), [])
        self.assertEqual(missing_data.get("total_gross_amount"), 0.0)
        self.assertIs(missing_data.get("empty_result"), True)
        self.assertIs(missing_data.get("metrics_complete"), True)
        self.assertIs(missing_data.get("currency_applicable"), False)

    def test_filtered_item_sales_counts_distinct_orders_across_product_aliases(
        self,
    ) -> None:
        self._seed_account(1)
        first = self._sample_payload(account_pk=1)
        first_item = first["order_item_list"][0]
        first_item.update(
            {
                "id": 1701,
                "lineId": 1701,
                "productName": "Alias Product A",
                "productCode": "SHARED-PRODUCT",
                "contentId": 7001,
                "barcode": "ALIAS-A",
                "quantity": 1,
            }
        )
        second_alias = copy.deepcopy(first_item)
        second_alias.update(
            {
                "id": 1702,
                "lineId": 1702,
                "productName": "Alias Product B",
                "contentId": 7002,
                "barcode": "ALIAS-B",
                "quantity": 2,
            }
        )
        first["order_item_list"].append(second_alias)

        second = self._sample_payload(account_pk=1)
        second["order_data_list"][0].update(
            {
                "id": 1002,
                "shipmentPackageId": 1002,
                "orderNumber": "ORD-1002",
                "lastModifiedDate": 1700000010000,
            }
        )
        second["order_item_list"][0].update(
            {
                "id": 2701,
                "lineId": 2701,
                "order_data_id": 1002,
                "orderNumber": "ORD-1002",
                "snapshotLastModifiedDate": 1700000010000,
                "productName": "Alias Product A",
                "productCode": "SHARED-PRODUCT",
                "contentId": 7001,
                "barcode": "ALIAS-A",
                "quantity": 3,
            }
        )
        for payload in (first, second):
            saved = orders_pipeline.save_orders_to_db(
                Result.ok(data=payload),
                db_name=self.db_path,
            )
            self.assertTrue(saved.success, saved.message)

        filtered = orders_agentic_repo.summarize_order_item_sales(
            product_identities=[{"product_code": "SHARED-PRODUCT"}],
            group_by="product",
            db_name=self.db_path,
        )

        self.assertTrue(filtered.success, filtered.message)
        data = dict(filtered.data or {})
        rows = list(data.get("rows") or [])
        self.assertEqual(data.get("population_order_count"), 2)
        self.assertEqual(data.get("matched_order_count"), 2)
        self.assertEqual(data.get("order_count"), 2)
        self.assertEqual(data.get("total_quantity"), 6)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(int(row.get("order_count") or 0) for row in rows), 3)

    def test_order_item_sales_report_snapshot_uses_same_canonical_aggregate_without_customer_pii(self) -> None:
        self._seed_account(1)
        payload = self._sample_payload(account_pk=1)
        payload["order_data_list"][0].update(
            {
                "customerFirstName": "Gizli",
                "customerLastName": "Musteri",
                "shipmentAddress": {"fullAddress": "Gizli Sokak 42"},
            }
        )
        payload["order_item_list"][0].update(
            {"quantity": 4, "lineGrossAmount": 399.96, "barcode": "BAR-REPORT"}
        )
        saved = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(saved.success, saved.message)

        report = orders_agentic_repo.build_order_item_sales_report_snapshot(
            start_date_ms=1699999999000,
            end_date_ms=1700000030000,
            period_label="Son 3 hafta",
            db_name=self.db_path,
        )

        self.assertTrue(report.success, report.message)
        data = report.data or {}
        snapshot = data.get("report_snapshot") or {}
        self.assertEqual(snapshot.get("snapshot_id"), data.get("snapshot_id"))
        self.assertEqual((snapshot.get("metadata") or {}).get("contains_customer_pii"), False)
        self.assertEqual(data.get("leading_five_quantity"), 4)
        self.assertEqual(data.get("leading_five_quantity_share"), 100.0)
        self.assertEqual(
            (snapshot.get("metadata") or {}).get("leading_five_quantity"),
            4,
        )
        self.assertEqual(
            (snapshot.get("metadata") or {}).get(
                "leading_five_quantity_share"
            ),
            100.0,
        )
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("Gizli Musteri", serialized)
        self.assertNotIn("Gizli Sokak", serialized)
        detail_sheet = (snapshot.get("sheets") or [None, {}])[1]
        self.assertEqual((detail_sheet.get("rows") or [])[0][6], 4)
        self.assertEqual((detail_sheet.get("rows") or [])[0][8], 399.96)
        detail_columns = {
            column.get("key"): column
            for column in (detail_sheet.get("columns") or [])
        }
        for identity_key in ("sku", "barcode", "content_id", "product_code"):
            self.assertEqual(detail_columns[identity_key].get("number_format"), "@")
        self.assertEqual(detail_columns["gross_amount"].get("number_format"), "#,##0.00")

    def test_selected_return_reason_summary_deduplicates_claim_snapshots(self) -> None:
        self._seed_account(1)
        created = create_records(
            model=ReturnClaim,
            data_list=[
                {
                    "claimId": "CLAIM-R1",
                    "orderNumber": "ORD-R1",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000000,
                    "claimDate": 1700000000000,
                    "claimItemStatus": "WaitingInAction",
                    "claimReason": "Hasarli urun",
                    "claimReasons": ["Hasarli urun"],
                    "itemCount": 1,
                },
                {
                    "claimId": "CLAIM-R1",
                    "orderNumber": "ORD-R1",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000005000,
                    "claimDate": 1700000000000,
                    "claimItemStatus": "WaitingInAction",
                    "claimReason": "Yanlis urun",
                    "claimReasons": ["Yanlis urun"],
                    "itemCount": 2,
                },
                {
                    "claimId": "CLAIM-R2",
                    "orderNumber": "ORD-R2",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000010000,
                    "claimDate": 1700000010000,
                    "claimItemStatus": "WaitingInAction",
                    "claimReason": "Yanlis urun",
                    "claimReasons": ["Yanlis urun"],
                    "itemCount": 1,
                },
            ],
            db_name=self.db_path,
            mode="plain",
        )
        self.assertTrue(created.success, created.message)

        summary = orders_agentic_repo.summarize_return_reasons(
            claim_ids=["CLAIM-R1", "CLAIM-R2"],
            db_name=self.db_path,
        )

        self.assertTrue(summary.success, summary.message)
        data = summary.data or {}
        self.assertEqual(data.get("claim_count"), 2)
        self.assertEqual(data.get("reason_count"), 1)
        self.assertEqual((data.get("rows") or [])[0].get("reason"), "Yanlis urun")
        self.assertEqual((data.get("rows") or [])[0].get("claim_count"), 2)
        self.assertEqual((data.get("rows") or [])[0].get("item_count"), 3)

    def test_return_summary_uses_latest_claim_snapshot_and_account_scope(self) -> None:
        self._seed_account(1)
        self._seed_account(2)
        created = create_records(
            model=ReturnClaim,
            data_list=[
                {
                    "claimId": "CLAIM-S1",
                    "orderNumber": "ORD-S1",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000000,
                    "claimDate": 1700000000000,
                    "claimItemStatus": "WaitingInAction",
                    "itemCount": 1,
                    "totalPrice": 10.0,
                },
                {
                    "claimId": "CLAIM-S1",
                    "orderNumber": "ORD-S1",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000005000,
                    "claimDate": 1700000000000,
                    "claimItemStatus": "WaitingInAction",
                    "itemCount": 2,
                    "totalPrice": 50.0,
                },
                {
                    "claimId": "CLAIM-S2",
                    "orderNumber": "ORD-S2",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000010000,
                    "claimDate": 1700000010000,
                    "claimItemStatus": "Accepted",
                    "itemCount": 1,
                    "totalPrice": 25.0,
                },
                {
                    "claimId": "CLAIM-OTHER",
                    "orderNumber": "ORD-OTHER",
                    "api_account_id": 2,
                    "lastModifiedDate": 1700000020000,
                    "claimDate": 1700000020000,
                    "claimItemStatus": "WaitingInAction",
                    "itemCount": 9,
                    "totalPrice": 900.0,
                },
            ],
            db_name=self.db_path,
            mode="plain",
        )
        self.assertTrue(created.success, created.message)

        summary = orders_agentic_repo.summarize_returns(
            api_account_ids=[1],
            db_name=self.db_path,
        )

        self.assertTrue(summary.success, summary.message)
        data = summary.data or {}
        self.assertEqual(data.get("total_claims"), 2)
        self.assertEqual(data.get("total_items"), 3)
        self.assertEqual(data.get("estimated_return_amount"), 75.0)
        self.assertEqual(data.get("waiting_action_count"), 1)
        self.assertEqual(
            data.get("status_counts"),
            {"Accepted": 1, "WaitingInAction": 1},
        )
        self.assertEqual(
            {row.get("api_account_id") for row in data.get("scope_rows") or []},
            {1},
        )

    def test_order_details_exact_refs_do_not_cross_accounts_with_same_order_number(self) -> None:
        self._seed_account(1)
        self._seed_account(2)
        first_payload = self._sample_payload(account_pk=1)
        second_payload = self._sample_payload(account_pk=2)

        first_res = orders_pipeline.save_orders_to_db(Result.ok(data=first_payload), db_name=self.db_path)
        second_res = orders_pipeline.save_orders_to_db(Result.ok(data=second_payload), db_name=self.db_path)
        self.assertTrue(first_res.success, first_res.message)
        self.assertTrue(second_res.success, second_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            details = orders_pipeline.get_order_full_details_by_numbers(
                ["ORD-1001"],
                mode="latest",
                order_refs=[{"orderNumber": "ORD-1001", "api_account_id": 2}],
            )

        self.assertTrue(details.success, details.message)
        orders = (details.data or {}).get("orders") or []
        self.assertEqual(len(orders), 1)
        self.assertEqual(getattr(orders[0].get("header"), "api_account_id", None), 2)

    def test_save_orders_to_db_uses_shipment_package_id_when_id_missing(self) -> None:
        self._seed_account()
        payload = {
            "order_data_list": [
                {
                    "shipmentPackageId": 3001,
                    "orderNumber": "ORD-3001",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000000,
                    "orderDate": 1700000000000,
                    "status": "Created",
                    "shipmentPackageStatus": "ReadyToShip",
                }
            ],
            "order_item_list": [
                {
                    "orderNumber": "ORD-3001",
                    "api_account_id": 1,
                    "order_data_id": 3001,
                    "snapshotLastModifiedDate": 1700000000000,
                    "quantity": 1,
                    "productCode": 801,
                    "id": 1801,
                    "lineId": 1801,
                }
            ],
        }

        save_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(save_res.success, save_res.message)

        read_res = get_records(model=orders_pipeline.OrderData, db_name=self.db_path)
        self.assertTrue(read_res.success, read_res.message)
        rows = (read_res.data or {}).get("records", []) or []
        self.assertEqual(len(rows), 1)
        self.assertEqual(getattr(rows[0], "id", None), 3001)

    def test_normalize_order_data_skips_row_without_snapshot_identity(self) -> None:
        orders, items = orders_pipeline.normalize_order_data(
            {
                "orderNumber": "ORD-NO-ID",
                "lastModifiedDate": 1700000000000,
                "lines": [{"id": 1, "productCode": 901, "quantity": 1}],
            },
            1,
        )
        self.assertEqual(orders, [])
        self.assertEqual(items, [])

    def test_get_latest_orders_with_ready_to_ship_filter(self) -> None:
        self._seed_account()
        payload = self._sample_payload()
        save_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            read_res = orders_pipeline.get_latest_orders(shipment_statuses=["ReadyToShip"])

        self.assertTrue(read_res.success, read_res.message)
        orders = (read_res.data or {}).get("orders", [])
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].orderNumber, "ORD-1001")

    def test_get_latest_orders_matches_order_status_when_package_status_differs(self) -> None:
        self._seed_account()
        payload = self._sample_payload()
        payload["order_data_list"][0].update(
            {
                "orderNumber": "ORD-RETURNED",
                "status": "Returned",
                "shipmentPackageStatus": "UnDeliveredAndReturned",
            }
        )
        payload["order_item_list"][0]["orderNumber"] = "ORD-RETURNED"
        save_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            read_res = orders_pipeline.get_latest_orders(shipment_statuses=["Returned"])

        self.assertTrue(read_res.success, read_res.message)
        orders = (read_res.data or {}).get("orders", [])
        self.assertEqual([row.orderNumber for row in orders], ["ORD-RETURNED"])

    def test_get_latest_ready_to_ship_orders_excludes_simulation_records(self) -> None:
        self._seed_account()
        payload = self._sample_payload()
        payload["order_data_list"].append(
            {
                "id": 1002,
                "shipmentPackageId": 1002,
                "orderNumber": "SIM-READY-1",
                "api_account_id": 1,
                "lastModifiedDate": 1700000000000,
                "orderDate": 1700000000000,
                "status": "Created",
                "shipmentPackageStatus": "ReadyToShip",
                "cargoProviderName": "Simulated Cargo",
            }
        )
        payload["order_item_list"].append(
            {
                "orderNumber": "SIM-READY-1",
                "api_account_id": 1,
                "order_data_id": 1002,
                "snapshotLastModifiedDate": 1700000000000,
                "quantity": 1,
                "productCode": 502,
                "id": 1502,
                "lineId": 1502,
            }
        )
        save_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            read_res = orders_pipeline.get_latest_ready_to_ship_orders()

        self.assertTrue(read_res.success, read_res.message)
        orders = (read_res.data or {}).get("orders", [])
        self.assertEqual([row.orderNumber for row in orders], ["ORD-1001"])

    def test_get_nonfinal_order_numbers_defaults_to_operational_statuses_only(self) -> None:
        self._seed_account()
        payload = {
            "order_data_list": [
                {
                    "id": 1101,
                    "shipmentPackageId": 1101,
                    "orderNumber": "ORD-READY",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000000,
                    "orderDate": 1700000000000,
                    "status": "Created",
                    "shipmentPackageStatus": "ReadyToShip",
                },
                {
                    "id": 1102,
                    "shipmentPackageId": 1102,
                    "orderNumber": "ORD-SHIPPED",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000100,
                    "orderDate": 1700000000100,
                    "status": "Shipped",
                    "shipmentPackageStatus": "Shipped",
                },
                {
                    "id": 1103,
                    "shipmentPackageId": 1103,
                    "orderNumber": "ORD-CANCELLED",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000200,
                    "orderDate": 1700000000200,
                    "status": "Cancelled",
                    "shipmentPackageStatus": "Cancelled",
                },
                {
                    "id": 1104,
                    "shipmentPackageId": 1104,
                    "orderNumber": "ORD-UNDELIVERED-RETURNED",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000300,
                    "orderDate": 1700000000300,
                    "status": "UnDeliveredAndReturned",
                    "shipmentPackageStatus": "UnDeliveredAndReturned",
                },
                {
                    "id": 1105,
                    "shipmentPackageId": 1105,
                    "orderNumber": "SIM-OPEN",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000400,
                    "orderDate": 1700000000400,
                    "status": "Created",
                    "shipmentPackageStatus": "ReadyToShip",
                    "cargoProviderName": "Simulated Cargo",
                },
            ],
            "order_item_list": [
                {
                    "orderNumber": "ORD-READY",
                    "api_account_id": 1,
                    "order_data_id": 1101,
                    "snapshotLastModifiedDate": 1700000000000,
                    "quantity": 1,
                    "productCode": 6101,
                    "id": 7101,
                    "lineId": 7101,
                },
                {
                    "orderNumber": "ORD-SHIPPED",
                    "api_account_id": 1,
                    "order_data_id": 1102,
                    "snapshotLastModifiedDate": 1700000000100,
                    "quantity": 1,
                    "productCode": 6102,
                    "id": 7102,
                    "lineId": 7102,
                },
                {
                    "orderNumber": "ORD-CANCELLED",
                    "api_account_id": 1,
                    "order_data_id": 1103,
                    "snapshotLastModifiedDate": 1700000000200,
                    "quantity": 1,
                    "productCode": 6103,
                    "id": 7103,
                    "lineId": 7103,
                },
                {
                    "orderNumber": "ORD-UNDELIVERED-RETURNED",
                    "api_account_id": 1,
                    "order_data_id": 1104,
                    "snapshotLastModifiedDate": 1700000000300,
                    "quantity": 1,
                    "productCode": 6104,
                    "id": 7104,
                    "lineId": 7104,
                },
                {
                    "orderNumber": "SIM-OPEN",
                    "api_account_id": 1,
                    "order_data_id": 1105,
                    "snapshotLastModifiedDate": 1700000000400,
                    "quantity": 1,
                    "productCode": 6105,
                    "id": 7105,
                    "lineId": 7105,
                },
            ],
        }
        save_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            read_res = orders_pipeline.get_nonfinal_order_numbers()

        self.assertTrue(read_res.success, read_res.message)
        self.assertEqual((read_res.data or {}).get("order_numbers", []), ["ORD-READY", "ORD-SHIPPED"])

    def test_get_latest_orders_includes_multiple_shipment_statuses(self) -> None:
        self._seed_account()
        payload = {
            "order_data_list": [
                {
                    "id": 2001,
                    "orderNumber": "ORD-2001",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000000,
                    "orderDate": 1700000000000,
                    "status": "Picking",
                    "shipmentPackageStatus": "ReadyToShip",
                    "customerFirstName": "A",
                    "customerLastName": "B",
                },
                {
                    "id": 2002,
                    "orderNumber": "ORD-2002",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000100,
                    "orderDate": 1700000000100,
                    "status": "Cancelled",
                    "shipmentPackageStatus": "Cancelled",
                    "customerFirstName": "C",
                    "customerLastName": "D",
                },
            ],
            "order_item_list": [
                {
                    "orderNumber": "ORD-2001",
                    "api_account_id": 1,
                    "order_data_id": 2001,
                    "snapshotLastModifiedDate": 1700000000000,
                    "quantity": 1,
                    "productCode": 701,
                    "id": 1701,
                    "lineId": 1701,
                    "orderLineItemStatusName": "Picking",
                    "merchantSku": "SKU-701",
                    "productName": "Product 701",
                },
                {
                    "orderNumber": "ORD-2002",
                    "api_account_id": 1,
                    "order_data_id": 2002,
                    "snapshotLastModifiedDate": 1700000000100,
                    "quantity": 1,
                    "productCode": 702,
                    "id": 1702,
                    "lineId": 1702,
                    "orderLineItemStatusName": "Cancelled",
                    "merchantSku": "SKU-702",
                    "productName": "Product 702",
                },
            ],
        }
        save_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            read_res = orders_pipeline.get_latest_orders()

        self.assertTrue(read_res.success, read_res.message)
        orders = (read_res.data or {}).get("orders", [])
        statuses = {
            str(getattr(o, "shipmentPackageStatus", None) or getattr(o, "status", "")).strip()
            for o in orders
        }
        self.assertEqual(len(orders), 2)
        self.assertIn("ReadyToShip", statuses)
        self.assertIn("Cancelled", statuses)

    def test_get_latest_orders_filters_by_status_platform_and_date(self) -> None:
        self._seed_account(pk=1)
        create_records(
            model=ApiAccount,
            data_list=[{"pk": 2, "account_id": "ACC-2", "comp_name": "Company 2", "platform": "amazon"}],
            db_name=self.db_path,
            mode="plain",
        )
        payload = {
            "order_data_list": [
                {
                    "id": 2101,
                    "orderNumber": "ORD-TY-IN",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000000,
                    "orderDate": 1700000000000,
                    "status": "Picking",
                    "shipmentPackageStatus": "ReadyToShip",
                },
                {
                    "id": 2102,
                    "orderNumber": "ORD-TY-OUT",
                    "api_account_id": 1,
                    "lastModifiedDate": 1701000000000,
                    "orderDate": 1701000000000,
                    "status": "Picking",
                    "shipmentPackageStatus": "ReadyToShip",
                },
                {
                    "id": 2103,
                    "orderNumber": "ORD-AMZ-IN",
                    "api_account_id": 2,
                    "lastModifiedDate": 1700000005000,
                    "orderDate": 1700000005000,
                    "status": "Picking",
                    "shipmentPackageStatus": "ReadyToShip",
                },
            ],
            "order_item_list": [
                {
                    "orderNumber": "ORD-TY-IN",
                    "api_account_id": 1,
                    "order_data_id": 2101,
                    "snapshotLastModifiedDate": 1700000000000,
                    "quantity": 1,
                    "productCode": 9001,
                    "id": 9101,
                    "lineId": 9101,
                },
                {
                    "orderNumber": "ORD-TY-OUT",
                    "api_account_id": 1,
                    "order_data_id": 2102,
                    "snapshotLastModifiedDate": 1701000000000,
                    "quantity": 1,
                    "productCode": 9002,
                    "id": 9102,
                    "lineId": 9102,
                },
                {
                    "orderNumber": "ORD-AMZ-IN",
                    "api_account_id": 2,
                    "order_data_id": 2103,
                    "snapshotLastModifiedDate": 1700000005000,
                    "quantity": 1,
                    "productCode": 9003,
                    "id": 9103,
                    "lineId": 9103,
                },
            ],
        }
        save_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            read_res = orders_pipeline.get_latest_orders_filtered(
                shipment_statuses=["Created", "ReadyToShip"],
                platform_codes=["TRENDYOL"],
                start_ms=1699999999000,
                end_ms=1700000001000,
            )

        self.assertTrue(read_res.success, read_res.message)
        orders = (read_res.data or {}).get("orders", [])
        self.assertEqual([getattr(row, "orderNumber", "") for row in orders], ["ORD-TY-IN"])

    def test_get_order_full_details_latest_uses_only_latest_snapshot_items(self) -> None:
        self._seed_account()
        payload = {
            "order_data_list": [
                {
                    "id": 3001,
                    "orderNumber": "ORD-LATEST-1",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000000,
                    "orderDate": 1700000000000,
                    "status": "Cancelled",
                    "shipmentPackageStatus": "Cancelled",
                    "customerFirstName": "Old",
                    "customerLastName": "Snapshot",
                },
                {
                    "id": 3002,
                    "orderNumber": "ORD-LATEST-1",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000001000,
                    "orderDate": 1700000001000,
                    "status": "Created",
                    "shipmentPackageStatus": "ReadyToShip",
                    "customerFirstName": "New",
                    "customerLastName": "Snapshot",
                },
            ],
            "order_item_list": [
                {
                    "orderNumber": "ORD-LATEST-1",
                    "api_account_id": 1,
                    "order_data_id": 3001,
                    "snapshotLastModifiedDate": 1700000000000,
                    "quantity": 1,
                    "productCode": 801,
                    "id": 1801,
                    "lineId": 1801,
                    "orderLineItemStatusName": "Cancelled",
                    "merchantSku": "SKU-OLD-A",
                    "productName": "Old Product A",
                },
                {
                    "orderNumber": "ORD-LATEST-1",
                    "api_account_id": 1,
                    "order_data_id": 3001,
                    "snapshotLastModifiedDate": 1700000000000,
                    "quantity": 1,
                    "productCode": 802,
                    "id": 1802,
                    "lineId": 1802,
                    "orderLineItemStatusName": "Cancelled",
                    "merchantSku": "SKU-OLD-B",
                    "productName": "Old Product B",
                },
                {
                    "orderNumber": "ORD-LATEST-1",
                    "api_account_id": 1,
                    "order_data_id": 3002,
                    "snapshotLastModifiedDate": 1700000001000,
                    "quantity": 1,
                    "productCode": 803,
                    "id": 1803,
                    "lineId": 1803,
                    "orderLineItemStatusName": "ReadyToShip",
                    "merchantSku": "SKU-NEW",
                    "productName": "New Product",
                },
            ],
        }
        save_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            read_res = orders_pipeline.get_order_full_details_by_numbers(["ORD-LATEST-1"], mode="latest")

        self.assertTrue(read_res.success, read_res.message)
        orders = (read_res.data or {}).get("orders", [])
        self.assertEqual(len(orders), 1)
        bundle = orders[0]
        items = bundle.get("items", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(getattr(items[0], "merchantSku", ""), "SKU-NEW")

    def test_get_order_full_details_latest_filters_out_older_items_of_same_package(self) -> None:
        self._seed_account()
        payload = {
            "order_data_list": [
                {
                    "id": 3101,
                    "orderNumber": "ORD-LATEST-2",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000000,
                    "orderDate": 1700000000000,
                    "status": "ReadyToShip",
                    "shipmentPackageStatus": "ReadyToShip",
                    "customerFirstName": "Package",
                    "customerLastName": "Old",
                },
                {
                    "id": 3101,
                    "orderNumber": "ORD-LATEST-2",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000001000,
                    "orderDate": 1700000001000,
                    "status": "Shipped",
                    "shipmentPackageStatus": "Shipped",
                    "customerFirstName": "Package",
                    "customerLastName": "New",
                },
            ],
            "order_item_list": [
                {
                    "orderNumber": "ORD-LATEST-2",
                    "api_account_id": 1,
                    "order_data_id": 3101,
                    "snapshotLastModifiedDate": 1700000000000,
                    "quantity": 1,
                    "productCode": 901,
                    "id": 1901,
                    "lineId": 1901,
                    "orderLineItemStatusName": "Picking",
                    "merchantSku": "SKU-DUPLICATE",
                    "productName": "Duplicate Product",
                    "amount": 89.99,
                },
                {
                    "orderNumber": "ORD-LATEST-2",
                    "api_account_id": 1,
                    "order_data_id": 3101,
                    "snapshotLastModifiedDate": 1700000001000,
                    "quantity": 1,
                    "productCode": 901,
                    "id": 1901,
                    "lineId": 1901,
                    "orderLineItemStatusName": "Shipped",
                    "merchantSku": "SKU-DUPLICATE",
                    "productName": "Duplicate Product",
                    "amount": 89.99,
                },
            ],
        }
        save_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            read_res = orders_pipeline.get_order_full_details_by_numbers(["ORD-LATEST-2"], mode="latest")

        self.assertTrue(read_res.success, read_res.message)
        orders = (read_res.data or {}).get("orders", [])
        self.assertEqual(len(orders), 1)
        bundle = orders[0]
        data = bundle.get("data", [])
        self.assertEqual(len(data), 1)
        self.assertEqual(getattr(data[0], "shipmentPackageStatus", ""), "Shipped")
        items = bundle.get("items", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(getattr(items[0], "snapshotLastModifiedDate", None), 1700000001000)

    def _sample_return_claim(
        self,
        *,
        claim_id: str = "CLM-1001",
        status: str = "WaitingInAction",
        last_modified: int = 1700000000000,
        claim_date: int = 1700000000000,
        item_ids: list[str] | None = None,
    ) -> dict:
        line_ids = list(item_ids or ["LINE-1", "LINE-2"])
        return {
            "id": claim_id,
            "claimId": claim_id,
            "claimNumber": claim_id,
            "orderNumber": "ORD-1001",
            "orderDate": 1699999999000,
            "claimDate": claim_date,
            "lastModifiedDate": last_modified,
            "customerFirstName": "Return",
            "customerLastName": "Customer",
            "cargoTrackingNumber": "RET-TRACK-1",
            "cargoProviderName": "Trendyol Express Marketplace",
            "orderShipmentPackageId": 1001,
            "orderOutboundPackageId": 654321,
            "items": [
                {
                    "orderLine": {
                        "id": 5001,
                        "productName": "Return Product",
                        "barcode": "RET-BARCODE-1",
                        "merchantSku": "RET-SKU-1",
                        "price": 35.0,
                    },
                    "claimItems": [
                        {
                            "id": line_id,
                            "orderLineItemId": 9000 + idx,
                            "claimItemStatus": {"name": status},
                            "customerClaimItemReason": {"name": "Beğenmedim"},
                            "trendyolClaimItemReason": {"name": "Beğenmedim"},
                        }
                        for idx, line_id in enumerate(line_ids, start=1)
                    ],
                }
            ],
        }

    def test_format_order_status_maps_code_to_user_label(self) -> None:
        self.assertEqual(orders_actions.format_order_status("ReadyToShip"), "Kargoya Hazır")
        self.assertEqual(orders_actions.format_order_status("AtCollectionPoint"), "Teslimat Noktasında")

    def test_filter_orders_uses_shipment_status_code(self) -> None:
        orders = [
            SimpleNamespace(
                orderNumber="ORD-A",
                shipmentPackageStatus="ReadyToShip",
                status="Picking",
                customerFirstName="A",
                customerLastName="B",
            ),
            SimpleNamespace(
                orderNumber="ORD-B",
                shipmentPackageStatus="Cancelled",
                status="Cancelled",
                customerFirstName="C",
                customerLastName="D",
            ),
        ]

        res = orders_actions.filter_orders(
            orders,
            {
                "processed_mode": "all",
                "shipment_status": "İptal Edildi",
                "shipment_status_code": "Cancelled",
                "date_enabled": False,
            },
        )
        self.assertTrue(res.success, res.message)
        filtered = (res.data or {}).get("filtered", [])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(getattr(filtered[0], "orderNumber", ""), "ORD-B")

    def test_filter_orders_uses_platform_filter_with_api_account_fallback(self) -> None:
        trendyol_order = SimpleNamespace(
            orderNumber="ORD-TY",
            api_account=SimpleNamespace(platform="TRENDYOL"),
        )
        amazon_order = SimpleNamespace(
            orderNumber="ORD-AMZ",
            api_account=SimpleNamespace(platform="AMAZON"),
        )

        res = orders_actions.filter_orders(
            [trendyol_order, amazon_order],
            {
                "platform": "Trendyol",
                "platform_code": "TRENDYOL",
                "date_enabled": False,
            },
        )

        self.assertTrue(res.success, res.message)
        filtered = (res.data or {}).get("filtered", [])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(getattr(filtered[0], "orderNumber", ""), "ORD-TY")

    def test_shipment_status_codes_for_load_expands_ui_aliases(self) -> None:
        self.assertIsNone(orders_actions.shipment_status_codes_for_load("all"))
        self.assertIsNone(orders_actions.shipment_status_codes_for_load("Tümü"))
        self.assertIsNone(orders_actions.shipment_status_codes_for_load("Seçiniz"))
        self.assertEqual(
            orders_actions.shipment_status_codes_for_load("Created"),
            ["Created", "ReadyToShip"],
        )
        self.assertEqual(
            orders_actions.shipment_status_codes_for_load("ReadyToShip"),
            ["Created", "ReadyToShip"],
        )
        self.assertEqual(
            orders_actions.shipment_status_codes_for_load("Cancelled"),
            ["Cancelled", "Unsupplied"],
        )
        self.assertIsNone(orders_actions.return_status_codes_for_load("Tümü"))
        self.assertIsNone(orders_actions._platform_codes_for_load("Tümü"))
        self.assertIsNone(orders_actions._platform_codes_for_load("Seçiniz"))
        self.assertEqual(
            orders_actions.return_status_codes_for_load("Aktif Iadeler"),
            ["Created", "WaitingInAction", "WaitingFraudCheck", "InAnalysis", "Unresolved"],
        )
        self.assertEqual(
            orders_actions.return_status_codes_for_load("__open_returns__"),
            ["Created", "WaitingInAction", "WaitingFraudCheck", "InAnalysis", "Unresolved"],
        )
        self.assertEqual(orders_actions._platform_codes_for_load("TRENDYOL"), ["TRENDYOL"])

    def test_filter_orders_treats_selection_placeholders_as_no_filter(self) -> None:
        order = SimpleNamespace(
            orderNumber="ORD-001",
            shipmentPackageStatus="ReadyToShip",
            status="ReadyToShip",
            customerFirstName="Ali",
            customerLastName="Veli",
            cargoProviderName="Trendyol Express Marketplace",
            cargoTrackingNumber="",
            totalPrice=99.99,
            orderDate=datetime(2026, 4, 1, 10, 30, 0),
            api_account=SimpleNamespace(platform="TRENDYOL"),
        )

        res = orders_actions.filter_orders(
            [order],
            {
                "cargo": "Seçiniz",
                "platform": "Tümü",
                "platform_code": "",
                "shipment_status": "Tümü",
                "shipment_status_code": "",
                "deadline_category": "all",
                "processed_mode": "all",
                "date_enabled": True,
                "date_from": datetime(2026, 3, 4).date(),
                "date_to": datetime(2026, 4, 4).date(),
            },
        )

        self.assertTrue(res.success, res.message)
        filtered = (res.data or {}).get("filtered", [])
        self.assertEqual(len(filtered), 1)

    def test_filter_orders_global_search_does_not_touch_detached_items_relationship(self) -> None:
        class _DetachedOrder:
            def __init__(self) -> None:
                self.orderNumber = "11099694168"
                self.shipmentPackageStatus = "ReadyToShip"
                self.status = "ReadyToShip"
                self.customerFirstName = "Ali"
                self.customerLastName = "Veli"
                self.cargoProviderName = "Trendyol Express"
                self.claimNumber = ""
                self.claimId = ""
                self.claimReason = ""
                self.cargoTrackingNumber = ""

            @property
            def items(self):
                raise AssertionError("lazy relationship should not be touched")

        res = orders_actions.filter_orders(
            [_DetachedOrder()],
            {
                "global": "11099694168",
                "processed_mode": "all",
                "date_enabled": False,
            },
        )

        self.assertTrue(res.success, res.message)
        filtered = (res.data or {}).get("filtered", [])
        self.assertEqual(len(filtered), 1)

    def test_resolve_order_platform_code_caches_api_account_fallback(self) -> None:
        order = SimpleNamespace(
            orderNumber="ORD-CACHE",
            api_account=SimpleNamespace(platform="TRENDYOL"),
        )

        self.assertEqual(orders_actions.resolve_order_platform_code(order), "TRENDYOL")
        self.assertEqual(getattr(order, "_orders_platform_code_cache", ""), "TRENDYOL")

    def test_get_order_date_caches_first_resolved_date(self) -> None:
        order = SimpleNamespace(orderDate=datetime(2026, 3, 19, 10, 30, 0))

        resolved = orders_actions.get_order_date(order)

        self.assertEqual(str(resolved), "2026-03-19")
        self.assertEqual(str(getattr(order, "_orders_date_cache", None)), "2026-03-19")

    def test_list_changeable_cargo_providers_filters_by_platform(self) -> None:
        trendyol_rows = orders_actions.list_changeable_cargo_providers("TRENDYOL")
        etsy_rows = orders_actions.list_changeable_cargo_providers("ETSY")

        self.assertTrue(any(str(row.get("code") or "") == "TEXMP" for row in trendyol_rows))
        self.assertFalse(any(str(row.get("code") or "") == "TEXMP" for row in etsy_rows))
        self.assertTrue(all(str(row.get("code") or "").strip() for row in trendyol_rows))

    def test_cargo_provider_code_for_name_handles_turkish_character_variants(self) -> None:
        self.assertEqual(
            orders_actions.cargo_provider_code_for_name(
                "Yurtiçi Kargo Marketplace",
                platform_code="TRENDYOL",
            ),
            "YKMP",
        )
        self.assertEqual(
            orders_actions.cargo_provider_code_for_name(
                "Yurtiçi Kargo Marketplace (YKMP)",
                platform_code="TRENDYOL",
            ),
            "YKMP",
        )

    def test_order_platform_filter_options_use_shared_catalog(self) -> None:
        self.assertEqual(
            orders_actions.order_platform_filter_options(include_all=False),
            platform_select_options(include_all=False),
        )

    def test_refresh_cargo_filter_only_shows_current_order_cargos(self) -> None:
        class _FakeCombo:
            def __init__(self) -> None:
                self.items: list[str] = []
                self.current_text = ""

            def blockSignals(self, _value: bool) -> None:
                return None

            def clear(self) -> None:
                self.items = []

            def addItem(self, text, data=None) -> None:
                _ = data
                self.items.append(str(text))

            def addItems(self, items) -> None:
                for item in items or []:
                    self.items.append(str(item))

            def setCurrentText(self, text: str) -> None:
                self.current_text = str(text or "")

        combo = _FakeCombo()
        orders = [
            SimpleNamespace(cargoProviderName="Trendyol Express Marketplace", api_account=SimpleNamespace(platform="TRENDYOL")),
            SimpleNamespace(cargoProviderName="Aras Kargo Marketplace", api_account=SimpleNamespace(platform="TRENDYOL")),
        ]

        res = orders_actions.refresh_cargo_filter(
            combo,
            orders,
            platform_code="TRENDYOL",
            preferred_cargo="Aras Kargo Marketplace",
        )

        self.assertTrue(res.success, res.message)
        self.assertEqual(
            combo.items,
            ["Tümü", "Aras Kargo Marketplace", "Trendyol Express Marketplace"],
        )
        self.assertEqual(combo.current_text, "Aras Kargo Marketplace")

    def test_compute_main_fetch_window_prefers_last_used_delta(self) -> None:
        now_ms = 1_700_000_000_000
        one_hour_ago = now_ms - (60 * 60 * 1000)
        final_ep, start_ep = orders_actions._compute_main_fetch_window(
            now_ms=now_ms,
            last_used_ms_list=[one_hour_ago],
            initial_lookback_hours=24 * 30,
        )
        self.assertEqual(start_ep, now_ms)
        self.assertEqual(final_ep, one_hour_ago - (10 * 60 * 1000))

    def test_compute_main_fetch_window_uses_older_last_used_when_available(self) -> None:
        now_ms = 1_700_000_000_000
        five_days_ago = now_ms - (5 * 24 * 60 * 60 * 1000)
        final_ep, start_ep = orders_actions._compute_main_fetch_window(
            now_ms=now_ms,
            last_used_ms_list=[five_days_ago],
            initial_lookback_hours=24 * 30,
        )
        self.assertEqual(start_ep, now_ms)
        self.assertEqual(final_ep, five_days_ago - (10 * 60 * 1000))

    def test_compute_main_fetch_window_defaults_to_30_days_without_last_used(self) -> None:
        now_ms = 1_700_000_000_000
        final_ep, start_ep = orders_actions._compute_main_fetch_window(
            now_ms=now_ms,
            last_used_ms_list=[],
        )
        safety_ms = int(orders_actions.MAX_FETCH_WINDOW_SAFETY_MINUTES) * 60 * 1000
        self.assertEqual(start_ep, now_ms)
        self.assertEqual(final_ep, now_ms - (30 * 24 * 60 * 60 * 1000) + safety_ms)

    def test_compute_main_fetch_window_clamps_old_last_used_to_30_days(self) -> None:
        now_ms = 1_700_000_000_000
        ninety_days_ago = now_ms - (90 * 24 * 60 * 60 * 1000)
        final_ep, start_ep = orders_actions._compute_main_fetch_window(
            now_ms=now_ms,
            last_used_ms_list=[ninety_days_ago],
        )
        safety_ms = int(orders_actions.MAX_FETCH_WINDOW_SAFETY_MINUTES) * 60 * 1000
        self.assertEqual(start_ep, now_ms)
        self.assertEqual(final_ep, now_ms - (30 * 24 * 60 * 60 * 1000) + safety_ms)

    def test_split_status_query_windows_splits_ranges_over_14_days(self) -> None:
        start_ms = 1_700_000_000_000
        end_ms = start_ms + (15 * 24 * 60 * 60 * 1000)
        windows = orders_pipeline._split_status_query_windows(start_ms, end_ms)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0][0], start_ms)
        self.assertEqual(windows[-1][1], end_ms)

    def test_fetch_orders_for_status_queries_multiple_windows(self) -> None:
        class FakeApi:
            def __init__(self) -> None:
                self.calls = []

            async def find_orders(self, status, start_date, end_date, page):
                self.calls.append((status, start_date, end_date, page))
                if page > 0:
                    return Result.ok(data={"content": []}, close_dialog=False)
                payload = {
                    "id": len(self.calls),
                    "lastModifiedDate": end_date,
                    "orderNumber": f"ORD-{len(self.calls)}",
                    "status": status,
                    "shipmentPackageStatus": "ReadyToShip",
                    "packageHistories": [{"createdDate": end_date, "status": status}],
                    "lines": [{"quantity": 1, "productCode": len(self.calls)}],
                }
                return Result.ok(data={"content": [payload]}, close_dialog=False)

        fake_api = FakeApi()
        start_ms = 1_700_000_000_000
        end_ms = start_ms + (15 * 24 * 60 * 60 * 1000)
        res = asyncio.run(
            orders_pipeline.fetch_orders_for_status(
                api=fake_api,
                status="Created",
                comp_api_account_id=1,
                start_page=0,
                final_ep_time=start_ms,
                start_ep_time=end_ms,
            )
        )
        self.assertTrue(res.success, res.message)
        self.assertEqual(len((res.data or {}).get("orders", [])), 2)
        self.assertEqual(len(fake_api.calls), 4)
        diagnostics = (res.data or {}).get("sync_diagnostics") or {}
        self.assertEqual(diagnostics.get("source_rows_seen"), 2)
        self.assertEqual(diagnostics.get("normalized_order_rows"), 2)
        self.assertEqual(diagnostics.get("skipped_source_rows"), 0)
        self.assertTrue(diagnostics.get("source_rows_complete"))
        self.assertEqual(diagnostics.get("windows_queried"), 2)
        self.assertEqual(diagnostics.get("pages_queried"), 4)

    def test_fetch_orders_for_status_rejects_partial_page_failure_with_diagnostics(self) -> None:
        class FakeApi:
            environment = "stage"

            async def find_orders(self, status, start_date, end_date, page):
                if page == 0:
                    return Result.ok(
                        data={
                            "content": [
                                {
                                    "id": 501,
                                    "shipmentPackageId": 501,
                                    "lastModifiedDate": end_date,
                                    "orderNumber": "ORD-PARTIAL-1",
                                    "status": status,
                                    "lines": [{"id": 1, "quantity": 1, "productCode": 1}],
                                }
                            ],
                            "totalPages": 3,
                        },
                        close_dialog=False,
                    )
                return Result.fail(
                    "HTTP 503",
                    close_dialog=False,
                    data={"status_code": 503},
                )

        res = asyncio.run(
            orders_pipeline.fetch_orders_for_status(
                api=FakeApi(),
                status="Created",
                comp_api_account_id=2,
                start_page=0,
                final_ep_time=1_700_000_000_000,
                start_ep_time=1_700_000_000_000,
            )
        )

        self.assertFalse(res.success)
        self.assertEqual(len((res.data or {}).get("orders") or []), 1)
        diagnostics = (res.data or {}).get("sync_diagnostics") or {}
        self.assertFalse(diagnostics.get("source_rows_complete"))
        self.assertEqual(diagnostics.get("fetch_errors"), 1)
        self.assertEqual((diagnostics.get("fetch_error") or {}).get("kind"), "request_failed")
        self.assertEqual((diagnostics.get("fetch_error") or {}).get("page"), 1)

    def test_fetch_orders_for_status_rejects_empty_page_before_reported_end(self) -> None:
        class FakeApi:
            environment = "stage"

            async def find_orders(self, status, start_date, end_date, page):
                return Result.ok(
                    data={"content": [], "totalPages": 3, "page": page},
                    close_dialog=False,
                )

        res = asyncio.run(
            orders_pipeline.fetch_orders_for_status(
                api=FakeApi(),
                status="Picking",
                comp_api_account_id=2,
                start_page=0,
                final_ep_time=1_700_000_000_000,
                start_ep_time=1_700_000_000_000,
            )
        )

        self.assertFalse(res.success)
        diagnostics = (res.data or {}).get("sync_diagnostics") or {}
        self.assertFalse(diagnostics.get("source_rows_complete"))
        self.assertEqual(
            (diagnostics.get("fetch_error") or {}).get("kind"),
            "empty_page_before_reported_end",
        )

    def test_fetch_claims_reports_empty_intermediate_page_as_partial(self) -> None:
        account = SimpleNamespace(pk=2, account_id="2738", comp_name="Stage Test")

        class FakeApi:
            async def find_claims(self, **kwargs):
                page = int(kwargs.get("page") or 0)
                if page == 0:
                    return Result.ok(
                        data={
                            "content": [
                                {
                                    "claimId": "CLAIM-PARTIAL-1",
                                    "claimDate": 1_700_000_000_000,
                                    "lastModifiedDate": 1_700_000_000_000,
                                    "items": [],
                                }
                            ],
                            "totalPages": 3,
                        },
                        close_dialog=False,
                    )
                return Result.ok(
                    data={"content": [], "totalPages": 3, "page": page},
                    close_dialog=False,
                )

        with patch.object(orders_actions, "_trendyol_api_for_account", return_value=FakeApi()):
            rows, errors = asyncio.run(
                orders_actions._fetch_claims_for_account(
                    account,
                    start_ms=1_699_000_000_000,
                    end_ms=1_700_000_000_000,
                    size=50,
                )
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("pagination eksik", errors[0])

    def test_fetch_orders_all_policy_excludes_identityless_awaiting_rows_without_inventing_ids(self) -> None:
        class FakeApi:
            def __init__(self, **kwargs) -> None:
                self.environment = kwargs.get("environment", "production")

            async def find_orders(self, status, start_date, end_date, page):
                if page > 0:
                    return Result.ok(data={"content": []}, close_dialog=False)
                return Result.ok(
                    data={
                        "content": [
                            {
                                "id": 7001,
                                "shipmentPackageId": 7001,
                                "orderNumber": "ORD-VALID",
                                "lastModifiedDate": end_date,
                                "status": status,
                                "lines": [{"id": 71, "quantity": 1, "productCode": 701}],
                            },
                            {
                                "shipmentPackageId": None,
                                "orderNumber": "ORD-IDENTITYLESS",
                                "lastModifiedDate": end_date,
                                "status": status,
                                "lines": [{"id": 72, "quantity": 1, "productCode": 702}],
                            },
                        ]
                    },
                    close_dialog=False,
                )

        account_payload = [
            2,
            "stage-key",
            "stage-secret",
            "2738",
            None,
            {"environment": "stage"},
        ]
        with patch.object(orders_pipeline, "TrendyolApi", FakeApi):
            res = asyncio.run(
                orders_pipeline.fetch_orders_all(
                    ["Awaiting"],
                    1_700_000_000_000,
                    1_700_000_000_000,
                    [account_payload],
                )
            )

        self.assertTrue(res.success, res.message)
        self.assertEqual(len((res.data or {}).get("order_data_list", [])), 1)
        diagnostics = (res.data or {}).get("sync_diagnostics") or {}
        self.assertEqual(diagnostics.get("source_rows_seen"), 2)
        self.assertEqual(diagnostics.get("normalized_order_rows"), 1)
        self.assertEqual(diagnostics.get("skipped_source_rows"), 0)
        self.assertEqual(diagnostics.get("policy_excluded_source_rows"), 1)
        self.assertTrue(diagnostics.get("source_rows_complete"))
        self.assertEqual(
            (diagnostics.get("policy_excluded_reasons") or {}).get("missing_snapshot_identity"),
            1,
        )
        self.assertEqual((diagnostics.get("runs") or [])[0].get("environment"), "stage")
        self.assertNotIn("ORD-IDENTITYLESS", repr(diagnostics))
        self.assertIn("operational sipariş snapshot'ı dışında", res.message)

    def test_fetch_orders_all_rejects_identityless_actionable_rows_without_inventing_ids(self) -> None:
        class FakeApi:
            def __init__(self, **kwargs) -> None:
                self.environment = kwargs.get("environment", "production")

            async def find_orders(self, status, start_date, end_date, page):
                return Result.ok(
                    data={
                        "content": []
                        if page > 0
                        else [
                            {
                                "shipmentPackageId": None,
                                "orderNumber": "ORD-ACTIONABLE-IDENTITYLESS",
                                "lastModifiedDate": end_date,
                                "status": status,
                                "lines": [],
                            }
                        ]
                    },
                    close_dialog=False,
                )

        account_payload = [2, "stage-key", "stage-secret", "2738", None, {"environment": "stage"}]
        with patch.object(orders_pipeline, "TrendyolApi", FakeApi):
            res = asyncio.run(
                orders_pipeline.fetch_orders_all(
                    ["Created"],
                    1_700_000_000_000,
                    1_700_000_000_000,
                    [account_payload],
                )
            )

        self.assertTrue(res.success, res.message)
        diagnostics = (res.data or {}).get("sync_diagnostics") or {}
        self.assertEqual(diagnostics.get("source_rows_seen"), 1)
        self.assertEqual(diagnostics.get("skipped_source_rows"), 1)
        self.assertEqual(diagnostics.get("policy_excluded_source_rows"), 0)
        self.assertFalse(diagnostics.get("source_rows_complete"))
        self.assertNotIn("ORD-ACTIONABLE-IDENTITYLESS", repr(diagnostics))
        self.assertIn("uydurma kimlik", res.message)

    def test_fetch_orders_all_deduplicates_same_snapshot_across_status_queries(self) -> None:
        class FakeApi:
            def __init__(self, **kwargs) -> None:
                self.environment = kwargs.get("environment", "production")

            async def find_orders(self, status, start_date, end_date, page):
                if page > 0:
                    return Result.ok(data={"content": []}, close_dialog=False)
                return Result.ok(
                    data={
                        "content": [
                            {
                                "id": 8101,
                                "shipmentPackageId": 8101,
                                "orderNumber": "ORD-SHARED-SNAPSHOT",
                                "lastModifiedDate": end_date,
                                "status": "Picking",
                                "lines": [{"id": 81, "lineId": 81, "quantity": 1, "productCode": 801}],
                            }
                        ]
                    },
                    close_dialog=False,
                )

        account_payload = [1, "key", "secret", "2738", None, {"environment": "stage"}]
        with patch.object(orders_pipeline, "TrendyolApi", FakeApi):
            res = asyncio.run(
                orders_pipeline.fetch_orders_all(
                    ["Created", "Picking"],
                    1_700_000_000_000,
                    1_700_000_000_000,
                    [account_payload],
                )
            )

        self.assertTrue(res.success, res.message)
        self.assertEqual(len((res.data or {}).get("order_data_list", [])), 1)
        self.assertEqual(len((res.data or {}).get("order_item_list", [])), 1)
        diagnostics = (res.data or {}).get("sync_diagnostics") or {}
        self.assertEqual(diagnostics.get("source_rows_seen"), 2)
        self.assertEqual(diagnostics.get("normalized_order_rows"), 2)
        self.assertEqual(diagnostics.get("emitted_order_rows"), 1)
        self.assertEqual(diagnostics.get("emitted_item_rows"), 1)
        self.assertEqual(diagnostics.get("duplicate_order_rows"), 1)
        self.assertEqual(diagnostics.get("duplicate_item_rows"), 1)
        self.assertTrue(diagnostics.get("source_rows_complete"))

    def test_save_orders_to_db_preserves_fetch_completeness_diagnostics(self) -> None:
        self._seed_account()
        payload = self._sample_payload()
        payload["sync_diagnostics"] = {
            "source_rows_seen": 2,
            "normalized_order_rows": 1,
            "skipped_source_rows": 1,
            "skipped_reasons": {"missing_snapshot_identity": 1},
            "source_rows_complete": False,
        }

        save_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)

        self.assertTrue(save_res.success, save_res.message)
        diagnostics = (save_res.data or {}).get("sync_diagnostics") or {}
        self.assertFalse(diagnostics.get("source_rows_complete"))
        self.assertEqual(diagnostics.get("skipped_source_rows"), 1)
        persistence = diagnostics.get("persistence") or {}
        self.assertEqual(persistence.get("input_order_rows"), 1)
        self.assertEqual(persistence.get("eligible_order_rows"), 1)
        self.assertEqual(persistence.get("rejected_order_rows"), 0)
        self.assertTrue(persistence.get("input_rows_complete"))

    def test_refresh_nonfinal_orders_normalizes_order_number_response_without_awaiting_sync_normalizer(self) -> None:
        class FakeApi:
            async def get_order_by_number(self, order_number, page=0, size=50):
                return Result.ok(
                    "ok",
                    close_dialog=False,
                    data={
                        "content": [
                            {
                                "id": 9001,
                                "shipmentPackageId": 9001,
                                "orderNumber": order_number,
                                "lastModifiedDate": 1700000005000,
                                "orderDate": 1700000000000,
                                "status": "Delivered",
                                "shipmentPackageStatus": "Delivered",
                                "lines": [
                                    {
                                        "quantity": 1,
                                        "productCode": 9001,
                                        "id": 19001,
                                        "lineId": 19001,
                                    }
                                ],
                            }
                        ]
                    },
                )

        with patch.object(orders_actions, "_trendyol_api", return_value=FakeApi()):
            res = asyncio.run(
                orders_actions._refresh_nonfinal_orders_async(
                    ["ORD-OLD-READY"],
                    [(1, "api-key", "api-secret", "seller-id", None)],
                )
            )

        self.assertTrue(res.success, res.message)
        orders = (res.data or {}).get("order_data_list", [])
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["shipmentPackageStatus"], "Delivered")

    def test_active_returns_refresh_success_advances_to_nonfinal_stage(self) -> None:
        source = inspect.getsource(orders_actions.get_orders_from_companies)
        start = source.index("def handle_active_returns_refresh")
        end = source.index("parent_widget.active_returns_refresh_worker.result_ready", start)
        handler_source = source[start:end]

        self.assertIn("_start_nonfinal_stage()", handler_source)
        self.assertNotIn("_start_active_returns_refresh_stage()", handler_source)

    def test_active_returns_refresh_defaults_to_claim_id_verification_without_status_scan(self) -> None:
        account = SimpleNamespace(pk=1)
        claim = SimpleNamespace(claimId="CLM-ACTIVE-1", api_account_id=1)
        calls: list[dict] = []

        async def fake_fetch(accounts, **kwargs):
            calls.append(dict(kwargs))
            return Result.ok(
                "ok",
                close_dialog=False,
                data={
                    "return_claim_list": [
                        {
                            "api_account_id": 1,
                            "claimId": "CLM-ACTIVE-1",
                            "claimNumber": "CLM-ACTIVE-1",
                            "orderNumber": "ORD-ACTIVE-1",
                            "claimItemStatus": "WaitingInAction",
                            "lastModifiedDate": 1700000000000,
                        }
                    ],
                    "errors": [],
                },
            )

        with patch.object(
            orders_actions,
            "get_latest_return_claims_filtered",
            return_value=Result.ok("local", close_dialog=False, data={"claims": [claim]}),
        ), patch.object(
            orders_actions,
            "_fetch_returns_from_active_companies_async",
            side_effect=fake_fetch,
        ), patch.object(
            orders_actions,
            "save_return_claims_to_db",
            return_value=Result.ok(
                "saved",
                close_dialog=False,
                data={"changed": False, "counts": {"claims_inserted": 0, "claims_restored": 0}},
            ),
        ):
            res = asyncio.run(orders_actions._refresh_active_return_claims_from_api_async([account]))

        self.assertTrue(res.success, res.message)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get("claim_ids"), ["CLM-ACTIVE-1"])
        self.assertNotIn("claim_item_status", calls[0])

    def test_nonfinal_refresh_interval_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "orders_runtime_state.json"
            now_ms = 1_700_000_000_000

            should_first = orders_actions._should_run_nonfinal_refresh(
                now_ms=now_ms,
                interval_hours=6,
                state_path=state_path,
            )
            self.assertTrue(should_first)

            orders_actions._mark_nonfinal_refresh_completed(
                now_ms=now_ms,
                state_path=state_path,
            )

            should_second = orders_actions._should_run_nonfinal_refresh(
                now_ms=now_ms + (2 * 60 * 60 * 1000),
                interval_hours=6,
                state_path=state_path,
            )
            self.assertFalse(should_second)

            should_third = orders_actions._should_run_nonfinal_refresh(
                now_ms=now_ms + (7 * 60 * 60 * 1000),
                interval_hours=6,
                state_path=state_path,
            )
            self.assertTrue(should_third)

    def test_progress_main_to_59_ignores_updates_when_locked(self) -> None:
        btn = self._DummyProgress()
        orders_actions._set_progress_lock(btn, True)
        orders_actions._progress_main_to_59(btn, 5, 5)
        self.assertIsNone(btn.value)

        orders_actions._set_progress_lock(btn, False)
        orders_actions._progress_main_to_59(btn, 5, 5)
        self.assertEqual(btn.value, 59)

    def test_progress_returns_to_79(self) -> None:
        btn = self._DummyProgress()
        orders_actions._set_progress_lock(btn, False)
        orders_actions._progress_returns_60_to_79(btn, 5, 5)
        self.assertEqual(btn.value, 79)

    def test_set_progress_stage_text_updates_button_text(self) -> None:
        btn = self._DummyProgress()
        orders_actions.set_progress_stage_text(btn, "Siparişler çekiliyor...")
        self.assertEqual(btn.running_text, "Siparişler çekiliyor...")

    def test_normalize_detail_action_status_maps_ready_to_ship_to_created(self) -> None:
        order = SimpleNamespace(shipmentPackageStatus="ReadyToShip", status="")
        self.assertEqual(
            orders_views.OrdersManagerWindow._normalize_detail_action_status(order),
            "created",
        )

    def test_returns_window_defaults_status_filter_to_waiting_action(self) -> None:
        class _DummyFilter:
            def __init__(self) -> None:
                self.current_text = ""
                self.signal_blocks: list[bool] = []

            def blockSignals(self, blocked: bool) -> None:
                self.signal_blocks.append(bool(blocked))

            def setCurrentText(self, text: str) -> None:
                self.current_text = str(text or "")

        dummy_window = SimpleNamespace(
            order_status_filter=_DummyFilter(),
            _is_returns_mode=lambda: True,
        )

        orders_views.OrdersManagerWindow._apply_default_order_status_selection(dummy_window)

        self.assertEqual(dummy_window.order_status_filter.current_text, "Aksiyon Bekliyor")
        self.assertEqual(dummy_window.order_status_filter.signal_blocks, [True, False])

    def test_returns_window_stale_result_populates_review_list(self) -> None:
        class _DummyList:
            def __init__(self) -> None:
                self.orders = []
                self.filtered_orders = []
                self.cleared = False

            def clear_active_order(self) -> None:
                self.cleared = True

            def apply_filter_result(self, rows) -> None:
                self.filtered_orders = list(rows or [])

        class _DummyLabel:
            def __init__(self) -> None:
                self.text = ""

            def setText(self, text: str) -> None:
                self.text = str(text or "")

        claim = SimpleNamespace(claimId="CLM-ST-UI", sync_deleted_at="2026-01-01T00:00:00")
        dummy_list = _DummyList()
        dummy_window = SimpleNamespace(
            _order_items_cache={"x": 1},
            _active_order=claim,
            list_widget=dummy_list,
            selected_count_label=_DummyLabel(),
            _update_label=lambda: None,
            _update_pagination_ui=lambda: None,
            _refresh_selection_side_panel=lambda: None,
        )

        with patch.object(returns_views.MessageHandler, "show"):
            returns_views.ReturnsManagerWindow._show_stale_returns_result(
                dummy_window,
                Result.ok("ok", close_dialog=False, data={"claims": [claim]}),
            )

        self.assertEqual(dummy_window._order_items_cache, {})
        self.assertIsNone(dummy_window._active_order)
        self.assertTrue(dummy_list.cleared)
        self.assertEqual(dummy_list.orders, [claim])
        self.assertEqual(dummy_list.filtered_orders, [claim])
        self.assertIn("Stale iade", dummy_window.selected_count_label.text)

    def test_returns_window_restore_selected_stale_claim_calls_action(self) -> None:
        class _DummyList:
            def __init__(self) -> None:
                self.cleared = False

            def clear_active_order(self) -> None:
                self.cleared = True

        claim = SimpleNamespace(
            claimId="CLM-ST-RESTORE-UI",
            claimNumber="",
            api_account_id=7,
            sync_deleted_at="2026-01-01T00:00:00",
        )
        shown: dict[str, Result] = {}
        dummy_window = SimpleNamespace(
            _is_returns_mode=lambda: True,
            _active_order=claim,
            _order_items_cache={"x": 1},
            list_widget=_DummyList(),
            _returns_date_window_ms=lambda: (0, 9999999999999),
            _show_stale_returns_result=lambda result: shown.setdefault("result", result),
        )

        with patch.object(returns_views.MessageHandler, "show"), patch.object(
            returns_views,
            "restore_return_claims_from_stale",
            return_value=Result.ok("restored", close_dialog=False, data={"restored": 1}),
        ) as restore_mock, patch.object(
            returns_views,
            "get_stale_return_claims",
            return_value=Result.ok("stale", close_dialog=False, data={"claims": []}),
        ) as stale_mock:
            returns_views.ReturnsManagerWindow._on_restore_stale_return_clicked(dummy_window)

        restore_mock.assert_called_once_with(
            claim_ids=["CLM-ST-RESTORE-UI"],
            api_account_ids=[7],
            reason="manual returns stale restore",
        )
        stale_mock.assert_called_once_with(start_ms=0, end_ms=9999999999999)
        self.assertEqual(dummy_window._order_items_cache, {})
        self.assertIsNone(dummy_window._active_order)
        self.assertTrue(dummy_window.list_widget.cleared)
        self.assertTrue(shown["result"].success)

    def test_summarize_order_shipping_deadline_for_future_order(self) -> None:
        order = SimpleNamespace(_is_return=False, agreedDeliveryDate=1_700_097_200_000, status="Created")
        info = orders_actions.summarize_order_shipping_deadline(order, now_ms=1_700_000_000_000)
        self.assertFalse(info["is_overdue"])
        self.assertEqual(info["text"], "1 gün 3 saat var kargolamaya")

    def test_summarize_order_shipping_deadline_for_overdue_order(self) -> None:
        order = SimpleNamespace(_is_return=False, agreedDeliveryDate=1_699_989_200_000, status="Created")
        info = orders_actions.summarize_order_shipping_deadline(order, now_ms=1_700_000_000_000)
        self.assertTrue(info["is_overdue"])
        self.assertEqual(info["text"], "3 saat gecikti")

    def test_summarize_order_shipping_deadline_supports_datetime_values(self) -> None:
        deadline_dt = datetime.fromtimestamp(1_700_097_200_000 / 1000, tz=orders_actions.TZ_GMT3).replace(tzinfo=None)
        order = SimpleNamespace(_is_return=False, agreedDeliveryDate=deadline_dt, shipmentPackageStatus="ReadyToShip")
        info = orders_actions.summarize_order_shipping_deadline(order, now_ms=1_700_000_000_000)
        self.assertFalse(info["is_overdue"])
        self.assertEqual(info["text"], "1 gün 3 saat var kargolamaya")

    def test_classify_order_shipping_deadline_buckets(self) -> None:
        overdue = SimpleNamespace(_is_return=False, agreedDeliveryDate=1_699_989_200_000, status="Created")
        due_today = SimpleNamespace(_is_return=False, agreedDeliveryDate=1_700_050_400_000, shipmentPackageStatus="ReadyToShip")
        sufficient = SimpleNamespace(_is_return=False, agreedDeliveryDate=1_700_136_800_000, status="Created")

        now_ms = 1_700_000_000_000
        self.assertEqual(orders_actions.classify_order_shipping_deadline(overdue, now_ms=now_ms), "overdue")
        self.assertEqual(orders_actions.classify_order_shipping_deadline(due_today, now_ms=now_ms), "due_today")
        self.assertEqual(orders_actions.classify_order_shipping_deadline(sufficient, now_ms=now_ms), "sufficient_time")

    def test_filter_orders_by_deadline_category(self) -> None:
        now_ms = 1_700_000_000_000
        overdue = SimpleNamespace(_is_return=False, agreedDeliveryDate=1_699_989_200_000, status="Created")
        due_today = SimpleNamespace(_is_return=False, agreedDeliveryDate=1_700_050_400_000, status="Created")
        sufficient = SimpleNamespace(_is_return=False, agreedDeliveryDate=1_700_136_800_000, status="Created")
        orders = [overdue, due_today, sufficient]

        with patch.object(orders_actions, "_now_epoch_ms", return_value=now_ms):
            res = orders_actions.filter_orders(
                orders,
                {
                    "deadline_category": "due_today",
                    "date_enabled": False,
                },
            )

        self.assertTrue(res.success, res.message)
        filtered = (res.data or {}).get("filtered", [])
        self.assertEqual(filtered, [due_today])

    def test_global_filter_skips_item_scan_when_record_fields_match(self) -> None:
        class ExplodingItem:
            def __getattribute__(self, name):
                raise AssertionError("item scan should not run when record fields already match")

        records = [
            SimpleNamespace(
                orderNumber="MATCH-ORDER-1",
                claimNumber="",
                claimId="",
                claimReason="",
                cargoProviderName="",
                customerFirstName="",
                customerLastName="",
                cargoTrackingNumber="",
                shipmentPackageStatus="ReadyToShip",
                status="Created",
                items=[ExplodingItem()],
            )
        ]

        res = orders_pipeline.filter_order_records_in_memory(records, {"global": "match-order"})

        self.assertTrue(res.success, res.message)
        self.assertEqual((res.data or {}).get("filtered", []), records)

    def test_filter_order_records_in_memory_large_haystack_match_stays_fast(self) -> None:
        records = [
            SimpleNamespace(
                orderNumber=f"BULK-{idx:05d}",
                claimNumber="",
                claimId="",
                claimReason="",
                cargoProviderName="",
                customerFirstName="Jane",
                customerLastName="Doe",
                cargoTrackingNumber=f"TRK-{idx:05d}",
                shipmentPackageStatus="ReadyToShip",
                status="Created",
                items=[SimpleNamespace(productName="Product", merchantSku="SKU", sku="", barcode="")],
            )
            for idx in range(10000)
        ]

        started_at = time.perf_counter()
        res = orders_pipeline.filter_order_records_in_memory(records, {"global": "bulk-09"})
        elapsed = time.perf_counter() - started_at

        self.assertTrue(res.success, res.message)
        self.assertEqual(len((res.data or {}).get("filtered", [])), 1000)
        self.assertLess(elapsed, 1.0)

    def test_filter_orders_by_deadline_category_supports_datetime_values(self) -> None:
        now_ms = 1_700_000_000_000
        overdue = SimpleNamespace(
            _is_return=False,
            agreedDeliveryDate=datetime.fromtimestamp(1_699_989_200_000 / 1000, tz=orders_actions.TZ_GMT3).replace(tzinfo=None),
            status="Created",
        )
        due_today = SimpleNamespace(
            _is_return=False,
            agreedDeliveryDate=datetime.fromtimestamp(1_700_050_400_000 / 1000, tz=orders_actions.TZ_GMT3).replace(tzinfo=None),
            shipmentPackageStatus="ReadyToShip",
        )
        sufficient = SimpleNamespace(
            _is_return=False,
            agreedDeliveryDate=datetime.fromtimestamp(1_700_136_800_000 / 1000, tz=orders_actions.TZ_GMT3).replace(tzinfo=None),
            status="Created",
        )
        orders = [overdue, due_today, sufficient]

        with patch.object(orders_actions, "_now_epoch_ms", return_value=now_ms):
            res = orders_actions.filter_orders(
                orders,
                {
                    "deadline_category": "overdue",
                    "date_enabled": False,
                },
            )

        self.assertTrue(res.success, res.message)
        filtered = (res.data or {}).get("filtered", [])
        self.assertEqual(filtered, [overdue])

    def test_filter_orders_by_deadline_category_ignores_delivered_orders(self) -> None:
        now_ms = 1_700_000_000_000
        delivered = SimpleNamespace(_is_return=False, agreedDeliveryDate=1_699_989_200_000, status="Delivered")
        ready = SimpleNamespace(_is_return=False, agreedDeliveryDate=1_699_989_200_000, status="Created")

        with patch.object(orders_actions, "_now_epoch_ms", return_value=now_ms):
            res = orders_actions.filter_orders(
                [delivered, ready],
                {
                    "deadline_category": "overdue",
                    "date_enabled": False,
                },
            )

        self.assertTrue(res.success, res.message)
        filtered = (res.data or {}).get("filtered", [])
        self.assertEqual(filtered, [ready])

    def test_filter_returns_active_status_filter_matches_open_return_statuses(self) -> None:
        waiting = SimpleNamespace(_is_return=True, claimItemStatus="WaitingInAction", shipmentPackageStatus="WaitingInAction")
        created = SimpleNamespace(_is_return=True, claimItemStatus="Created", shipmentPackageStatus="Created")
        accepted = SimpleNamespace(_is_return=True, claimItemStatus="Accepted", shipmentPackageStatus="Accepted")

        res = orders_actions.filter_orders(
            [waiting, created, accepted],
            {
                "shipment_status_code": "__open_returns__",
                "date_enabled": False,
                "processed_mode": "all",
            },
        )

        self.assertTrue(res.success, res.message)
        filtered = (res.data or {}).get("filtered", [])
        self.assertEqual(filtered, [waiting, created])

    def test_normalize_return_claim_uses_root_status_when_line_status_is_missing(self) -> None:
        claim = self._sample_return_claim(status="WaitingInAction")
        for item in claim.get("items", []) or []:
            for claim_item in item.get("claimItems", []) or []:
                claim_item.pop("claimItemStatus", None)
                claim_item.pop("status", None)
        claim["claimItemStatus"] = "WaitingInAction"

        normalized = orders_pipeline.normalize_return_claim(claim, 1)

        self.assertEqual(normalized["claimItemStatus"], "WaitingInAction")
        self.assertEqual(normalized["waitingClaimLineItemIds"], normalized["claimLineItemIds"])

    def test_load_returns_from_db_uses_latest_claims(self) -> None:
        self._seed_account()
        save_order_res = orders_pipeline.save_orders_to_db(Result.ok(data=self._sample_payload()), db_name=self.db_path)
        self.assertTrue(save_order_res.success, save_order_res.message)
        normalized = orders_pipeline.normalize_return_claim(self._sample_return_claim(), 1)
        save_res = orders_pipeline.save_return_claims_to_db(
            Result.ok(data={"return_claim_list": [normalized]}),
            db_name=self.db_path,
        )
        self.assertTrue(save_res.success, save_res.message)
        claim_day = datetime.fromtimestamp(
            int(normalized["claimDate"]) / 1000,
            tz=orders_actions.TZ_GMT3,
        ).date()

        with patch.object(orders_pipeline, "DB_NAME", self.db_path), \
             patch.object(orders_actions, "get_latest_return_claims_filtered", wraps=orders_pipeline.get_latest_return_claims_filtered):
            res = orders_actions.load_returns_from_db(
                date_from=claim_day,
                date_to=claim_day,
            )

        self.assertTrue(res.success, res.message)
        records = (res.data or {}).get("records", [])
        self.assertEqual(len(records), 1)
        self.assertEqual(getattr(records[0], "claimId", ""), "CLM-1001")

        rows_res = get_records(model=ReturnClaim, db_name=self.db_path)
        self.assertTrue(rows_res.success, rows_res.message)
        saved_claim = ((rows_res.data or {}).get("records", []) or [None])[0]
        self.assertIsNotNone(saved_claim)
        self.assertEqual(getattr(saved_claim, "order_header_id", None), 1)

    def test_get_latest_return_claims_filters_by_status_platform_and_date(self) -> None:
        self._seed_account(pk=1)
        create_records(
            model=ApiAccount,
            data_list=[{"pk": 2, "account_id": "ACC-2", "comp_name": "Company 2", "platform": "amazon"}],
            db_name=self.db_path,
            mode="plain",
        )
        claim_rows = [
            {
                "api_account_id": 1,
                "claimId": "CLM-TY-IN",
                "claimNumber": "CLM-TY-IN",
                "orderNumber": "ORD-TY-IN",
                "claimDate": 1700000000000,
                "orderDate": 1700000000000,
                "lastModifiedDate": 1700000001000,
                "claimItemStatus": "WaitingInAction",
            },
            {
                "api_account_id": 1,
                "claimId": "CLM-TY-OUT",
                "claimNumber": "CLM-TY-OUT",
                "orderNumber": "ORD-TY-OUT",
                "claimDate": 1701000000000,
                "orderDate": 1701000000000,
                "lastModifiedDate": 1701000001000,
                "claimItemStatus": "WaitingInAction",
            },
            {
                "api_account_id": 2,
                "claimId": "CLM-AMZ-IN",
                "claimNumber": "CLM-AMZ-IN",
                "orderNumber": "ORD-AMZ-IN",
                "claimDate": 1700000000000,
                "orderDate": 1700000000000,
                "lastModifiedDate": 1700000001000,
                "claimItemStatus": "WaitingInAction",
            },
        ]
        save_res = create_records(model=ReturnClaim, data_list=claim_rows, db_name=self.db_path, mode="plain")
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            read_res = orders_pipeline.get_latest_return_claims_filtered(
                start_ms=1699999999000,
                end_ms=1700000001000,
                claim_statuses=["WaitingInAction"],
                platform_codes=["TRENDYOL"],
            )

        self.assertTrue(read_res.success, read_res.message)
        claims = (read_res.data or {}).get("claims", [])
        self.assertEqual([getattr(row, "claimId", "") for row in claims], ["CLM-TY-IN"])

    def test_active_returns_filter_loads_created_and_waiting_but_not_closed_claims(self) -> None:
        self._seed_account(pk=1)
        claim_rows = [
            {
                "api_account_id": 1,
                "claimId": "CLM-CREATED",
                "claimNumber": "CLM-CREATED",
                "orderNumber": "ORD-CREATED",
                "claimDate": 1700000000000,
                "orderDate": 1700000000000,
                "lastModifiedDate": 1700000001000,
                "claimItemStatus": "Created",
            },
            {
                "api_account_id": 1,
                "claimId": "CLM-WAITING",
                "claimNumber": "CLM-WAITING",
                "orderNumber": "ORD-WAITING",
                "claimDate": 1700000000100,
                "orderDate": 1700000000100,
                "lastModifiedDate": 1700000001100,
                "claimItemStatus": "WaitingInAction",
            },
            {
                "api_account_id": 1,
                "claimId": "CLM-ACCEPTED",
                "claimNumber": "CLM-ACCEPTED",
                "orderNumber": "ORD-ACCEPTED",
                "claimDate": 1700000000200,
                "orderDate": 1700000000200,
                "lastModifiedDate": 1700000001200,
                "claimItemStatus": "Accepted",
            },
        ]
        save_res = create_records(model=ReturnClaim, data_list=claim_rows, db_name=self.db_path, mode="plain")
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path), patch.object(orders_actions, "get_latest_return_claims_filtered", wraps=orders_pipeline.get_latest_return_claims_filtered):
            read_res = orders_actions.load_returns_for_source_filters(
                date_from=datetime.fromtimestamp(1700000000000 / 1000, tz=orders_actions.TZ_GMT3).date(),
                date_to=datetime.fromtimestamp(1700000000200 / 1000, tz=orders_actions.TZ_GMT3).date(),
                shipment_status_code="__open_returns__",
            )

        self.assertTrue(read_res.success, read_res.message)
        claims = (read_res.data or {}).get("records", [])
        self.assertEqual(
            [getattr(row, "claimId", "") for row in claims],
            ["CLM-WAITING", "CLM-CREATED"],
        )

    def test_save_return_claims_links_header_by_package_when_order_number_differs(self) -> None:
        self._seed_account()
        save_order_res = orders_pipeline.save_orders_to_db(Result.ok(data=self._sample_payload()), db_name=self.db_path)
        self.assertTrue(save_order_res.success, save_order_res.message)

        raw_claim = self._sample_return_claim()
        raw_claim["orderNumber"] = "ORD-UNMATCHED"
        normalized = orders_pipeline.normalize_return_claim(raw_claim, 1)

        save_res = orders_pipeline.save_return_claims_to_db(
            Result.ok(data={"return_claim_list": [normalized]}),
            db_name=self.db_path,
        )
        self.assertTrue(save_res.success, save_res.message)

        rows_res = get_records(model=ReturnClaim, db_name=self.db_path)
        self.assertTrue(rows_res.success, rows_res.message)
        saved_claim = ((rows_res.data or {}).get("records", []) or [None])[0]
        self.assertIsNotNone(saved_claim)
        self.assertEqual(getattr(saved_claim, "order_header_id", None), 1)

    def test_finalize_pipeline_sets_progress_to_100(self) -> None:
        btn = self._DummyProgress()
        orders_actions._set_progress_lock(btn, False)
        orders_actions._finalize_pipeline(btn, [], False)
        self.assertEqual(btn.value, 100)
        self.assertTrue(getattr(btn, "_orders_progress_locked", False))

    def test_normalize_return_claim_groups_claim_items(self) -> None:
        raw_claim = self._sample_return_claim(item_ids=["LINE-1", "LINE-2", "LINE-3"])
        normalized = orders_pipeline.normalize_return_claim(raw_claim, 1)

        self.assertEqual(normalized["claimId"], "CLM-1001")
        self.assertEqual(normalized["claimItemStatus"], "WaitingInAction")
        self.assertEqual(normalized["itemCount"], 3)
        self.assertEqual(normalized["totalPrice"], 105.0)
        self.assertEqual(normalized["waitingClaimLineItemIds"], ["LINE-1", "LINE-2", "LINE-3"])
        self.assertEqual(len(normalized["itemsJson"]), 1)
        self.assertEqual(normalized["itemsJson"][0]["qty"], 3)

    def test_get_latest_return_claims_returns_latest_snapshot(self) -> None:
        self._seed_account()
        old_claim = orders_pipeline.normalize_return_claim(
            self._sample_return_claim(status="WaitingInAction", last_modified=1700000000000),
            1,
        )
        new_claim = orders_pipeline.normalize_return_claim(
            self._sample_return_claim(status="Accepted", last_modified=1700000001000),
            1,
        )

        save_res = orders_pipeline.save_return_claims_to_db(
            Result.ok(data={"return_claim_list": [old_claim, new_claim]}),
            db_name=self.db_path,
        )
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            read_res = orders_pipeline.get_latest_return_claims(start_ms=0, end_ms=9999999999999)

        self.assertTrue(read_res.success, read_res.message)
        claims = (read_res.data or {}).get("claims", [])
        self.assertEqual(len(claims), 1)
        claim = claims[0]
        self.assertEqual(getattr(claim, "claimItemStatus", ""), "Accepted")
        self.assertTrue(bool(getattr(claim, "_is_return", False)))
        self.assertEqual(len(getattr(claim, "_return_items", []) or []), 1)
        self.assertEqual(len(getattr(claim, "items", []) or []), 1)
        self.assertEqual(getattr(getattr(claim, "api_account", None), "comp_name", ""), "Company 1")

    def test_get_latest_return_claims_status_filter_uses_latest_snapshot(self) -> None:
        self._seed_account()
        old_claim = orders_pipeline.normalize_return_claim(
            self._sample_return_claim(status="WaitingInAction", last_modified=1700000000000),
            1,
        )
        new_claim = orders_pipeline.normalize_return_claim(
            self._sample_return_claim(status="Accepted", last_modified=1700000001000),
            1,
        )
        active_waiting_claim = orders_pipeline.normalize_return_claim(
            self._sample_return_claim(
                claim_id="CLM-1002",
                status="WaitingInAction",
                last_modified=1700000002000,
            ),
            1,
        )

        save_res = orders_pipeline.save_return_claims_to_db(
            Result.ok(data={"return_claim_list": [old_claim, new_claim, active_waiting_claim]}),
            db_name=self.db_path,
        )
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            read_res = orders_pipeline.get_latest_return_claims_filtered(
                start_ms=0,
                end_ms=9999999999999,
                claim_statuses=["WaitingInAction"],
            )

        self.assertTrue(read_res.success, read_res.message)
        claims = (read_res.data or {}).get("claims", [])
        self.assertEqual([getattr(row, "claimId", "") for row in claims], ["CLM-1002"])

    def test_stale_return_claims_can_be_listed_and_restored(self) -> None:
        self._seed_account()
        claim = orders_pipeline.normalize_return_claim(
            self._sample_return_claim(claim_id="CLM-STALE-RESTORE", status="WaitingInAction", last_modified=1700000003000),
            1,
        )
        save_res = orders_pipeline.save_return_claims_to_db(
            Result.ok(data={"return_claim_list": [claim]}),
            db_name=self.db_path,
        )
        self.assertTrue(save_res.success, save_res.message)

        stale_res = orders_pipeline.mark_return_claims_stale(
            claim_ids=["CLM-STALE-RESTORE"],
            api_account_ids=[1],
            reason="test restore affordance",
            db_name=self.db_path,
        )
        self.assertTrue(stale_res.success, stale_res.message)
        self.assertEqual((stale_res.data or {}).get("stale_marked"), 1)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            active_res = orders_pipeline.get_latest_return_claims(
                start_ms=0,
                end_ms=9999999999999,
                claim_ids=["CLM-STALE-RESTORE"],
            )
        self.assertTrue(active_res.success, active_res.message)
        self.assertEqual((active_res.data or {}).get("claims"), [])

        listed_res = orders_pipeline.get_stale_return_claims(
            start_ms=0,
            end_ms=9999999999999,
            claim_ids=["CLM-STALE-RESTORE"],
            api_account_ids=[1],
            db_name=self.db_path,
        )
        self.assertTrue(listed_res.success, listed_res.message)
        listed_claims = (listed_res.data or {}).get("claims") or []
        self.assertEqual([getattr(row, "claimId", "") for row in listed_claims], ["CLM-STALE-RESTORE"])
        self.assertTrue(getattr(listed_claims[0], "sync_deleted_at", None))

        restore_res = orders_pipeline.restore_return_claims_from_stale(
            claim_ids=["CLM-STALE-RESTORE"],
            api_account_ids=[1],
            reason="manual review restore",
            db_name=self.db_path,
        )
        self.assertTrue(restore_res.success, restore_res.message)
        self.assertEqual((restore_res.data or {}).get("restored"), 1)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            restored_active_res = orders_pipeline.get_latest_return_claims(
                start_ms=0,
                end_ms=9999999999999,
                claim_ids=["CLM-STALE-RESTORE"],
            )
        self.assertTrue(restored_active_res.success, restored_active_res.message)
        restored_claims = (restored_active_res.data or {}).get("claims") or []
        self.assertEqual([getattr(row, "claimId", "") for row in restored_claims], ["CLM-STALE-RESTORE"])
        self.assertIsNone(getattr(restored_claims[0], "sync_deleted_at", None))

    def test_approve_return_claim_uses_waiting_line_ids(self) -> None:
        captured: dict[str, object] = {}

        async def fake_approve(self, *, claim_id, claim_line_item_ids):
            captured["claim_id"] = claim_id
            captured["claim_line_item_ids"] = list(claim_line_item_ids or [])
            return Result.ok("approved", close_dialog=False)

        async def fake_refresh(accounts, *, start_ms, end_ms, size, claim_ids=None):
            captured["refresh_claim_ids"] = list(claim_ids or [])
            refreshed_claim = orders_pipeline.normalize_return_claim(
                self._sample_return_claim(status="Accepted", last_modified=1700000002000),
                1,
            )
            return Result.ok(
                "refreshed",
                close_dialog=False,
                data={"return_claim_list": [refreshed_claim], "errors": []},
            )

        order = SimpleNamespace(
            claimId="CLM-1001",
            claimNumber="CLM-1001",
            waitingClaimLineItemIds=["LINE-1", "LINE-2"],
            claimItemStatus="WaitingInAction",
            api_account=SimpleNamespace(
                pk=1,
                api_key="key",
                api_secret="secret",
                account_id="seller-1",
            ),
        )

        with patch.object(orders_actions.TrendyolApi, "approve_claim_line_items", fake_approve), \
             patch.object(orders_actions, "_fetch_returns_from_active_companies_async", fake_refresh), \
             patch.object(
                 orders_actions,
                 "save_return_claims_to_db",
                 return_value=Result.ok("saved", close_dialog=False, data={"changed": True}),
             ):
            result = orders_actions.approve_return_claim.__wrapped__(order)

        self.assertTrue(result.success, result.message)
        self.assertEqual(captured["claim_id"], "CLM-1001")
        self.assertEqual(captured["claim_line_item_ids"], ["LINE-1", "LINE-2"])
        self.assertEqual(captured["refresh_claim_ids"], ["CLM-1001"])

    def test_load_order_items_for_order_number_uses_latest_snapshot_and_modern_amount_fields(self) -> None:
        self._seed_account()
        payload = {
            "order_data_list": [
                {
                    "id": 3001,
                    "orderNumber": "ORD-3001",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000000000,
                    "orderDate": 1700000000000,
                    "status": "Picking",
                    "shipmentPackageStatus": "ReadyToShip",
                },
                {
                    "id": 3002,
                    "orderNumber": "ORD-3001",
                    "api_account_id": 1,
                    "lastModifiedDate": 1700000001000,
                    "orderDate": 1700000001000,
                    "status": "Picking",
                    "shipmentPackageStatus": "ReadyToShip",
                },
            ],
            "order_item_list": [
                {
                    "orderNumber": "ORD-3001",
                    "api_account_id": 1,
                    "order_data_id": 3001,
                    "snapshotLastModifiedDate": 1700000000000,
                    "quantity": 1,
                    "productCode": 801,
                    "id": 1801,
                    "lineId": 1801,
                    "merchantSku": "SKU-OLD",
                    "productName": "Old Item",
                    "amount": 10.0,
                },
                {
                    "orderNumber": "ORD-3001",
                    "api_account_id": 1,
                    "order_data_id": 3002,
                    "snapshotLastModifiedDate": 1700000001000,
                    "quantity": 2,
                    "productCode": 802,
                    "id": 1802,
                    "lineId": 1802,
                    "merchantSku": "SKU-NEW",
                    "productName": "New Item",
                    "amount": None,
                    "lineGrossAmount": 42.5,
                    "lineUnitPrice": 21.25,
                },
            ],
        }
        save_res = orders_pipeline.save_orders_to_db(Result.ok(data=payload), db_name=self.db_path)
        self.assertTrue(save_res.success, save_res.message)

        with patch.object(orders_pipeline, "DB_NAME", self.db_path):
            read_res = orders_actions.load_order_items_for_order_number("ORD-3001", api_account_id=1)

        self.assertTrue(read_res.success, read_res.message)
        items = (read_res.data or {}).get("items", []) or []
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "New Item")
        self.assertEqual(items[0]["sku"], "SKU-NEW")
        self.assertEqual(float(items[0]["amount"]), 42.5)

        rows_res = get_records(model=OrderItem, db_name=self.db_path)
        self.assertTrue(rows_res.success, rows_res.message)
        rows = sorted((rows_res.data or {}).get("records", []) or [], key=lambda row: int(getattr(row, "pk", 0) or 0))
        self.assertEqual(len(rows), 2)
        self.assertEqual(getattr(rows[0], "order_data_pk", None), 1)
        self.assertEqual(getattr(rows[1], "order_data_pk", None), 2)

    def test_sync_observability_reports_exact_account_counts_and_db_readback(self) -> None:
        self._seed_account()
        payload = self._sample_payload()
        payload["sync_diagnostics"] = {
            "source_rows_seen": 1,
            "normalized_order_rows": 1,
            "normalized_item_rows": 1,
            "skipped_source_rows": 0,
            "skipped_reasons": {},
            "source_rows_complete": True,
            "fetch_errors": 0,
        }
        fetch_result = Result.ok("fake remote fetch", data=payload)

        first_save = orders_pipeline.save_orders_to_db(fetch_result, db_name=self.db_path)
        self.assertTrue(first_save.success, first_save.message)
        first = orders_pipeline.build_orders_sync_observability(
            fetch_result,
            first_save,
            account_ids=[1],
            start_ms=1699990000000,
            end_ms=1700010000000,
            db_name=self.db_path,
        )

        self.assertEqual(first["fetched"]["unique_orders"], 1)
        self.assertEqual(first["fetched"]["order_snapshots"], 1)
        self.assertEqual(first["fetched"]["item_rows"], 1)
        self.assertEqual(first["writes"]["order_snapshots_inserted"], 1)
        self.assertEqual(first["writes"]["order_snapshots_already_present"], 0)
        self.assertEqual(first["accounts"][0]["order_snapshots_inserted"], 1)
        self.assertEqual(first["accounts"][0]["order_snapshots_updated"], 0)
        self.assertEqual(first["accounts"][0]["source_rows_skipped"], 0)
        self.assertEqual(first["accounts"][0]["fetch_errors"], 0)
        self.assertTrue(first["db_readback"]["required"])
        self.assertTrue(first["db_readback"]["source_identity_contract_complete"])
        self.assertTrue(first["db_readback"]["verified"])
        self.assertEqual(first["db_readback"]["found_order_snapshots"], 1)
        self.assertEqual(first["db_readback"]["found_item_rows"], 1)
        self.assertEqual(first["watermark"]["fresh_through_ms"], 1700010000000)

        second_save = orders_pipeline.save_orders_to_db(fetch_result, db_name=self.db_path)
        self.assertTrue(second_save.success, second_save.message)
        second = orders_pipeline.build_orders_sync_observability(
            fetch_result,
            second_save,
            account_ids=[1],
            start_ms=1699990000000,
            end_ms=1700010000000,
            db_name=self.db_path,
        )
        self.assertEqual(second["writes"]["order_snapshots_inserted"], 0)
        self.assertEqual(second["writes"]["order_snapshots_already_present"], 1)
        self.assertEqual(second["writes"]["item_rows_already_present"], 1)
        self.assertEqual(second["accounts"][0]["order_snapshots_inserted"], 0)
        self.assertEqual(second["accounts"][0]["order_snapshots_already_present"], 1)
        self.assertTrue(second["db_readback"]["verified"])

    def test_sync_observability_fails_readback_for_unpersisted_remote_snapshot(self) -> None:
        self._seed_account()
        payload = self._sample_payload()
        payload["sync_diagnostics"] = {
            "source_rows_seen": 1,
            "normalized_order_rows": 1,
            "normalized_item_rows": 1,
            "source_rows_complete": True,
            "fetch_errors": 0,
        }
        fetch_result = Result.ok("fake remote fetch", data=payload)
        fake_save = Result.ok(
            "save claimed success without a write",
            data={
                "counts": {"headers_inserted": 1, "data_inserted": 1, "items_inserted": 1},
                "sync_diagnostics": {
                    "persistence": {"eligible_order_rows": 1, "eligible_item_rows": 1}
                },
            },
        )

        summary = orders_pipeline.build_orders_sync_observability(
            fetch_result,
            fake_save,
            account_ids=[1],
            start_ms=1699990000000,
            end_ms=1700010000000,
            db_name=self.db_path,
        )

        self.assertFalse(summary["db_readback"]["verified"])
        self.assertEqual(summary["db_readback"]["missing_order_snapshots"], 1)
        self.assertEqual(summary["db_readback"]["missing_item_rows"], 1)
        self.assertEqual(summary["watermark"]["fresh_through_ms"], 0)

    def test_sync_observability_keeps_policy_excluded_awaiting_rows_auditable(self) -> None:
        self._seed_account()
        payload = self._sample_payload()
        payload["sync_diagnostics"] = {
            "source_rows_seen": 2,
            "normalized_order_rows": 1,
            "normalized_item_rows": 1,
            "skipped_source_rows": 0,
            "skipped_reasons": {},
            "policy_excluded_source_rows": 1,
            "policy_excluded_reasons": {"missing_snapshot_identity": 1},
            "source_rows_complete": True,
            "fetch_errors": 0,
        }
        fetch_result = Result.ok("fake remote fetch", data=payload)
        save_result = orders_pipeline.save_orders_to_db(fetch_result, db_name=self.db_path)

        self.assertTrue(save_result.success, save_result.message)
        summary = orders_pipeline.build_orders_sync_observability(
            fetch_result,
            save_result,
            account_ids=[1],
            start_ms=1699990000000,
            end_ms=1700010000000,
            db_name=self.db_path,
        )

        self.assertTrue(summary["watermark"]["source_rows_complete"])
        self.assertTrue(summary["db_readback"]["verified"])
        self.assertEqual(summary["fetched"]["source_rows_seen"], 2)
        self.assertEqual(summary["fetched"]["order_snapshots"], 1)
        self.assertEqual(summary["excluded"]["source_rows"], 1)
        self.assertEqual(
            summary["excluded"]["source_reasons"],
            {"missing_snapshot_identity": 1},
        )
        self.assertEqual(summary["accounts"][0]["source_rows_policy_excluded"], 1)
        self.assertEqual(summary["watermark"]["fresh_through_ms"], 1700010000000)
