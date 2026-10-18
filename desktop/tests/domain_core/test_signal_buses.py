from __future__ import annotations

import unittest

from Account.signals.signals import account_signals
from Listing.signals.signals import listing_signals
from Logistics.signals.signals import logistics_signals
from Marketplaces.signals.signals import marketplace_signals
from Orders.signals.signals import order_signals
from Stock.signals.signals import stock_signals


class TestSignalBuses(unittest.TestCase):
    def test_account_company_changed_emits(self) -> None:
        called: list[int] = []

        def _slot() -> None:
            called.append(1)

        account_signals.company_changed.connect(_slot)
        try:
            account_signals.company_changed.emit()
        finally:
            account_signals.company_changed.disconnect(_slot)

        self.assertEqual(len(called), 1)

    def test_listing_signals_emit_expected_payloads(self) -> None:
        badge_payloads: list[int] = []
        cleared: list[int] = []

        def _on_badge_changed(value: int) -> None:
            badge_payloads.append(int(value))

        def _on_badge_cleared() -> None:
            cleared.append(1)

        listing_signals.badge_changed.connect(_on_badge_changed)
        listing_signals.badge_cleared.connect(_on_badge_cleared)
        try:
            listing_signals.badge_changed.emit(3)
            listing_signals.badge_cleared.emit()
        finally:
            listing_signals.badge_changed.disconnect(_on_badge_changed)
            listing_signals.badge_cleared.disconnect(_on_badge_cleared)

        self.assertEqual(badge_payloads, [3])
        self.assertEqual(len(cleared), 1)

    def test_order_signals_emit_expected_payloads(self) -> None:
        changed_count: list[int] = []
        loaded_payloads: list[list] = []
        persisted_payloads: list[dict] = []

        def _on_changed() -> None:
            changed_count.append(1)

        def _on_loaded(payload: list) -> None:
            loaded_payloads.append(payload)

        def _on_persisted(payload: dict) -> None:
            persisted_payloads.append(payload)

        order_signals.orders_changed.connect(_on_changed)
        order_signals.orders_loaded.connect(_on_loaded)
        order_signals.orders_persisted.connect(_on_persisted)
        try:
            order_signals.orders_changed.emit()
            order_signals.orders_loaded.emit([{"orderNumber": "T-1"}])
            order_signals.orders_persisted.emit({"source": "test", "order_item_list": []})
        finally:
            order_signals.orders_changed.disconnect(_on_changed)
            order_signals.orders_loaded.disconnect(_on_loaded)
            order_signals.orders_persisted.disconnect(_on_persisted)

        self.assertEqual(len(changed_count), 1)
        self.assertEqual(loaded_payloads, [[{"orderNumber": "T-1"}]])
        self.assertEqual(persisted_payloads, [{"source": "test", "order_item_list": []}])

    def test_stock_signals_emit_expected_payloads(self) -> None:
        created_ids: list[int] = []
        refreshed: list[int] = []
        quick_access_payloads: list[tuple[str, int]] = []

        def _on_item_created(item_id: int) -> None:
            created_ids.append(int(item_id))

        def _on_refreshed() -> None:
            refreshed.append(1)

        def _on_quick_access(section: str, delta: int) -> None:
            quick_access_payloads.append((str(section), int(delta)))

        stock_signals.item_created.connect(_on_item_created)
        stock_signals.refreshed.connect(_on_refreshed)
        stock_signals.quick_access_changed.connect(_on_quick_access)
        try:
            stock_signals.item_created.emit(42)
            stock_signals.refreshed.emit()
            stock_signals.quick_access_changed.emit("items", 2)
        finally:
            stock_signals.item_created.disconnect(_on_item_created)
            stock_signals.refreshed.disconnect(_on_refreshed)
            stock_signals.quick_access_changed.disconnect(_on_quick_access)

        self.assertEqual(created_ids, [42])
        self.assertEqual(len(refreshed), 1)
        self.assertEqual(quick_access_payloads, [("items", 2)])

    def test_marketplace_signals_emit_expected_payloads(self) -> None:
        changed_count: list[int] = []

        def _on_changed() -> None:
            changed_count.append(1)

        marketplace_signals.marketplaces_changed.connect(_on_changed)
        try:
            marketplace_signals.marketplaces_changed.emit()
        finally:
            marketplace_signals.marketplaces_changed.disconnect(_on_changed)

        self.assertEqual(len(changed_count), 1)

    def test_logistics_signals_emit_expected_payloads(self) -> None:
        provider_events: list[int] = []
        tariff_events: list[int] = []

        def _on_providers_changed() -> None:
            provider_events.append(1)

        def _on_tariffs_changed() -> None:
            tariff_events.append(1)

        logistics_signals.cargo_providers_changed.connect(_on_providers_changed)
        logistics_signals.cargo_tariffs_changed.connect(_on_tariffs_changed)
        try:
            logistics_signals.cargo_providers_changed.emit()
            logistics_signals.cargo_tariffs_changed.emit()
        finally:
            logistics_signals.cargo_providers_changed.disconnect(_on_providers_changed)
            logistics_signals.cargo_tariffs_changed.disconnect(_on_tariffs_changed)

        self.assertEqual(len(provider_events), 1)
        self.assertEqual(len(tariff_events), 1)


if __name__ == "__main__":
    unittest.main()
