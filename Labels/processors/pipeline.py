# Labels/pipeline.py
from __future__ import annotations

from typing import List, Dict, Any, Optional
import os
import tempfile
from pathlib import Path

from Feedback.processors.pipeline import Result, map_error_to_message
from Orders.views.actions import collect_selected_orders
from Orders.processors.trendyol_pipeline import get_order_full_details_by_numbers

from docxtpl import DocxTemplate, InlineImage, RichText
from docx.shared import Mm, RGBColor, Pt  # Pt, RGBColor gerekirse ekleriz

from Labels.constants.constants import get_label_model_config
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import math







def sort_label_payload(
        label_payload: dict,
        mode: str,
) -> dict:
    """
    label_payload içindeki tüm label'ları verilen mode'a göre sıralar.

    mode:
        - "none"      : hiç dokunma
        - "product"   : ilk dolu ürün adına göre (alfabetik)
        - "quantity"  : toplam adet (yüksekten düşüğe), sonra ürün adına göre
        - "optimal"   : önce ürün adına göre, sonra toplam adete göre (yüksekten düşüğe)

    Not:
        - Girdi payload'ı mutate etmiyor; yeni bir dict döndürüyor.
    """
    if not label_payload or mode == "none":
        return label_payload

    pages = label_payload.get("pages") or []
    labels_per_page = label_payload.get("labels_per_page") or 24
    max_items_per_label = label_payload.get("max_items_per_label") or 8

    # Tüm label'ları flatten et
    all_labels = [lbl for page in pages for lbl in page]

    def extract_label_metrics(lbl: dict):
        """
        Bir label içinden:
          - primary_product: ilk dolu prodX
          - total_qty: tüm qtyX toplamı
        """
        primary_product = ""
        total_qty = 0

        for i in range(1, max_items_per_label + 1):
            p = (lbl.get(f"prod{i}", "") or "").strip()
            q = lbl.get(f"qty{i}", 0)

            # primary product: ilk dolu ürün
            if not primary_product and p:
                primary_product = p

            try:
                q_int = int(q)
            except (TypeError, ValueError):
                q_int = 0

            total_qty += q_int

        return primary_product.lower(), total_qty

    # Sıralama anahtarı
    def sort_key(lbl: dict):
        prod_name, total_qty = extract_label_metrics(lbl)

        if mode == "product":
            # Ürün adına göre (A-Z)
            return (prod_name, -total_qty)  # aynı ürünlerde çok adedi öne alır
        elif mode == "quantity":
            # Toplam adede göre (yüksekten düşüğe), sonra ürün adına göre
            return (-total_qty, prod_name)
        elif mode == "optimal":
            # Önce ürün adına göre grupla, her ürün grubunda çok adedi öne al
            return (prod_name, -total_qty)
        else:
            # Bilinmeyen mode → dokunma
            return (0,)

    sorted_labels = sorted(all_labels, key=sort_key)

    # Yeniden sayfalara böl
    new_pages: list[list[dict]] = []
    for i in range(0, len(sorted_labels), labels_per_page):
        new_pages.append(sorted_labels[i:i + labels_per_page])

    # Yeni payload
    new_payload = dict(label_payload)
    new_payload["pages"] = new_pages
    new_payload["total_labels"] = len(sorted_labels)
    new_payload["total_pages"] = len(new_pages)

    return new_payload







# ─────────────────────────────────────────
# 1) LABEL PAYLOAD ÜRETİCİ
# ─────────────────────────────────────────
def create_order_label_from_orders(
        list_widget,
        *,
        brand_code: str = "TANEX",
        model_code: str = "TANEX_2736",
) -> Result:
    """
    Orders.get_order_full_details_by_numbers çıktısından,
    Word şablonuna direkt gömülebilecek label payload üretir.
    """
    try:
        # 0️⃣ Seçilen marka/model için konfig
        cfg = get_label_model_config(brand_code, model_code)
        if not cfg:
            return Result.fail(
                f"Etiket konfigi bulunamadı: {brand_code}/{model_code}",
                close_dialog=False,
            )

        max_items_per_label: int = cfg.get("max_items_per_label", 8)
        labels_per_page: int = cfg.get("labels_per_page", 24)

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
                    for key in (
                            "fullAddress",
                            "address",
                            "neighborhood",
                            "district",
                            "city",
                            "postalCode",
                    ):
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

            # 3️⃣ max_items_per_label'lik item chunk'ları
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
                    "cargotrackingnumber": barcode_value,
                }

                # prod1..prodN / qty1..qtyN
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


