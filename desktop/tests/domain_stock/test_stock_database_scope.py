"""The same stock domain operations keep each caller's database binding."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from sqlmodel import Session, SQLModel

from Core.utils.model_utils import get_engine
from Finance.models.trendyol.models import Brand
from Stock.processors import pipeline as stock
from tests.support.db_case import IsolatedDbTestCase


class TestStockDatabaseScope(IsolatedDbTestCase):
    def setUp(self):
        super().setUp()
        self.other = str(Path(self.db_path).with_name("other.sqlite3"))
        SQLModel.metadata.create_all(get_engine(self.other))

    def test_concurrent_creates_and_brand_lookup_stay_in_own_database(self):
        for database, brand_id in ((self.db_path, 111), (self.other, 222)):
            with Session(get_engine(database)) as session:
                session.add(Brand(pk=brand_id, name="Scope Brand"))
                session.commit()
        barrier = Barrier(2)
        default_database = stock.DB_NAME

        def create(database):
            with stock.database_scope(database):
                barrier.wait(timeout=15)
                created = stock.create_item(sku="SCOPED", name="Ürün", brand="Scope Brand")
                assert created.success, created.message
                return stock.list_items().data["records"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            left = pool.submit(create, self.db_path)
            right = pool.submit(create, self.other)
            left_rows, right_rows = left.result(timeout=30), right.result(timeout=30)
        self.assertEqual([(row.sku, row.brand_id) for row in left_rows], [("SCOPED", 111)])
        self.assertEqual([(row.sku, row.brand_id) for row in right_rows], [("SCOPED", 222)])
        self.assertEqual(stock.DB_NAME, default_database)
        self.assertIsNone(stock._DATABASE_SCOPE.get())

    def test_nested_scope_restores_after_failure_and_explicit_read_overrides_it(self):
        with patch.object(stock, "DB_NAME", self.db_path):
            with stock.database_scope(self.other):
                self.assertTrue(stock.create_item(sku="OTHER", name="Diğer").success)
                try:
                    with stock.database_scope(self.db_path):
                        self.assertTrue(stock.create_item(sku="DEFAULT", name="Varsayılan").success)
                        raise ValueError("exercise restoration")
                except ValueError:
                    pass
                self.assertEqual([row.sku for row in stock.list_items().data["records"]], ["OTHER"])
                self.assertEqual([row.sku for row in stock.list_items(db_name=self.db_path).data["records"]], ["DEFAULT"])
            self.assertEqual([row.sku for row in stock.list_items().data["records"]], ["DEFAULT"])
