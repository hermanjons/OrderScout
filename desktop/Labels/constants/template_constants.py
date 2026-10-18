from __future__ import annotations

from typing import Optional

from Labels.constants.paths import LABEL_ASSETS_DIR


LABEL_BRANDS = [
    {"code": "TANEX", "name": "Tanex"},
]

_SHIPPING_LABEL_PLACEHOLDERS = {
    "barcode": "barcode_{n}",
    "ordernumber": "ordernumber_{n}",
    "name": "name_{n}",
    "surname": "surname_{n}",
    "address": "address_{n}",
    "cargotrackingnumber": "cargotrackingnumber_{n}",
    "cargoprovidername": "cargoprovidername_{n}",
    "product": "prod{i}_{n}",
    "qty": "qty{i}_{n}",
    "storename": "storename_{n}",
    "platform": "platform_{n}",
    "sla_hours_left": "sla_hours_left_{n}",
}

# Aynı kargo etiketi veri sözleşmesini kullanan hazır şablonlar bu şemayı paylaşır.
# Eski isim geriye dönük uyumluluk için korunur.
_TANEX_2736_PLACEHOLDERS = _SHIPPING_LABEL_PLACEHOLDERS

_TANEX_2736_FIELDS = {
    "ordernumber": {"font_name": "Arial", "font_size": 11},
    "name": {"font_name": "Segoe UI", "font_size": 9},
    "surname": {"font_name": "Segoe UI", "font_size": 9},
    "address": {
        "font_name": "Arial",
        "font_size": 12,
        "fit_chars_at_base": 50,
        "min_font_size": 7,
    },
    "cargotrackingnumber": {"font_name": "Arial", "font_size": 11},
    "cargoprovidername": {"font_name": "Arial", "font_size": 8},
    "product": {
        "font_name": "Arial",
        "font_size": 18,
        "fit_chars_at_base": 22,
        "min_font_size": 8,
    },
    "qty": {"font_name": "", "font_size": 18, "bold": True},
    "storename": {"font_name": "Segoe UI", "font_size": 10},
    "platform": {"font_name": "Arial", "font_size": 10},
}


def _scale_field_styles(field_styles: dict, factor: float) -> dict:
    scaled: dict = {}
    for field_name, style in field_styles.items():
        scaled_style = dict(style)
        if scaled_style.get("font_size") is not None:
            scaled_style["font_size"] = round(float(scaled_style["font_size"]) * factor, 2)
        scaled[field_name] = scaled_style
    return scaled


_TANEX_2610_FIELDS = _scale_field_styles(_TANEX_2736_FIELDS, 1.0)
_TANEX_2610_FIELDS["address"]["font_size"] = 11
_TANEX_2610_FIELDS["address"]["fit_chars_at_base"] = 75
_TANEX_2610_FIELDS["address"]["min_font_size"] = 8
_TANEX_2610_FIELDS["product"]["fit_chars_at_base"] = 36
_TANEX_2610_FIELDS["product"]["min_font_size"] = 10

_TANEX_2736_BARCODE = {
    "image_width_mm": 36,
    "attention_image_width_mm": 36.5,
    "module_width": 0.19,
    "module_height": 9.0,
    "font_size": 10,
    "text_distance": 1.0,
    "quiet_zone": 0.2,
}

_TANEX_2610_BARCODE = {
    **_TANEX_2736_BARCODE,
    "image_width_mm": 54,
    "attention_image_width_mm": 54.75,
    "module_height": 9.0,
}

_TANEX_2736_SLA_IMAGE_WIDTH_MM = 16.3

_TANEX_2736_CARGO_PROVIDER_LOGOS = {
    "Trendyol Express Marketplace": {"filename": "express-logo.png", "width_mm": 16.3},
    "Aras Kargo Marketplace": {"filename": "aras-logo.png", "width_mm": 16.3},
    "yurtiçi kargo": {"filename": "logo_yurtici.png", "width_mm": 12},
}


