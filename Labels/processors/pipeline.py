# Labels/pipeline.py
from __future__ import annotations
from typing import List, Dict, Any

from Feedback.processors.pipeline import Result, map_error_to_message

# Seçili siparişleri toplamak için
from Orders.views.actions import collect_selected_orders

# Sipariş detaylarını (Header + Data + Item) getiren fonksiyon
from Orders.processors.trendyol_pipeline import get_order_full_details_by_numbers
from math import ceil


# Labels/pipeline.py (içine ekle)
from io import BytesIO
from typing import Optional, Dict, Any


def create_order_label_from_orders(
    list_widget,
    *,
    brand_code: str = "TANEX",
    model_code: str = "TANEX_2736",
    max_items_per_label: int = 8,
    labels_per_page: int = 24
) -> Result:

    try:
        # --- 1) seçili siparişleri al ---
        sel_res = collect_selected_orders(list_widget)
        if not sel_res.success:
            return sel_res

        order_numbers = sel_res.data.get("selected_orders", [])
        if not order_numbers:
            return Result.fail("Hiçbir sipariş seçilmedi.", close_dialog=False)

        # --- 2) sipariş detayları ---
        detail_res = get_order_full_details_by_numbers(order_numbers)
        if not detail_res.success:
            return detail_res

        orders = detail_res.data.get("orders", [])

        final_labels = []

        for pkg in orders:
            header = pkg.get("header")
            items = pkg.get("items", [])
            if not header:
                continue

            order_no = str(header.orderNumber)
            full_name = getattr(header, "customer", "") or ""
            address = getattr(header, "customerAddress", "") or ""

            # normalize items
            normalized = []
            for it in items:
                qty = getattr(it, "quantity", 1)
                normalized.append({
                    "name": getattr(it, "merchantSku", ""),
                    "qty": int(qty),
                })

            # ürünleri 8’lik hale getir
            chunks = [normalized[i:i+8] for i in range(0, len(normalized), 8)] or [[]]

            for chunk in chunks:
                label_dict = {
                    "barcode": order_no,
                    "ordernumber": order_no,
                    "fullname": full_name,
                    "address": address
                }

                # prod1..prod8 / qty1..qty8
                for idx in range(8):
                    if idx < len(chunk):
                        label_dict[f"prod{idx+1}"] = chunk[idx]["name"]
                        label_dict[f"qty{idx+1}"] = chunk[idx]["qty"]
                    else:
                        label_dict[f"prod{idx+1}"] = ""
                        label_dict[f"qty{idx+1}"] = ""

                final_labels.append(label_dict)

        # sayfalama
        pages = [
            final_labels[i:i+labels_per_page]
            for i in range(0, len(final_labels), labels_per_page)
        ]

        payload = {
            "brand_code": brand_code,
            "model_code": model_code,
            "labels_per_page": labels_per_page,
            "total_labels": len(final_labels),
            "total_pages": len(pages),
            "pages": pages
        }

        return Result.ok(
            f"{len(order_numbers)} sipariş için {len(final_labels)} label hazırlandı.",
            data={"label_payload": payload},
            close_dialog=False
        )

    except Exception as e:
        return Result.fail(str(e), close_dialog=False)





def generate_code128_barcode(
    value: str,
    *,
    write_text: bool = False,
    dpi: int = 300,
    writer_options: Optional[Dict[str, Any]] = None,
    return_pil: bool = False,
) -> Result:
    """
    Verilen 'value' için Code128 barkod üretir ve PNG bytes döner.

    Dönüş (success):
        Result.data = {
            "png_bytes": b"...",         # PNG ikili verisi
            "width": int,
            "height": int,
            "dpi": int,
            "pil_image": <PIL.Image> | None  # return_pil=True ise
        }

    Not: 'python-barcode' ve 'Pillow' gerektirir.
         pip install python-barcode pillow
    """
    try:
        if not value or not isinstance(value, str):
            return Result.fail("Geçersiz barkod değeri.", close_dialog=False)

        try:
            from barcode import Code128
            from barcode.writer import ImageWriter
        except Exception:
            return Result.fail(
                "Barkod kütüphaneleri eksik. 'python-barcode' ve 'Pillow' kurun.",
                close_dialog=False
            )

        # Varsayılan çizim ayarları
        opts = {
            "module_width": 0.20,     # çizgi kalınlığı
            "module_height": 15.0,    # barkod yüksekliği (mm)
            "font_size": 10,
            "text_distance": 1,
            "quiet_zone": 2.0,
            "write_text": write_text,
            "dpi": dpi,
        }
        if writer_options:
            opts.update(writer_options)

        code = Code128(value, writer=ImageWriter())
        pil_img = code.render(writer_options=opts)   # Pillow Image

        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        w, h = pil_img.size

        data = {
            "png_bytes": png_bytes,
            "width": w,
            "height": h,
            "dpi": dpi,
            "pil_image": pil_img if return_pil else None,
        }
        return Result.ok("Barkod üretildi.", close_dialog=False, data=data)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
