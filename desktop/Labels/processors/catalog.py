from __future__ import annotations

from typing import Optional

from Labels.constants.template_constants import (
    get_label_model_config as _get_label_model_config,
    resolve_label_model_reference as _resolve_label_model_reference,
)


def get_label_model_config(brand_code: str, model_code: str) -> Optional[dict]:
    return _get_label_model_config(brand_code, model_code)


def resolve_label_model_reference(
    query: str,
    *,
    brand_code: str = "",
    model_code: str = "",
) -> Optional[dict]:
    return _resolve_label_model_reference(
        query,
        brand_code=brand_code,
        model_code=model_code,
    )
