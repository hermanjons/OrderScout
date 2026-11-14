"""Local business scope must agree across lookup, order receipts and API guards."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, SQLModel

from Account.models.models import ApiAccount
from Account.processors.environment import account_environment_scope, resolve_account_environment
from Account.processors.local_health import lookup_local_accounts, summarize_local_account_health
from Core.db import model_registry  # noqa: F401
from Core.utils.model_utils import get_engine
from Orders.models.trendyol.models import OrderData, OrderHeader


@pytest.fixture
def local_database(tmp_path):
    database = str(tmp_path / "local-accounts.sqlite3")
    engine = get_engine(database)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        for pk, name in [(101, "Ardıç Ana Mağaza-demo"), (102, "Ege Mağaza-demo"), (103, "Pera Mağaza-demo")]:
            session.add(ApiAccount(pk=pk, account_id=str(900000 + pk), comp_name=name, platform="TRENDYOL",
                                   api_key="", api_secret="", token_valid=False,
                                   extra_config={"environment": "local", "data_origin": "synthetic", "auto_sync_mode": "local"}))
        session.commit()
        # The newest five selected orders belong to one store; the population
        # count includes all three stores. Their scope metadata must differ.
        for index, account_pk in enumerate([102, 103, 101, 101, 101, 101, 101], 1):
            stamp = 1792700000000 + index * 3600_000
            header = OrderHeader(orderNumber=f"DEMO-SCOPE-{index}", api_account_id=account_pk)
            session.add(header)
            session.flush()
            session.add(OrderData(order_header_id=header.pk, api_account_id=account_pk,
                                  orderNumber=header.orderNumber, id=8000 + index, shipmentPackageId=8000 + index,
                                  status="Delivered", shipmentPackageStatus="Delivered", orderDate=stamp,
                                  lastModifiedDate=stamp, totalPrice=100, packageTotalPrice=100, currencyCode="TRY"))
        session.commit()
    return database


def test_three_local_accounts_lookup_health_and_order_scope_agree(local_database):
    from AI.processors import tools

    all_accounts = lookup_local_accounts(db_name=local_database)
    assert all_accounts.success and all_accounts.data["count"] == 3
    assert {row["environment"] for row in all_accounts.data["account_scopes"]} == {"local"}
    named = tools.marketplaces_account_lookup(query="Ardıç Ana Mağaza-demo", db_name=local_database)
    assert named.success and named.data["count"] == 1
    assert named.data["accounts"][0]["api_account_id"] == 101
    assert named.data["accounts"][0]["environment"] == "local"
    no_match = lookup_local_accounts(query="bulunmayanxyz", db_name=local_database)
    assert no_match.success and no_match.data["count"] == 0
    health = summarize_local_account_health(db_name=local_database)
    assert health.success and health.data["accounts_total"] == 3
    assert all(row["environment"] == "local" for row in health.data["accounts"])
    summary = tools.orders_summary(db_name=local_database, period="all")
    assert summary.success, summary.message
    assert summary.data["total_orders"] == 7
    assert summary.data["environment_by_account"] == {"101": "local", "102": "local", "103": "local"}
    assert len(summary.data["account_scopes"]) == 3
    assert not all_accounts.data["network_request_performed"]
    assert "api_key" not in json.dumps(named.data)


def test_recent_orders_distinguishes_selection_from_population_scope(local_database):
    from AI.processors.tools import recent_orders

    result = recent_orders(db_name=local_database, period="all", limit=5)
    assert result.success, result.message
    assert result.data["listed_count"] == 5 and result.data["total_count"] == 7
    assert result.data["environment_by_account"] == {"101": "local"}
    assert result.data["population_environment_by_account"] == {"101": "local", "102": "local", "103": "local"}
    assert {row["api_account_id"] for row in result.data["population_account_scopes"]} == {101, 102, 103}
    assert len(result.data["account_by_order"]) == 5


@pytest.mark.parametrize("extra", [
    {"environment": "local"}, {"api_environment": "local"},
    {"environment": "production", "data_origin": "synthetic"},
    {"environment": "stage", "auto_sync_mode": "local"},
])
def test_local_markers_block_all_remote_clients_even_with_credentials(extra):
    from Finance.api.trendyol.finance_api import TrendyolFinanceApi
    from Listing.api.trendyol.listing_api import TrendyolListingApi
    from Marketplaces.api.trendyol.base_api import trendyol_account_client_kwargs
    from Orders.api.trendyol.orders_api import TrendyolApi

    account = SimpleNamespace(account_id="900101", platform="TRENDYOL", api_key="synthetic-key",
                              api_secret="synthetic-secret", extra_config=extra)
    assert resolve_account_environment(account) == "local"
    with patch("Marketplaces.api.trendyol.base_api.resolve_credential_bundle") as bundle:
        with pytest.raises(ValueError, match="Local marketplace"):
            trendyol_account_client_kwargs(account)
        for client in (TrendyolApi, TrendyolListingApi, TrendyolFinanceApi):
            with pytest.raises(ValueError, match="Local marketplace"):
                client.from_account(account)
        bundle.assert_not_called()


def test_local_remote_health_check_skips_network_even_with_production_override():
    from Account.processors import pipeline

    with patch.object(pipeline, "async_make_request", new=AsyncMock()) as request:
        result = pipeline.check_company_api_health(
            platform="TRENDYOL", account_id="900101", api_key="synthetic-key", api_secret="synthetic-secret",
            extra_config={"environment": "local", "data_origin": "synthetic"}, environment="production")
    assert result.success and result.data["environment"] == "local" and result.data["skipped"]
    assert not result.data["network_request_performed"]
    request.assert_not_awaited()


def test_remote_environment_contract_and_legacy_defaults_stay_canonical():
    from Marketplaces.api.trendyol.base_api import BaseTrendyolApi, trendyol_account_client_kwargs
    from Marketplaces.processors.catalog import normalize_marketplace_environment

    for alias, expected in [("live", "production"), ("staging", "stage")]:
        account = {"account_id": "900101", "api_key": "key", "api_secret": "secret", "extra_config": {"environment": alias}}
        assert trendyol_account_client_kwargs(account)["environment"] == expected
    with pytest.raises(ValueError):
        normalize_marketplace_environment("local")
    with pytest.raises(ValueError):
        BaseTrendyolApi(api_key_id="key", api_key_secret="secret", supplier_id="900101", environment="local")
    legacy = account_environment_scope({"platform": "TRENDYOL", "extra_config": {}})
    assert legacy == {"environment": "production", "environment_source": "trendyol_catalog_default"}
