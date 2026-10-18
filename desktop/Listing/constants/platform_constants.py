from __future__ import annotations


def canonical_platform_code(value) -> str:
    from Marketplaces.processors.catalog import canonical_platform_code as _canonical_platform_code

    return _canonical_platform_code(value)


def platform_label_for_code(code) -> str:
    from Marketplaces.processors.catalog import platform_label_for_code as _platform_label_for_code

    return _platform_label_for_code(code)


__all__ = [
    "canonical_platform_code",
    "platform_label_for_code",
]
