from __future__ import annotations

from typing import Optional

from sqlmodel import Field, SQLModel, Session, select

from Core.db import model_registry  # noqa: F401
import Core.utils.model_utils as model_utils
from Core.utils.model_utils import create_records, get_engine
from Core.db.models import SOURCE_IDENTITY_TABLES, build_source_id
from Finance.models.trendyol.models import Brand
from Marketplaces.models.models import Marketplace
from tests.support.db_case import IsolatedDbTestCase


class WideInsertRow(SQLModel, table=True):
    pk: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    c01: str
    c02: str
    c03: str
    c04: str
    c05: str
    c06: str
    c07: str
    c08: str
    c09: str
    c10: str
    c11: str
    c12: str


class MixedColumnUpsertRow(SQLModel, table=True):
    pk: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    extra_value: Optional[float] = None


class TestModelUtilsAdaptiveChunking(IsolatedDbTestCase):
    def _rows(self, prefix: str) -> list[dict]:
        rows: list[dict] = []
        for idx in range(100):
            rows.append(
                {
                    "code": f"{prefix}-{idx}",
                    "c01": "v1",
                    "c02": "v2",
                    "c03": "v3",
                    "c04": "v4",
                    "c05": "v5",
                    "c06": "v6",
                    "c07": "v7",
                    "c08": "v8",
                    "c09": "v9",
                    "c10": "v10",
                    "c11": "v11",
                    "c12": "v12",
                }
            )
        return rows

    def test_create_records_ignore_splits_large_insert_batches(self) -> None:
        res = create_records(
            model=WideInsertRow,
            data_list=self._rows("ignore"),
            db_name=self.db_path,
            conflict_keys=["code"],
            mode="ignore",
            chunk_size=500,
        )
        self.assertTrue(res.success, res.message)
        self.assertEqual((res.data or {}).get("inserted"), 100)

    def test_create_records_update_splits_large_upsert_batches(self) -> None:
        first = create_records(
            model=WideInsertRow,
            data_list=self._rows("update"),
            db_name=self.db_path,
            conflict_keys=["code"],
            mode="ignore",
            chunk_size=500,
        )
        self.assertTrue(first.success, first.message)

        updated_rows = self._rows("update")
        for row in updated_rows:
            row["c12"] = "changed"

        res = create_records(
            model=WideInsertRow,
            data_list=updated_rows,
            db_name=self.db_path,
            conflict_keys=["code"],
            mode="update",
            chunk_size=500,
        )
        self.assertTrue(res.success, res.message)
        self.assertEqual((res.data or {}).get("affected"), 100)

    def test_create_records_preserves_fields_when_chunk_rows_have_different_columns(self) -> None:
        res = create_records(
            model=MixedColumnUpsertRow,
            data_list=[
                {"code": "row-1", "name": "first"},
                {"code": "row-2", "name": "second", "extra_value": 42.5},
            ],
            db_name=self.db_path,
            conflict_keys=["code"],
            mode="ignore",
            chunk_size=500,
        )
        self.assertTrue(res.success, res.message)

        with Session(get_engine(self.db_path)) as session:
            rows = session.exec(
                select(MixedColumnUpsertRow).order_by(MixedColumnUpsertRow.code)
            ).all()

        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0].extra_value)
        self.assertEqual(rows[1].extra_value, 42.5)

    def test_create_records_ignore_survives_unique_pk_collision_outside_conflict_target(self) -> None:
        first = create_records(
            model=MixedColumnUpsertRow,
            data_list=[{"pk": 1, "code": "row-1", "name": "first"}],
            db_name=self.db_path,
            conflict_keys=["code"],
            mode="ignore",
            chunk_size=500,
        )
        self.assertTrue(first.success, first.message)

        second = create_records(
            model=MixedColumnUpsertRow,
            data_list=[
                {"pk": 1, "code": "row-2", "name": "duplicate-pk"},
                {"pk": 2, "code": "row-3", "name": "second"},
            ],
            db_name=self.db_path,
            conflict_keys=["code"],
            mode="ignore",
            chunk_size=500,
        )
        self.assertTrue(second.success, second.message)
        self.assertEqual((second.data or {}).get("inserted"), 1)

        with Session(get_engine(self.db_path)) as session:
            rows = session.exec(
                select(MixedColumnUpsertRow).order_by(MixedColumnUpsertRow.pk)
            ).all()

        self.assertEqual([(row.pk, row.code) for row in rows], [(1, "row-1"), (2, "row-3")])

    def test_detect_sqlite_max_variables_parses_compile_option(self) -> None:
        class _FakeCursor:
            def execute(self, query: str):
                self.query = query
                return self

            def fetchall(self):
                return [("THREADSAFE=1",), ("MAX_VARIABLE_NUMBER=32766",)]

        self.assertEqual(model_utils._detect_sqlite_max_variables(_FakeCursor()), 32766)

    def test_create_records_populates_source_identity_for_builtin_and_user_models(self) -> None:
        marketplace_res = create_records(
            model=Marketplace,
            data_list=[{"code": "TRENDYOL", "label": "Trendyol"}],
            db_name=self.db_path,
            conflict_keys=["code"],
            mode="ignore",
        )
        self.assertTrue(marketplace_res.success, marketplace_res.message)

        brand_res = create_records(
            model=Brand,
            data_list=[{"name": "Demo Brand"}],
            db_name=self.db_path,
            conflict_keys=["name"],
            mode="ignore",
        )
        self.assertTrue(brand_res.success, brand_res.message)

        with Session(get_engine(self.db_path)) as session:
            marketplace_row = session.exec(select(Marketplace)).first()
            brand_row = session.exec(select(Brand)).first()

        self.assertIsNotNone(marketplace_row)
        self.assertEqual(getattr(marketplace_row, "sourceType", ""), "builtin")
        self.assertEqual(getattr(marketplace_row, "sourceId", None), build_source_id("marketplace", {"code": "TRENDYOL"}, source_type="builtin"))
        self.assertIsNotNone(getattr(marketplace_row, "created_at", None))
        self.assertIsNotNone(getattr(marketplace_row, "updated_at", None))
        self.assertIsNotNone(brand_row)
        self.assertEqual(getattr(brand_row, "sourceType", ""), "user")
        self.assertEqual(getattr(brand_row, "sourceId", None), build_source_id("brand", {"name": "Demo Brand"}, source_type="user"))
        self.assertIsNotNone(getattr(brand_row, "created_at", None))
        self.assertIsNotNone(getattr(brand_row, "updated_at", None))

    def test_all_source_identity_tables_have_audit_columns(self) -> None:
        for table_name in SOURCE_IDENTITY_TABLES:
            table = SQLModel.metadata.tables.get(table_name)
            self.assertIsNotNone(table, table_name)
            columns = {column.name for column in table.columns}
            self.assertIn("created_at", columns, table_name)
            self.assertIn("updated_at", columns, table_name)
