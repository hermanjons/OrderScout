"""Published schemas describe actual canonical business results, including nulls."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError
from sqlmodel import Session, SQLModel

from AI.processors import tools
from AI.processors.business_acceptance_fixtures import seed_business_fixture
from AI.processors.operation_catalog import operation_metadata_for_agent_tool
from AI.processors.task_runtime import _tool_result_field_names, _tool_source_contract
from Core.utils.model_utils import get_engine
from Finance.models.trendyol.models import FinanceManualTransaction
from Stock.constants.domain_constants import StockTxDirection, StockTxReason
from Stock.models.models import StockItem, StockTx


@pytest.fixture
def database(tmp_path):
    db = str(tmp_path / "business.sqlite3")
    seed_business_fixture(db, isolation_root=tmp_path)
    return db


def actual_result(operation, db, **arguments):
    tool = tools.available_tools()[operation]
    result = tool.handler(db_name=db, **arguments)
    assert result.success, result.message
    Draft202012Validator.check_schema(tool.result_schema)
    Draft202012Validator(tool.result_schema).validate(result.data)
    assert set(result.data) == set(tool.result_schema["properties"])
    return tool, result.data


def test_actual_mixed_currency_finance_schema_preserves_native_rows_and_nullable_scalars(database):
    tool, data = actual_result("finance.cashflow_summary", database, period="all")
    assert data["start_ms"] is data["end_ms"] is None
    assert data["currency"] is data["combined_net"] is None
    assert all(data[key] is None for key in ("marketplace_credit", "marketplace_debt", "marketplace_net", "manual_in", "manual_out"))
    assert {row["currency"]: row["combined_net"] for row in data["currency_totals"]} == {"TRY": 200, "USD": 20}
    assert data["transaction_type_counts"] == {"Sale": 2}
    assert "banka/kasa bakiyesi" in tool.description.casefold() and "currency_totals" in tool.description


def test_actual_stock_schema_describes_per_currency_valuation_and_native_unit_balances(database):
    tool, data = actual_result("stock.inventory_overview", database, limit=1)
    assert len(data["top_balances"]) == 1 and data["active_items"] == 3
    assert {row["currency"]: row["amount"] for row in data["stock_value_by_currency"]} == {"TRY": 400, "USD": 30}
    assert data["balance_by_unit"] == [{"unit": "adet", "balance": 7}]
    assert data["stock_valuation_complete"] is True and data["valuation_missing_items"] == 0
    assert "limit yalniz" in tool.description and "magaza/finans baglantisi kanitlamaz" in tool.description


def test_actual_mixed_physical_units_and_missing_cost_are_schema_valid_without_fabricated_total(database):
    with Session(get_engine(database)) as session:
        session.add_all([StockItem(pk=404, sku="KG-KNOWN", name="Known kg", unit="kg", is_active=True),
                         StockItem(pk=405, sku="KG-MISSING", name="Missing cost kg", unit="kg", is_active=True)])
        session.flush()
        session.add_all([StockTx(item_id=404, warehouse_id=301, direction=StockTxDirection.IN_, reason=StockTxReason.manual_in,
                                 qty=2, unit_cost=5, currency="EUR", unit_cost_input_mode="gross", company_id=201),
                         StockTx(item_id=405, warehouse_id=301, direction=StockTxDirection.IN_, reason=StockTxReason.manual_in,
                                 qty=3, unit_cost=None, currency="TRY", company_id=201)])
        session.commit()
    tool, data = actual_result("stock.inventory_overview", database, limit=50)
    assert data["total_balance"] is None
    assert {row["unit"]: row["balance"] for row in data["balance_by_unit"]} == {"adet": 7, "kg": 5}
    assert data["stock_valuation_complete"] is False and data["valuation_missing_items"] == 1
    missing = next(row for row in data["top_balances"] if row["sku"] == "KG-MISSING")
    assert missing["stock_value"] is None and missing["stock_value_currency"] == ""
    assert missing["valuation_missing_quantity"] == 3


def test_actual_empty_sources_and_single_currency_finance_are_schema_valid(tmp_path):
    db = str(tmp_path / "empty.sqlite3")
    SQLModel.metadata.create_all(get_engine(db))
    _, empty = actual_result("stock.inventory_overview", db)
    assert empty["total_balance"] == 0 and empty["stock_value_by_currency"] == [] and empty["top_balances"] == []
    _, empty_finance = actual_result("finance.cashflow_summary", db, period="all")
    assert empty_finance["currency"] == "TRY" and empty_finance["combined_net"] == 0
    with Session(get_engine(db)) as session:
        session.add(FinanceManualTransaction(transactionDate=1791710000000, direction="in", amount=100,
                                            currency="TRY", categoryName="Test receipt"))
        session.commit()
    _, single = actual_result("finance.cashflow_summary", db, period="all")
    assert single["currency"] == "TRY" and single["manual_in"] == single["combined_net"] == 100
    assert len(single["currency_totals"]) == 1


@pytest.mark.parametrize("operation,unsupported", [
    ("finance.cashflow_summary", {"inflows", "outflows", "net_amount", "transactions", "bank_balance_available"}),
    ("stock.inventory_overview", {"total_inventory_value", "currency", "items", "missing_cost_items", "valuation_method"}),
])
def test_catalog_and_compact_planner_contract_expose_only_actual_field_names(database, operation, unsupported):
    tool, actual = actual_result(operation, database)
    metadata = operation_metadata_for_agent_tool(tool)
    assert metadata.output_schema == tool.result_schema
    assert set(_tool_result_field_names(tool)) == set(actual)
    assert not unsupported.intersection(_tool_result_field_names(tool))
    contract = _tool_source_contract(tool)
    output = contract.split("; output_schema=", 1)[1].split("; input_source_requirements=", 1)[0]
    assert json.loads(output) == tool.result_schema
    for alias in unsupported:
        changed = deepcopy(actual)
        changed[alias] = 123
        with pytest.raises(ValidationError):
            Draft202012Validator(tool.result_schema).validate(changed)


@pytest.mark.parametrize("operation,path,value", [
    ("finance.cashflow_summary", ("currency_totals", 0, "combined_net"), "200"),
    ("stock.inventory_overview", ("top_balances", 0, "stock_value"), "400"),
    ("stock.inventory_overview", ("balance_by_unit", 0, "balance"), True),
])
def test_schema_rejects_text_or_boolean_amounts_in_native_result_rows(database, operation, path, value):
    tool, actual = actual_result(operation, database)
    changed = deepcopy(actual)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        Draft202012Validator(tool.result_schema).validate(changed)
