# Labels/pipeline.py
from __future__ import annotations
from math import ceil



from typing import List, Dict, Any
from Feedback.processors.pipeline import Result, map_error_to_message
from Orders.views.actions import collect_selected_orders
from Orders.processors.trendyol_pipeline import get_order_full_details_by_numbers


from docxtpl import DocxTemplate, InlineImage
from docx.shared import Mm
import tempfile
import os

from Feedback.processors.pipeline import Result, map_error_to_message



def create_order_label_from_orders(
    list_widget,
    *,
    brand_code: str = "TANEX",
    model_code: str = "TANEX_2736",
    max_items_per_label: int = 8,
    labels_per_page: int = 24,
) -> Result:
    """
    Orders.get_order_full_details_by_numbers çıktısından,
    Word şablonuna direkt gömülebilecek label payload üretir.

    Dönüş:
        Result.data = {
            "label_payload": {
                "brand_code": ...,
                "model_code": ...,
                "max_items_per_label": 8,
                "labels_per_page": 24,
                "total_labels": N,
                "total_pages": P,
                "pages": [
                    [   # page 1
                        {
                            "barcode": "<cargoTrackingNumber or orderNumber>",
                            "ordernumber": "1069...",
                            "fullname": "...",
                            "address": "...",
                            "cargoProviderName": "...",
                            "prod1": "...", "qty1": 1,
                            ...
                            "prod8": "", "qty8": "",
                        },
                        ...
                    ],
                    ...
                ]
            }
        }
    """
    try:
        # 1️⃣ Seçili siparişler
        sel_res = collect_selected_orders(list_widget)
        if not sel_res or not isinstance(sel_res, Result):
            return Result.fail("Seçili siparişler okunamadı.", close_dialog=False)
        if not sel_res.success:
            return sel_res

        order_numbers: List[str] = sel_res.data.get("selected_orders", []) or []
        if not order_numbers:
            return Result.fail("Hiçbir sipariş seçilmedi.", close_dialog=False)

        # 2️⃣ Detaylar (header + data + items)
        detail_res = get_order_full_details_by_numbers(order_numbers)
        if not detail_res or not isinstance(detail_res, Result):
            return Result.fail("Sipariş detayları alınamadı.", close_dialog=False)
        if not detail_res.success:
            return detail_res

        orders = detail_res.data.get("orders", []) or []

        final_labels: List[Dict[str, Any]] = []

        for pkg in orders:
            header = pkg.get("header")
            snapshots = pkg.get("data", []) or []
            items = pkg.get("items", []) or []

            if not header:
                continue

            order_no = str(getattr(header, "orderNumber", "")).strip()

            # 2.a) Fullname, address, cargoTrackingNumber, cargoProviderName
            fullname = ""
            address = ""
            cargo_tracking = ""
            cargo_provider_name = ""

            if snapshots:
                # son snapshot
                latest = max(
                    snapshots,
                    key=lambda d: getattr(d, "lastModifiedDate", 0) or 0
                )

                # isim
                first = (getattr(latest, "customerFirstName", "") or "").strip()
                last = (getattr(latest, "customerLastName", "") or "").strip()
                fullname = " ".join(p for p in [first, last] if p)

                # adres
                addr_dict = (
                    getattr(latest, "shipmentAddress", None)
                    or getattr(latest, "invoiceAddress", None)
                    or {}
                )
                if isinstance(addr_dict, dict):
                    parts = []
                    for key in ("fullAddress", "address", "neighborhood", "district", "city", "postalCode"):
                        v = addr_dict.get(key)
                        if v:
                            parts.append(str(v).strip())
                    address = ", ".join(parts)

                # kargo bilgileri
                cargo_tracking = (getattr(latest, "cargoTrackingNumber", "") or "").strip()
                cargo_provider_name = (getattr(latest, "cargoProviderName", "") or "").strip()

            # barkodda öncelik kargo takip numarası, yoksa order no
            barcode_value = cargo_tracking or order_no

            # 2.b) OrderItem → prod/qty normalize
            normalized: List[Dict[str, Any]] = []
            for it in items:
                qty_raw = getattr(it, "quantity", 1) or 1
                try:
                    qty = int(qty_raw)
                except (TypeError, ValueError):
                    qty = 1

                normalized.append({
                    "name": (getattr(it, "merchantSku", "") or "").strip(),
                    "qty": qty,
                })

            # 3️⃣ 8'lik item chunk'ları
            chunks = [
                normalized[i:i + max_items_per_label]
                for i in range(0, len(normalized), max_items_per_label)
            ] or [[]]

            for chunk in chunks:
                label_dict: Dict[str, Any] = {
                    "barcode": barcode_value,
                    "ordernumber": order_no,
                    "fullname": fullname,
                    "address": address,
                    "cargoProviderName": cargo_provider_name,
                }

                # prod1..prod8 / qty1..qty8
                for idx in range(max_items_per_label):
                    p_key = f"prod{idx + 1}"
                    q_key = f"qty{idx + 1}"
                    if idx < len(chunk):
                        label_dict[p_key] = chunk[idx]["name"]
                        label_dict[q_key] = chunk[idx]["qty"]
                    else:
                        label_dict[p_key] = ""
                        label_dict[q_key] = ""

                final_labels.append(label_dict)

        # 4️⃣ Sayfalama
        pages: List[List[Dict[str, Any]]] = [
            final_labels[i:i + labels_per_page]
            for i in range(0, len(final_labels), labels_per_page)
        ]

        payload = {
            "brand_code": brand_code,
            "model_code": model_code,
            "max_items_per_label": max_items_per_label,
            "labels_per_page": labels_per_page,
            "total_labels": len(final_labels),
            "total_pages": len(pages),
            "pages": pages,
        }

        return Result.ok(
            f"{len(order_numbers)} sipariş için {len(final_labels)} label hazırlandı.",
            data={"label_payload": payload},
            close_dialog=False,
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)





