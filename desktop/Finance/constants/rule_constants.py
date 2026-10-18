from __future__ import annotations


FINANCE_COST_RULE_RESOLVER_MAP: dict[str, dict[str, str]] = {
    "cargo_amount_matcher": {
        "module": "Logistics.processors.cargo_amount_matcher",
        "callable": "resolve_cargo_amount_matcher",
    },
}

__all__ = ["FINANCE_COST_RULE_RESOLVER_MAP"]