def _scale_logo_widths(provider_logos: dict, factor: float) -> dict:
    return {
        provider_name: {
            **logo,
            "width_mm": round(float(logo["width_mm"]) * factor, 2),
        }
        for provider_name, logo in provider_logos.items()
    }


_TANEX_2610_CARGO_PROVIDER_LOGOS = _scale_logo_widths(
    _TANEX_2736_CARGO_PROVIDER_LOGOS,
    20 / _TANEX_2736_SLA_IMAGE_WIDTH_MM,
)

_TANEX_2610_SLA_IMAGE_WIDTH_MM = 20

_TANEX_2736_CARGO_PROVIDER_ALIASES = {
    "Trendyol Express Marketplace": ["trendyol express", "trendyol express mkt", "ty express"],
    "Aras Kargo Marketplace": ["aras kargo", "aras"],
    "yurtiçi kargo": ["yurtici kargo", "yurtiçi", "yurtici"],
}

LABEL_MODELS_BY_BRAND = {
    "TANEX": [
        {
            "code": "TANEX_2736",
            "manufacturer_ref": "TW-2736",
            "name": "Tanex TW-2736 (24'lü küçük etiket)",
            "desc": "70 x 36 mm, A4 üzerinde 3 x 8 düzen, 24 etiket/sayfa",
            "template_rel_path": "TANEX_2736.docx",
            "labels_per_page": 24,
            "sheet_rows": 8,
            "sheet_columns": 3,
            "label_width_mm": 70,
            "label_height_mm": 36,
            "max_items_per_label": 4,
            "placeholders": _TANEX_2736_PLACEHOLDERS,
            "fields": _TANEX_2736_FIELDS,
            "barcode": _TANEX_2736_BARCODE,
            "sla_image_width_mm": _TANEX_2736_SLA_IMAGE_WIDTH_MM,
            "cargo_provider_logos": _TANEX_2736_CARGO_PROVIDER_LOGOS,
            "cargo_provider_aliases": _TANEX_2736_CARGO_PROVIDER_ALIASES,
        },
        {
            "code": "TANEX_2610",
            "manufacturer_ref": "TW-2610",
            "name": "Tanex TW-2610 (10'lu büyük etiket)",
            "desc": "105 x 57 mm, A4 üzerinde 2 x 5 düzen, 10 etiket/sayfa",
            "template_rel_path": "TANEX_2610.docx",
            "labels_per_page": 10,
            "sheet_rows": 5,
            "sheet_columns": 2,
            "label_width_mm": 105,
            "label_height_mm": 57,
            "max_items_per_label": 4,
            "placeholders": _SHIPPING_LABEL_PLACEHOLDERS,
            "fields": _TANEX_2610_FIELDS,
            "barcode": _TANEX_2610_BARCODE,
            "sla_image_width_mm": _TANEX_2610_SLA_IMAGE_WIDTH_MM,
            "cargo_provider_logos": _TANEX_2610_CARGO_PROVIDER_LOGOS,
            "cargo_provider_aliases": _TANEX_2736_CARGO_PROVIDER_ALIASES,
        },
    ],
}

LABEL_TEMPLATE_PATHS = {
    (brand_code, model["code"]): str(LABEL_ASSETS_DIR / model["template_rel_path"])
    for brand_code, models in LABEL_MODELS_BY_BRAND.items()
    for model in list(models or [])
    if model.get("template_rel_path")
}
_LABEL_MODEL_CONFIG_CACHE: dict[tuple[str, str], dict] = {}


def _normalized_catalog_code(value: str) -> str:
    return "".join(
        character
        for character in str(value or "").strip().upper()
        if character.isalnum()
    )