def generate_code128_barcode(
    value: str,
    *,
    save_path: Optional[str] = None,
    write_text: bool = False,
    dpi: int = 300,
    writer_options: Optional[Dict[str, Any]] = None,
    return_pil: bool = False,
) -> Result:
    """
    Code128 PNG üretir. save_path verilirse PNG dosya olarak kaydedilir.
    """

    try:
        if not value or not isinstance(value, str):
            return Result.fail("Geçersiz barkod değeri.", close_dialog=False)

        from barcode import Code128
        from barcode.writer import ImageWriter
        from io import BytesIO

        opts = {
            "module_width": 0.20,
            "module_height": 15.0,
            "font_size": 10,
            "text_distance": 1,
            "quiet_zone": 2.0,
            "write_text": write_text,
            "dpi": dpi,
        }
        if writer_options:
            opts.update(writer_options)

        code = Code128(value, writer=ImageWriter())
        pil_img = code.render(writer_options=opts)

        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # ✔ Eğer kullanıcı save_path verdiyse diske yaz
        if save_path:
            with open(save_path, "wb") as f:
                f.write(png_bytes)

        return Result.ok(
            "Barkod üretildi.",
            data={
                "png_bytes": png_bytes,
                "pil_image": pil_img if return_pil else None,
                "width": pil_img.size[0],
                "height": pil_img.size[1],
                "dpi": dpi,
                "path": save_path,
            },
            close_dialog=False,
        )

    except Exception as e:
        return Result.fail(str(e), close_dialog=False)



def export_labels_to_word(label_payload, template_path, output_path):
    """
    Word içinde hiçbir kod olmadan, sadece {{alan_adı}} yazılan yerlere
    payload verilerini basar.

    Word şablonu tek bir label içerir.
    Kod bunu payload içindeki tüm label’lar için tekrar eder.
    """
    try:
        pages = label_payload.get("pages") or []
        labels = [lbl for page in pages for lbl in page]

        if not labels:
            return Result.fail("Yazdırılacak label yok.", close_dialog=False)

        # Word şablonunu yükle
        doc = DocxTemplate(template_path)

        final_render_list = []

        # geçici klasör
        tmp_dir = os.path.join(tempfile.gettempdir(), "orderscout_barcode_cache")
        os.makedirs(tmp_dir, exist_ok=True)

        for i, lbl in enumerate(labels, start=1):
            lbl = dict(lbl)

            # barkod
            barcode_val = lbl.get("barcode", "")
            if barcode_val:
                file_path = os.path.join(tmp_dir, f"barcode_{i}.png")
                generate_code128_barcode(
                    barcode_val,
                    save_path=file_path
                )

                lbl["barcode_img"] = InlineImage(doc, file_path, width=Mm(35))
            else:
                lbl["barcode_img"] = ""

            final_render_list.append(lbl)

        # Word içinde bir döngü çalıştıracağız
        context = {
            "labels": final_render_list
        }

        doc.render(context)
        doc.save(output_path)

        return Result.ok(
            f"{len(final_render_list)} etiket Word dosyasına işlendi.",
            data={"output_path": output_path},
            close_dialog=False
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)