from __future__ import annotations

from typing import Callable

from Finance.processors.rule_loader import build_finance_rule_handler_map


LISTING_BUILTIN_RULE_HANDLERS: dict[str, Callable] = build_finance_rule_handler_map()
