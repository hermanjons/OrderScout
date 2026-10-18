from __future__ import annotations

import asyncio
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import Listing.api.trendyol.listing_api as listing_api
import Listing.processors.trendyol.pipeline as listing_pipeline
from Feedback.processors.pipeline import Result


class TestTrendyolListingApi(TestCase):
    @classmethod
    def _api_source(cls) -> str:
        return Path(listing_api.__file__).resolve().read_text(encoding="utf-8")

    def test_flatten_approved_items_expands_variants(self) -> None:
        rows = listing_pipeline._flatten_approved_items(
            [
                {
                    "contentId": 9001,
                    "productMainId": "MAIN-1",
                    "title": "Approved Product",
                    "description": "desc",
                    "brand": {"id": 11, "name": "BrandX"},
                    "category": {"id": 22, "name": "CatX"},
                    "images": [{"url": "https://cdn.example.com/a.jpg"}],
                    "attributes": [{"attributeId": 1, "attributeValueId": 2}],
                    "variants": [
                        {
                            "variantId": 501,
                            "barcode": "8690000000001",
                            "stockCode": "STK-1",
                            "onSale": True,
                            "price": {"salePrice": 99.9, "listPrice": 109.9, "currency": "TRY"},
                            "vatRate": 20,
                        }
                    ],
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["productId"], "9001:8690000000001")
        self.assertEqual(row["productContentId"], 9001)
        self.assertEqual(row["platformListingId"], 9001)
        self.assertEqual(row["brand"], "BrandX")
        self.assertEqual(row["brandId"], 11)
        self.assertEqual(row["categoryName"], "CatX")
        self.assertEqual(row["salePrice"], 99.9)
        self.assertEqual(row["listPrice"], 109.9)
        self.assertEqual(row["currencyCode"], "TRY")
        self.assertTrue(row["approved"])

    def test_flatten_approved_items_builds_unique_product_ids_when_variant_id_missing(self) -> None:
        rows = listing_pipeline._flatten_approved_items(
            [
                {
                    "contentId": 9001,
                    "productMainId": "MAIN-1",
                    "title": "Approved Product",
                    "variants": [
                        {
                            "barcode": "8690000000001",
                            "stockCode": "STK-1",
                            "price": {"salePrice": 99.9, "listPrice": 109.9, "currency": "TRY"},
                        },
                        {
                            "barcode": "8690000000002",
                            "stockCode": "STK-2",
                            "price": {"salePrice": 89.9, "listPrice": 99.9, "currency": "TRY"},
                        },
                    ],
                }
            ]
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["productId"], "9001:8690000000001")
        self.assertEqual(rows[1]["productId"], "9001:8690000000002")

    def test_flatten_unapproved_items_normalizes_nested_fields(self) -> None:
        rows = listing_pipeline._flatten_unapproved_items(
            [
                {
                    "barcode": "8690000000002",
                    "stockCode": "STK-2",
                    "title": "Draft Product",
                    "brand": {"id": 44, "name": "BrandY"},
                    "category": {"id": 55, "name": "CatY"},
                    "media": [{"url": "https://cdn.example.com/b.jpg"}],
                    "salePrice": 49.5,
                    "listPrice": 59.5,
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["productId"], "8690000000002")
        self.assertEqual(row["brand"], "BrandY")
        self.assertEqual(row["brandId"], 44)
        self.assertEqual(row["categoryName"], "CatY")
        self.assertEqual(row["images"], [{"url": "https://cdn.example.com/b.jpg"}])
        self.assertFalse(row["approved"])

    def test_sanitize_page_size_uses_v2_limits(self) -> None:
        self.assertEqual(listing_api._sanitize_page_size(999, approved=True), 100)
        self.assertEqual(listing_api._sanitize_page_size(5000, approved=False), 1000)

    def test_listing_api_uses_listing_constants_for_marketplace_profiles(self) -> None:
        source = self._api_source()
        self.assertIn("from Listing.constants.trendyol.constants import", source)
        self.assertNotIn("from Marketplaces.constants.catalog_constants import", source)

    def test_list_products_does_not_require_store_front_code_for_turkey_v2(self) -> None:
        captured: dict[str, object] = {}

        async def fake_request(**kwargs):
            captured.update(kwargs)
            return Result.ok(
                "ok",
                close_dialog=False,
                data={"json": {"content": []}, "status_code": 200},
            )

        api = listing_api.TrendyolListingApi("key", "secret", "123")
        with patch("Listing.api.trendyol.listing_api.async_make_request", side_effect=fake_request):
            result = asyncio.run(api._list_products_single_state(approved=True))

        self.assertTrue(result.success, result.message)
        headers = dict(captured.get("headers") or {})
        self.assertNotIn("storeFrontCode", headers)

    def test_list_products_all_ignores_next_page_token_before_10000_boundary(self) -> None:
        requests: list[dict[str, object]] = []

        async def fake_request(**kwargs):
            requests.append(kwargs)
            params = dict(kwargs.get("params") or {})
            page = int(params.get("page", 0))
            payload = {
                "content": [
                    {"contentId": page * 100 + i + 1, "variants": [{"variantId": page * 100 + i + 1, "barcode": f"B{page * 100 + i + 1}"}]}
                    for i in range(100)
                ],
                "page": page,
                "size": 100,
                "totalPages": 2,
                "totalElements": 2,
                "nextPageToken": "TOKEN-1",
            }
            return Result.ok("ok", close_dialog=False, data={"json": payload, "status_code": 200})

        api = listing_api.TrendyolListingApi("key", "secret", "123")
        with patch("Listing.api.trendyol.listing_api.async_make_request", side_effect=fake_request):
            result = asyncio.run(api.list_products_all(size=100, approved=True, max_pages=2))

        self.assertTrue(result.success, result.message)
        self.assertEqual(len(requests), 2)
        first_params = dict(requests[0].get("params") or {})
        second_params = dict(requests[1].get("params") or {})
        self.assertEqual(first_params.get("page"), 0)
        self.assertNotIn("nextPageToken", first_params)
        self.assertEqual(second_params.get("page"), 1)
        self.assertNotIn("nextPageToken", second_params)

    def test_list_products_all_uses_next_page_token_after_10000_boundary(self) -> None:
        requests: list[dict[str, object]] = []

        async def fake_request(**kwargs):
            requests.append(kwargs)
            params = dict(kwargs.get("params") or {})
            page = int(params.get("page", 0))
            has_token = "nextPageToken" in params
            payload = {
                "content": [
                    {"contentId": page * 100 + i + 1, "variants": [{"variantId": page * 100 + i + 1, "barcode": f"B{page * 100 + i + 1}"}]}
                    for i in range(100)
                ],
                "page": page,
                "size": 100,
                "totalPages": 101,
                "totalElements": 10001,
                "nextPageToken": "TOKEN-BOUNDARY",
            }
            if has_token:
                payload["page"] = 100
            return Result.ok("ok", close_dialog=False, data={"json": payload, "status_code": 200})

        api = listing_api.TrendyolListingApi("key", "secret", "123")
        with patch("Listing.api.trendyol.listing_api.async_make_request", side_effect=fake_request):
            result = asyncio.run(api.list_products_all(start_page=99, size=100, approved=True, max_pages=2))

        self.assertTrue(result.success, result.message)
        self.assertEqual(len(requests), 2)
        first_params = dict(requests[0].get("params") or {})
        second_params = dict(requests[1].get("params") or {})
        self.assertEqual(first_params.get("page"), 99)
        self.assertNotIn("nextPageToken", first_params)
        self.assertNotIn("page", second_params)
        self.assertEqual(second_params.get("nextPageToken"), "TOKEN-BOUNDARY")

    def test_list_products_rejects_next_page_token_when_approved_is_unspecified(self) -> None:
        api = listing_api.TrendyolListingApi("key", "secret", "123")
        result = asyncio.run(api.list_products(approved=None, next_page_token="TOKEN-1"))
        self.assertFalse(result.success)
        self.assertIn("next_page_token", str(result.message or ""))

    def test_list_products_all_rejects_next_page_token_when_approved_is_unspecified(self) -> None:
        api = listing_api.TrendyolListingApi("key", "secret", "123")
        result = asyncio.run(api.list_products_all(approved=None, next_page_token="TOKEN-1"))
        self.assertFalse(result.success)
        self.assertIn("next_page_token", str(result.message or ""))

    def test_fetch_listings_all_progress_uses_page_progress(self) -> None:
        updates: list[tuple[int, int]] = []

        async def fake_fetch_listings_for_account(**kwargs):
            tracker = kwargs.get("tracker")
            if tracker is not None:
                await tracker.set_page_progress((kwargs["api_account_id"], "approved"), 1, 2, True)
                await tracker.set_page_progress((kwargs["api_account_id"], "approved"), 2, 2, False)
                await tracker.set_page_progress((kwargs["api_account_id"], "unapproved"), 1, 2, True)
                await tracker.set_page_progress((kwargs["api_account_id"], "unapproved"), 2, 2, False)
            return Result.ok(
                "ok",
                close_dialog=False,
                data={"items": [{"productId": f"P-{kwargs['api_account_id']}"}], "meta": {"page": 0}},
            )

        accounts = [
            [101, "key-1", "secret-1", "seller-1", ""],
            [202, "key-2", "secret-2", "seller-2", ""],
        ]

        with patch("Listing.processors.trendyol.pipeline.fetch_listings_for_account", side_effect=fake_fetch_listings_for_account):
            result = asyncio.run(
                listing_pipeline.fetch_listings_all(
                    accounts,
                    fetch_all_pages=True,
                    progress_callback=lambda current, total: updates.append((int(current), int(total))),
                )
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual(updates, [(1, 5), (2, 5), (3, 6), (4, 6), (5, 7), (6, 7), (7, 8), (8, 8)])

    def test_update_approved_content_uses_v2_stage_endpoint_and_exact_payload(self) -> None:
        captured: dict[str, object] = {}

        async def fake_request(**kwargs):
            captured.update(kwargs)
            return Result.ok(
                "ok",
                close_dialog=False,
                data={"json": {"batchRequestId": "BATCH-CONTENT-1"}, "status_code": 200},
            )

        api = listing_api.TrendyolListingApi("key", "secret", "2738", environment="stage")
        with patch("Listing.api.trendyol.listing_api.async_make_request", side_effect=fake_request):
            result = asyncio.run(
                api.update_approved_content(
                    items=[
                        {
                            "contentId": 9001,
                            "title": "Yeni Başlık",
                            "images": ["https://cdn.example.com/a.jpg"],
                        }
                    ]
                )
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual(captured.get("method"), "POST")
        self.assertEqual(
            captured.get("url"),
            "https://stageapigw.trendyol.com/integration/product/sellers/2738/products/content-bulk-update",
        )
        self.assertEqual(
            captured.get("json"),
            {
                "items": [
                    {
                        "contentId": 9001,
                        "title": "Yeni Başlık",
                        "images": [{"url": "https://cdn.example.com/a.jpg"}],
                    }
                ]
            },
        )
        self.assertEqual((result.data or {}).get("batch_request_id"), "BATCH-CONTENT-1")

    def test_stage_listing_operations_use_only_stage_endpoints(self) -> None:
        captured: list[dict[str, object]] = []

        async def fake_request(**kwargs):
            captured.append(dict(kwargs))
            return Result.ok(
                "ok",
                close_dialog=False,
                data={"json": {"content": [], "batchRequestId": "BATCH-STAGE-1"}, "status_code": 200},
            )

        api = listing_api.TrendyolListingApi("key", "secret", "2738", environment="stage")
        with patch("Listing.api.trendyol.listing_api.async_make_request", side_effect=fake_request):
            listed = asyncio.run(api._list_products_single_state(approved=True))
            updated = asyncio.run(
                api.update_price_and_inventory(
                    items=[
                        {
                            "barcode": "8690000000001",
                            "quantity": 2,
                            "salePrice": 90.0,
                            "listPrice": 100.0,
                        }
                    ]
                )
            )
            checked = asyncio.run(api.get_batch_request_result(batch_request_id="BATCH-STAGE-1"))

        self.assertTrue(listed.success, listed.message)
        self.assertTrue(updated.success, updated.message)
        self.assertTrue(checked.success, checked.message)
        self.assertEqual(
            [row.get("url") for row in captured],
            [
                "https://stageapigw.trendyol.com/integration/product/sellers/2738/products/approved",
                "https://stageapigw.trendyol.com/integration/inventory/sellers/2738/products/price-and-inventory",
                "https://stageapigw.trendyol.com/integration/product/sellers/2738/products/batch-requests/BATCH-STAGE-1",
            ],
        )
        self.assertTrue(
            all("https://apigw.trendyol.com" not in str(row.get("url") or "") for row in captured)
        )

    def test_listing_client_rejects_cross_environment_base_url_overrides(self) -> None:
        cases = (
            ("stage", "https://apigw.trendyol.com/integration"),
            ("production", "https://stageapigw.trendyol.com/integration"),
        )
        for environment, base_url in cases:
            with self.subTest(environment=environment, base_url=base_url):
                with self.assertRaisesRegex(ValueError, "does not match"):
                    listing_api.TrendyolListingApi(
                        "key",
                        "secret",
                        "2738",
                        environment=environment,
                        base_url=base_url,
                    )

    def test_update_approved_content_rejects_unsafe_or_incomplete_payload_before_request(self) -> None:
        invalid_rows = [
            [{"contentId": 0, "title": "x"}],
            [{"contentId": 1}],
            [{"contentId": 1, "title": "x" * 101}],
            [{"contentId": 1, "description": "x" * 30001}],
            [{"contentId": 1, "images": ["http://cdn.example.com/a.jpg"]}],
            [{"contentId": 1, "images": [f"https://cdn.example.com/{i}.jpg" for i in range(9)]}],
            [{"contentId": 1, "attributes": []}],
        ]
        api = listing_api.TrendyolListingApi("key", "secret", "2738", environment="stage")
        with patch("Listing.api.trendyol.listing_api.async_make_request") as request_mock:
            for items in invalid_rows:
                with self.subTest(items=items):
                    result = asyncio.run(api.update_approved_content(items=items))
                    self.assertFalse(result.success)
            request_mock.assert_not_called()

    def test_update_approved_content_pipeline_preserves_stage_and_verifies_batch(self) -> None:
        created: list[dict[str, object]] = []

        class FakeApi:
            def __init__(self, *args, **kwargs):
                created.append({"args": args, "kwargs": kwargs})

            async def update_approved_content(self, *, items):
                return Result.ok(
                    "queued",
                    close_dialog=False,
                    data={"batch_request_id": "BATCH-CONTENT-2"},
                )

            async def get_batch_request_result(self, *, batch_request_id):
                return Result.ok(
                    "done",
                    close_dialog=False,
                    data={
                        "raw": {
                            "items": [
                                {
                                    "requestItem": {"contentId": 9002},
                                    "status": "SUCCESS",
                                    "failureReasons": [],
                                }
                            ]
                        }
                    },
                )

        with patch("Listing.processors.trendyol.pipeline.TrendyolListingApi", FakeApi):
            result = asyncio.run(
                listing_pipeline.update_approved_content_for_account(
                    api_key="key",
                    api_secret="secret",
                    seller_id="2738",
                    items=[{"contentId": 9002, "description": "Yeni açıklama"}],
                    content_id=9002,
                    poll_interval=0,
                    max_wait=1,
                    environment="stage",
                    accept_language="tr-TR",
                )
            )

        self.assertTrue(result.success, result.message)
        self.assertTrue((result.data or {}).get("verified"))
        self.assertEqual((result.data or {}).get("content_id"), 9002)
        self.assertEqual(created[0]["kwargs"].get("environment"), "stage")
        self.assertEqual(created[0]["kwargs"].get("accept_language"), "tr-TR")
