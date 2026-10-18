from __future__ import annotations

from importlib import import_module
from typing import Any, Callable

from Finance.constants.rule_constants import FINANCE_COST_RULE_RESOLVER_MAP

_RULE_CALLABLE_CACHE: dict[str, Callable[[dict[str, Any] | None, dict[str, Any] | None], dict[str, Any]]] = {}


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_finance_rule_key(value: Any) -> str:
    return _compact_text(value)


def finance_rule_resolver_entry(rule_key: Any) -> dict[str, str]:
    normalized_key = normalize_finance_rule_key(rule_key)
    payload = dict(FINANCE_COST_RULE_RESOLVER_MAP.get(normalized_key) or {})
    return payload if payload else {}


def get_finance_rule_callable(rule_key: Any) -> Callable[[dict[str, Any] | None, dict[str, Any] | None], dict[str, Any]]:
    normalized_key = normalize_finance_rule_key(rule_key)
    cached = _RULE_CALLABLE_CACHE.get(normalized_key)
    if cached is not None:
        return cached
    entry = finance_rule_resolver_entry(normalized_key)
    module_name = _compact_text(entry.get("module"))
    callable_name = _compact_text(entry.get("callable"))
    if not normalized_key or not module_name or not callable_name:
        raise KeyError(f"Finance rule resolver tanimi bulunamadi: {normalized_key or '-'}")
    module = import_module(module_name)
    resolver = getattr(module, callable_name, None)
    if not callable(resolver):
        raise RuntimeError(f"Finance rule resolver cagirilabilir degil: {normalized_key} -> {module_name}.{callable_name}")
    _RULE_CALLABLE_CACHE[normalized_key] = resolver
    return resolver


def resolve_finance_rule(
    rule_key: Any,
    source_config: dict[str, Any] | None,
    source_context: dict[str, Any] | None,
) -> dict[str, Any]:
    resolver = get_finance_rule_callable(rule_key)
    payload = resolver(source_config, source_context)
    return dict(payload or {}) if isinstance(payload, dict) else {}


def build_finance_rule_handler_map() -> dict[str, Callable[[dict[str, Any] | None, dict[str, Any] | None], dict[str, Any]]]:
    return {
        rule_key: get_finance_rule_callable(rule_key)
        for rule_key in FINANCE_COST_RULE_RESOLVER_MAP
    }


def clear_finance_rule_callable_cache() -> None:
    _RULE_CALLABLE_CACHE.clear()


__all__ = [
    "build_finance_rule_handler_map",
    "clear_finance_rule_callable_cache",
    "finance_rule_resolver_entry",
    "get_finance_rule_callable",
    "normalize_finance_rule_key",
    "resolve_finance_rule",
]
