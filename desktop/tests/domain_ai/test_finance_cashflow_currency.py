from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from AI.processors import agent, tools
from Feedback.processors.pipeline import Result


def _cashflow(finance_rows=(), manual_rows=(), *, scalar=False):
    def list_records(kind, **_kwargs):
        rows = finance_rows if kind == "transaction" else manual_rows
        return Result.ok("read", data={"records": list(rows)})

    with patch.object(tools.finance_repo, "list_records", side_effect=list_records), patch.object(
        tools, "_period_range", return_value=(None, None, "Test")
    ):
        function = tools.finance_cashflow_net if scalar else tools.finance_cashflow_summary
        return function()


@pytest.mark.parametrize("currency", ["TRY", "USD"])
def test_cashflow_preserves_single_currency(currency):
    result = _cashflow(
        [SimpleNamespace(currency=currency, credit=100, debt=20, netAmount=80)],
        [SimpleNamespace(currency=currency, amount=10, direction="out", categoryKey="rent")],
    )

    assert result.success, result.message
    assert result.data["currency"] == currency
    assert result.data["combined_net"] == 70
    assert result.data["currency_totals"][0]["combined_net"] == 70
    assert f"70.00 {currency}" in result.message
    assert "banka bakiyesi" in result.message
    scalar = _cashflow(
        [SimpleNamespace(currency=currency, credit=100, debt=20, netAmount=80)],
        [SimpleNamespace(currency=currency, amount=10, direction="out", categoryKey="rent")],
        scalar=True,
    )
    assert scalar.success and scalar.data["amount"] == 70
    assert scalar.data["currency"] == currency
    assert "tahsilat gerceklesmesi" in scalar.message


def test_cashflow_keeps_mixed_currencies_separate_and_rejects_single_amount():
    rows = [
        SimpleNamespace(currency="TRY", credit=100, debt=0, netAmount=100),
        SimpleNamespace(currency="USD", credit=10, debt=0, netAmount=10),
    ]
    result = _cashflow(rows)

    assert result.success, result.message
    assert result.data["combined_net"] is None
    assert result.data["currency"] is None
    assert {row["currency"]: row["combined_net"] for row in result.data["currency_totals"]} == {
        "TRY": 100,
        "USD": 10,
    }
    assert "110.00 TRY" not in result.message
    assert not _cashflow(rows, scalar=True).success
    visible = agent._deterministic_single_tool_answer(
        "finance.cashflow_summary", result.data, result.message
    )
    assert "100 TRY" in visible and "10 USD" in visible
    assert "110 TRY" not in visible and "Net nakit: 0 TRY" not in visible


def test_cashflow_does_not_guess_missing_currency_and_keeps_empty_legacy_zero():
    missing = _cashflow([SimpleNamespace(currency=None, credit=10, debt=0, netAmount=10)])
    assert missing.success and missing.data["combined_net"] is None
    assert missing.data["currency_totals"][0]["currency"] == "UNSPECIFIED"
    assert not _cashflow([SimpleNamespace(currency=None, netAmount=10)], scalar=True).success

    empty = _cashflow()
    assert empty.success and empty.data["combined_net"] == 0
    assert empty.data["currency"] == "TRY"


def test_cashflow_repository_failure_is_not_treated_as_empty():
    with patch.object(tools.finance_repo, "list_records", return_value=Result.fail("db failed")), patch.object(
        tools, "_period_range", return_value=(None, None, "Test")
    ):
        result = tools.finance_cashflow_summary()
    assert not result.success
