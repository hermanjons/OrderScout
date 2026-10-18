from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from Marketplaces.processors.catalog import marketplace_api_operation_profile


class TestMarketplaceOperationContract(unittest.TestCase):
    @staticmethod
    def _runtime_python_files() -> list[Path]:
        desktop_root = Path(__file__).resolve().parents[2]
        ignored_roots = {
            "tests",
            "Testing",
            "images",
            ".venv",
            ".pytest_cache",
            ".uv-cache-codex",
            ".uv-cache-run",
            "__pycache__",
        }
        files = list(desktop_root.glob("*.py"))
        for root in desktop_root.iterdir():
            if not root.is_dir() or root.name in ignored_roots or root.name.startswith("."):
                continue
            files.extend(root.rglob("*.py"))
        return sorted(files)

    def test_trendyol_read_profile_exposes_shared_operation_contract(self) -> None:
        profile = marketplace_api_operation_profile("TRENDYOL", "orders", "list_orders")

        contract = profile["operationContract"]
        self.assertEqual(contract["owner_domain"], "marketplaces")
        self.assertEqual(contract["effect_class"], "read")
        self.assertEqual(contract["risk_level"], "R0")
        self.assertEqual(contract["approval_policy"], "none")
        self.assertEqual(contract["environment_scope"], ["production", "stage"])

    def test_trendyol_write_profile_requires_prepare_and_confirmation(self) -> None:
        profile = marketplace_api_operation_profile(
            "TRENDYOL",
            "orders",
            "change_cargo_provider",
        )

        contract = profile["operationContract"]
        self.assertEqual(contract["effect_class"], "external_mutation")
        self.assertEqual(contract["risk_level"], "R2")
        self.assertEqual(contract["approval_policy"], "prepare_then_confirm")
        self.assertTrue(contract["supports_prepare"])
        self.assertTrue(contract["supports_verify"])

    def test_trendyol_stage_profile_resolves_explicit_stage_base_url(self) -> None:
        profile = marketplace_api_operation_profile(
            "TRENDYOL",
            "orders",
            "list_orders",
            "stage",
        )

        self.assertEqual(profile["environment"], "stage")
        self.assertTrue(profile["environmentSupported"])
        self.assertEqual(profile["baseUrl"], "https://stageapigw.trendyol.com")
        self.assertEqual(
            profile["operationContract"]["environment_scope"],
            ["production", "stage"],
        )

    def test_trendyol_listing_stage_profile_keeps_integration_prefix(self) -> None:
        profile = marketplace_api_operation_profile(
            "TRENDYOL",
            "listing",
            "list_approved_products",
            "stage",
        )

        self.assertEqual(
            profile["baseUrl"],
            "https://stageapigw.trendyol.com/integration",
        )

    def test_trendyol_http_client_inventory_is_explicit_and_complete(self) -> None:
        desktop_root = Path(__file__).resolve().parents[2]
        clients: list[str] = []
        for path in self._runtime_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                base_names = {
                    base.id
                    if isinstance(base, ast.Name)
                    else base.attr
                    if isinstance(base, ast.Attribute)
                    else ""
                    for base in node.bases
                }
                if "BaseTrendyolApi" in base_names:
                    clients.append(
                        f"{path.relative_to(desktop_root).as_posix()}::{node.name}"
                    )

        self.assertEqual(
            clients,
            [
                "Finance/api/trendyol/finance_api.py::TrendyolFinanceApi",
                "Listing/api/trendyol/listing_api.py::TrendyolListingApi",
                "Orders/api/trendyol/orders_api.py::TrendyolApi",
            ],
        )

    def test_runtime_never_hardcodes_trendyol_api_origins_outside_catalog(self) -> None:
        forbidden_origin = re.compile(
            r"https://(?:stageapi|stageapigw|api|apigw)\.trendyol\.com",
            re.IGNORECASE,
        )
        violations: list[str] = []
        desktop_root = Path(__file__).resolve().parents[2]
        for path in self._runtime_python_files():
            if forbidden_origin.search(path.read_text(encoding="utf-8-sig")):
                violations.append(path.relative_to(desktop_root).as_posix())

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
