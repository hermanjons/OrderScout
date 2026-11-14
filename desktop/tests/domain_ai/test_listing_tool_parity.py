from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator
from sqlmodel import Session

from AI.processors import tools
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result
from Listing.models.models import ListingProduct
from Listing.processors import catalog_queries
from Listing.views import actions
from Testing.processors.business_agent_fixtures import seed_business_fixture


CATALOG_TOOLS = (
    "listing.summary", "listing.counts", "listing.attention", "listing.attention_count", "listing.search",
    "listing.title_lookup", "listing.detail_lookup", "listing.stock_lookup", "listing.status_lookup",
    "listing.url_lookup", "listing.price_lookup",
)


@pytest.fixture
def database(tmp_path):
    database = str(tmp_path / "fixture.sqlite3")
    seed_business_fixture(database, isolation_root=tmp_path)
    with Session(get_engine(database)) as session:
        session.add_all([
            ListingProduct(pk=801, api_account_id=101, product_id="SPECIAL-P", title="Kesirli Ürün",
                           barcode="SPECIAL-BAR", stock_code="SPECIAL-SKU", quantity=0.004, sale_price=0,
                           list_price=125.5, on_sale=True, approved=None, archived=False, raw={"currencyCode": "USD"}),
            ListingProduct(pk=802, api_account_id=102, product_id="SPECIAL-P", title="Other account",
                           barcode="SPECIAL-BAR", stock_code="SPECIAL-SKU", quantity=7, sale_price=99,
                           list_price=130, on_sale=True, approved=True, archived=False),
        ])
        session.commit()
    return database


@pytest.mark.parametrize("name", CATALOG_TOOLS)
def test_all_catalog_read_contracts_match_actual_account_scoped_results(database, name):
    tool = tools.registered_tools()[name]
    arguments = {"db_name": database, "api_account_ids": [101]}
    if "query" in tool.parameters["properties"]:
        arguments["query"] = "SPECIAL-SKU"
    result = tool.handler(**arguments)
    assert result.success, result.message
    assert tool.canonical_callable.startswith("Listing.processors.catalog_queries.")
    Draft202012Validator(tool.result_schema).validate(result.data)
    assert set(result.data) == set(tool.result_schema["properties"])
    for collection in ("results", "titles", "details", "stocks", "statuses", "urls", "prices", "sample_listings", "listings"):
        if collection in result.data:
            assert all(row["api_account_id"] == 101 for row in result.data[collection])


def test_manual_editor_data_and_every_price_or_quantity_lookup_preserve_zero_and_fraction(database):
    manual = actions.action_get_listings_from_db(db_name=database, api_account_ids=[101], barcode="SPECIAL-BAR")
    assert manual.success, manual.message
    source = manual.data["items"][0]
    assert source["salePrice"] == 0 and source["quantity"] == 0.004
    for name, collection in (("listing.search", "results"), ("listing.detail_lookup", "details"),
                              ("listing.price_lookup", "prices"), ("listing.stock_lookup", "stocks")):
        result = tools.registered_tools()[name].handler(db_name=database, query="SPECIAL-SKU", api_account_ids=[101])
        row = result.data[collection][0]
        assert row["listing_id"] == 801 and row["api_account_id"] == 101
        assert row["quantity"] == 0.004
        assert row["approved"] is None
        assert row["currency"] == "USD"
        if "sale_price" in row:
            assert row["sale_price"] == 0


@pytest.mark.parametrize("name", CATALOG_TOOLS)
def test_source_failure_survives_every_catalog_read_adapter_without_empty_success(name):
    failure = Result.fail("İlan kataloğu okunamadı.", data={"source": "listing", "reason": "unavailable"})
    with patch.object(catalog_queries, "read_listing_products", return_value=failure):
        result = tools.registered_tools()[name].handler(db_name="unused.sqlite3")
    assert result is failure
    assert result.data == {"source": "listing", "reason": "unavailable"}


def test_lookup_pages_and_empty_account_selection_have_explicit_contracts(database):
    from AI.runtime.schema import validate_tool_arguments
    tool = tools.registered_tools()["listing.price_lookup"]
    assert "arguments.api_account_ids:minItems" in validate_tool_arguments(tool, {"api_account_ids": []})
    page = tool.handler(db_name=database, query="SPECIAL-SKU", limit=1)
    last = tool.handler(db_name=database, query="SPECIAL-SKU", limit=1, offset=1)
    assert page.data["total"] == 2 and page.data["has_more"] is True
    assert last.data["total"] == 2 and last.data["has_more"] is False
    assert page.data["prices"][0]["listing_id"] != last.data["prices"][0]["listing_id"]
