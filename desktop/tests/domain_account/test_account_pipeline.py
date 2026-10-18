from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import Account.processors.pipeline as account_pipeline
from sqlmodel import Session, select

from Finance.models.trendyol.models import FinanceCargoInvoiceItem, FinanceTransaction
from Listing.models import (
    ListingProduct,
    ListingProductCostSnapshot,
    ListingProductHistory,
    ListingProductStockSnapshot,
)
from Marketplaces.models import Marketplace
from Orders.models.trendyol.models import OrderHeader, ReturnClaim
from Stock.models import StockItem
from Core.processors.credential_store import store_credential_bundle
from Core.utils import model_utils

from tests.support.db_case import IsolatedDbTestCase


class TestAccountPipeline(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._db_patch = patch.object(account_pipeline, "DB_NAME", self.db_path)
        self._db_patch.start()
        engine = model_utils.get_engine(self.db_path)
        with Session(engine) as session:
            for code, label in (
                ("TRENDYOL", "Trendyol"),
                ("AMAZON", "Amazon"),
                ("ETSY", "Etsy"),
            ):
                session.add(Marketplace(code=code, label=label))
            session.commit()

    def tearDown(self) -> None:
        self._db_patch.stop()
        super().tearDown()

    def test_create_update_delete_company_roundtrip(self) -> None:
        create_res = account_pipeline.save_company_to_db(
            {
                "account_id": "10001",
                "comp_name": "Acme Store",
                "platform": "trendyol",
                "api_key": "key",
                "api_secret": "secret",
            }
        )
        self.assertTrue(create_res.success, create_res.message)

        all_res = account_pipeline.get_all_companies()
        self.assertTrue(all_res.success, all_res.message)
        records = (all_res.data or {}).get("records", [])
        self.assertEqual(len(records), 1)

        pk = records[0].pk
        update_res = account_pipeline.update_company(pk, {"comp_name": "Acme Updated"})
        self.assertTrue(update_res.success, update_res.message)

        by_id_res = account_pipeline.get_company_by_id([pk])
        self.assertTrue(by_id_res.success, by_id_res.message)
        updated_record = (by_id_res.data or {}).get("records", [None])[0]
        self.assertIsNotNone(updated_record)
        self.assertEqual(updated_record.comp_name, "Acme Updated")

        delete_res = account_pipeline.delete_company_from_db(pk)
        self.assertTrue(delete_res.success, delete_res.message)

        delete_again_res = account_pipeline.delete_company_from_db(pk)
        self.assertFalse(delete_again_res.success)

    def test_delete_company_cleans_related_account_records(self) -> None:
        create_res = account_pipeline.save_company_to_db(
            {
                "account_id": "20002",
                "comp_name": "Cascade Store",
                "platform": "trendyol",
            }
        )
        self.assertTrue(create_res.success, create_res.message)

        records = (account_pipeline.get_all_companies().data or {}).get("records", [])
        self.assertEqual(len(records), 1)
        pk = records[0].pk
        self.assertIsNotNone(pk)

        engine = model_utils.get_engine(self.db_path)
        with Session(engine) as session:
            session.add(StockItem(pk=10, sku="SKU-10", name="Stock 10"))
            header = OrderHeader(orderNumber="ORD-1", api_account_id=pk)
            session.add(header)
            session.commit()
            session.refresh(header)

            session.add(ReturnClaim(api_account_id=pk, claimId="CLM-1", lastModifiedDate=1))
            session.add(FinanceTransaction(api_account_id=pk, serviceKey="svc", recordId="rec-1", transactionDate=1))
            session.add(FinanceCargoInvoiceItem(api_account_id=pk, invoiceSerialNumber="INV-1"))
            listing = ListingProduct(api_account_id=pk, product_id="P1")
            session.add(listing)
            session.commit()
            session.refresh(listing)
            session.add(ListingProductStockSnapshot(listing_id=int(listing.pk), stock_item_id=10, qty=1))
            session.add(ListingProductCostSnapshot(listing_id=int(listing.pk), cost_key="cargo"))
            session.add(ListingProductHistory(api_account_id=pk, product_id="P1"))
            session.commit()

        delete_res = account_pipeline.delete_company_from_db(pk)
        self.assertTrue(delete_res.success, delete_res.message)

        with Session(engine) as session:
            self.assertEqual(len(session.exec(select(OrderHeader)).all()), 0)
            self.assertEqual(len(session.exec(select(ReturnClaim)).all()), 0)
            self.assertEqual(len(session.exec(select(FinanceTransaction)).all()), 0)
            self.assertEqual(len(session.exec(select(FinanceCargoInvoiceItem)).all()), 0)
            self.assertEqual(len(session.exec(select(ListingProduct)).all()), 0)
            self.assertEqual(len(session.exec(select(ListingProductStockSnapshot)).all()), 0)
            self.assertEqual(len(session.exec(select(ListingProductCostSnapshot)).all()), 0)
            self.assertEqual(len(session.exec(select(ListingProductHistory)).all()), 0)

    def test_update_non_existing_company_fails(self) -> None:
        res = account_pipeline.update_company(9999, {"comp_name": "Nope"})
        self.assertFalse(res.success)
        self.assertIn("Güncellenecek şirket bulunamadı", res.message)

    def test_company_platform_is_canonicalized_on_save_and_update(self) -> None:
        create_res = account_pipeline.save_company_to_db(
            {
                "account_id": "30003",
                "comp_name": "Label Store",
                "platform": "Trendyol",
                "api_key": "key",
                "api_secret": "secret",
            }
        )
        self.assertTrue(create_res.success, create_res.message)

        records = (account_pipeline.get_all_companies().data or {}).get("records", [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].platform, "TRENDYOL")

        update_res = account_pipeline.update_company(records[0].pk, {"platform": "amazon"})
        self.assertTrue(update_res.success, update_res.message)

        updated_record = (account_pipeline.get_company_by_id([records[0].pk]).data or {}).get("records", [None])[0]
        self.assertIsNotNone(updated_record)
        self.assertEqual(updated_record.platform, "AMAZON")

    def test_save_company_rejects_unknown_platform_at_pipeline_level(self) -> None:
        create_res = account_pipeline.save_company_to_db(
            {
                "account_id": "30004",
                "comp_name": "Invalid Platform Store",
                "platform": "UNKNOWN_PLATFORM",
            }
        )

        self.assertFalse(create_res.success)
        self.assertIn("Geçersiz platform", create_res.message)

    def test_get_active_companies_returns_only_active_rows(self) -> None:
        active_res = account_pipeline.save_company_to_db(
            {
                "account_id": "40001",
                "comp_name": "Active Store",
                "platform": "trendyol",
                "is_active": True,
            }
        )
        inactive_res = account_pipeline.save_company_to_db(
            {
                "account_id": "40002",
                "comp_name": "Inactive Store",
                "platform": "trendyol",
                "is_active": False,
            }
        )
        self.assertTrue(active_res.success, active_res.message)
        self.assertTrue(inactive_res.success, inactive_res.message)

        result = account_pipeline.get_active_companies()

        self.assertTrue(result.success, result.message)
        records = (result.data or {}).get("records", [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].comp_name, "Active Store")

    def test_run_company_api_health_check_batch_aggregates_counts(self) -> None:
        rows = [
            {"pk": 1, "comp_name": "A", "platform": "TRENDYOL", "account_id": "1", "api_key": "k1", "api_secret": "s1"},
            {"pk": 2, "comp_name": "B", "platform": "TRENDYOL", "account_id": "2", "api_key": "k2", "api_secret": "s2"},
            {"pk": 3, "comp_name": "C", "platform": "AMAZON", "account_id": "3", "api_key": "k3", "api_secret": "s3"},
        ]

        with patch.object(
            account_pipeline,
            "_check_company_api_health_async",
            new=AsyncMock(side_effect=[
                account_pipeline.Result.ok("ok", close_dialog=False, data={"platform": "TRENDYOL"}),
                account_pipeline.Result.fail("fail", close_dialog=False, data={"platform": "TRENDYOL"}),
                account_pipeline.Result.ok("skip", close_dialog=False, data={"platform": "AMAZON", "skipped": True}),
            ]),
        ):
            res = account_pipeline.run_company_api_health_check_batch(rows)

        self.assertTrue(res.success, res.message)
        data = res.data or {}
        self.assertEqual(int(data.get("checked") or 0), 3)
        self.assertEqual(int(data.get("ok") or 0), 1)
        self.assertEqual(int(data.get("failed") or 0), 1)
        self.assertEqual(int(data.get("skipped") or 0), 1)

    def test_run_company_api_health_check_batch_persists_token_valid_state(self) -> None:
        create_one = account_pipeline.save_company_to_db(
            {
                "account_id": "50001",
                "comp_name": "Healthy Store",
                "platform": "trendyol",
                "api_key": "k1",
                "api_secret": "s1",
            }
        )
        create_two = account_pipeline.save_company_to_db(
            {
                "account_id": "50002",
                "comp_name": "Broken Store",
                "platform": "trendyol",
                "api_key": "k2",
                "api_secret": "s2",
            }
        )
        self.assertTrue(create_one.success, create_one.message)
        self.assertTrue(create_two.success, create_two.message)

        records = (account_pipeline.get_all_companies().data or {}).get("records", [])
        self.assertEqual(len(records), 2)
        rows = [
            {
                "pk": records[0].pk,
                "comp_name": records[0].comp_name,
                "platform": records[0].platform,
                "account_id": records[0].account_id,
                "api_key": records[0].api_key,
                "api_secret": records[0].api_secret,
            },
            {
                "pk": records[1].pk,
                "comp_name": records[1].comp_name,
                "platform": records[1].platform,
                "account_id": records[1].account_id,
                "api_key": records[1].api_key,
                "api_secret": records[1].api_secret,
            },
        ]

        with patch.object(
            account_pipeline,
            "_check_company_api_health_async",
            new=AsyncMock(side_effect=[
                account_pipeline.Result.ok("ok", close_dialog=False, data={"platform": "TRENDYOL"}),
                account_pipeline.Result.fail("fail", close_dialog=False, data={"platform": "TRENDYOL"}),
            ]),
        ):
            res = account_pipeline.run_company_api_health_check_batch(rows)

        self.assertTrue(res.success, res.message)
        refreshed = (account_pipeline.get_all_companies().data or {}).get("records", [])
        token_valid_by_pk = {int(row.pk): bool(row.token_valid) for row in refreshed if row.pk is not None}
        self.assertTrue(token_valid_by_pk[int(rows[0]["pk"])])
        self.assertFalse(token_valid_by_pk[int(rows[1]["pk"])])

    def test_health_check_skips_platform_without_profile(self) -> None:
        result = account_pipeline.check_company_api_health(
            platform="AMAZON",
            account_id="123",
            api_key="key",
            api_secret="secret",
        )

        self.assertTrue(result.success, result.message)
        self.assertTrue(bool((result.data or {}).get("skipped")))
        self.assertEqual((result.data or {}).get("platform"), "AMAZON")

    def test_health_check_uses_marketplace_profile_success_message(self) -> None:
        async def _fake_request(**_: Any):
            return account_pipeline.Result.ok(
                "ok",
                close_dialog=False,
                data={"status_code": 200},
            )

        with patch.object(account_pipeline, "async_make_request", side_effect=_fake_request):
            result = account_pipeline.check_company_api_health(
                platform="TRENDYOL",
                account_id="784195",
                api_key="key",
                api_secret="secret",
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("status_code"), 200)
        self.assertEqual(result.message, "API bağlantı kontrolü başarılı.")

    def test_stage_health_check_resolves_bundle_and_uses_stage_endpoint(self) -> None:
        captured: dict[str, Any] = {}

        async def _fake_request(**kwargs: Any):
            captured.update(kwargs)
            return account_pipeline.Result.ok(
                "ok",
                close_dialog=False,
                data={"status_code": 200},
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "credentials.json"
            with patch.dict(os.environ, {"ORDERSCOUT_CREDENTIAL_STORE_PATH": str(store_path)}):
                reference = store_credential_bundle(
                    "trendyol-stage-test",
                    {
                        "seller_id": "2738",
                        "api_key": "stage-key",
                        "api_secret": "stage-secret",
                    },
                    reference="credential://trendyol-stage-test/2738",
                )
                with patch.object(account_pipeline, "async_make_request", side_effect=_fake_request):
                    result = account_pipeline.check_company_api_health(
                        platform="TRENDYOL",
                        account_id="2738",
                        api_key=reference,
                        api_secret=None,
                        extra_config={"environment": "stage"},
                    )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("environment"), "stage")
        self.assertEqual(
            captured.get("url"),
            "https://stageapigw.trendyol.com/integration/product/sellers/2738/products/approved",
        )
        self.assertEqual((captured.get("headers") or {}).get("User-Agent"), "2738-SelfIntegration")
        self.assertNotIn("stage-key", repr(result.data))
        self.assertNotIn("stage-secret", repr(result.data))

    def test_stage_health_check_rejects_credential_bundle_from_another_seller(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "credentials.json"
            with patch.dict(os.environ, {"ORDERSCOUT_CREDENTIAL_STORE_PATH": str(store_path)}):
                reference = store_credential_bundle(
                    "trendyol-stage-test",
                    {"seller_id": "2738", "api_key": "key", "api_secret": "secret"},
                )
                with patch.object(account_pipeline, "async_make_request", new=AsyncMock()) as request:
                    result = account_pipeline.check_company_api_health(
                        platform="TRENDYOL",
                        account_id="9999",
                        api_key=reference,
                        api_secret=None,
                        environment="stage",
                    )

        self.assertFalse(result.success)
        self.assertIn("eşleşmiyor", result.message)
        request.assert_not_awaited()

    def test_health_check_maps_http_status_to_marketplace_message(self) -> None:
        async def _fake_request(**_: Any):
            return account_pipeline.Result.fail(
                "fail",
                close_dialog=False,
                data={"status_code": 401},
            )

        with patch.object(account_pipeline, "async_make_request", side_effect=_fake_request):
            result = account_pipeline.check_company_api_health(
                platform="TRENDYOL",
                account_id="784195",
                api_key="key",
                api_secret="secret",
            )

        self.assertFalse(result.success)
        self.assertEqual(result.message, "Trendyol API Key veya API Secret bilgileri geçersiz.")

    def test_health_check_requires_profile_credentials(self) -> None:
        result = account_pipeline.check_company_api_health(
            platform="TRENDYOL",
            account_id="784195",
            api_key="",
            api_secret="",
        )

        self.assertFalse(result.success)
        self.assertIn("API Key", result.message)

    def test_update_company_rejects_blank_required_identity_fields(self) -> None:
        create_res = account_pipeline.save_company_to_db(
            {
                "account_id": "60001",
                "comp_name": "Validation Store",
                "platform": "trendyol",
            }
        )
        self.assertTrue(create_res.success, create_res.message)

        record = (account_pipeline.get_all_companies().data or {}).get("records", [None])[0]
        self.assertIsNotNone(record)

        update_res = account_pipeline.update_company(record.pk, {"comp_name": "   "})

        self.assertFalse(update_res.success)
        self.assertIn("Şirket adı boş olamaz", update_res.message)

    def test_update_company_rejects_unknown_only_payload(self) -> None:
        create_res = account_pipeline.save_company_to_db(
            {
                "account_id": "60002",
                "comp_name": "Unknown Payload Store",
                "platform": "trendyol",
            }
        )
        self.assertTrue(create_res.success, create_res.message)

        record = (account_pipeline.get_all_companies().data or {}).get("records", [None])[0]
        self.assertIsNotNone(record)

        update_res = account_pipeline.update_company(record.pk, {"unknown_field": "value"})

        self.assertFalse(update_res.success)
        self.assertIn("geçerli şirket verisi", update_res.message.lower())

    def test_update_company_resets_token_valid_when_health_identity_changes(self) -> None:
        create_res = account_pipeline.save_company_to_db(
            {
                "account_id": "60003",
                "comp_name": "Credential Store",
                "platform": "trendyol",
                "api_key": "key-1",
                "api_secret": "secret-1",
            }
        )
        self.assertTrue(create_res.success, create_res.message)

        record = (account_pipeline.get_all_companies().data or {}).get("records", [None])[0]
        self.assertIsNotNone(record)
        self.assertTrue(bool(record.token_valid))

        update_res = account_pipeline.update_company(record.pk, {"api_secret": "secret-2"})

        self.assertTrue(update_res.success, update_res.message)
        refreshed = (account_pipeline.get_company_by_id([record.pk]).data or {}).get("records", [None])[0]
        self.assertIsNotNone(refreshed)
        self.assertFalse(bool(refreshed.token_valid))

    def test_update_company_preserves_token_valid_for_non_health_changes(self) -> None:
        create_res = account_pipeline.save_company_to_db(
            {
                "account_id": "60004",
                "comp_name": "Display Name Store",
                "platform": "trendyol",
                "api_key": "key-1",
                "api_secret": "secret-1",
            }
        )
        self.assertTrue(create_res.success, create_res.message)

        record = (account_pipeline.get_all_companies().data or {}).get("records", [None])[0]
        self.assertIsNotNone(record)

        update_res = account_pipeline.update_company(record.pk, {"comp_name": "Display Name Store Updated"})

        self.assertTrue(update_res.success, update_res.message)
        refreshed = (account_pipeline.get_company_by_id([record.pk]).data or {}).get("records", [None])[0]
        self.assertIsNotNone(refreshed)
        self.assertTrue(bool(refreshed.token_valid))

    def test_update_company_skips_commit_and_signal_when_payload_is_unchanged(self) -> None:
        create_res = account_pipeline.save_company_to_db(
            {
                "account_id": "60005",
                "comp_name": "Noop Store",
                "platform": "trendyol",
            }
        )
        self.assertTrue(create_res.success, create_res.message)

        record = (account_pipeline.get_all_companies().data or {}).get("records", [None])[0]
        self.assertIsNotNone(record)

        with patch.object(account_pipeline, "_emit_company_changed") as mock_emit:
            update_res = account_pipeline.update_company(record.pk, {"comp_name": "Noop Store"})

        self.assertTrue(update_res.success, update_res.message)
        self.assertEqual(update_res.message, "Şirket verisinde değişiklik yok.")
        mock_emit.assert_not_called()

    def test_delete_company_succeeds_even_if_order_signal_emit_fails(self) -> None:
        create_res = account_pipeline.save_company_to_db(
            {
                "account_id": "60006",
                "comp_name": "Signal Safe Store",
                "platform": "trendyol",
            }
        )
        self.assertTrue(create_res.success, create_res.message)

        record = (account_pipeline.get_all_companies().data or {}).get("records", [None])[0]
        self.assertIsNotNone(record)

        fake_order_signals = SimpleNamespace(
            orders_changed=SimpleNamespace(emit=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        )
        with patch.object(account_pipeline, "order_signals", fake_order_signals):
            delete_res = account_pipeline.delete_company_from_db(record.pk)

        self.assertTrue(delete_res.success, delete_res.message)
        records_after_delete = (account_pipeline.get_all_companies().data or {}).get("records", [])
        self.assertEqual(records_after_delete, [])

    def test_process_logo_rejects_unsupported_extensions(self) -> None:
        invalid_logo = Path(self._tmp_dir.name) / "logo.txt"
        invalid_logo.write_text("not-an-image", encoding="utf-8")

        result = account_pipeline.process_logo(str(invalid_logo))

        self.assertFalse(result.success)
        self.assertIn("Desteklenmeyen logo formatı", result.message)
