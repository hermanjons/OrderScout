from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from Core.processors.credential_store import store_credential_bundle
from Feedback.processors.pipeline import Result
from Marketplaces.api.trendyol.base_api import trendyol_account_client_kwargs
from Orders.api.trendyol.orders_api import TrendyolApi


class TestTrendyolOrdersApi(IsolatedAsyncioTestCase):
    async def test_find_orders_reads_endpoint_and_query_defaults_from_marketplaces_json(self) -> None:
        api = TrendyolApi("key", "secret", "784195")
        fake_request = AsyncMock(
            return_value=Result.ok(
                close_dialog=False,
                data={
                    "json": {"content": [], "totalPages": 1, "page": 0, "totalElements": 0},
                    "status_code": 200,
                },
            )
        )

        with patch("Orders.api.trendyol.orders_api.async_make_request", fake_request):
            res = await api.find_orders("Created", 1000, 2000, 3, size=75)

        self.assertTrue(res.success, res.message)
        fake_request.assert_awaited_once()
        kwargs = fake_request.await_args.kwargs
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(
            kwargs["url"],
            "https://apigw.trendyol.com/integration/order/sellers/784195/orders",
        )
        self.assertEqual(kwargs["params"]["orderByField"], "PackageLastModifiedDate")
        self.assertEqual(kwargs["params"]["orderByDirection"], "DESC")
        self.assertEqual(kwargs["params"]["page"], 3)
        self.assertEqual(kwargs["params"]["size"], 75)
        self.assertEqual(kwargs["params"]["status"], "Created")

    async def test_find_orders_uses_explicit_stage_endpoint_without_production_fallback(self) -> None:
        api = TrendyolApi("key", "secret", "2738", environment="stage")
        fake_request = AsyncMock(
            return_value=Result.ok(
                close_dialog=False,
                data={
                    "json": {"content": [], "totalPages": 0, "page": 0, "totalElements": 0},
                    "status_code": 200,
                },
            )
        )

        with patch("Orders.api.trendyol.orders_api.async_make_request", fake_request):
            res = await api.find_orders("Created", 1000, 2000, 0, size=1)

        self.assertTrue(res.success, res.message)
        request_url = fake_request.await_args.kwargs["url"]
        self.assertEqual(
            request_url,
            "https://stageapigw.trendyol.com/integration/order/sellers/2738/orders",
        )
        self.assertNotIn("https://apigw.trendyol.com", request_url)
        self.assertEqual((res.data or {}).get("environment"), "stage")
        self.assertEqual((res.data or {}).get("seller_id"), "2738")

    async def test_stage_api_resolves_dpapi_bundle_by_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "credentials.json"
            with patch.dict(os.environ, {"ORDERSCOUT_CREDENTIAL_STORE_PATH": str(store_path)}):
                reference = store_credential_bundle(
                    "trendyol-stage-test",
                    {
                        "seller_id": "2738",
                        "api_key": "stage-key",
                        "api_secret": "stage-secret",
                        "integration_code": "integration-ref",
                        "token": "stage-token",
                    },
                    reference="credential://trendyol-stage-test/2738",
                )
                api = TrendyolApi(
                    environment="stage",
                    credential_reference=reference,
                )

            self.assertEqual(api.supplier_id, "2738")
            self.assertEqual(api.auth, ("stage-key", "stage-secret"))
            self.assertEqual(api.integration_code, "integration-ref")
            self.assertEqual(api.token, "stage-token")
            self.assertTrue(api.credential_managed)
            self.assertEqual(api.environment, "stage")

    async def test_account_adapter_deduplicates_same_bundle_reference_from_column_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "credentials.json"
            with patch.dict(os.environ, {"ORDERSCOUT_CREDENTIAL_STORE_PATH": str(store_path)}):
                reference = store_credential_bundle(
                    "trendyol-stage-test",
                    {"seller_id": "2738", "api_key": "stage-key", "api_secret": "stage-secret"},
                    reference="credential://trendyol-stage-test/2738",
                )
                kwargs = trendyol_account_client_kwargs(
                    {
                        "api_key": reference,
                        "api_secret": "",
                        "account_id": "2738",
                        "extra_config": {
                            "environment": "stage",
                            "credential_reference": reference,
                        },
                    }
                )
                api = TrendyolApi(**kwargs)

            self.assertIsNone(kwargs["api_key_id"])
            self.assertEqual(kwargs["credential_reference"], reference)
            self.assertEqual(api.auth, ("stage-key", "stage-secret"))
            self.assertNotEqual(api.api_key_id, reference)

    async def test_account_adapter_rejects_conflicting_bundle_references(self) -> None:
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            trendyol_account_client_kwargs(
                {
                    "api_key": "credential://one",
                    "api_secret": "",
                    "account_id": "2738",
                    "extra_config": {"credential_reference": "credential://two"},
                }
            )

    async def test_credential_bundle_rejects_cross_seller_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "credentials.json"
            with patch.dict(os.environ, {"ORDERSCOUT_CREDENTIAL_STORE_PATH": str(store_path)}):
                reference = store_credential_bundle(
                    "trendyol-stage-test",
                    {"seller_id": "2738", "api_key": "key", "api_secret": "secret"},
                )
                with self.assertRaisesRegex(ValueError, "seller"):
                    TrendyolApi(
                        supplier_id="9999",
                        environment="stage",
                        credential_reference=reference,
                    )

    async def test_api_rejects_unknown_environment_before_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "environment"):
            TrendyolApi("key", "secret", "2738", environment="sandbox")

    async def test_change_cargo_provider_uses_error_code_message_from_marketplaces_json(self) -> None:
        api = TrendyolApi("key", "secret", "784195")
        fake_request = AsyncMock(
            return_value=Result.fail(
                "ham hata",
                close_dialog=False,
                data={
                    "status_code": 409,
                    "json": {"errorCode": "CPE003"},
                },
            )
        )

        with patch("Orders.api.trendyol.orders_api.async_make_request", fake_request):
            res = await api.change_cargo_provider(package_id="PKG-1", cargo_provider="YKMP")

        self.assertFalse(res.success)
        self.assertIn("yalnızca pazaryeri siparişlerinde", res.message.lower())
        kwargs = fake_request.await_args.kwargs
        self.assertEqual(kwargs["method"], "PUT")
        self.assertEqual(
            kwargs["url"],
            "https://apigw.trendyol.com/integration/order/sellers/784195/shipment-packages/PKG-1/cargo-providers",
        )
        self.assertEqual(kwargs["json"], {"cargoProvider": "YKMP"})

    async def test_read_operation_retries_timeout_then_reports_attempt_metadata(self) -> None:
        api = TrendyolApi("key", "secret", "2738", environment="stage")
        timeout_error = TimeoutError("temporary timeout")
        fake_request = AsyncMock(
            side_effect=[
                Result.fail("timeout", error=timeout_error, close_dialog=False),
                Result.fail("timeout", error=timeout_error, close_dialog=False),
                Result.ok(
                    close_dialog=False,
                    data={
                        "json": {"content": [], "totalPages": 0, "page": 0, "totalElements": 0},
                        "status_code": 200,
                    },
                ),
            ]
        )

        with patch("Orders.api.trendyol.orders_api.async_make_request", fake_request), \
             patch("Core.api.Api_engine.asyncio.sleep", new_callable=AsyncMock) as fake_sleep:
            res = await api.find_orders("Created", 1000, 2000, 0, size=10)

        self.assertTrue(res.success, res.message)
        self.assertEqual(fake_request.await_count, 3)
        self.assertEqual(fake_sleep.await_count, 2)
        self.assertEqual((res.data or {}).get("request_attempts"), 3)
        self.assertEqual((res.data or {}).get("request_retries"), 2)

    async def test_http_error_matrix_preserves_status_and_safe_retry_boundary(self) -> None:
        api = TrendyolApi("key", "secret", "2738", environment="stage")
        for status_code in (401, 403, 404, 409, 429, 500, 503):
            with self.subTest(status_code=status_code):
                fake_request = AsyncMock(
                    return_value=Result.fail(
                        f"HTTP {status_code}",
                        close_dialog=False,
                        data={"status_code": status_code, "json": {"message": "redacted test error"}},
                    )
                )
                with patch("Orders.api.trendyol.orders_api.async_make_request", fake_request), \
                     patch("Core.api.Api_engine.asyncio.sleep", new_callable=AsyncMock):
                    res = await api.find_orders("Created", 1000, 2000, 0, size=10)

                self.assertFalse(res.success)
                self.assertEqual(int((res.data or {}).get("status_code") or 0), status_code)
                expected_attempts = 3 if status_code in {429, 500, 503} else 1
                self.assertEqual(fake_request.await_count, expected_attempts)
                self.assertEqual(int((res.data or {}).get("request_attempts") or 0), expected_attempts)

    async def test_effectful_put_never_retries_transient_http_failure(self) -> None:
        api = TrendyolApi("key", "secret", "2738", environment="stage")
        fake_request = AsyncMock(
            return_value=Result.fail(
                "HTTP 503",
                close_dialog=False,
                data={"status_code": 503, "json": {"message": "temporary"}},
            )
        )

        with patch("Orders.api.trendyol.orders_api.async_make_request", fake_request), \
             patch("Core.api.Api_engine.asyncio.sleep", new_callable=AsyncMock) as fake_sleep:
            res = await api.change_cargo_provider(package_id="PKG-1", cargo_provider="ARASMP")

        self.assertFalse(res.success)
        self.assertEqual(fake_request.await_count, 1)
        fake_sleep.assert_not_awaited()
        self.assertEqual(int((res.data or {}).get("request_attempts") or 0), 1)

    async def test_cancellation_propagates_without_retry_or_failure_rewrite(self) -> None:
        api = TrendyolApi("key", "secret", "2738", environment="stage")
        fake_request = AsyncMock(side_effect=asyncio.CancelledError())

        with patch("Orders.api.trendyol.orders_api.async_make_request", fake_request), \
             patch("Core.api.Api_engine.asyncio.sleep", new_callable=AsyncMock) as fake_sleep:
            with self.assertRaises(asyncio.CancelledError):
                await api.find_orders("Created", 1000, 2000, 0, size=10)

        self.assertEqual(fake_request.await_count, 1)
        fake_sleep.assert_not_awaited()

    async def test_approve_claim_line_items_uses_json_defined_endpoint(self) -> None:
        api = TrendyolApi("key", "secret", "784195")
        fake_request = AsyncMock(
            return_value=Result.ok(
                close_dialog=False,
                data={
                    "json": None,
                    "status_code": 200,
                },
            )
        )

        with patch("Orders.api.trendyol.orders_api.async_make_request", fake_request):
            res = await api.approve_claim_line_items(
                claim_id="CLM-9",
                claim_line_item_ids=["LINE-1", "LINE-2"],
            )

        self.assertTrue(res.success, res.message)
        kwargs = fake_request.await_args.kwargs
        self.assertEqual(kwargs["method"], "PUT")
        self.assertEqual(
            kwargs["url"],
            "https://apigw.trendyol.com/integration/order/sellers/784195/claims/CLM-9/items/approve",
        )
        self.assertEqual(kwargs["json"], {"claimLineItemIdList": ["LINE-1", "LINE-2"]})

    async def test_find_claims_accepts_list_response_body(self) -> None:
        api = TrendyolApi("key", "secret", "784195")
        fake_request = AsyncMock(
            return_value=Result.ok(
                close_dialog=False,
                data={
                    "json": [{"claimId": "CLM-1"}],
                    "status_code": 200,
                },
            )
        )

        with patch("Orders.api.trendyol.orders_api.async_make_request", fake_request):
            res = await api.find_claims(start_date=1000, end_date=2000, page=0, size=50)

        self.assertTrue(res.success, res.message)
        self.assertEqual((res.data or {}).get("content"), [{"claimId": "CLM-1"}])
        self.assertEqual((res.data or {}).get("totalPages"), 1)
        self.assertEqual((res.data or {}).get("totalElements"), 1)

    async def test_find_claims_treats_scalar_response_body_as_empty_page(self) -> None:
        api = TrendyolApi("key", "secret", "784195")
        fake_request = AsyncMock(
            return_value=Result.ok(
                close_dialog=False,
                data={
                    "json": True,
                    "status_code": 200,
                },
            )
        )

        with patch("Orders.api.trendyol.orders_api.async_make_request", fake_request):
            res = await api.find_claims(start_date=1000, end_date=2000, page=0, size=50)

        self.assertTrue(res.success, res.message)
        self.assertEqual((res.data or {}).get("content"), [])
        self.assertEqual((res.data or {}).get("totalPages"), 0)
