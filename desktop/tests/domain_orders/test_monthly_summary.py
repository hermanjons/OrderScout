from datetime import datetime
from unittest.mock import patch

from sqlmodel import Session

from Account.models.models import ApiAccount
from Core.utils.model_utils import get_engine
from Orders.models.trendyol.models import OrderData
from Orders.processors import monthly_summary
from Orders.views.actions import action_summarize_orders_by_month
from tests.support.db_case import IsolatedDbTestCase


def ms(value):
    return int(datetime.fromisoformat(value).timestamp() * 1000)


class TestMonthlyOrderSummary(IsolatedDbTestCase):
    def setUp(self):
        super().setUp()
        with Session(get_engine(self.db_path)) as session:
            session.add_all([
                ApiAccount(pk=1, account_id="MONTH-A", comp_name="A", platform="trendyol"),
                ApiAccount(pk=2, account_id="MONTH-B", comp_name="B", platform="trendyol"),
            ])
            session.commit()

    def add_orders(self, rows):
        with Session(get_engine(self.db_path)) as session:
            session.add_all([OrderData(**row) for row in rows])
            session.commit()

    def read(self, start="2026-01-01T00:00:00+03:00", end="2026-03-31T23:59:59.999+03:00", accounts=None):
        return action_summarize_orders_by_month(start_date_ms=ms(start), end_date_ms=ms(end),
                                               api_account_ids=accounts, db_name=self.db_path)

    def test_latest_snapshots_keep_cancellation_in_order_month_and_currencies_separate(self):
        self.add_orders([
            dict(orderNumber="SHARED", id=11, api_account_id=1, orderDate=ms("2026-01-10T10:00:00+03:00"),
                 lastModifiedDate=100, status="Created", totalPrice=999, currencyCode="TRY"),
            dict(orderNumber="SHARED", id=11, api_account_id=1, orderDate=ms("2026-01-10T10:00:00+03:00"),
                 lastModifiedDate=ms("2026-03-10T10:00:00+03:00"), shipmentPackageStatus="Cancelled",
                 packageTotalPrice=10.25, totalPrice=100, currencyCode="TRY"),
            dict(orderNumber="SHARED", id=11, api_account_id=2, orderDate=ms("2026-01-10T10:00:00+03:00"),
                 lastModifiedDate=200, status="Delivered", totalPrice=700, currencyCode="TRY"),
            dict(orderNumber="USD-JAN", id=12, api_account_id=1, orderDate=ms("2026-01-11T10:00:00+03:00"),
                 lastModifiedDate=300, status="Delivered", totalPrice=20.1, currencyCode="usd"),
            dict(orderNumber="TRY-MARCH", id=13, api_account_id=1, orderDate=ms("2026-03-02T10:00:00+03:00"),
                 lastModifiedDate=400, status="Returned", totalPrice=0.1, currencyCode="TRY"),
            dict(orderNumber="TRY-MARCH-2", id=14, api_account_id=1, orderDate=ms("2026-03-03T10:00:00+03:00"),
                 lastModifiedDate=500, status="Delivered", totalPrice=0.2, currencyCode="TRY"),
            dict(orderNumber="SIM-EXCLUDED", id=15, api_account_id=1, orderDate=ms("2026-01-12T10:00:00+03:00"),
                 lastModifiedDate=600, status="Cancelled", totalPrice=10000, currencyCode="TRY"),
        ])
        result = self.read(accounts=[1])
        assert result.success, result.message
        data = result.data
        assert data["total_orders"] == 4 and data["cancelled_orders"] == 1
        assert data["simulated_excluded"] == 1 and data["scope_account_ids"] == [1]
        assert data["api_account_ids"] == [1]
        assert data["currencies"] == ["TRY", "USD"]
        rows = {(row["month"], row["currency"]): row for row in data["rows"]}
        assert len(rows) == 6
        jan_try = rows["2026-01", "TRY"]
        assert (jan_try["total_orders"], jan_try["cancelled_orders"], jan_try["non_cancelled_orders"]) == (1, 1, 0)
        assert jan_try["total_amount"] == jan_try["cancelled_amount"] == 10.25
        assert jan_try["non_cancelled_amount"] == 0
        assert rows["2026-01", "USD"]["non_cancelled_amount"] == 20.1
        assert rows["2026-02", "TRY"]["total_orders"] == 0
        assert rows["2026-02", "USD"]["total_amount"] == 0
        assert rows["2026-03", "TRY"]["non_cancelled_amount"] == 0.3
        assert data["cancellation_basis"] == "latest_order_status_in_order_date_month"
        all_accounts = self.read()
        assert all_accounts.success and all_accounts.data["total_orders"] == 5
        assert next(row for row in all_accounts.data["rows"] if (row["month"], row["currency"]) == ("2026-01", "TRY"))["total_orders"] == 2

    def test_inclusive_partial_month_boundaries_and_local_midnight(self):
        start = ms("2026-01-15T00:00:00+03:00")
        end = ms("2026-03-10T23:59:59.999+03:00")
        dates = [start - 1, start, ms("2026-01-31T20:59:59.999+00:00"),
                 ms("2026-01-31T21:00:00+00:00"), end, end + 1]
        self.add_orders([dict(orderNumber=f"BOUND-{index}", id=index + 100, api_account_id=1,
            orderDate=value, lastModifiedDate=index + 1, status="Delivered", totalPrice=1, currencyCode="TRY")
            for index, value in enumerate(dates)])
        result = self.read("2026-01-15T00:00:00+03:00", "2026-03-10T23:59:59.999+03:00", [1])
        assert result.success, result.message
        assert [(row["month"], row["total_orders"]) for row in result.data["rows"]] == [
            ("2026-01", 2), ("2026-02", 1), ("2026-03", 1)]
        assert result.data["scope"]["start_date_ms"] == start
        assert result.data["scope"]["end_date_ms"] == end
        assert result.data["timezone"] == "UTC+03:00"
        assert [(row["month"], row["start_date"], row["end_date"]) for row in result.data["partial_months"]] == [
            ("2026-01", "2026-01-15", "2026-01-31"), ("2026-03", "2026-03-01", "2026-03-10")]
        assert result.data["partial_months"][0]["start_ms"] == start
        assert result.data["partial_months"][-1]["end_ms"] == end

    def test_partial_month_facts_cover_leap_years_and_same_month_without_duplicates(self):
        full = self.read("2024-02-01T00:00:00+03:00", "2024-02-29T23:59:59.999+03:00", [1])
        assert full.success and full.data["partial_months"] == []
        partial = self.read("2024-02-10T00:00:00+03:00", "2024-02-20T23:59:59.999+03:00", [1])
        assert partial.success
        assert len(partial.data["partial_months"]) == 1
        assert partial.data["partial_months"][0]["start_date"] == "2024-02-10"
        assert partial.data["partial_months"][0]["end_date"] == "2024-02-20"

    def test_zero_missing_amount_and_missing_currency_are_distinct(self):
        self.add_orders([
            dict(orderNumber="ZERO", id=201, api_account_id=1, orderDate=ms("2026-01-01T00:00:00+03:00"),
                 lastModifiedDate=1, status="Delivered", packageTotalPrice=0, totalPrice=999, currencyCode="TRY"),
            dict(orderNumber="NO-AMOUNT", id=202, api_account_id=1, orderDate=ms("2026-01-02T00:00:00+03:00"),
                 lastModifiedDate=2, status="Cancelled", currencyCode="TRY"),
            dict(orderNumber="NO-CURRENCY", id=203, api_account_id=1, orderDate=ms("2026-01-03T00:00:00+03:00"),
                 lastModifiedDate=3, status="Delivered", totalPrice=25, currencyCode=None),
        ])
        result = self.read(accounts=[1])
        assert result.success, result.message
        rows = {(row["month"], row["currency"]): row for row in result.data["rows"]}
        assert rows["2026-01", "TRY"]["non_cancelled_amount"] == 0
        assert rows["2026-01", "TRY"]["total_amount"] is None
        assert rows["2026-01", "TRY"]["cancelled_amount"] is None
        assert rows["2026-01", "TRY"]["cancelled_missing_amount_orders"] == 1
        assert rows["2026-01", None]["total_amount"] is None
        assert rows["2026-01", None]["total_orders"] == 1
        assert result.data["missing_currency_orders"] == result.data["missing_amount_orders"] == 1

    def test_empty_scope_preserves_months_without_inventing_a_currency(self):
        result = self.read(accounts=[1])
        assert result.success and result.data["complete"]
        assert result.data["currencies"] == [] and result.data["total_orders"] == 0
        assert [row["month"] for row in result.data["rows"]] == ["2026-01", "2026-02", "2026-03"]
        assert all(row["total_orders"] == 0 and row["currency"] is None for row in result.data["rows"])

    def test_cancellation_uses_exact_canonical_status_instead_of_substring(self):
        statuses = ["Cancelled", "Unsupplied", "NotCancelled", "cancellation_pending", "Returned"]
        self.add_orders([dict(orderNumber=f"STATUS-{index}", id=index + 250, api_account_id=1,
            orderDate=ms("2026-01-05T10:00:00+03:00"), lastModifiedDate=index + 1,
            status=status, totalPrice=10, currencyCode="TRY") for index, status in enumerate(statuses)])
        result = self.read(accounts=[1])
        assert result.success, result.message
        january = result.data["rows"][0]
        assert january["total_orders"] == 5
        assert january["cancelled_orders"] == 2 and january["cancelled_amount"] == 20
        assert january["non_cancelled_orders"] == 3 and january["non_cancelled_amount"] == 30

    def test_invalid_account_ids_are_rejected_before_the_domain_read(self):
        for accounts in ([True], [1.5], ["1"], [0], [-1], [None], "1"):
            with patch.object(monthly_summary, "get_latest_orders_filtered") as read:
                result = self.read(accounts=accounts)
            assert not result.success
            assert result.data["reason"] == "monthly_positive_account_ids_required"
            read.assert_not_called()

    def test_manual_action_and_model_adapter_call_the_same_domain_reader(self):
        from AI.runtime.orders_monthly_contracts import orders_monthly_summary, monthly_order_summary_tool

        self.add_orders([dict(orderNumber="ALIAS", id=301, api_account_id=1,
            orderDate=ms("2026-01-31T21:00:00+00:00"), lastModifiedDate=1,
            status="Unsupplied", totalPrice=12, currencyCode="TRY")])
        with patch.object(monthly_summary, "get_latest_orders_filtered", wraps=monthly_summary.get_latest_orders_filtered) as read:
            manual = self.read(accounts=[1])
            model = orders_monthly_summary(start_date="2026-01-01", end_date="2026-03-31",
                                           api_account_ids=[1], db_name=self.db_path)
        assert manual.success and model.success
        assert read.call_count == 2
        assert model.data["rows"] == manual.data["rows"]
        assert model.data["source_snapshot_hash"] == manual.data["source_snapshot_hash"]
        assert model.data["cancelled_orders"] == 1
        assert monthly_order_summary_tool().canonical_callable == "Orders.views.actions.action_summarize_orders_by_month"

    def test_invalid_dates_do_not_silently_read_today(self):
        from AI.runtime.orders_monthly_contracts import orders_monthly_summary

        for first, last in (("2026-02-30", "2026-03-31"), ("2026-03-31", "2026-01-01"),
                            ("2026-01-01-extra", "2026-03-31")):
            with patch.object(monthly_summary, "get_latest_orders_filtered") as read:
                result = orders_monthly_summary(start_date=first, end_date=last, db_name=self.db_path)
            assert not result.success
            read.assert_not_called()

    def test_source_fingerprint_changes_when_amount_changes(self):
        self.add_orders([dict(orderNumber="HASH", id=401, api_account_id=1,
            orderDate=ms("2026-01-01T00:00:00+03:00"), lastModifiedDate=1,
            status="Delivered", totalPrice=12, currencyCode="TRY")])
        before = self.read(accounts=[1])
        with Session(get_engine(self.db_path)) as session:
            row = session.get(OrderData, 1)
            row.totalPrice = 13
            session.add(row)
            session.commit()
        after = self.read(accounts=[1])
        assert before.success and after.success
        assert before.data["source_snapshot_hash"] != after.data["source_snapshot_hash"]
        assert before.data["source_revision"] == after.data["source_revision"]