def get_label_model_config(brand_code: str, model_code: str) -> Optional[dict]:
    requested_brand = str(brand_code or "").strip()
    requested_model = str(model_code or "").strip()
    normalized_brand_key = _normalized_catalog_code(requested_brand)
    normalized_brand = next(
        (
            known_brand
            for known_brand in LABEL_MODELS_BY_BRAND
            if _normalized_catalog_code(known_brand) == normalized_brand_key
        ),
        requested_brand,
    )
    normalized_model = _normalized_catalog_code(requested_model)
    cache_key = (normalized_brand, normalized_model)
    cached = _LABEL_MODEL_CONFIG_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    models = LABEL_MODELS_BY_BRAND.get(normalized_brand, []) or []
    for model in models:
        canonical_code = str(model.get("code") or "").strip()
        manufacturer_ref = str(model.get("manufacturer_ref") or "").strip()
        aliases = {
            _normalized_catalog_code(canonical_code),
            _normalized_catalog_code(manufacturer_ref),
        }
        numeric_aliases = {
            "".join(character for character in alias if character.isdigit())
            for alias in aliases
        }
        if normalized_model not in aliases and normalized_model not in numeric_aliases:
            continue
        payload = dict(model)
        payload["template_path"] = LABEL_TEMPLATE_PATHS.get(
            (normalized_brand, canonical_code)
        )
        _LABEL_MODEL_CONFIG_CACHE[cache_key] = dict(payload)
        return dict(payload)
    return None


def resolve_label_model_reference(
    query: str,
    *,
    brand_code: str = "",
    model_code: str = "",
) -> Optional[dict]:
    """Resolve a user-facing label reference to one canonical catalog model."""

    normalized_query = _normalized_catalog_code(query)
    normalized_brand = _normalized_catalog_code(brand_code)
    normalized_reference = _normalized_catalog_code(
        " ".join(
            value
            for value in (query, brand_code, model_code)
            if str(value or "").strip()
        )
    )
    referenced_brands = [
        known_brand
        for known_brand in LABEL_MODELS_BY_BRAND
        if (
            _normalized_catalog_code(known_brand) == normalized_brand
            or (
                _normalized_catalog_code(known_brand)
                and _normalized_catalog_code(known_brand) in normalized_reference
            )
        )
    ]
    brand_filter = referenced_brands[0] if len(referenced_brands) == 1 else ""
    query_matches: list[tuple[str, dict]] = []
    for known_brand, models in LABEL_MODELS_BY_BRAND.items():
        if brand_filter and known_brand != brand_filter:
            continue
        for model in models or []:
            aliases = {
                _normalized_catalog_code(model.get("code")),
                _normalized_catalog_code(model.get("manufacturer_ref")),
            }
            aliases.update(
                "".join(character for character in alias if character.isdigit())
                for alias in tuple(aliases)
            )
            if normalized_reference and any(
                alias and alias in normalized_reference for alias in aliases
            ):
                query_matches.append((known_brand, dict(model)))
    if len(query_matches) == 1:
        resolved_brand, resolved_model = query_matches[0]
        payload = get_label_model_config(
            resolved_brand,
            str(resolved_model.get("code") or ""),
        ) or dict(resolved_model)
        payload["brand_code"] = resolved_brand
        payload["model_code"] = str(resolved_model.get("code") or "")
        return payload

    configured = get_label_model_config(brand_filter or brand_code, model_code)
    if configured is None:
        return None
    payload = dict(configured)
    payload["brand_code"] = next(
        (
            known_brand
            for known_brand in LABEL_MODELS_BY_BRAND
            if known_brand == brand_filter
            or _normalized_catalog_code(known_brand) == normalized_brand
        ),
        str(brand_code or "").strip(),
    )
    payload["model_code"] = str(configured.get("code") or model_code or "").strip()
    return payload


def clear_label_template_cache() -> None:
    _LABEL_MODEL_CONFIG_CACHE.clear()

__all__ = [
    "LABEL_BRANDS",
    "LABEL_MODELS_BY_BRAND",
    "LABEL_TEMPLATE_PATHS",
    "clear_label_template_cache",
    "get_label_model_config",
    "resolve_label_model_reference",
]
