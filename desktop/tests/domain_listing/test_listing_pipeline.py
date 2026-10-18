from __future__ import annotations

import Listing.processors.pipeline as listing_pipeline
from sqlmodel import Session, select

from Account.models.models import ApiAccount
from Core.utils import model_utils
from Finance.models.trendyol.models import FinanceCostItem
from Logistics.models.models import LogisticsCargoProvider
from Listing.models import ListingProduct, ListingProductCostSnapshot, ListingProductStockSnapshot
from Stock.models import StockItem

from tests.support.db_case import IsolatedDbTestCase


class TestListingPipeline(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        engine = model_utils.get_engine(self.db_path)
        with Session(engine) as session:
            session.add(
                ApiAccount(
                    pk=1,
                    account_id="seller-1",
                    comp_name="Demo Seller",
                    platform="trendyol",
                )
            )
            session.add(StockItem(pk=7, sku="SKU-7", name="Stock 7"))
            session.add(StockItem(pk=9, sku="SKU-9", name="Stock 9"))
            session.add(StockItem(pk=11, sku="SKU-11", name="Stock 11"))
            session.add(
                FinanceCostItem(
                    pk=101,
                    costKey="paketleme",
                    name="Paketleme",
                    valueType="numeric",
                    createdAt="2026-04-04T10:00:00",
                    updatedAt="2026-04-04T10:00:00",
                )
            )
            session.add(
                FinanceCostItem(
                    pk=102,
                    costKey="komisyon",
                    name="Komisyon",
                    valueType="percentage",
                    createdAt="2026-04-04T10:00:00",
                    updatedAt="2026-04-04T10:00:00",
                )
            )
            session.add(
                FinanceCostItem(
                    pk=103,
                    costKey="kargo",
                    name="Kargo",
                    valueType="numeric",
                    createdAt="2026-04-04T10:00:00",
                    updatedAt="2026-04-04T10:00:00",
                )
            )
            session.add(
                LogisticsCargoProvider(
                    pk=41,
                    platformCode="TRENDYOL",
                    cargoProviderCode="ARAS",
                    cargoProviderName="Aras Kargo Marketplace",
                )
            )
            session.add(
                LogisticsCargoProvider(
                    pk=42,
                    platformCode="TRENDYOL",
                    cargoProviderCode="YURTICI",
                    cargoProviderName="Yurtici Kargo Marketplace",
                )
            )
            session.commit()

    def _sample_item(self, *, quantity: float, sale_price: float) -> dict:
        return {
            "api_account_id": 1,
            "productId": "P-1001",
            "title": "Test Listing",
            "barcode": "8690000000001",
            "stockCode": "STK-1001",
            "brand": "BrandX",
            "quantity": quantity,
            "approved": True,
            "archived": False,
            "onSale": True,
            "listPrice": 120.0,
            "salePrice": sale_price,
            "images": [],
            "attributes": [],
        }

    def test_save_listings_tracks_updates_and_history(self) -> None:
        first = listing_pipeline.save_listings_to_db([self._sample_item(quantity=5, sale_price=99.0)], db_name=self.db_path)
        self.assertTrue(first.success, first.message)
        self.assertTrue((first.data or {}).get("changed"))
        self.assertEqual(((first.data or {}).get("counts") or {}).get("inserted"), 1)

        second = listing_pipeline.save_listings_to_db([self._sample_item(quantity=2, sale_price=89.0)], db_name=self.db_path)
        self.assertTrue(second.success, second.message)
        self.assertTrue((second.data or {}).get("changed"))
        counts = (second.data or {}).get("counts", {})
        self.assertEqual(counts.get("updated"), 1)
        self.assertEqual(counts.get("history"), 1)

        read = listing_pipeline.get_listings_from_db(api_account_ids=[1], db_name=self.db_path)
        self.assertTrue(read.success, read.message)
        items = (read.data or {}).get("items", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].get("quantity"), 2.0)
        self.assertEqual(items[0].get("salePrice"), 89.0)

    def test_save_listings_ignores_raw_only_differences(self) -> None:
        item = self._sample_item(quantity=5, sale_price=99.0)
        item["rawSource"] = {"content": {"x": 1}}
        first = listing_pipeline.save_listings_to_db([item], db_name=self.db_path)
        self.assertTrue(first.success, first.message)

        changed_raw = self._sample_item(quantity=5, sale_price=99.0)
        changed_raw["lastUpdateDate"] = 999999999
        changed_raw["version"] = 42
        changed_raw["rawSource"] = {"content": {"x": 2, "serverTime": "volatile"}}

        second = listing_pipeline.save_listings_to_db([changed_raw], db_name=self.db_path)
        self.assertTrue(second.success, second.message)
        self.assertFalse((second.data or {}).get("changed"))
        self.assertEqual(((second.data or {}).get("counts") or {}).get("updated"), 0)

    def test_save_listings_ignores_json_order_only_differences(self) -> None:
        item = self._sample_item(quantity=5, sale_price=99.0)
        item["images"] = [
            {"url": "https://cdn.example.com/b.jpg", "order": 2},
            {"url": "https://cdn.example.com/a.jpg", "order": 1},
        ]
        item["attributes"] = [
            {"attributeId": 2, "attributeValueId": 20},
            {"attributeId": 1, "attributeValueId": 10},
        ]
        item["deliveryOption"] = [
            {"name": "FAST", "enabled": True},
            {"name": "STANDARD", "enabled": True},
        ]
        first = listing_pipeline.save_listings_to_db([item], db_name=self.db_path)
        self.assertTrue(first.success, first.message)

        reordered = self._sample_item(quantity=5, sale_price=99.0)
        reordered["images"] = [
            {"url": "https://cdn.example.com/a.jpg", "order": 1},
            {"url": "https://cdn.example.com/b.jpg", "order": 2},
        ]
        reordered["attributes"] = [
            {"attributeValueId": 10, "attributeId": 1},
            {"attributeValueId": 20, "attributeId": 2},
        ]
        reordered["deliveryOptions"] = [
            {"enabled": True, "name": "STANDARD"},
            {"enabled": True, "name": "FAST"},
        ]

        second = listing_pipeline.save_listings_to_db([reordered], db_name=self.db_path)
        self.assertTrue(second.success, second.message)
        self.assertFalse((second.data or {}).get("changed"))
        self.assertEqual(((second.data or {}).get("counts") or {}).get("updated"), 0)

    def test_save_listings_prunes_missing_rows_on_full_sync(self) -> None:
        first = listing_pipeline.save_listings_to_db(
            [
                self._sample_item(quantity=5, sale_price=99.0),
                {
                    "api_account_id": 1,
                    "productId": "P-2002",
                    "title": "Second Listing",
                    "barcode": "8690000000002",
                    "stockCode": "STK-2002",
                    "brand": "BrandY",
                    "quantity": 3,
                    "approved": True,
                    "archived": False,
                    "onSale": True,
                    "listPrice": 130.0,
                    "salePrice": 119.0,
                    "images": [],
                    "attributes": [],
                },
            ],
            db_name=self.db_path,
        )
        self.assertTrue(first.success, first.message)

        second = listing_pipeline.save_listings_to_db(
            [self._sample_item(quantity=6, sale_price=101.0)],
            db_name=self.db_path,
            sync_api_account_ids=[1],
            prune_missing=True,
        )
        self.assertTrue(second.success, second.message)
        counts = (second.data or {}).get("counts") or {}
        self.assertEqual(counts.get("deleted"), 1)

        read = listing_pipeline.get_listings_from_db(api_account_ids=[1], db_name=self.db_path)
        self.assertTrue(read.success, read.message)
        items = (read.data or {}).get("items", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].get("productId"), "P-1001")

    def test_save_listings_normalizes_v2_nested_brand_category_and_media(self) -> None:
        item = {
            "api_account_id": 1,
            "contentId": 7001,
            "productMainId": "MAIN-7001",
            "barcode": "8690000000701",
            "stockCode": "STK-7001",
            "title": "Nested Listing",
            "brand": {"id": 91, "name": "BrandNested"},
            "category": {"id": 92, "name": "CategoryNested"},
            "media": [{"url": "https://cdn.example.com/nested.jpg"}],
            "salePrice": 77.0,
            "listPrice": 88.0,
            "approved": False,
        }

        save_res = listing_pipeline.save_listings_to_db([item], db_name=self.db_path)
        self.assertTrue(save_res.success, save_res.message)

        read = listing_pipeline.get_listings_from_db(api_account_ids=[1], db_name=self.db_path)
        self.assertTrue(read.success, read.message)
        stored = (read.data or {}).get("items", [None])[0]
        self.assertIsNotNone(stored)
        self.assertEqual(stored["productId"], "7001")
        self.assertEqual(stored["brand"], "BrandNested")
        self.assertEqual(stored["brandId"], 91)
        self.assertEqual(stored["categoryName"], "CategoryNested")
        self.assertEqual(stored["platformListingId"], "7001")
        self.assertEqual(stored["productContentId"], 7001)
        self.assertEqual(stored["images"], [{"url": "https://cdn.example.com/nested.jpg"}])

    def test_get_listing_brands_from_db_uses_status_filtered_distinct_query(self) -> None:
        seed = listing_pipeline.save_listings_to_db(
            [
                {
                    **self._sample_item(quantity=5, sale_price=99.0),
                    "productId": "P-ACTIVE-1",
                    "brand": "BrandAlpha",
                },
                {
                    **self._sample_item(quantity=3, sale_price=89.0),
                    "productId": "P-ACTIVE-2",
                    "brand": "BrandAlpha",
                },
                {
                    **self._sample_item(quantity=0, sale_price=79.0),
                    "productId": "P-STOCK-0",
                    "brand": "BrandZero",
                    "onSale": False,
                },
                {
                    **self._sample_item(quantity=2, sale_price=69.0),
                    "productId": "P-ARCHIVE-1",
                    "brand": "BrandArchive",
                    "archived": True,
                    "onSale": False,
                },
            ],
            db_name=self.db_path,
        )
        self.assertTrue(seed.success, seed.message)

        active = listing_pipeline.get_listing_brands_from_db(
            api_account_ids=[1],
            listing_status="active",
            db_name=self.db_path,
        )
        self.assertTrue(active.success, active.message)
        self.assertEqual((active.data or {}).get("brands"), ["BrandAlpha"])

        out_of_stock = listing_pipeline.get_listing_brands_from_db(
            api_account_ids=[1],
            listing_status="out_of_stock",
            db_name=self.db_path,
        )
        self.assertTrue(out_of_stock.success, out_of_stock.message)
        self.assertEqual((out_of_stock.data or {}).get("brands"), ["BrandZero"])

        archived = listing_pipeline.get_listing_brands_from_db(
            api_account_ids=[1],
            listing_status="archived",
            db_name=self.db_path,
        )
        self.assertTrue(archived.success, archived.message)
        self.assertEqual((archived.data or {}).get("brands"), ["BrandArchive"])

    def test_set_listing_stock_items_merges_quantities(self) -> None:
        seed = listing_pipeline.save_listings_to_db([self._sample_item(quantity=1, sale_price=50.0)], db_name=self.db_path)
        self.assertTrue(seed.success, seed.message)

        set_res = listing_pipeline.set_listing_stock_items(
            api_account_id=1,
            product_id="P-1001",
            stock_items=[
                {"stock_item_id": 7, "qty": 1},
                {"stock_item_id": 7, "qty": 2},
                {"stock_item_id": 9, "qty": 3},
                {"stock_item_id": 11, "qty": 0},
            ],
            db_name=self.db_path,
        )
        self.assertTrue(set_res.success, set_res.message)

        read = listing_pipeline.get_listings_from_db(api_account_ids=[1], db_name=self.db_path)
        self.assertTrue(read.success, read.message)
        item = (read.data or {}).get("items", [None])[0]
        self.assertIsNotNone(item)

        stock_items = sorted(item.get("stock_items", []), key=lambda x: x["stock_item_id"])
        self.assertEqual(stock_items, [{"stock_item_id": 7, "qty": 3.0}, {"stock_item_id": 9, "qty": 3.0}])

        engine = model_utils.get_engine(self.db_path)
        with Session(engine) as session:
            listing_id = session.exec(
                select(ListingProduct.pk)
                .where(ListingProduct.api_account_id == 1)
                .where(ListingProduct.product_id == "P-1001")
            ).first()
            rows = session.exec(
                select(ListingProductStockSnapshot)
                .where(ListingProductStockSnapshot.listing_id == int(listing_id))
                .order_by(ListingProductStockSnapshot.pk.asc())
            ).all()

        self.assertEqual(
            [(int(row.stock_item_id), float(row.qty or 0.0), str(row.status)) for row in rows],
            [(7, 3.0, "append"), (9, 3.0, "append")],
        )

    def test_set_listing_cost_items_merges_by_cost_key(self) -> None:
        seed = listing_pipeline.save_listings_to_db([self._sample_item(quantity=1, sale_price=50.0)], db_name=self.db_path)
        self.assertTrue(seed.success, seed.message)

        set_res = listing_pipeline.set_listing_cost_items(
            api_account_id=1,
            product_id="P-1001",
            cost_items=[
                {"cost_key": "paketleme", "amount": 12.5},
                {"cost_key": "paketleme", "amount": 15.0},
                {"cost_key": "etiket", "amount": 3.25},
                {"cost_key": "", "amount": 7.0},
            ],
            db_name=self.db_path,
        )
        self.assertTrue(set_res.success, set_res.message)

        read = listing_pipeline.get_listings_from_db(api_account_ids=[1], db_name=self.db_path)
        self.assertTrue(read.success, read.message)
        item = (read.data or {}).get("items", [None])[0]
        self.assertIsNotNone(item)

        cost_items = sorted(
            (
                {"cost_key": row.get("cost_key"), "amount": row.get("amount")}
                for row in (item.get("cost_items", []) or [])
            ),
            key=lambda x: x["cost_key"],
        )
        self.assertEqual(
            cost_items,
            [{"cost_key": "etiket", "amount": 3.25}, {"cost_key": "paketleme", "amount": 15.0}],
        )

    def test_set_listing_cost_items_persists_dynamic_fields(self) -> None:
        seed = listing_pipeline.save_listings_to_db([self._sample_item(quantity=1, sale_price=50.0)], db_name=self.db_path)
        self.assertTrue(seed.success, seed.message)

        set_res = listing_pipeline.set_listing_cost_items(
            api_account_id=1,
            product_id="P-1001",
            cost_items=[
                {"cost_key": "iscilik", "calculation_type": "manual", "amount": 10.0},
                {"cost_key": "komisyon", "calculation_type": "manual", "amount": 21.0},
                {
                    "cost_key": "kargo",
                    "calculation_type": "automatic",
                    "source_config": {
                        "ruleKey": "cargo_amount_matcher",
                        "cargoProviderId": 41,
                        "cargoProviderCode": "ARAS",
                        "cargoProviderName": "Aras Kargo Marketplace",
                    },
                },
            ],
            db_name=self.db_path,
        )
        self.assertTrue(set_res.success, set_res.message)

        read = listing_pipeline.get_listings_from_db(api_account_ids=[1], db_name=self.db_path)
        self.assertTrue(read.success, read.message)
        item = (read.data or {}).get("items", [None])[0]
        self.assertIsNotNone(item)

        cost_items = {row["cost_key"]: row for row in (item.get("cost_items", []) or [])}
        self.assertEqual(cost_items["iscilik"]["calculation_type"], "manual")
        self.assertEqual(cost_items["iscilik"]["amount"], 10.0)
        self.assertIsNone(cost_items["iscilik"]["quantity"])
        self.assertEqual(cost_items["iscilik"]["source_type"], "manual_value")
        self.assertEqual(cost_items["iscilik"]["source_config"], {"amount": 10.0})
        self.assertEqual(cost_items["komisyon"]["calculation_type"], "manual")
        self.assertEqual(cost_items["komisyon"]["amount"], 21.0)
        self.assertEqual(cost_items["komisyon"]["source_type"], "manual_value")
        self.assertEqual(cost_items["komisyon"]["source_config"], {"amount": 21.0})
        self.assertEqual(cost_items["kargo"]["calculation_type"], "automatic")
        self.assertEqual(cost_items["kargo"]["source_type"], "builtin_resolver")
        self.assertIsNone(cost_items["kargo"]["amount"])
        self.assertIsNone(cost_items["kargo"]["tariff_key"])
        self.assertEqual(
            cost_items["kargo"]["source_config"],
            {
                "ruleKey": "cargo_amount_matcher",
                "cargoProviderId": 41,
                "cargoProviderCode": "ARAS",
                "cargoProviderName": "Aras Kargo Marketplace",
            },
        )

        set_res_again = listing_pipeline.set_listing_cost_items(
            api_account_id=1,
            product_id="P-1001",
            cost_items=[
                {"cost_key": "iscilik", "calculation_type": "manual", "amount": 10.0},
                {"cost_key": "komisyon", "calculation_type": "manual", "amount": 21.0},
                {
                    "cost_key": "kargo",
                    "calculation_type": "automatic",
                    "source_config": {
                        "ruleKey": "cargo_amount_matcher",
                        "cargoProviderId": 41,
                        "cargoProviderCode": "ARAS",
                        "cargoProviderName": "Aras Kargo Marketplace",
                    },
                },
            ],
            db_name=self.db_path,
        )
        self.assertTrue(set_res_again.success, set_res_again.message)

    def test_set_listing_cost_items_requires_cargo_provider_for_cargo_card(self) -> None:
        seed = listing_pipeline.save_listings_to_db([self._sample_item(quantity=1, sale_price=50.0)], db_name=self.db_path)
        self.assertTrue(seed.success, seed.message)

        set_res = listing_pipeline.set_listing_cost_items(
            api_account_id=1,
            product_id="P-1001",
            cost_items=[
                {"cost_key": "kargo", "calculation_type": "automatic"},
            ],
            db_name=self.db_path,
        )
        self.assertFalse(set_res.success)
        self.assertIn("kargo firması", str(set_res.message).casefold())

    def test_set_listing_cost_items_persists_cargo_provider_link(self) -> None:
        seed = listing_pipeline.save_listings_to_db([self._sample_item(quantity=1, sale_price=50.0)], db_name=self.db_path)
        self.assertTrue(seed.success, seed.message)

        set_res = listing_pipeline.set_listing_cost_items(
            api_account_id=1,
            product_id="P-1001",
            cost_items=[
                {
                    "cost_key": "kargo",
                    "source_type": "builtin_resolver",
                    "source_config": {
                        "ruleKey": "cargo_amount_matcher",
                        "cargoProviderId": 41,
                        "cargoProviderCode": "ARAS",
                        "cargoProviderName": "Aras Kargo Marketplace",
                    },
                },
            ],
            db_name=self.db_path,
        )
        self.assertTrue(set_res.success, set_res.message)

        read = listing_pipeline.get_listings_from_db(api_account_ids=[1], db_name=self.db_path)
        self.assertTrue(read.success, read.message)
        item = (read.data or {}).get("items", [None])[0]
        self.assertIsNotNone(item)
        cargo_row = {row["cost_key"]: row for row in (item.get("cost_items", []) or [])}["kargo"]
        self.assertEqual(cargo_row.get("cargo_provider_id"), 41)
        self.assertEqual(
            cargo_row.get("source_config"),
            {
                "ruleKey": "cargo_amount_matcher",
                "cargoProviderId": 41,
                "cargoProviderCode": "ARAS",
                "cargoProviderName": "Aras Kargo Marketplace",
            },
        )

        engine = model_utils.get_engine(self.db_path)
        with Session(engine) as session:
            listing_id = session.exec(
                select(ListingProduct.pk)
                .where(ListingProduct.api_account_id == 1)
                .where(ListingProduct.product_id == "P-1001")
            ).first()
            row = session.exec(
                select(ListingProductCostSnapshot)
                .where(ListingProductCostSnapshot.listing_id == int(listing_id))
                .where(ListingProductCostSnapshot.cost_key == "kargo")
            ).first()

        self.assertIsNotNone(row)
        self.assertEqual(int(row.cargo_provider_id or 0), 41)

    def test_set_listing_cost_items_persists_explicit_db_field_source(self) -> None:
        seed = listing_pipeline.save_listings_to_db([self._sample_item(quantity=1, sale_price=50.0)], db_name=self.db_path)
        self.assertTrue(seed.success, seed.message)

        set_res = listing_pipeline.set_listing_cost_items(
            api_account_id=1,
            product_id="P-1001",
            cost_items=[
                {
                    "cost_key": "komisyon",
                    "source_type": "db_field",
                    "source_config": {"fieldPath": "commissionRate", "label": "API Komisyonu"},
                },
            ],
            db_name=self.db_path,
        )
        self.assertTrue(set_res.success, set_res.message)

        read = listing_pipeline.get_listings_from_db(api_account_ids=[1], db_name=self.db_path)
        self.assertTrue(read.success, read.message)
        item = (read.data or {}).get("items", [None])[0]
        self.assertIsNotNone(item)
        cost_items = {row["cost_key"]: row for row in (item.get("cost_items", []) or [])}
        self.assertEqual(cost_items["komisyon"]["source_type"], "db_field")
        self.assertEqual(cost_items["komisyon"]["source_config"], {"fieldPath": "commissionRate", "label": "API Komisyonu"})
        self.assertEqual(cost_items["komisyon"]["calculation_type"], "manual")
        self.assertIsNone(cost_items["komisyon"]["amount"])

    def test_set_listing_cost_items_uses_latest_snapshot_state_for_current_matches(self) -> None:
        seed = listing_pipeline.save_listings_to_db([self._sample_item(quantity=1, sale_price=50.0)], db_name=self.db_path)
        self.assertTrue(seed.success, seed.message)

        first_res = listing_pipeline.set_listing_cost_items(
            api_account_id=1,
            product_id="P-1001",
            cost_items=[
                {"cost_key": "paketleme", "amount": 12.5},
                {"cost_key": "komisyon", "amount": 8.0},
            ],
            db_name=self.db_path,
        )
        self.assertTrue(first_res.success, first_res.message)

        second_res = listing_pipeline.set_listing_cost_items(
            api_account_id=1,
            product_id="P-1001",
            cost_items=[
                {"cost_key": "komisyon", "amount": 9.0},
            ],
            db_name=self.db_path,
        )
        self.assertTrue(second_res.success, second_res.message)

        read = listing_pipeline.get_listings_from_db(api_account_ids=[1], db_name=self.db_path)
        self.assertTrue(read.success, read.message)
        item = (read.data or {}).get("items", [None])[0]
        self.assertIsNotNone(item)

        cost_items = {row["cost_key"]: row for row in (item.get("cost_items", []) or [])}
        self.assertEqual(sorted(cost_items.keys()), ["komisyon"])
        self.assertEqual(cost_items["komisyon"]["amount"], 9.0)

        engine = model_utils.get_engine(self.db_path)
        with Session(engine) as session:
            listing_id = session.exec(
                select(ListingProduct.pk)
                .where(ListingProduct.api_account_id == 1)
                .where(ListingProduct.product_id == "P-1001")
            ).first()
            rows = session.exec(
                select(ListingProductCostSnapshot)
                .where(ListingProductCostSnapshot.listing_id == int(listing_id))
                .order_by(ListingProductCostSnapshot.pk.asc())
            ).all()

        self.assertEqual([(row.cost_key, row.status) for row in rows], [
            ("paketleme", "append"),
            ("komisyon", "append"),
            ("komisyon", "set"),
            ("paketleme", "remove"),
        ])

    def test_listing_cost_snapshots_store_resolved_amounts(self) -> None:
        seed = listing_pipeline.save_listings_to_db([self._sample_item(quantity=2, sale_price=150.0)], db_name=self.db_path)
        self.assertTrue(seed.success, seed.message)

        set_res = listing_pipeline.set_listing_cost_items(
            api_account_id=1,
            product_id="P-1001",
            cost_items=[
                {"cost_key": "paketleme", "calculation_type": "manual", "amount": 5.0},
                {
                    "cost_key": "komisyon",
                    "source_type": "db_field",
                    "source_config": {"fieldPath": "commissionRate", "label": "API Komisyonu"},
                },
            ],
            db_name=self.db_path,
        )
        self.assertTrue(set_res.success, set_res.message)

        item = self._sample_item(quantity=2, sale_price=150.0)
        item["commissionRate"] = 10
        item["cost_items"] = [
            {"cost_key": "paketleme", "source_type": "manual_value", "source_config": {"amount": 5.0}},
            {"cost_key": "komisyon", "source_type": "db_field", "source_config": {"fieldPath": "commissionRate", "label": "API Komisyonu"}},
        ]
        estimation = listing_pipeline.estimate_listing_profit(
            item=item,
            stock_cost_map={},
            cost_card_map={
                "paketleme": {"costKey": "paketleme", "name": "Paketleme", "valueType": "numeric", "isVatIncluded": False, "vatRate": 20},
                "komisyon": {"costKey": "komisyon", "name": "Komisyon", "valueType": "percentage", "isVatIncluded": False, "vatRate": 20},
            },
            cargo_tariffs=[],
            platform_code="TRENDYOL",
        )
        self.assertIn("estimated_profit_detail", estimation)

        snap_res = listing_pipeline.sync_listing_cost_snapshots_for_item(item=item, estimation=estimation, db_name=self.db_path)
        self.assertTrue(snap_res.success, snap_res.message)

        engine = model_utils.get_engine(self.db_path)
        with Session(engine) as session:
            listing_id = session.exec(
                select(ListingProduct.pk)
                .where(ListingProduct.api_account_id == 1)
                .where(ListingProduct.product_id == "P-1001")
            ).first()
            rows = session.exec(
                select(ListingProductCostSnapshot)
                .where(ListingProductCostSnapshot.listing_id == int(listing_id))
                .order_by(ListingProductCostSnapshot.pk.asc())
            ).all()

        self.assertEqual(len(rows), 2)
        latest_rows = {str(row.cost_key): row for row in rows}
        self.assertEqual(sorted(latest_rows.keys()), ["komisyon", "paketleme"])
        self.assertEqual({str(row.status) for row in rows}, {"append"})
        self.assertEqual(int(latest_rows["komisyon"].cost_item_id or 0), 102)
        self.assertEqual(int(latest_rows["paketleme"].cost_item_id or 0), 101)
        self.assertAlmostEqual(float(latest_rows["komisyon"].resolved_amount or 0.0), 18.0)
        self.assertAlmostEqual(float(latest_rows["paketleme"].resolved_amount or 0.0), 6.0)

        read = listing_pipeline.get_listings_from_db(api_account_ids=[1], db_name=self.db_path)
        self.assertTrue(read.success, read.message)
        current_item = (read.data or {}).get("items", [None])[0]
        self.assertIsNotNone(current_item)
        current_cost_items = {row["cost_key"]: row for row in (current_item.get("cost_items", []) or [])}
        self.assertAlmostEqual(float(current_cost_items["komisyon"]["resolved_amount"] or 0.0), 18.0)
        self.assertAlmostEqual(float(current_cost_items["paketleme"]["resolved_amount"] or 0.0), 6.0)

        snap_res_again = listing_pipeline.sync_listing_cost_snapshots_for_item(item=item, estimation=estimation, db_name=self.db_path)
        self.assertTrue(snap_res_again.success, snap_res_again.message)

        with Session(engine) as session:
            rows_again = session.exec(
                select(ListingProductCostSnapshot)
                .where(ListingProductCostSnapshot.listing_id == int(listing_id))
                .order_by(ListingProductCostSnapshot.pk.asc())
            ).all()
        self.assertEqual(len(rows_again), 2)

    def test_match_cargo_tariff_for_listing_matches_platform_and_ranges(self) -> None:
        matched = listing_pipeline.match_cargo_tariff_for_listing(
            sale_price=199.99,
            dimensional_weight=2.0,
            platform_code="Trendyol",
            cargo_tariffs=[
                {
                    "tariffKey": "other-platform",
                    "platformCode": "HEPSIBURADA",
                    "minDesi": 0,
                    "maxDesi": 10,
                    "minSalePrice": 0,
                    "maxSalePrice": 500,
                    "amount": 8,
                    "isVatIncluded": True,
                    "isActive": True,
                },
                {
                    "tariffKey": "match-a",
                    "platformCode": "TRENDYOL",
                    "minDesi": 0,
                    "maxDesi": 10,
                    "minSalePrice": 0,
                    "maxSalePrice": 500,
                    "amount": 10,
                    "isVatIncluded": False,
                    "vatRate": 20,
                    "isActive": True,
                },
            ],
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched["tariffKey"], "match-a")
        self.assertAlmostEqual(matched["effectiveAmount"], 12.0)

    def test_match_cargo_tariff_for_listing_honors_selected_provider(self) -> None:
        matched = listing_pipeline.match_cargo_tariff_for_listing(
            sale_price=199.99,
            dimensional_weight=2.0,
            platform_code="Trendyol",
            cargo_provider_id=42,
            cargo_tariffs=[
                {
                    "tariffKey": "aras-match",
                    "platformCode": "TRENDYOL",
                    "cargo_provider_id": 41,
                    "cargoProviderCode": "ARAS",
                    "minDesi": 0,
                    "maxDesi": 10,
                    "minSalePrice": 0,
                    "maxSalePrice": 500,
                    "amount": 10,
                    "isVatIncluded": True,
                    "isActive": True,
                },
                {
                    "tariffKey": "yurtici-match",
                    "platformCode": "TRENDYOL",
                    "cargo_provider_id": 42,
                    "cargoProviderCode": "YURTICI",
                    "minDesi": 0,
                    "maxDesi": 10,
                    "minSalePrice": 0,
                    "maxSalePrice": 500,
                    "amount": 12,
                    "isVatIncluded": True,
                    "isActive": True,
                },
            ],
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched["tariffKey"], "yurtici-match")

    def test_estimate_listing_profit_uses_stock_commission_and_automatic_cargo(self) -> None:
        result = listing_pipeline.estimate_listing_profit(
            item={
                "salePrice": 100.0,
                "vatRate": 20.0,
                "dimensionalWeight": 1.5,
                "stock_items": [{"stock_item_id": 7, "qty": 2}],
                "cost_items": [
                    {"cost_key": "komisyon", "calculation_type": "manual", "amount": 20.0},
                    {"cost_key": "kargo", "calculation_type": "automatic"},
                ],
            },
            stock_cost_map={7: 15.0},
            stock_vat_rate_map={7: 20.0},
            cost_card_map={
                "komisyon": {
                    "valueType": "percentage",
                    "isVatIncluded": False,
                    "vatRate": 20,
                },
                "kargo": {
                    "valueType": "numeric",
                    "defaultMatchMode": "automatic",
                    "isVatIncluded": True,
                },
            },
            cargo_tariffs=[
                {
                    "tariffKey": "texmp-1",
                    "platformCode": "TRENDYOL",
                    "minDesi": 0,
                    "maxDesi": 10,
                    "minSalePrice": 0,
                    "maxSalePrice": 200,
                    "amount": 10.0,
                    "isVatIncluded": False,
                    "vatRate": 20,
                    "isActive": True,
                }
            ],
            platform_code="Trendyol",
        )
        self.assertTrue(result["estimated_profit_ready"])
        self.assertAlmostEqual(result["stock_cost_total"], 30.0)
        self.assertAlmostEqual(result["commission_cost"], 24.0)
        self.assertAlmostEqual(result["cargo_cost"], 12.0)
        self.assertAlmostEqual(result["purchase_vat"], 5.0)
        self.assertAlmostEqual(result["commission_vat"], 4.0)
        self.assertAlmostEqual(result["cargo_vat"], 2.0)
        self.assertAlmostEqual(result["sale_vat"], 100.0 / 120.0 * 20.0)
        self.assertAlmostEqual(result["net_vat"], (100.0 / 120.0 * 20.0) - 11.0)
        self.assertAlmostEqual(result["estimated_profit"], 28.3333333333, places=4)
        self.assertEqual(result["estimated_profit_text"], "28.33 TL")
        self.assertEqual(result["matched_cargo_tariff_key"], "texmp-1")
        self.assertEqual(len(result["estimated_profit_breakdown"]), 10)
        detail_costs = (result.get("estimated_profit_detail") or {}).get("applied_costs") or []
        self.assertEqual([row.get("key") for row in detail_costs], ["stock", "komisyon", "kargo"])
        self.assertEqual(result["estimated_profit_breakdown"][-1]["label"], "Tahmini Kar")
        self.assertEqual(result["estimated_profit_breakdown"][-2]["label"], "Nihai KDV")
        self.assertEqual(result["estimated_profit_breakdown"][-1]["value_text"], "28.33 TL")

    def test_estimate_listing_profit_honors_selected_cargo_provider_tariff_in_builtin_resolver(self) -> None:
        result = listing_pipeline.estimate_listing_profit(
            item={
                "salePrice": 114.99,
                "vatRate": 20.0,
                "dimensionalWeight": None,
                "stock_items": [{"stock_item_id": 7, "qty": 1}],
                "cost_items": [
                    {
                        "cost_key": "kargo",
                        "source_type": "builtin_resolver",
                        "source_config": {
                            "ruleKey": "cargo_amount_matcher",
                            "cargoProviderCode": "ARAS",
                            "cargoProviderName": "Aras Kargo Marketplace",
                        },
                    }
                ],
            },
            stock_cost_map={7: 15.0},
            stock_vat_rate_map={7: 20.0},
            cost_card_map={
                "kargo": {
                    "costKey": "kargo",
                    "name": "Kargo",
                    "valueType": "numeric",
                    "isVatIncluded": False,
                    "vatRate": 20.0,
                    "defaultSourceType": "builtin_resolver",
                    "defaultSourceConfig": {"ruleKey": "cargo_amount_matcher"},
                },
            },
            cargo_tariffs=[
                {
                    "tariffKey": "ptt-0",
                    "name": "PTT 0 Desi",
                    "platformCode": "TRENDYOL",
                    "cargoProviderCode": "PTTMP",
                    "cargoProviderName": "PTT Kargo Marketplace",
                    "minDesi": 0,
                    "maxDesi": 0,
                    "amount": 50.0,
                    "isVatIncluded": False,
                    "vatRate": 20.0,
                    "isActive": True,
                },
                {
                    "tariffKey": "aras-0",
                    "name": "Aras 0 Desi",
                    "platformCode": "TRENDYOL",
                    "cargoProviderCode": "ARASMP",
                    "cargoProviderName": "Aras Kargo Marketplace",
                    "minDesi": 0,
                    "maxDesi": 0,
                    "amount": 77.54,
                    "isVatIncluded": False,
                    "vatRate": 20.0,
                    "isActive": True,
                },
            ],
            platform_code="Trendyol",
        )
        self.assertTrue(result["estimated_profit_ready"])
        self.assertEqual(result["matched_cargo_tariff_key"], "aras-0")
        self.assertEqual(result["matched_cargo_tariff_name"], "Aras 0 Desi")
        self.assertAlmostEqual(result["cargo_cost"], 93.048, places=3)
        detail_costs = (result.get("estimated_profit_detail") or {}).get("applied_costs") or []
        cargo_row = next((row for row in detail_costs if row.get("key") == "kargo"), {})
        self.assertIn("Aras 0 Desi", str(cargo_row.get("note") or ""))
        self.assertIn("Aras Kargo Marketplace", str(cargo_row.get("note") or ""))
        self.assertNotIn("PTT", str(cargo_row.get("note") or ""))

    def test_estimate_listing_profit_supports_sale_quantity_multiplier(self) -> None:
        result = listing_pipeline.estimate_listing_profit(
            item={
                "salePrice": 100.0,
                "vatRate": 0.0,
                "dimensionalWeight": 1.0,
                "stock_items": [{"stock_item_id": 7, "qty": 1}],
                "cost_items": [
                    {"cost_key": "komisyon", "calculation_type": "manual", "amount": 10.0},
                    {"cost_key": "kargo", "calculation_type": "automatic"},
                    {"cost_key": "platform", "calculation_type": "manual", "amount": 5.0},
                ],
            },
            stock_cost_map={7: 15.0},
            stock_vat_rate_map={7: 0.0},
            cost_card_map={
                "komisyon": {
                    "valueType": "percentage",
                    "isVatIncluded": True,
                    "vatRate": 0.0,
                },
                "kargo": {
                    "valueType": "numeric",
                    "defaultMatchMode": "automatic",
                    "isVatIncluded": True,
                    "vatRate": 0.0,
                },
                "platform": {
                    "valueType": "numeric",
                    "isVatIncluded": True,
                    "vatRate": 0.0,
                },
            },
            cargo_tariffs=[
                {
                    "tariffKey": "desi-1",
                    "platformCode": "TRENDYOL",
                    "minDesi": 0,
                    "maxDesi": 1,
                    "minSalePrice": 0,
                    "maxSalePrice": None,
                    "amount": 10.0,
                    "isVatIncluded": True,
                    "vatRate": 0.0,
                    "isActive": True,
                },
                {
                    "tariffKey": "desi-3",
                    "platformCode": "TRENDYOL",
                    "minDesi": 3,
                    "maxDesi": 3,
                    "minSalePrice": 0,
                    "maxSalePrice": None,
                    "amount": 18.0,
                    "isVatIncluded": True,
                    "vatRate": 0.0,
                    "isActive": True,
                },
            ],
            platform_code="Trendyol",
            sale_quantity=3,
        )
        self.assertTrue(result["estimated_profit_ready"])
        self.assertEqual(result["sale_quantity"], 3.0)
        self.assertAlmostEqual(result["stock_cost_total"], 45.0)
        self.assertAlmostEqual(result["commission_cost"], 30.0)
        self.assertAlmostEqual(result["cargo_cost"], 18.0)
        self.assertAlmostEqual(result["other_cost_total"], 5.0)
        self.assertAlmostEqual(result["estimated_profit"], 202.0)
        detail = result.get("estimated_profit_detail") or {}
        summary = detail.get("summary") or {}
        self.assertEqual(summary.get("sale_quantity_text"), "3")
        self.assertEqual(summary.get("sale_price_text"), "300.00 TL")
        self.assertEqual(summary.get("dimensional_weight_text"), "3.00")
        self.assertEqual(result["matched_cargo_tariff_key"], "desi-3")

    def test_estimate_listing_profit_treats_legacy_percentage_mode_as_manual(self) -> None:
        result = listing_pipeline.estimate_listing_profit(
            item={
                "salePrice": 100.0,
                "vatRate": 0.0,
                "dimensionalWeight": 0.0,
                "stock_items": [{"stock_item_id": 7, "qty": 1}],
                "cost_items": [
                    {"cost_key": "komisyon", "calculation_type": "percentage", "amount": 20.0},
                ],
            },
            stock_cost_map={7: 15.0},
            stock_vat_rate_map={7: 0.0},
            cost_card_map={
                "komisyon": {
                    "valueType": "percentage",
                    "isVatIncluded": True,
                    "vatRate": 0.0,
                },
            },
            cargo_tariffs=[],
            platform_code="Trendyol",
        )
        self.assertTrue(result["estimated_profit_ready"])
        self.assertAlmostEqual(result["commission_cost"], 20.0)
        self.assertAlmostEqual(result["estimated_profit"], 65.0)
        self.assertFalse(any("desteklenmeyen" in str(x).casefold() for x in result["estimated_profit_missing_reasons"]))

    def test_estimate_listing_profit_supports_db_field_source(self) -> None:
        result = listing_pipeline.estimate_listing_profit(
            item={
                "salePrice": 100.0,
                "vatRate": 0.0,
                "commissionRate": 17.0,
                "stock_items": [{"stock_item_id": 7, "qty": 1}],
                "cost_items": [
                    {
                        "cost_key": "komisyon",
                        "source_type": "db_field",
                        "source_config": {"fieldPath": "commissionRate", "label": "API Komisyonu"},
                    },
                ],
            },
            stock_cost_map={7: 15.0},
            stock_vat_rate_map={7: 0.0},
            cost_card_map={
                "komisyon": {
                    "valueType": "percentage",
                    "isVatIncluded": True,
                    "vatRate": 0.0,
                },
            },
            cargo_tariffs=[],
            platform_code="Trendyol",
        )
        self.assertTrue(result["estimated_profit_ready"])
        self.assertAlmostEqual(result["commission_cost"], 17.0)
        self.assertAlmostEqual(result["estimated_profit"], 68.0)
        detail_costs = (result.get("estimated_profit_detail") or {}).get("applied_costs") or []
        self.assertEqual(detail_costs[1].get("source_type"), "db_field")
        self.assertEqual(detail_costs[1].get("note"), "API Komisyonu")

    def test_estimate_listing_profit_falls_back_to_zero_desi_when_weight_missing(self) -> None:
        result = listing_pipeline.estimate_listing_profit(
            item={
                "salePrice": 100.0,
                "vatRate": 0.0,
                "dimensionalWeight": None,
                "stock_items": [{"stock_item_id": 7, "qty": 1}],
                "cost_items": [
                    {"cost_key": "kargo", "calculation_type": "automatic"},
                ],
            },
            stock_cost_map={7: 15.0},
            stock_vat_rate_map={7: 0.0},
            cost_card_map={
                "kargo": {
                    "valueType": "numeric",
                    "defaultMatchMode": "automatic",
                    "isVatIncluded": True,
                },
            },
            cargo_tariffs=[
                {
                    "tariffKey": "desi-0",
                    "platformCode": "TRENDYOL",
                    "minDesi": 0,
                    "maxDesi": 0,
                    "minSalePrice": 0,
                    "maxSalePrice": None,
                    "amount": 10.0,
                    "isVatIncluded": True,
                    "vatRate": 0.0,
                    "isActive": True,
                }
            ],
            platform_code="Trendyol",
        )
        self.assertTrue(result["estimated_profit_ready"])
        self.assertAlmostEqual(result["cargo_cost"], 10.0)
        self.assertEqual(result["matched_cargo_tariff_key"], "desi-0")
        detail_costs = (result.get("estimated_profit_detail") or {}).get("applied_costs") or []
        self.assertEqual([row.get("key") for row in detail_costs], ["stock", "kargo"])

    def test_estimate_listing_profit_uses_stock_dimensions_for_total_desi(self) -> None:
        result = listing_pipeline.estimate_listing_profit(
            item={
                "salePrice": 100.0,
                "vatRate": 0.0,
                "dimensionalWeight": None,
                "stock_items": [{"stock_item_id": 7, "qty": 2}],
                "cost_items": [
                    {"cost_key": "kargo", "calculation_type": "automatic"},
                ],
            },
            stock_cost_map={7: 15.0},
            stock_vat_rate_map={7: 0.0},
            stock_dimension_map={
                7: {
                    "weight_kg": 0.4,
                    "length_cm": 30.0,
                    "width_cm": 20.0,
                    "height_cm": 15.0,
                }
            },
            cost_card_map={
                "kargo": {
                    "valueType": "numeric",
                    "defaultMatchMode": "automatic",
                    "isVatIncluded": True,
                },
            },
            cargo_tariffs=[
                {
                    "tariffKey": "desi-0",
                    "platformCode": "TRENDYOL",
                    "minDesi": 0,
                    "maxDesi": 0,
                    "minSalePrice": 0,
                    "maxSalePrice": None,
                    "amount": 5.0,
                    "isVatIncluded": True,
                    "vatRate": 0.0,
                    "isActive": True,
                },
                {
                    "tariffKey": "desi-6",
                    "platformCode": "TRENDYOL",
                    "minDesi": 6,
                    "maxDesi": 6,
                    "minSalePrice": 0,
                    "maxSalePrice": None,
                    "amount": 12.0,
                    "isVatIncluded": True,
                    "vatRate": 0.0,
                    "isActive": True,
                },
            ],
            platform_code="Trendyol",
        )
        self.assertTrue(result["estimated_profit_ready"])
        self.assertAlmostEqual(result["cargo_cost"], 12.0)
        self.assertEqual(result["matched_cargo_tariff_key"], "desi-6")
        summary = (result.get("estimated_profit_detail") or {}).get("summary") or {}
        self.assertEqual(summary.get("dimensional_weight_text"), "6.00")
        self.assertEqual(summary.get("stock_total_desi_text"), "6.00")
        self.assertEqual(summary.get("dimensional_weight_source"), "stock")

    def test_estimate_listing_profit_marks_missing_stock_vat_rate(self) -> None:
        result = listing_pipeline.estimate_listing_profit(
            item={
                "salePrice": 100.0,
                "vatRate": 20.0,
                "stock_items": [{"stock_item_id": 7, "qty": 1}],
                "cost_items": [],
            },
            stock_cost_map={7: 60.0},
            cost_card_map={},
            cargo_tariffs=[],
            platform_code="Trendyol",
        )
        self.assertFalse(result["estimated_profit_ready"])
        self.assertAlmostEqual(result["stock_cost_total"], 60.0)
        self.assertAlmostEqual(result["sale_vat"], 100.0 / 120.0 * 20.0)
        self.assertTrue(
            any("kdv" in str(x).casefold() and "stok kart" in str(x).casefold() for x in result["estimated_profit_missing_reasons"])
        )

    def test_estimate_listing_profit_reports_stock_cost_input_mode_in_detail(self) -> None:
        result = listing_pipeline.estimate_listing_profit(
            item={
                "salePrice": 120.0,
                "vatRate": 20.0,
                "stock_items": [{"stock_item_id": 7, "qty": 1}],
                "cost_items": [],
            },
            stock_cost_map={7: 120.0},
            stock_vat_rate_map={7: 20.0},
            stock_cost_meta_map={7: {"input_mode": "net"}},
            cost_card_map={},
            cargo_tariffs=[],
            platform_code="Trendyol",
        )
        detail_costs = (result.get("estimated_profit_detail") or {}).get("applied_costs") or []
        self.assertEqual(detail_costs[0].get("key"), "stock")
        self.assertIn("KDV hariç", str(detail_costs[0].get("note") or ""))

    def test_estimate_listing_profit_reports_missing_inputs(self) -> None:
        result = listing_pipeline.estimate_listing_profit(
            item={
                "salePrice": 100.0,
                "stock_items": [],
                "cost_items": [
                    {"cost_key": "kargo", "calculation_type": "automatic"},
                ],
            },
            stock_cost_map={},
            cost_card_map={
                "kargo": {
                    "valueType": "numeric",
                    "defaultMatchMode": "automatic",
                    "isVatIncluded": True,
                },
            },
            cargo_tariffs=[],
            platform_code="Trendyol",
        )
        self.assertFalse(result["estimated_profit_ready"])
        reasons = [str(x).casefold() for x in result["estimated_profit_missing_reasons"]]
        self.assertTrue(any(("urun" in x or "ürün" in x) and "bulun" in x for x in reasons))
        self.assertTrue(any("kargo" in x and "bulun" in x for x in reasons))
        self.assertEqual(result["estimated_profit_breakdown"][-1]["label"], "Tahmini Kar")
