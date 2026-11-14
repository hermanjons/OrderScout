"""Shared business operations must not depend on UI actions or the agent runtime."""
import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize("relative", [
    "Stock/processors/item_queries.py",
    "Stock/processors/item_updates.py",
    "Stock/processors/policy_rules.py",
    "Listing/processors/catalog_queries.py",
    "Finance/processors/cashflow.py",
    "Finance/processors/catalog_reads.py",
    "Orders/processors/profit.py",
    "Orders/processors/profit_export.py",
    "Orders/processors/profit_workbook.py",
])
def test_extracted_business_operations_have_no_ui_or_ai_imports(relative):
    path = Path(__file__).resolve().parents[2] / relative
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    assert not [name for name in modules if ".views" in name or name == "AI" or name.startswith("AI.")]
