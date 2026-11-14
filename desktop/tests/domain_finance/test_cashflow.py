from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlmodel import Session

from Account.models.models import ApiAccount
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result
from Finance.models.trendyol.models import FinanceManualTransaction, FinanceTransaction
from Finance.processors import cashflow
from Finance.views import actions
from tests.support.db_case import IsolatedDbTestCase


class TestCashflowDatabase(IsolatedDbTestCase):
    def _seed(self):
        with Session(get_engine(self.db_path)) as session:
            session.add_all([
                ApiAccount(pk=1, account_id="cashflow-1", comp_name="First", platform="trendyol"),
                ApiAccount(pk=2, account_id="cashflow-2", comp_name="Second", platform="trendyol"),
            ])
            session.commit()
            session.add_all([
                FinanceTransaction(api_account_id=1, serviceKey="settlements", recordId="start",
                                   transactionDate=1000, transactionType="Sale", currency="TRY",
                                   credit=100, debt=20, netAmount=80),
                FinanceTransaction(api_account_id=2, serviceKey="settlements", recordId="end",
                                   transactionDate=2000, transactionType="Refund", currency="TRY",
                                   credit=25, debt=5, netAmount=20),
                FinanceTransaction(serviceKey="settlements", recordId="before", transactionDate=999,
                                   currency="TRY", credit=1000, debt=0, netAmount=1000),
                FinanceTransaction(serviceKey="settlements", recordId="after", transactionDate=2001,
                                   currency="TRY", credit=1000, debt=0, netAmount=1000),
                FinanceManualTransaction(transactionDate=1000, direction="income", amount=10,
                                         currency="TRY", categoryName="Income"),
                FinanceManualTransaction(transactionDate=2000, direction="out", amount=3,
                                         currency="TRY", categoryKey="rent"),
                FinanceManualTransaction(transactionDate=1500, direction="income", amount=1000,
                                         currency="TRY", isDeleted=True),
                FinanceManualTransaction(transactionDate=2001, direction="income", amount=1000, currency="TRY"),
            ])
            session.commit()

    def test_date_scope_is_inclusive_across_accounts_and_deleted_manual_rows_are_excluded(self):
        self._seed()
        result = cashflow.read_cashflow_summary(db_name=self.db_path, start_ms=1000, end_ms=2000)
        assert result.success, result.message
        assert result.data == {
            "currency": "TRY", "marketplace_credit": 125.0, "marketplace_debt": 25.0,
            "marketplace_net": 100.0, "manual_in": 10.0, "manual_out": 3.0,
            "combined_net": 107.0, "manual_by_category": {"Income": 10.0, "rent": -3.0},
            "transaction_type_counts": {"Sale": 1, "Refund": 1},
            "currency_totals": [{
                "currency": "TRY", "marketplace_credit": 125.0, "marketplace_debt": 25.0,
                "marketplace_net": 100.0, "manual_in": 10.0, "manual_out": 3.0,
                "combined_net": 107.0, "manual_by_category": {"Income": 10.0, "rent": -3.0},
            }],
        }
        assert cashflow.read_cashflow_summary(db_name=self.db_path, end_ms=999).data["combined_net"] == 1000
        assert cashflow.read_cashflow_summary(db_name=self.db_path, start_ms=2001).data["combined_net"] == 2000

    def test_manual_ui_and_cashflow_reader_share_the_same_amount_aggregation(self):
        self._seed()
        original = cashflow.transaction_amount_totals
        observed = []

        def aggregate(records):
            totals = original(records)
            observed.append(totals)
            return totals

        with patch.object(cashflow, "transaction_amount_totals", side_effect=aggregate), patch.object(
            actions, "transaction_amount_totals", side_effect=aggregate
        ):
            domain = cashflow.read_cashflow_summary(db_name=self.db_path)
            ui = actions.load_finance_transactions_from_db(db_name=self.db_path, limit=None)
        assert domain.success and ui.success, (domain.message, ui.message)
        ui_rows = ui.data["records"]
        assert len(ui_rows) == 7
        assert len(observed) == 2
        assert observed[1]["netAmount"] == domain.data["combined_net"] == 3107
        assert "3.107" in ui.data["summary_text"] or "3107" in ui.data["summary_text"]
        assert original(row for row in ui_rows if row["sourceKind"] != "manual")["netAmount"] == domain.data["marketplace_net"]

    def test_cashflow_read_is_complete_beyond_the_ui_record_limit(self):
        with Session(get_engine(self.db_path)) as session:
            session.add_all([
                FinanceTransaction(serviceKey="settlements", recordId=f"row-{index}", transactionDate=1000,
                                   transactionType="Sale", currency="TRY", credit=1, debt=0, netAmount=1)
                for index in range(5001)
            ])
            session.commit()
        result = cashflow.read_cashflow_summary(db_name=self.db_path)
        assert result.success, result.message
        assert result.data["combined_net"] == 5001
        assert result.data["transaction_type_counts"] == {"Sale": 5001}


@pytest.mark.parametrize("failed_kind", ["transaction", "manual_transaction"])
def test_repository_failures_preserve_the_exact_result_and_diagnostics(monkeypatch, failed_kind):
    failure = Result.fail("Finance read failed", close_dialog=False,
                          data={"code": "cashflow_source_unavailable", "retryable": True})

    def read(kind, **kwargs):
        return failure if kind == failed_kind else Result.ok("read", data={"records": []})

    monkeypatch.setattr(cashflow.agentic_repository, "list_records", read)
    assert cashflow.read_cashflow_summary(db_name="unused.sqlite3") is failure


def test_currency_groups_never_produce_a_mixed_or_unknown_scalar(monkeypatch):
    rows = [
        SimpleNamespace(currency="TRY", credit=100, debt=10, netAmount=90),
        SimpleNamespace(currency="USD", credit=10, debt=0, netAmount=10),
        SimpleNamespace(currency=None, credit=2, debt=0, netAmount=2),
    ]
    manual_rows = [SimpleNamespace(currency="USD", direction="in", amount=5, categoryKey="deposit")]
    monkeypatch.setattr(cashflow.agentic_repository, "list_records", lambda kind, **kwargs:
        Result.ok("read", data={"records": rows if kind == "transaction" else manual_rows}))
    result = cashflow.read_cashflow_summary()
    assert result.success
    assert result.data["currency"] is None and result.data["combined_net"] is None
    assert {row["currency"]: row["combined_net"] for row in result.data["currency_totals"]} == {
        "TRY": 90, "USD": 15, "UNSPECIFIED": 2,
    }


def test_empty_currency_scope_retains_zero_without_guessing_existing_missing_currency(monkeypatch):
    monkeypatch.setattr(cashflow.agentic_repository, "list_records", lambda *args, **kwargs:
        Result.ok("read", data={"records": []}))
    result = cashflow.read_cashflow_summary()
    assert result.success and result.data["currency"] == "TRY" and result.data["combined_net"] == 0
