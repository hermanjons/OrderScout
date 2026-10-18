from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from Feedback.processors.pipeline import Result
from Finance.api.trendyol.finance_api import TrendyolFinanceApi


class TestTrendyolFinanceApi(IsolatedAsyncioTestCase):
    async def test_get_settlements_reads_endpoint_and_query_defaults_from_marketplaces_json(self) -> None:
        api = TrendyolFinanceApi("key", "secret", "784195")
        fake_request = AsyncMock(
            return_value=Result.ok(
                close_dialog=False,
                data={
                    "json": {"content": [], "totalPages": 1, "page": 0, "totalElements": 0},
                    "status_code": 200,
                },
            )
        )

        with patch("Finance.api.trendyol.finance_api.async_make_request", fake_request):
            res = await api.get_settlements(
                transaction_date_start=1_700_000_000_000,
                transaction_date_end=1_700_086_400_000,
                transaction_type="Sale",
            )

        self.assertTrue(res.success, res.message)
        kwargs = fake_request.await_args.kwargs
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(
            kwargs["url"],
            "https://apigw.trendyol.com/integration/finance/che/sellers/784195/settlements",
        )
        self.assertEqual(kwargs["params"]["page"], 0)
        self.assertEqual(kwargs["params"]["size"], 500)
        self.assertEqual(kwargs["params"]["transactionType"], "Sale")

    async def test_get_settlements_uses_stage_endpoint_without_production_fallback(self) -> None:
        api = TrendyolFinanceApi(
            "stage-key",
            "stage-secret",
            "2738",
            environment="stage",
        )
        fake_request = AsyncMock(
            return_value=Result.ok(
                close_dialog=False,
                data={
                    "json": {
                        "content": [],
                        "totalPages": 1,
                        "page": 0,
                        "totalElements": 0,
                    },
                    "status_code": 200,
                },
            )
        )

        with patch("Finance.api.trendyol.finance_api.async_make_request", fake_request):
            res = await api.get_settlements(
                transaction_date_start=1_700_000_000_000,
                transaction_date_end=1_700_086_400_000,
            )

        self.assertTrue(res.success, res.message)
        kwargs = fake_request.await_args.kwargs
        self.assertEqual(api.environment, "stage")
        self.assertEqual(
            kwargs["url"],
            "https://stageapigw.trendyol.com/integration/finance/che/sellers/2738/settlements",
        )
        self.assertNotIn("https://apigw.trendyol.com", kwargs["url"])

    async def test_stage_client_rejects_explicit_production_base_url_override(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match"):
            TrendyolFinanceApi(
                "stage-key",
                "stage-secret",
                "2738",
                environment="stage",
                base_url="https://apigw.trendyol.com",
            )

    async def test_get_other_financials_uses_status_message_from_marketplaces_json(self) -> None:
        api = TrendyolFinanceApi("key", "secret", "784195")
        fake_request = AsyncMock(
            return_value=Result.fail(
                "ham hata",
                close_dialog=False,
                data={
                    "status_code": 404,
                    "json": {"message": "missing"},
                },
            )
        )

        with patch("Finance.api.trendyol.finance_api.async_make_request", fake_request):
            res = await api.get_other_financials(
                transaction_date_start=1_700_000_000_000,
                transaction_date_end=1_700_086_400_000,
            )

        self.assertFalse(res.success)
        self.assertIn("finans servisi", res.message.lower())
        self.assertIn("bulunamadı", res.message.lower())

    async def test_get_cargo_invoice_items_uses_json_defined_path_parameter(self) -> None:
        api = TrendyolFinanceApi("key", "secret", "784195")
        fake_request = AsyncMock(
            return_value=Result.ok(
                close_dialog=False,
                data={
                    "json": {"content": [], "totalPages": 1, "page": 0, "totalElements": 0},
                    "status_code": 200,
                },
            )
        )

        with patch("Finance.api.trendyol.finance_api.async_make_request", fake_request):
            res = await api.get_cargo_invoice_items(invoice_serial_number="INV-2026-1")

        self.assertTrue(res.success, res.message)
        kwargs = fake_request.await_args.kwargs
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(
            kwargs["url"],
            "https://apigw.trendyol.com/integration/finance/che/sellers/784195/cargo-invoice/INV-2026-1/items",
        )
        self.assertEqual(kwargs["params"]["page"], 0)
        self.assertEqual(kwargs["params"]["size"], 500)

