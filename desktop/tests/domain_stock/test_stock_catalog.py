from __future__ import annotations

from unittest import TestCase

from Stock.constants.constants import ITEM_TYPE_OPTIONS
from Stock.constants.catalog_constants import item_type_options, sub_group_map, upper_group_names, upper_group_rows


class TestStockCatalog(TestCase):
    def test_item_type_options_catalog_matches_constants_export(self) -> None:
        self.assertEqual(ITEM_TYPE_OPTIONS, item_type_options())
        self.assertTrue(ITEM_TYPE_OPTIONS)

    def test_upper_group_rows_have_unique_names(self) -> None:
        rows = upper_group_rows()
        names = [str((row or {}).get("name") or "").strip() for row in rows]

        self.assertTrue(names)
        self.assertEqual(len(names), len({name.casefold() for name in names}))
        self.assertEqual(upper_group_names(), names)

    def test_sub_group_map_uses_known_upper_groups(self) -> None:
        upper_group_lookup = {name.casefold() for name in upper_group_names()}
        data = sub_group_map()

        self.assertTrue(data)
        for category, rows in data.items():
            self.assertIn(str(category).strip().casefold(), upper_group_lookup)
            self.assertTrue(rows)
