"""Marketplace ordered units are explicit and cannot inherit Stock units."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, select

from AI.processors import tools
from AI.processors.analysis_operations import calculate_observations
from AI.processors.observation_projection import source_projection_hash
from AI.processors.observation_analysis_evidence import verified_observation_calculations
from AI.processors.semantic_verifier import _calculation_period_relation_problems
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from Core.utils.model_utils import get_engine
from Account.models.models import ApiAccount
from Orders.models.trendyol.models import OrderData, OrderHeader, OrderItem
from Orders.processors.agentic_repository import summarize_order_item_sales
from Stock.constants.domain_constants import StockTxDirection, StockTxReason
from Stock.models.models import StockItem, StockTx, Warehouse


@pytest.fixture
def sources(tmp_path):
    db = str(tmp_path / "ordered-quantity.sqlite3")
    engine = get_engine(db)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(ApiAccount(pk=101, account_id="fixture", comp_name="Quantity Fixture", platform="TRENDYOL",
                               extra_config={"environment": "stage"}, api_key="", api_secret=""))
        session.add(StockItem(pk=1, sku="SKU-A", name="Physical item", unit="adet", is_active=True))
        session.add(Warehouse(pk=1, name="Quantity fixture", code="UNIT"))
        session.flush()
        session.add(StockTx(item_id=1, warehouse_id=1, direction=StockTxDirection.IN_, reason=StockTxReason.manual_in,
                            qty=4, unit_cost=10, currency="TRY", occurred_at=datetime(2026, 10, 11, 12, 0)))
        header = OrderHeader(orderNumber="ORDER-FOUR", api_account_id=101)
        session.add(header)
        session.flush()
        order = OrderData(orderNumber="ORDER-FOUR", api_account_id=101, order_header_id=header.pk, id=1001,
                          status="Delivered", shipmentPackageStatus="Delivered", orderDate=1791710000000,
                          lastModifiedDate=1791710000000, currencyCode="TRY", totalPrice=40)
        session.add(order)
        session.flush()
        session.add(OrderItem(orderNumber=order.orderNumber, api_account_id=101, order_header_id=header.pk,
                              order_data_pk=order.pk, order_data_id=order.id, snapshotLastModifiedDate=order.lastModifiedDate,
                              id=2001, lineId=3001, quantity=4, sku="SKU-A", productName="Marketplace item",
                              currencyCode="TRY", lineGrossAmount=40, price=10))
        session.commit()
    orders = tools.orders_item_sales_summary(db_name=db, period="all", api_account_ids=[101])
    stock = tools.stock_inventory_overview(db_name=db)
    assert orders.success and stock.success, (orders.message, stock.message)
    yield db, orders.data, stock.data
    engine.dispose()


def _source(identity, operation, result):
    return {"source_id": identity, "source_step_id": f"read_{identity}", "operation_id": operation, "result": result}


def _subtract(sources, left, right):
    return calculate_observations(sources=sources, calculations=[{"calculation_id": "difference", "operator": "subtract",
        "operands": [{"source_id": left[0], "path": left[1]}, {"source_id": right[0], "path": right[1]}]}])


def test_one_canonical_order_line_with_quantity_four_contributes_four_marketplace_units(sources):
    db, orders, _ = sources
    with Session(get_engine(db)) as session:
        assert len(session.exec(select(OrderItem)).all()) == 1
    manual = summarize_order_item_sales(api_account_ids=[101], db_name=db)
    assert manual.success
    assert manual.data["order_count"] == 1 and manual.data["total_quantity"] == 4
    assert len(manual.data["rows"]) == 1 and manual.data["rows"][0]["quantity"] == 4
    assert manual.data["quantity_unit"] == manual.data["rows"][0]["quantity_unit"] == "marketplace_item"
    assert "not order-line count or Stock physical units" in manual.data["quantity_unit_description"]
    assert orders["quantity_unit"] == "marketplace_item" and orders["rows"][0]["quantity_unit"] == "marketplace_item"
    assert orders["total_quantity"] == 4 and orders["total_gross_amount"] == 40
    assert manual.data["source_snapshot_hash"] == orders["source_snapshot_hash"]


def test_generic_arithmetic_consumes_explicit_root_and_row_marketplace_units_and_hashes(sources):
    _, orders, _ = sources
    source = _source("orders", "orders.item_sales_summary", orders)
    result = _subtract([source], ("orders", "total_quantity"), ("orders", "rows.0.quantity"))
    assert result.success, result.data
    calculation = result.data["verified_calculations"][0]
    assert calculation["result_value"] == 0 and calculation["unit"] == "marketplace_item"
    assert calculation["result_kind"] == "count"
    assert {row["unit"] for row in calculation["operand_receipts"]} == {"marketplace_item"}
    assert calculation["source_receipts"][0]["source_result_hash"] == source_projection_hash(orders)
    changed = deepcopy(orders)
    changed["quantity_unit"] = "adet"
    assert source_projection_hash(changed) != calculation["source_receipts"][0]["source_result_hash"]
    rejected = _subtract([_source("orders", "orders.item_sales_summary", changed)],
                         ("orders", "total_quantity"), ("orders", "rows.0.quantity"))
    assert not rejected.success and rejected.data["reason"] == "analysis_incompatible_units"


def test_marketplace_average_sale_amount_keeps_the_ordered_unit_distinct(sources):
    _, orders, _ = sources
    result = calculate_observations(sources=[_source("orders", "orders.item_sales_summary", orders)],
        calculations=[{"calculation_id": "per_ordered_unit", "operator": "divide",
                       "operands": [{"source_id": "orders", "path": "total_gross_amount"},
                                    {"source_id": "orders", "path": "total_quantity"}]}])
    assert result.success, result.data
    calculation = result.data["verified_calculations"][0]
    assert calculation["result_value"] == 10
    assert calculation["unit"] == "TRY/marketplace_item"
    assert calculation["result_kind"] == "amount_per_quantity"


@pytest.mark.parametrize("operator", ["subtract", "add", "compare"])
def test_actual_stock_adet_cannot_be_equated_or_added_to_marketplace_ordered_units(sources, operator):
    _, orders, stock = sources
    assert stock["balance_by_unit"] == [{"unit": "adet", "balance": 4.0}]
    bound = [_source("orders", "orders.item_sales_summary", orders), _source("stock", "stock.inventory_overview", stock)]
    left = {"source_id": "orders", "path": "total_quantity"}
    right = {"source_id": "stock", "path": "balance_by_unit.0.balance"}
    if operator == "compare":
        result = calculate_observations(sources=bound, comparisons=[{"comparison_id": "same", "operator": "equals", "left": left, "right": right}])
    else:
        result = calculate_observations(sources=bound, calculations=[{"calculation_id": "mixed", "operator": operator, "operands": [left, right]}])
    assert not result.success and result.data["reason"] == "analysis_incompatible_units"
    assert result.data["verified"] is False


def test_missing_marketplace_unit_still_fails_closed_instead_of_assuming_adet(sources):
    _, orders, _ = sources
    old = deepcopy(orders)
    old.pop("quantity_unit")
    old["rows"][0].pop("quantity_unit")
    rejected = _subtract([_source("orders", "orders.item_sales_summary", old)],
                         ("orders", "total_quantity"), ("orders", "rows.0.quantity"))
    assert not rejected.success and rejected.data["reason"] == "analysis_quantity_unit_unknown"


def test_empty_canonical_marketplace_summary_retains_quantity_semantics(sources):
    db, _, _ = sources
    empty = summarize_order_item_sales(order_numbers=["MISSING"], db_name=db)
    assert empty.success and empty.data["rows"] == [] and empty.data["total_quantity"] == 0
    assert empty.data["quantity_unit"] == "marketplace_item"


def _actual_adjacent_reads(db):
    current_day = datetime.fromtimestamp(1791710000000 / 1000, tools.TZ_GMT3).date()
    previous_day = current_day - timedelta(days=1)
    results = []
    for day in (previous_day, current_day):
        result = tools.orders_item_sales_summary(db_name=db, api_account_ids=[101],
            start_date=day.isoformat(), end_date=day.isoformat())
        assert result.success, result.message
        results.append(result.data)
    return results


def test_actual_zero_previous_period_retains_exact_requested_bounds_and_hash_identity(sources):
    db, _, _ = sources
    prior, current = _actual_adjacent_reads(db)
    assert prior["total_quantity"] == 0 and prior["rows"] == []
    assert current["total_quantity"] == 4
    assert prior["end_date_ms"] + 1 == current["start_date_ms"]
    assert prior["end_date_ms"] - prior["start_date_ms"] == current["end_date_ms"] - current["start_date_ms"]
    manual = summarize_order_item_sales(api_account_ids=[101], start_date_ms=prior["start_date_ms"],
                                        end_date_ms=prior["end_date_ms"], db_name=db)
    assert manual.success and manual.data["rows"] == []
    assert manual.data["start_date_ms"] == prior["start_date_ms"] and manual.data["end_date_ms"] == prior["end_date_ms"]
    assert manual.data["source_snapshot_hash"] == prior["source_snapshot_hash"]
    previous_empty = summarize_order_item_sales(api_account_ids=[101], start_date_ms=prior["start_date_ms"] - 86400000,
                                                end_date_ms=prior["end_date_ms"] - 86400000, db_name=db)
    assert previous_empty.success and previous_empty.data["total_quantity"] == 0
    assert previous_empty.data["source_snapshot_hash"] != prior["source_snapshot_hash"]


@pytest.mark.parametrize("reverse_pair", [False, True])
def test_actual_zero_prior_and_current_quantity_prove_source_bound_equal_adjacent_periods(sources, reverse_pair):
    db, _, _ = sources
    prior, current = _actual_adjacent_reads(db)
    bound = [_source("prior", "orders.item_sales_summary", prior), _source("current", "orders.item_sales_summary", current)]
    result = _subtract(bound, ("current", "total_quantity"), ("prior", "total_quantity"))
    assert result.success, result.data
    state = AgentSessionState(goal="Compare current ordered quantity with the previous equal period", active_domain="general")
    for source in bound:
        state.completed_steps.append(AgentTaskStep(index=len(state.completed_steps) + 1, step_id=source["source_step_id"],
            prompt="Actually read canonical period", status="completed", verification_status="observed",
            tool_names=[source["operation_id"]], result_data={"tool_result": source["result"]}))
    state.completed_steps.append(AgentTaskStep(index=3, step_id="difference", prompt="Compute source-bound difference",
        status="completed", verification_status="observed", tool_names=["analysis.calculate"], result_data={"tool_result": result.data}))
    verified = verified_observation_calculations(state)
    assert len(verified) == 1
    assert verified[0]["result_value"] == 4 and verified[0]["unit"] == "marketplace_item"
    assert verified[0]["result_kind"] == "count"
    assert verified[0]["source_receipts"][0]["source_result_hash"] == source_projection_hash(prior)
    left, right = ("read_prior", "read_current") if reverse_pair else ("read_current", "read_prior")
    verdict = {"period_relations": [{"left_source_step_id": left, "right_source_step_id": right, "relation": "previous_equal_period"}]}
    periods = []
    assert _calculation_period_relation_problems(verdict, verified, observed_relations=periods) == []
    assert periods[0]["prior_source_step_id"] == "read_prior"
    assert periods[0]["current_source_step_id"] == "read_current"


def test_contradictory_numeric_period_alias_does_not_verify_the_actual_zero_period_comparison(sources):
    db, _, _ = sources
    prior, current = _actual_adjacent_reads(db)
    changed = deepcopy(prior)
    changed.update({"start_ms": changed["start_date_ms"] + 1, "end_ms": changed["end_date_ms"]})
    result = _subtract([_source("prior", "orders.item_sales_summary", changed), _source("current", "orders.item_sales_summary", current)],
                       ("current", "total_quantity"), ("prior", "total_quantity"))
    assert result.success  # Arithmetic and temporal alignment have separate proof.
    verdict = {"period_relations": [{"left_source_step_id": "read_current", "right_source_step_id": "read_prior", "relation": "previous_equal_period"}]}
    assert _calculation_period_relation_problems(verdict, result.data["verified_calculations"]) == ["calculation_observed_period_bounds_missing"]


def test_orders_catalog_exposes_actual_period_provenance_and_marketplace_quantity_fields(sources):
    from AI.processors.task_runtime import _tool_result_field_names
    db, _, _ = sources
    registry = tools.available_tools()
    summary = registry["orders.summary"].handler(db_name=db, period="all", api_account_ids=[101])
    prior, _ = _actual_adjacent_reads(db)
    assert summary.success
    for operation, actual, expected in (
        ("orders.summary", summary.data, {"start_ms", "end_ms", "source_revision", "source_snapshot_hash"}),
        ("orders.item_sales_summary", prior, {"start_date_ms", "end_date_ms", "source_revision", "source_snapshot_hash",
                                              "quantity_unit", "quantity_unit_description"}),
    ):
        assert expected.issubset(registry[operation].result_schema["properties"])
        assert expected.issubset(_tool_result_field_names(registry[operation]))
        assert expected.issubset(actual)
        assert "last_14_days" in registry[operation].description
