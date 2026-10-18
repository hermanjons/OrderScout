"""Synthetic seeding belongs to Testing; AI keeps a lazy compatibility API."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import runpy
import subprocess
import sys
from unittest.mock import patch

import pytest

from AI.processors import architecture_boundary, business_acceptance_fixtures
from AI.processors import tools
from Marketplaces.processors import catalog
from Testing.constants import trendyol_stage_constants
from Testing.processors import business_agent_fixtures


def test_compatibility_facade_invokes_actual_testing_owner_with_exact_arguments(tmp_path):
    database = tmp_path / "business.sqlite3"
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone(timedelta(hours=3)))
    with patch.object(business_agent_fixtures, "seed_business_fixture", wraps=business_agent_fixtures.seed_business_fixture) as seed:
        fixture = business_acceptance_fixtures.seed_business_fixture(str(database), isolation_root=tmp_path, now=now)
    seed.assert_called_once_with(str(database), isolation_root=tmp_path, now=now)
    assert fixture["as_of"] == now.isoformat() and fixture["customer_data"] is False
    stock = tools.stock_inventory_overview(db_name=str(database))
    assert stock.success
    assert {row["currency"]: row["amount"] for row in stock.data["stock_value_by_currency"]} == {"TRY": 400, "USD": 30}
    orders = tools.orders_summary(db_name=str(database), period="all", api_account_ids=[101])
    assert orders.success and orders.data["total_orders"] == 5
    audit = architecture_boundary.audit_ai_domain_model_imports([Path(business_acceptance_fixtures.__file__)])
    assert audit["valid"] and audit["violation_count"] == 0


def test_fresh_direct_script_compatibility_import_does_not_load_settings_or_domain_models():
    source = str(Path(business_acceptance_fixtures.__file__).resolve())
    code = ("import importlib.util, sys\n"
            f"spec = importlib.util.spec_from_file_location('business_acceptance_fixtures', {source!r})\n"
            "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
            "assert module.WORKFLOW_ACCEPTANCE_SPEC['name'] == 'Pilot Stok İncelemesi'\n"
            "assert 'report_title' in module.workflow_save_prompt()\n"
            "assert 'settings' not in sys.modules\n"
            "assert 'sqlmodel' not in sys.modules\n"
            "assert 'Testing.processors.business_agent_fixtures' not in sys.modules\n")
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_stage_url_is_exact_canonical_marketplace_stage_scope_without_production_fallback():
    stage = catalog.marketplace_api_scope_profile("TRENDYOL", "orders", "stage")
    production = catalog.marketplace_api_scope_profile("TRENDYOL", "orders", "production")
    assert stage["environment"] == "stage" and stage["environmentSupported"] is True
    assert trendyol_stage_constants.TRENDYOL_STAGE_BASE_URL == stage["baseUrl"]
    assert trendyol_stage_constants.TRENDYOL_STAGE_BASE_URL != production["baseUrl"]
    path = str(Path(trendyol_stage_constants.__file__).resolve())
    with patch.object(catalog, "marketplace_api_scope_profile", return_value={"baseUrl": "https://stage.fixture.invalid/"}) as resolve:
        loaded = runpy.run_path(path)
    resolve.assert_called_once_with("TRENDYOL", "orders", "stage")
    assert loaded["TRENDYOL_STAGE_BASE_URL"] == "https://stage.fixture.invalid"
    with patch.object(catalog, "marketplace_api_scope_profile", return_value={}):
        with pytest.raises(RuntimeError, match="canonical marketplace configuration"):
            runpy.run_path(path)