# ─────────────────────────────────────────
# 2) BARKOD ÜRETİCİ
# ─────────────────────────────────────────
def generate_code128_barcode(
        value: str,
        *,
        save_path: Optional[str] = None,
        write_text: bool = False,
        dpi: int = 300,
        # 🔽 BOYUT AYARLARI (mm ve font)
        module_width: Optional[float] = None,  # dik çizgi kalınlığı (mm)
        module_height: Optional[float] = None,  # barkod yüksekliği (mm)
        font_size: Optional[int] = None,
        quiet_zone: Optional[float] = None,  # sağ/sol boşluk (mm)
        text_distance: Optional[float] = None,  # barkod-alt yazı arası (mm)
        # Ek raw options
        writer_options: Optional[Dict[str, Any]] = None,
        return_pil: bool = False,
) -> Result:
    """
    Code128 PNG üretir. save_path verilirse PNG dosya olarak kaydedilir.

    Boyut ayarları:
        - module_width (mm): 1 bar kalınlığı
        - module_height (mm): barkodun yüksekliği
        - quiet_zone (mm): sağ/sol boşluklar
        - font_size: alt yazı font boyutu
        - text_distance (mm): barkod ile alt yazı arası mesafe
    """
    try:
        if not value or not isinstance(value, str):
            return Result.fail("Geçersiz barkod değeri.", close_dialog=False)

        try:
            from barcode import Code128
            from barcode.writer import ImageWriter
            from io import BytesIO
        except Exception:
            return Result.fail(
                "Barkod kütüphaneleri eksik. 'python-barcode' ve 'Pillow' kurun.",
                close_dialog=False
            )

        # Varsayılan çizim ayarları
        opts: Dict[str, Any] = {
            "module_width": 0.20,
            "module_height": 15.0,
            "font_size": 10,
            "text_distance": 1.0,
            "quiet_zone": 2.0,
            "write_text": write_text,
            "dpi": dpi,
        }

        # Fonksiyon parametreleri ile override
        if module_width is not None:
            opts["module_width"] = module_width
        if module_height is not None:
            opts["module_height"] = module_height
        if font_size is not None:
            opts["font_size"] = font_size
        if quiet_zone is not None:
            opts["quiet_zone"] = quiet_zone
        if text_distance is not None:
            opts["text_distance"] = text_distance

        # Dışarıdan gelen raw writer_options ile son bir override daha
        if writer_options:
            opts.update(writer_options)

        code = Code128(value, writer=ImageWriter())
        pil_img = code.render(writer_options=opts)

        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # Kaydetmek isteniyorsa dosyaya yaz
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
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _make_rich_text(
        value: str,
        *,
        font_name: str | None = None,
        font_size: int | None = None,
        color: str | None = None,  # "FF0000"
        bold: bool | None = None,
):
    if value in (None, ""):
        return ""

    rt = RichText()
    kwargs = {}

    if font_name:
        kwargs["font"] = font_name

    # 🔴 DİKKAT: docxtpl burada düz int bekliyor
    if font_size:
        kwargs["size"] = font_size

    if color:
        kwargs["color"] = color

    if bold is not None:
        kwargs["bold"] = bold

    rt.add(str(value), **kwargs)
    # debug için istersen:
    # print("RICH:", value, kwargs)
    return rt


