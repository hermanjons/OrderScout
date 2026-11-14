"""Shipment-status observations use the same labels as the manual order UI."""
import pytest
from sqlmodel import Session

from Account.models.models import ApiAccount
from Core.utils.model_utils import get_engine
from Orders.constants.trendyol.constants import TRENDYOL_ORDER_STATUS_ALIASES, TRENDYOL_STATUS_LABELS
from Orders.models.trendyol.models import OrderData
from Orders.processors.agentic_repository import summarize_orders
from Orders.processors.statuses import order_status_label_for_code
from Orders.views import actions
from tests.support.db_case import IsolatedDbTestCase


@pytest.mark.parametrize("code, expected", [
    *TRENDYOL_STATUS_LABELS.items(),
    *((alias, TRENDYOL_STATUS_LABELS[canonical]) for alias, canonical in TRENDYOL_ORDER_STATUS_ALIASES.items()),
    (" InVOiced ", "Faturalandı"), (" readyToSHIP ", "Kargoya Hazır"),
    (" uNSUPPLIED ", "İptal Edildi"),
    ("", "-"), (None, "-"), ("  ", "-"),
    ("UnDeliveredAndReturned", "Un Delivered And Returned"),
    ("external_code-V2", "external code V2"),
])
def test_shared_and_manual_order_labels_keep_existing_alias_case_and_fallback_behavior(code, expected):
    assert order_status_label_for_code(code) == expected
    assert actions.order_status_label_for_code(code) == expected


class TestOrderStatusSummary(IsolatedDbTestCase):
    def test_summary_labels_only_observed_latest_statuses_in_selected_account(self):
        with Session(get_engine(self.db_path)) as session:
            session.add_all([
                ApiAccount(pk=1, account_id="STATUS-A", comp_name="A", platform="trendyol"),
                ApiAccount(pk=2, account_id="STATUS-B", comp_name="B", platform="trendyol"),
            ])
            session.commit()
            session.add_all([
                OrderData(id=101, orderNumber="INVOICE", api_account_id=1, orderDate=1000,
                    lastModifiedDate=1000, shipmentPackageStatus="Shipped", totalPrice=10, currencyCode="TRY"),
                OrderData(id=101, orderNumber="INVOICE", api_account_id=1, orderDate=1000,
                    lastModifiedDate=2000, shipmentPackageStatus="Invoiced", totalPrice=10, currencyCode="TRY"),
                OrderData(id=102, orderNumber="READY", api_account_id=1, orderDate=1000,
                    lastModifiedDate=2000, shipmentPackageStatus="ReadyToShip", totalPrice=20, currencyCode="TRY"),
                OrderData(id=103, orderNumber="UNKNOWN", api_account_id=1, orderDate=1000,
                    lastModifiedDate=2000, shipmentPackageStatus="AwaitingPartnerX", totalPrice=30, currencyCode="TRY"),
                OrderData(id=104, orderNumber="OTHER", api_account_id=2, orderDate=1000,
                    lastModifiedDate=2000, shipmentPackageStatus="Delivered", totalPrice=100, currencyCode="TRY"),
            ])
            session.commit()

        result = summarize_orders(api_account_ids=[1], db_name=self.db_path)

        assert result.success, result.message
        assert result.data["status_counts"] == {"Invoiced": 1, "ReadyToShip": 1, "AwaitingPartnerX": 1}
        assert result.data["status_labels"] == {
            "Invoiced": "Faturalandı", "ReadyToShip": "Kargoya Hazır", "AwaitingPartnerX": "Awaiting Partner X"}
        assert result.data["total_orders"] == 3 and result.data["cancelled_orders"] == 0
        assert result.data["estimated_revenue"] == 60 and result.data["scope_account_ids"] == [1]

    def test_empty_summary_does_not_add_unobserved_status_labels(self):
        result = summarize_orders(db_name=self.db_path)
        assert result.success, result.message
        assert result.data["status_counts"] == result.data["status_labels"] == {}
