"""Low-stock boundary semantics come from the shared Stock domain."""
from __future__ import annotations

from sqlmodel import Session

from Core.utils.model_utils import get_engine
from Stock.constants.domain_constants import StockTxDirection, StockTxReason
from Stock.models import StockItem, StockTx, Warehouse
from Stock.processors.inventory_summary import read_low_stock_summary
from tests.support.db_case import IsolatedDbTestCase


class TestInventorySummary(IsolatedDbTestCase):
    def test_low_stock_includes_minimum_equality_and_nonpositive_without_minimum(self):
        with Session(get_engine(self.db_path)) as session:
            warehouse = Warehouse(name="Test Warehouse")
            session.add(warehouse)
            session.flush()
            for sku, balance, minimum, active in (
                ("BELOW", 4, 5, True),
                ("EQUAL", 5, 5, True),
                ("ABOVE", 6, 5, True),
                ("NO-MIN-POSITIVE", 1, None, True),
                ("NO-MIN-ZERO", 0, None, True),
                ("NO-MIN-NEGATIVE", -2, None, True),
                ("ZERO-MIN", 0, 0, True),
                ("INACTIVE", 0, 5, False),
            ):
                item = StockItem(sku=sku, name=sku, min_stock=minimum, is_active=active,
                                 safety_stock=999, reorder_point=999)
                session.add(item)
                session.flush()
                if balance:
                    session.add(StockTx(
                        item_id=item.pk, warehouse_id=warehouse.pk,
                        direction=StockTxDirection.IN_ if balance > 0 else StockTxDirection.OUT,
                        reason=StockTxReason.manual_in if balance > 0 else StockTxReason.manual_out,
                        qty=abs(balance),
                    ))
            session.commit()

        result = read_low_stock_summary(db_name=self.db_path)

        self.assertTrue(result.success, result.message)
        self.assertEqual(result.data["total_low_stock"], 5)
        self.assertEqual(
            {row["sku"]: (row["balance"], row["threshold"], row["gap"]) for row in result.data["items"]},
            {
                "BELOW": (4.0, 5.0, 1.0),
                "EQUAL": (5.0, 5.0, 0.0),
                "NO-MIN-ZERO": (0.0, 0.0, 0.0),
                "NO-MIN-NEGATIVE": (-2.0, 0.0, 2.0),
                "ZERO-MIN": (0.0, 0.0, 0.0),
            },
        )
        self.assertEqual(result.data["threshold_rule"], "stock_minimum_or_zero_balance")
        self.assertEqual(result.data["threshold_comparison"], "less_than_or_equal")
        self.assertIn("bakiye <= minimum", result.data["rule_description"])
        self.assertIn("eşit bakiye de dahildir", result.data["rule_description"])
        policy = result.data["low_stock_policy"]
        self.assertEqual(policy["evaluated_fields"], ["balance", "min_stock"])
        self.assertIn("safety_stock", policy["stored_fields_not_evaluated_by_this_read"])
        self.assertIn("reorder_point", policy["stored_fields_not_evaluated_by_this_read"])
        self.assertFalse(policy["notification_or_reorder_execution_proven"])