# ─────────────────────────────────────────
# 3) WORD'E DÖKME (+ sonra stil işle)
# ─────────────────────────────────────────
def export_labels_to_word(
        label_payload: dict,
        brand_code: str | None = None,
        model_code: str | None = None,
        output_path: str | None = None,
        *,
        template_path=None,
) -> Result:
    """
    Tüm label'ları, labels_per_page (örn. 24) adetlik sayfalara bölüp,
    her sayfa için ayrı docx üretir ve en sonunda TEK Word dosyasında birleştirir.

    - Alan stilleri constants.py → fields içinden gelir.
    - qty alanları için:
        * fields["qty"] temel font ayarını verir
        * qty > 1 ise kırmızı + bold yapılır.
    """
    try:
        if not label_payload:
            return Result.fail("Boş label_payload alındı.", close_dialog=False)

        # Brand / model'i payload'dan tamamla
        if brand_code is None:
            brand_code = label_payload.get("brand_code")
        if model_code is None:
            model_code = label_payload.get("model_code")

        if not brand_code or not model_code:
            return Result.fail(
                "Etiket markası / modeli belirlenemedi.",
                close_dialog=False,
            )

        if not output_path:
            return Result.fail(
                "Çıkış dosya yolu (output_path) belirtilmedi.",
                close_dialog=False,
            )

        # Model konfigi
        cfg = get_label_model_config(brand_code, model_code)
        if not cfg:
            return Result.fail(
                f"Etiket konfigi bulunamadı: {brand_code}/{model_code}",
                close_dialog=False,
            )

        labels_per_page = cfg.get("labels_per_page", 24)
        max_items_per_label = cfg.get("max_items_per_label", 8)

        # Alan bazlı stiller
        field_styles = cfg.get("fields", {}) or {}

        def fs(key: str) -> dict:
            return field_styles.get(key, {}) or {}

        ordernumber_style = fs("ordernumber")
        name_style = fs("name")
        surname_style = fs("surname")
        address_style = fs("address")
        cargotracking_style = fs("cargotrackingnumber")
        cargoprovider_style = fs("cargoprovidername")
        product_style = fs("product")
        qty_style = fs("qty")

        # Barkod ayarları
        barcode_cfg = cfg.get("barcode", {}) or {}
        image_width_mm = barcode_cfg.get("image_width_mm", 44)

        writer_opts: Dict[str, float | int] = {}
        if "module_width" in barcode_cfg:
            writer_opts["module_width"] = barcode_cfg["module_width"]
        if "module_height" in barcode_cfg:
            writer_opts["module_height"] = barcode_cfg["module_height"]
        if "font_size" in barcode_cfg:
            writer_opts["font_size"] = barcode_cfg["font_size"]
        if "text_distance" in barcode_cfg:
            writer_opts["text_distance"] = barcode_cfg["text_distance"]
        if "quiet_zone" in barcode_cfg:
            writer_opts["quiet_zone"] = barcode_cfg["quiet_zone"]

        # Template path
        if template_path is None:
            tp = cfg.get("template_path")
        else:
            tp = Path(template_path)

        if not tp or not Path(tp).is_file():
            return Result.fail(
                f"Word şablonu bulunamadı: {tp}",
                close_dialog=False,
            )

        # Tüm label'ları flatten et
        pages = label_payload.get("pages") or []
        labels = [lbl for page in pages for lbl in page]

        total_labels = len(labels)
        if not total_labels:
            return Result.fail("Yazdırılacak label yok.", close_dialog=False)

        total_pages = math.ceil(total_labels / labels_per_page)

        # Barkod PNG’leri için geçici klasör
        barcode_tmp_dir = os.path.join(
            tempfile.gettempdir(), "orderscout_barcode_cache_tpl"
        )
        os.makedirs(barcode_tmp_dir, exist_ok=True)

        # Sayfa docx'leri için geçici klasör
        pages_tmp_dir = os.path.join(
            tempfile.gettempdir(), "orderscout_label_pages"
        )
        os.makedirs(pages_tmp_dir, exist_ok=True)

        page_files: list[str] = []

        # Küçük helper: stil dict'inden RichText üret
        def style_text(value: str, style: dict):
            if not value:
                return ""
            return _make_rich_text(
                value,
                font_name=style.get("font_name"),
                font_size=style.get("font_size"),
                color=style.get("color"),
                bold=style.get("bold"),
            )

        # Her SAYFA için ayrı docx üret
        for page_index in range(total_pages):
            doc = DocxTemplate(str(tp))
            context: Dict[str, object] = {}

            start = page_index * labels_per_page
            end = min(start + labels_per_page, total_labels)
            num_labels_this_page = end - start

            # Bu sayfadaki label slotlarını doldur
            for slot, global_idx in enumerate(range(start, end), start=1):
                lbl = dict(labels[global_idx])
                n = slot  # 1..labels_per_page (sayfa içi index)

                order_no = lbl.get("ordernumber", "") or ""
                full_name = lbl.get("fullname", "") or ""
                address = lbl.get("address", "") or ""
                cargo_tr_no = lbl.get("cargotrackingnumber", "") or ""
                cargo_provider = lbl.get("cargoProviderName", "") or ""
                barcode_val = lbl.get("barcode", "") or ""

                # isim / soyisim parçalama
                name_part = ""
                surname_part = ""
                if full_name:
                    parts = full_name.split()
                    if len(parts) == 1:
                        name_part = parts[0]
                    else:
                        surname_part = parts[-1]
                        name_part = " ".join(parts[:-1])

                # --- Metin alanları (her zaman stil uygulanmış RichText) ---
                context[f"ordernumber_{n}"] = style_text(order_no, ordernumber_style)
                context[f"name_{n}"] = style_text(name_part, name_style)
                context[f"surname_{n}"] = style_text(surname_part, surname_style)
                context[f"address_{n}"] = style_text(address, address_style)
                context[f"cargotrackingnumber_{n}"] = style_text(
                    cargo_tr_no, cargotracking_style
                )
                context[f"cargoprovidername_{n}"] = style_text(
                    cargo_provider, cargoprovider_style
                )

                # --- Barkod görseli ---
                if barcode_val:
                    file_path = os.path.join(
                        barcode_tmp_dir, f"barcode_p{page_index + 1}_{n}.png"
                    )
                    res_bar = generate_code128_barcode(
                        barcode_val,
                        save_path=file_path,
                        writer_options=writer_opts or None,
                    )
                    if isinstance(res_bar, Result) and res_bar.success:
                        context[f"barcode_{n}"] = InlineImage(
                            doc,
                            file_path,
                            width=Mm(image_width_mm),
                        )
                    else:
                        context[f"barcode_{n}"] = barcode_val
                else:
                    context[f"barcode_{n}"] = ""

                # --- Ürünler (prod1..8 / qty1..8) ---
                for i in range(1, max_items_per_label + 1):
                    prod_key = f"prod{i}"
                    qty_key = f"qty{i}"

                    prod_val = lbl.get(prod_key, "") or ""
                    qty_val = lbl.get(qty_key, "")

                    # ürün adı → stil uygulanmış RichText
                    context[f"{prod_key}_{n}"] = style_text(prod_val, product_style)

                    # adet → koşullu RichText
                    if qty_val in (None, ""):
                        context[f"{qty_key}_{n}"] = ""
                    else:
                        try:
                            qty_int = int(qty_val)
                        except (TypeError, ValueError):
                            qty_int = 0

                        qty_text = str(qty_val)

                        base_font = qty_style.get("font_name")
                        base_size = qty_style.get("font_size")
                        base_color = qty_style.get("color")
                        base_bold = qty_style.get("bold")

                        # ŞART: 1'den büyükse kırmızı + bold
                        if qty_int > 1:
                            final_color = "FF0000"
                            final_bold = True
                        else:
                            final_color = base_color
                            final_bold = base_bold

                        context[f"{qty_key}_{n}"] = _make_rich_text(
                            qty_text,
                            font_name=base_font,
                            font_size=base_size,
                            color=final_color,
                            bold=final_bold,
                        )

            # Bu sayfada kullanılmayan slotları boşla
            for n in range(num_labels_this_page + 1, labels_per_page + 1):
                context[f"barcode_{n}"] = ""
                context[f"ordernumber_{n}"] = ""
                context[f"name_{n}"] = ""
                context[f"surname_{n}"] = ""
                context[f"address_{n}"] = ""
                context[f"cargotrackingnumber_{n}"] = ""
                context[f"cargoprovidername_{n}"] = ""
                for i in range(1, max_items_per_label + 1):
                    context[f"prod{i}_{n}"] = ""
                    context[f"qty{i}_{n}"] = ""

            # Şablonu doldur ve geçici sayfa dosyasına kaydet
            doc.render(context)
            page_path = os.path.join(
                pages_tmp_dir, f"orderscout_labels_page_{page_index + 1}.docx"
            )
            doc.save(page_path)
            page_files.append(page_path)

        # Geçici sayfa dosyalarını tek docx'te birleştir
        if not page_files:
            return Result.fail("Hiç sayfa üretilemedi.", close_dialog=False)

        main_doc = Document(page_files[0])
        for extra_path in page_files[1:]:
            sub_doc = Document(extra_path)
            for element in sub_doc.element.body:
                main_doc.element.body.append(element)

        main_doc.save(output_path)

        return Result.ok(
            f"{total_labels} etiket, {total_pages} Word sayfasına işlendi.",
            data={"output_path": output_path},
            close_dialog=False,
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
