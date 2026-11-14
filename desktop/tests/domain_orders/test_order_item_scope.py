from sqlmodel import Session

from Account.models.models import ApiAccount
from Core.utils.model_utils import get_engine
from Orders.models.trendyol.models import OrderData, OrderItem
from Orders.processors.trendyol.pipeline import get_latest_order_items_by_numbers
from tests.support.db_case import IsolatedDbTestCase


class TestOrderItemScope(IsolatedDbTestCase):
    def test_latest_items_keep_unassigned_and_named_account_snapshots_separate(self):
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="SCOPE", comp_name="Named account", platform="trendyol"))
            session.commit()
            session.add_all([
                OrderData(pk=701, orderNumber="SAME", id=901, api_account_id=None, lastModifiedDate=1000),
                OrderData(pk=702, orderNumber="SAME", id=901, api_account_id=1, lastModifiedDate=2000),
                OrderData(pk=703, orderNumber="SAME", id=901, api_account_id=None, lastModifiedDate=500),
                OrderData(pk=704, orderNumber="LEGACY", id=902, api_account_id=None, lastModifiedDate=3000),
            ])
            session.commit()
            session.add_all([
                OrderItem(orderNumber="SAME", order_data_pk=701, order_data_id=901, api_account_id=None,
                          snapshotLastModifiedDate=1000, quantity=2, lineId=1),
                OrderItem(orderNumber="SAME", order_data_pk=702, order_data_id=901, api_account_id=1,
                          snapshotLastModifiedDate=2000, quantity=99, lineId=1),
                OrderItem(orderNumber="SAME", order_data_pk=703, order_data_id=901, api_account_id=None,
                          snapshotLastModifiedDate=500, quantity=8, lineId=1),
                OrderItem(orderNumber="LEGACY", order_data_pk=None, order_data_id=902, api_account_id=None,
                          snapshotLastModifiedDate=3000, quantity=3, lineId=1),
            ])
            session.commit()
        result = get_latest_order_items_by_numbers(["SAME", "LEGACY"], db_name=self.db_path)
        assert result.success, result.message
        assert {(row.orderNumber, row.api_account_id, row.quantity) for row in result.data["items"]} == {
            ("SAME", None, 2), ("SAME", 1, 99), ("LEGACY", None, 3),
        }
        scoped = get_latest_order_items_by_numbers(["SAME", "LEGACY"], api_account_ids=[1], db_name=self.db_path)
        assert scoped.success, scoped.message
        assert [(row.api_account_id, row.quantity) for row in scoped.data["items"]] == [(1, 99)]
