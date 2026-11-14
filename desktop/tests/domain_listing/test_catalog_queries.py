"""Real cache parity, scope, precision and failures for shared listing reads."""
from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import text
from sqlmodel import Session

from Account.models.models import ApiAccount
from Core.utils import model_utils
from Listing.models.models import ListingProduct
from Listing.processors import catalog_queries as catalog
from Listing.processors import pipeline
from Listing.views import actions
from tests.support.db_case import IsolatedDbTestCase


class TestListingCatalogQueries(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        with Session(model_utils.get_engine(self.db_path)) as session:
            session.add_all([
                ApiAccount(pk=1, account_id="seller-1", comp_name="A", platform="trendyol"),
                ApiAccount(pk=2, account_id="seller-2", comp_name="B", platform="trendyol"),
            ])
            session.commit()

    def _save(self, product_id: str, **changes) -> None:
        item = {
            "api_account_id": 1, "productId": product_id, "title": f"Urun {product_id}",
            "barcode": f"BC-{product_id}", "stockCode": f"SKU-{product_id}", "brand": "Marka A",
            "quantity": 2, "approved": True, "archived": False, "onSale": True,
            "salePrice": 25, "listPrice": 30,
            **changes,
        }
        result = pipeline.save_listings_to_db([item], db_name=self.db_path)
        self.assertTrue(result.success, result.message)

    def _records(self, **filters):
        result = catalog.read_listing_products(db_name=self.db_path, **filters)
        self.assertTrue(result.success, result.message)
        return result.data["records"]

    def test_quantity_and_price_bounds_keep_zero_and_legacy_price_fallback(self) -> None:
        self._save("FREE", quantity=0, salePrice=0, listPrice=30)
        self._save("LIST-PRICE", quantity=0, salePrice=None, listPrice=10)
        self._save("LEGACY", quantity=0, salePrice=20, listPrice=10)
        self._save("UNKNOWN-QUANTITY", quantity=None, salePrice=10)
        with model_utils.get_engine(self.db_path).begin() as connection:
            connection.execute(text(
                "UPDATE trendyol_listing_product SET sale_price = 'unknown' WHERE product_id = 'LEGACY'"
            ))

        free = self._records(quantity_bounds=(0, 0), price_bounds=(0, 0))
        priced = self._records(quantity_bounds=(0, 0), price_bounds=(10, 10))
        self.assertEqual([row.product_id for row in free], ["FREE"])
        self.assertEqual({row.product_id for row in priced}, {"LIST-PRICE", "LEGACY"})

    def test_manual_reader_keeps_all_existing_filter_and_owner_semantics(self) -> None:
        self._save("A1", title="Kirmizi bardak", barcode="86911", stockCode="GLASS-A", brand="Cam")
        self._save("A2", quantity=None, approved=False, onSale=False, brand="Cam")
        self._save("A3", archived=True, quantity=0, brand="Diger")
        self._save("B1", api_account_id=2, archived=None, onSale=True, brand="Cam")
        self._save("B2", api_account_id=2, approved=None, onSale=False, quantity=-0.004, brand="Diger")
        cases = [
            ({}, {"A1", "A2", "A3", "B1", "B2"}),
            ({"api_account_ids": [1]}, {"A1", "A2", "A3"}),
            ({"api_account_ids": [999]}, set()),
            ({"api_account_ids": []}, {"A1", "A2", "A3", "B1", "B2"}),
            ({"listing_status": "active"}, {"A1", "B1"}),
            ({"active_listings": True}, {"A1", "B1"}),
            ({"listing_status": "archived", "active_listings": True}, {"A3"}),
            ({"listing_status": "out_of_stock"}, {"A2", "B2"}),
            ({"approved": False}, {"A2"}),
            ({"barcode": "691"}, {"A1"}),
            ({"stock_code": "GLASS"}, {"A1"}),
            ({"brand": ["Cam"], "api_account_ids": [1]}, {"A1", "A2"}),
            ({"brand": "Dige"}, {"A3", "B2"}),
            ({"product_id": "A", "listing_status": "active"}, {"A1"}),
            ({"search": "Cam", "api_account_ids": [2]}, {"B1"}),
            ({"search": "bardak"}, {"A1"}),
        ]
        for filters, expected in cases:
            with self.subTest(filters=filters):
                records = self._records(**filters)
                self.assertEqual({row.product_id for row in records}, expected)
                manual = actions.action_get_listings_from_db(db_name=self.db_path, **filters)
                self.assertTrue(manual.success, manual.message)
                self.assertEqual(
                    [(row.pk, row.api_account_id, row.product_id, row.quantity) for row in records],
                    [(row["listing_id"], row["api_account_id"], row["productId"], row["quantity"])
                     for row in manual.data["items"]],
                )

    def test_search_preserves_turkish_matching_and_requires_all_free_text_terms(self) -> None:
        self._save("P-1", title="İĞDE ŞİŞE ÇÖĞÜŞ", productCode="CONTENT-77", quantity=0.004)
        self._save("P-2", title="İğde bardağı", quantity=100)
        self._save("P-3", title="Şişe", quantity=10)
        for query in ("igde sise", "İĞDE ŞİŞE", "CONTENT-77 barkodlu urun", "P-1"):
            with self.subTest(query=query):
                result = catalog.read_listing_search(db_name=self.db_path, query=query)
                self.assertTrue(result.success, result.message)
                self.assertEqual([row["product_id"] for row in result.data["results"]], ["P-1"])
                self.assertEqual(result.data["query"], query)
        missing = catalog.read_listing_search(db_name=self.db_path, query="igde kalem")
        self.assertEqual(missing.data["total"], 0)

    def test_embedded_identifier_does_not_match_a_letter_inside_an_unrelated_word(self) -> None:
        self._save("a", title="Tamamen alakasiz", barcode="OTHER", stockCode="OTHER")
        result = catalog.read_listing_search(db_name=self.db_path, query="kalem ariyorum")
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.data["results"], [])
        exact = catalog.read_listing_search(db_name=self.db_path, query="a")
        self.assertEqual(exact.data["results"][0]["product_id"], "a")

    def test_exact_identifier_ranks_ahead_of_text_and_keeps_account_identity(self) -> None:
        self._save("FIRST", title="Sise", barcode="8690001", quantity=0.004)
        self._save("SECOND", title="8690001 tanitim", barcode="OTHER", quantity=100)
        self._save("FIRST", api_account_id=2, title="Baska hesap", barcode="8690001", quantity=5)
        result = catalog.read_listing_search(db_name=self.db_path, query="8690001")
        self.assertTrue(result.success, result.message)
        self.assertEqual([(row["api_account_id"], row["product_id"]) for row in result.data["results"]],
                         [(2, "FIRST"), (1, "FIRST"), (1, "SECOND")])
        self.assertEqual(len({row["listing_id"] for row in result.data["results"]}), 3)
        scoped = catalog.read_listing_search(db_name=self.db_path, query="8690001", api_account_ids=[1])
        self.assertEqual(scoped.data["total"], 2)
        self.assertEqual({row["api_account_id"] for row in scoped.data["results"]}, {1})

    def test_pagination_uses_complete_non_archived_source_and_stable_ties(self) -> None:
        with Session(model_utils.get_engine(self.db_path)) as session:
            session.add_all([
                ListingProduct(api_account_id=1, product_id=f"P-{index:03}", title="Ayni baslik",
                               archived=False, on_sale=False, quantity=0.004)
                for index in range(107)
            ])
            session.add(ListingProduct(api_account_id=1, product_id="ARCHIVED", archived=True))
            session.add(ListingProduct(api_account_id=2, product_id="OTHER-ACCOUNT", archived=False))
            session.commit()
        seen = []
        for offset, count in ((0, 50), (50, 50), (100, 7), (107, 0)):
            page = catalog.read_listing_search(db_name=self.db_path, limit=50, offset=offset, api_account_ids=[1])
            self.assertTrue(page.success, page.message)
            self.assertEqual(page.data["total"], 107)
            self.assertEqual(page.data["count"], count)
            self.assertEqual(page.data["offset"], offset)
            self.assertEqual(page.data["has_more"], offset + count < 107)
            seen.extend(row["listing_id"] for row in page.data["results"])
        self.assertEqual(len(seen), 107)
        self.assertEqual(len(set(seen)), 107)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(len(self._records(api_account_ids=[1])), 108)

    def test_saved_zero_price_and_fractional_quantity_match_actual_manual_cache(self) -> None:
        self._save("ZERO", salePrice=0, listPrice=0, quantity=0.004, currencyCode="usd",
                   price={"salePrice": 999, "listPrice": 999})
        manual = actions.action_get_listings_from_db(db_name=self.db_path)
        self.assertTrue(manual.success, manual.message)
        manual_row = manual.data["items"][0]
        self.assertEqual((manual_row["salePrice"], manual_row["listPrice"], manual_row["quantity"]),
                         (0, 0, 0.004))
        search = catalog.read_listing_search(db_name=self.db_path, query="ZERO")
        self.assertTrue(search.success, search.message)
        row = search.data["results"][0]
        self.assertEqual((row["sale_price"], row["list_price"], row["quantity"], row["currency"]),
                         (0, 0, 0.004, "USD"))
        self.assertEqual(row["listing_id"], manual_row["listing_id"])
        summary = catalog.read_listing_summary(db_name=self.db_path)
        self.assertEqual(summary.data["sample_listings"][0]["quantity"], 0.004)
        self.assertEqual(summary.data["out_of_stock"], 0)

    def test_missing_prices_remain_null_and_zero_sale_does_not_fall_back_to_list(self) -> None:
        self._save("UNKNOWN", salePrice=None, listPrice=None, quantity=None, approved=None, hasActiveCampaign=True)
        self._save("ZERO", salePrice=0, listPrice=90)
        self._save("FALLBACK", salePrice=None, listPrice=15.555)
        self._save("NESTED", salePrice="", listPrice=None, price={"salePrice": 3, "listPrice": 5})
        search = catalog.read_listing_search(db_name=self.db_path)
        self.assertTrue(search.success, search.message)
        rows = {row["product_id"]: row for row in search.data["results"]}
        self.assertIsNone(rows["UNKNOWN"]["sale_price"])
        self.assertIsNone(rows["UNKNOWN"]["list_price"])
        self.assertIsNone(rows["UNKNOWN"]["quantity"])
        self.assertIsNone(rows["UNKNOWN"]["approved"])
        self.assertTrue(rows["UNKNOWN"]["has_active_campaign"])
        self.assertEqual(rows["ZERO"]["sale_price"], 0)
        self.assertEqual(rows["ZERO"]["list_price"], 90)
        self.assertEqual(rows["FALLBACK"]["sale_price"], 15.55)
        self.assertEqual(rows["NESTED"]["sale_price"], 3)
        summary = catalog.read_listing_summary(db_name=self.db_path)
        self.assertEqual([row["product_id"] for row in summary.data["sample_listings"]],
                         ["ZERO", "NESTED", "FALLBACK", "UNKNOWN"])
        self.assertIsNone(summary.data["sample_listings"][-1]["approved"])

    def test_currency_precedence_matches_raw_manual_editor_fields(self) -> None:
        self._save("DEFAULT")
        self._save("CODE", currencyCode=" eur ", currency="USD")
        self._save("SNAKE", currency_code="gbp")
        self._save("TYPE", currencyType="usd")
        self._save("PRICE", priceCurrency="jpy")
        result = catalog.read_listing_search(db_name=self.db_path)
        self.assertTrue(result.success, result.message)
        self.assertEqual({row["product_id"]: row["currency"] for row in result.data["results"]},
                         {"DEFAULT": "TRY", "CODE": "EUR", "SNAKE": "GBP", "TYPE": "USD", "PRICE": "JPY"})

    def test_summary_and_attention_preserve_distinct_status_and_unknown_semantics(self) -> None:
        self._save("HEALTHY", quantity=0.004)
        self._save("MISSING", quantity=None, approved=None, onSale=None)
        self._save("WAITING", quantity=-0.004, approved=False, onSale=False, locked=True, currency="USD")
        self._save("UNSUPPLIED", locked=False, lockedByUnSuppliedReason=True)
        self._save("ARCHIVED", archived=True, quantity=0, approved=False, locked=True, onSale=False)
        self._save("OTHER", api_account_id=2, quantity=0, approved=False, onSale=False)
        summary = catalog.read_listing_summary(db_name=self.db_path, api_account_ids=[1])
        self.assertTrue(summary.success, summary.message)
        expected = {"total_listings": 5, "active_listings": 4, "archived": 1, "on_sale": 2,
                    "not_on_sale": 2, "approved": 2, "unapproved": 1, "locked": 1,
                    "needs_attention": 1, "out_of_stock": 2}
        self.assertEqual({key: summary.data[key] for key in expected}, expected)
        attention = catalog.read_listing_attention(db_name=self.db_path, api_account_ids=[1], limit=1)
        self.assertTrue(attention.success, attention.message)
        self.assertEqual(attention.data["attention_count"], 3)
        self.assertEqual(attention.data["reason_counts"],
                         {"out_of_stock": 2, "not_approved": 1, "locked": 2, "not_on_sale": 2})
        first = attention.data["listings"][0]
        self.assertEqual(first["product_id"], "WAITING")
        self.assertEqual(first["quantity"], -0.004)
        self.assertEqual(first["currency"], "USD")
        self.assertEqual(first["reasons"], ["out_of_stock", "not_approved", "locked", "not_on_sale"])
        self.assertTrue(attention.data["has_more"])
        second = catalog.read_listing_attention(db_name=self.db_path, api_account_ids=[1], offset=1, limit=1)
        self.assertEqual(second.data["listings"][0]["product_id"], "MISSING")
        self.assertIsNone(second.data["listings"][0]["approved"])
        self.assertIsNone(second.data["listings"][0]["quantity"])
        third = catalog.read_listing_attention(db_name=self.db_path, api_account_ids=[1], offset=2, limit=1)
        self.assertTrue(third.data["listings"][0]["locked"])
        self.assertFalse(third.data["has_more"])

    def test_real_database_failure_survives_each_read_boundary_unchanged(self) -> None:
        with Session(model_utils.get_engine(self.db_path)) as session:
            session.exec(text("DROP TABLE trendyol_listing_product"))
            session.commit()
        original_reader = catalog.read_listing_products
        failures = []

        def failing_reader(**kwargs):
            result = original_reader(**kwargs)
            failures.append(result)
            return result

        with patch.object(catalog, "read_listing_products", side_effect=failing_reader):
            for operation in (catalog.query_listing_products, catalog.read_listing_search,
                              catalog.read_listing_summary, catalog.read_listing_attention):
                with self.subTest(operation=operation.__name__):
                    result = operation(db_name=self.db_path)
                    self.assertFalse(result.success)
                    self.assertIs(result, failures[-1])
                    self.assertIsNotNone(result.error)
                    self.assertNotIn("results", result.data)
        with patch.object(pipeline, "read_listing_products", side_effect=failing_reader):
            manual = actions.action_get_listings_from_db(db_name=self.db_path)
            self.assertIs(manual, failures[-1])

    def test_invalid_pagination_is_a_failure_and_empty_pages_report_real_total(self) -> None:
        self._save("ONLY")
        for kwargs in ({"limit": "bad"}, {"offset": "bad"}):
            with self.subTest(kwargs=kwargs):
                result = catalog.read_listing_search(db_name=self.db_path, **kwargs)
                self.assertFalse(result.success)
                self.assertIsInstance(result.error, ValueError)
        page = catalog.read_listing_search(db_name=self.db_path, offset=10)
        self.assertEqual((page.data["total"], page.data["count"], page.data["has_more"]), (1, 0, False))
