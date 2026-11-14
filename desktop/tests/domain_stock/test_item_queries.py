"""Catalog tools must observe the manual inventory engine, including its precision."""
from unittest.mock import patch

from jsonschema import Draft202012Validator
from sqlmodel import Session

from AI.processors import tools
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result
from Stock.models.models import StockItem
from Stock.processors import item_queries, pipeline
from Stock.views import actions
from tests.support.db_case import IsolatedDbTestCase


class TestItemQueries(IsolatedDbTestCase):
    def seed(self):
        with Session(get_engine(self.db_path)) as session:
            session.add_all([
                StockItem(pk=1, sku="KG-İNCİR", name="İncir Çekirdeği", unit="kg", barcode="8690001",
                          brand="Çığ", min_stock=None, location_code="Şube-Üst"),
                StockItem(pk=2, sku="OTHER", name="KG İncir Kutusu", min_stock=0),
                StockItem(pk=3, sku="HIDDEN", name="İncir Eski", is_active=False),
            ])
            session.commit()
        with pipeline.database_scope(self.db_path):
            for name in ("Birinci", "İkinci"):
                result = pipeline.create_warehouse(name=name)
                self.assertTrue(result.success, result.message)
            warehouses = pipeline.list_warehouses().data["records"]
            for index, qty in enumerate((0.004, 0.125)):
                result = pipeline.manual_in(item_id=1, warehouse_id=warehouses[index].pk,
                                            qty=qty, unit_cost=20)
                self.assertTrue(result.success, result.message)
        return [row.pk for row in warehouses]

    def test_ai_and_manual_actions_use_identical_balances_without_money_rounding(self):
        self.seed()
        manual = actions.action_list_item_balances(db_name=self.db_path)
        expected = {row["item"].pk: row["on_hand"] for row in manual.data["records"]}
        query = actions.action_list_items_with_balances(db_name=self.db_path)
        listed = tools.stock_items_list(db_name=self.db_path)
        searched = tools.stock_search(db_name=self.db_path, query="incir cekirdegi")
        for result in (query, listed, searched):
            self.assertTrue(result.success, result.message)
            item = next(row for row in result.data["items"] if row["item_id"] == 1)
            self.assertEqual(item["balance"], expected[1])
            self.assertAlmostEqual(item["balance"], 0.129)
            self.assertIsNone(item["min_stock"])
            self.assertEqual(item["unit"], "kg")
            self.assertNotIn("HIDDEN", [row["sku"] for row in result.data["items"]])
        self.assertEqual(query.data, {key: value for key, value in listed.data.items() if key != "tool"})
        self.assertEqual(next(row for row in listed.data["items"] if row["item_id"] == 2)["min_stock"], 0)

    def test_search_ranks_exact_identity_and_normalizes_turkish_fields(self):
        self.seed()
        for query in ("KG-INCIR", "8690001", "incir cekirdegi", "cig", "sube ust"):
            result = item_queries.query_items_with_balances(db_name=self.db_path, query=query)
            self.assertTrue(result.success, result.message)
            self.assertEqual(result.data["items"][0]["item_id"], 1)
        missing = item_queries.query_items_with_balances(db_name=self.db_path, query="unmatched")
        self.assertTrue(missing.success)
        self.assertEqual(missing.data["total"], 0)

    def test_warehouse_scope_uses_the_same_domain_snapshot(self):
        warehouses = self.seed()
        result = actions.action_list_items_with_balances(db_name=self.db_path,
                                                         warehouse_id=warehouses[0], query="8690001")
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.data["items"][0]["balance"], 0.004)

    def test_pagination_has_no_hidden_hundred_card_ceiling_or_duplicate_pages(self):
        with Session(get_engine(self.db_path)) as session:
            session.add_all([StockItem(sku=f"SKU-{index:03}", name=f"Ürün {index:03}") for index in range(105)])
            session.commit()
        first = tools.stock_items_list(db_name=self.db_path, limit=100)
        last = tools.stock_items_list(db_name=self.db_path, limit=100, offset=100)
        self.assertTrue(first.success, first.message)
        self.assertTrue(last.success, last.message)
        self.assertEqual((first.data["total"], first.data["count"], first.data["has_more"]), (105, 100, True))
        self.assertEqual((last.data["total"], last.data["count"], last.data["has_more"]), (105, 5, False))
        self.assertEqual(len({row["item_id"] for row in first.data["items"] + last.data["items"]}), 105)

    def test_domain_failure_reaches_ui_and_ai_without_becoming_an_empty_catalog(self):
        failure = Result.fail("Stok değerleme kaynağı okunamadı.", data={"reason": "source_unavailable"})
        with patch.object(pipeline, "list_item_balances", return_value=failure):
            for read in (actions.action_list_items_with_balances, tools.stock_items_list, tools.stock_search):
                self.assertIs(read(db_name=self.db_path), failure)
        with patch.object(pipeline, "_engine", side_effect=OSError("Veritabanı açılamadı.")):
            result = tools.stock_item_count(db_name=self.db_path)
            self.assertFalse(result.success)
            self.assertIsInstance(result.error, OSError)

    def test_actual_results_match_catalog_schemas_and_card_counts(self):
        self.seed()
        registry = tools.registered_tools()
        for name in ("stock.search", "stock.items_list", "stock.item_count"):
            tool = registry[name]
            result = tool.handler(db_name=self.db_path)
            self.assertTrue(result.success, result.message)
            self.assertTrue(tool.canonical_callable.startswith("Stock.processors.item_queries."))
            Draft202012Validator(tool.result_schema).validate(result.data)
            self.assertEqual(set(result.data), set(tool.result_schema["properties"]))
        count = tools.stock_item_count(db_name=self.db_path).data
        self.assertEqual((count["total"], count["active"], count["count"]), (3, 2, 2))
