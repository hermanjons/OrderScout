from __future__ import annotations

import unittest
from unittest.mock import patch

from Feedback.processors.pipeline import Result
import Labels.views.actions as label_actions


class TestLabelActions(unittest.TestCase):
    def test_extract_order_numbers_deduplicates_in_selection_order(self) -> None:
        class Order:
            def __init__(self, order_number: str) -> None:
                self.orderNumber = order_number

        class ListWidget:
            def get_selected_orders(self):
                return [Order("ORD-1"), Order("ORD-2"), Order("ORD-1"), Order(" ")]

        res = label_actions.extract_order_numbers_from_list_widget(ListWidget())

        self.assertTrue(res.success, res.message)
        self.assertEqual((res.data or {}).get("order_numbers"), ["ORD-1", "ORD-2"])

    def test_extract_order_numbers_rejects_widget_without_selection_api(self) -> None:
        res = label_actions.extract_order_numbers_from_list_widget(object())
        self.assertFalse(res.success)
        self.assertIn("get_selected_orders", str(res.message))

    def test_extract_order_numbers_carries_account_scoped_references(self) -> None:
        class Order:
            def __init__(self, order_number: str, api_account_id: int) -> None:
                self.orderNumber = order_number
                self.api_account_id = api_account_id

        class ListWidget:
            def get_selected_orders(self):
                return [Order("ORD-SAME", 11), Order("ORD-SAME", 22)]

        res = label_actions.extract_order_numbers_from_list_widget(ListWidget())

        self.assertTrue(res.success, res.message)
        self.assertEqual((res.data or {}).get("order_numbers"), ["ORD-SAME"])
        self.assertEqual(
            (res.data or {}).get("order_refs"),
            [
                {"orderNumber": "ORD-SAME", "api_account_id": 11},
                {"orderNumber": "ORD-SAME", "api_account_id": 22},
            ],
        )
        self.assertTrue((res.data or {}).get("order_refs_complete"))

    def test_ensure_any_selected_orders_rejects_empty_selection(self) -> None:
        class ListWidget:
            def get_selected_orders(self):
                return []

        res = label_actions.ensure_any_selected_orders(ListWidget())
        self.assertFalse(res.success)
        self.assertIn("sipari", str(res.message).casefold())

    def test_mark_orders_extracted_uses_account_aware_filters(self) -> None:
        label_result = Result.ok(
            data={
                "order_refs": [
                    {"orderNumber": "ORD-1", "api_account_id": 11},
                    {"orderNumber": "ORD-1", "api_account_id": 22},
                ]
            }
        )

        with patch.object(
            label_actions,
            "update_records",
            side_effect=[
                Result.ok(data={"affected": 1}),
                Result.ok(data={"affected": 1}),
            ],
        ) as mocked_update:
            res = label_actions.mark_orders_extracted_from_label_result(label_result)

        self.assertTrue(res.success, res.message)
        self.assertEqual(mocked_update.call_count, 2)

        filters = [c.kwargs["filters"] for c in mocked_update.call_args_list]
        self.assertIn({"orderNumber": "ORD-1", "api_account_id": 11}, filters)
        self.assertIn({"orderNumber": "ORD-1", "api_account_id": 22}, filters)

    def test_mark_orders_extracted_requires_order_refs(self) -> None:
        label_result = Result.ok(data={"order_numbers": ["ORD-9"]})

        with patch.object(
            label_actions,
            "update_records",
            return_value=Result.ok(data={"affected": 1}),
        ) as mocked_update:
            res = label_actions.mark_orders_extracted_from_label_result(label_result)

        self.assertFalse(res.success)
        self.assertIn("order_refs", str(res.message))
        self.assertEqual(mocked_update.call_count, 0)


if __name__ == "__main__":
    unittest.main()
