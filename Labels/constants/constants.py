# Labels/constants/constants.py
from __future__ import annotations
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent
LABEL_ASSETS_DIR = _BASE_DIR.parent / "assets"

LABEL_BRANDS = [
    {
        "code": "TANEX",
        "name": "Tanex",
    },
]

LABEL_MODELS_BY_BRAND = {
    "TANEX": [
        {
            "code": "TANEX_2736",
            "name": "Tanex 2736 (24'lü küçük etiket)",
            "desc": "Standart Tanex 2736 sayfa düzeni, 24 label/sayfa",

            # assets klasörüne göre göreli yol
            "template_rel_path": "TANEX_2736.docx",

            # Kapasiteler
            "labels_per_page": 24,
            "max_items_per_label": 4,

            # 🔹 Placeholder isimleri (mantıksal alan → Word'deki pattern)
            # n = label index (1..24), i = ürün index (1..8)
            "placeholders": {
                "barcode": "barcode_{n}",
                "ordernumber": "ordernumber_{n}",
                "name": "name_{n}",
                "surname": "surname_{n}",
                "address": "address_{n}",
                "cargotrackingnumber": "cargotrackingnumber_{n}",
                "cargoprovidername": "cargoprovidername_{n}",
                "product": "prod{i}_{n}",
                "qty": "qty{i}_{n}",
                # ekstra alanlar:
                # mağaza adı + platform + SLA ikonu
                "storename": "storename_{n}",
                "platform": "platform_{n}",
                "sla_hours_left": "sla_hours_left_{n}",
            },

            # 🔹 Alan bazlı stil:
            #  - Buradaki font_name / font_size HER ZAMAN uygulanacak
            #  - Renk / bold gibi şeyleri kodda şartlı override ederiz (ör: qty>1 kırmızı)
            "fields": {
                "ordernumber": {
                    "font_name": "Arial",
                    "font_size": 11,
                },
                "name": {
                    "font_name": "Segoe UI",
                    "font_size": 14,
                },
                "surname": {
                    "font_name": "Segoe UI",
                    "font_size": 14,
                },
                "address": {
                    "font_name": "Arial",
                    "font_size": 12,
                },
                "cargotrackingnumber": {
                    "font_name": "Arial",
                    "font_size": 11,
                },
                "cargoprovidername": {
                    "font_name": "Arial",
                    "font_size": 8,
                },
                "product": {
                    "font_name": "Arial",
                    "font_size": 18,
                },

                # qty için temel stil (renk/bold koşullu override edilecek)
                "qty": {
                    "font_name": "Bebas Neue",
                    "font_size": 20,
                    # "color": "000000",
                    "bold": False,
                },

                # mağaza adı
                "storename": {
                    "font_name": "Segoe UI",
                    "font_size": 10,
                },
                # platform (TRENDYOL vb.)
                "platform": {
                    "font_name": "Arial",
                    "font_size": 10,
                },
            },

            # 🔴 Barkod / uyarı görseli ayarları
            "barcode": {
                # Normal barkod genişliği
                "image_width_mm": 46,

                # Uyarı görseli için ayrı genişlik / yükseklik
                "attention_image_width_mm": 36.5,
                # "attention_image_height_mm": 15,

                "module_width": 0.20,
                "module_height": 8.0,
                "font_size": 10,
                "text_distance": 1.0,
                "quiet_zone": 2.0,
            },

            # SLA (kalan süre) görseli için genişlik
            # export_labels_to_word içinde cfg.get("sla_image_width_mm", 10) ile okunuyor
            "sla_image_width_mm": 18,
            # istersen ileride yükseklik de kullanırsın:
            # "sla_image_height_mm": 6,

            # 🔵 Kargo firması logoları
            "cargo_provider_logos": {
                "Trendyol Express Marketplace": {
                    "filename": "express-logo.png",
                    "width_mm": 18,
                },
                "Aras Kargo Marketplace": {
                    "filename": "aras-logo.png",
                    "width_mm": 18,
                },
                "yurtiçi kargo": {
                    "filename": "logo_yurtici.png",
                    "width_mm": 12,
                },
                # elindeki diğer logoları da buraya ekleyebilirsin
            },

        },
    ],
}


def get_label_model_config(brand_code: str, model_code: str) -> dict | None:
    brand_code = (brand_code or "").strip()
    model_code = (model_code or "").strip()

    models = LABEL_MODELS_BY_BRAND.get(brand_code, []) or []
    for m in models:
        if m.get("code") == model_code:
            cfg = dict(m)

            rel = cfg.get("template_rel_path")
            if rel:
                cfg["template_path"] = str(LABEL_ASSETS_DIR / rel)
            else:
                cfg["template_path"] = None

            return cfg
    return None
