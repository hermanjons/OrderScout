from __future__ import annotations

import unittest

from Finance.processors.catalog import finance_builtin_cost_item_records


class FinanceCatalogTests(unittest.TestCase):
    def test_builtin_cost_items_include_packaging_and_commission_label(self) -> None:
        records = finance_builtin_cost_item_records()
        by_key = {str(row.get("costKey") or "").strip(): dict(row or {}) for row in records}

        self.assertIn("paketleme", by_key)
        self.assertEqual(str((by_key.get("paketleme") or {}).get("name") or ""), "Paketleme")
        self.assertEqual(str((by_key.get("komisyon") or {}).get("name") or ""), "Komisyon bedeli")


if __name__ == "__main__":
    unittest.main()
