# Labels/pipeline.py
from __future__ import annotations

from typing import List, Dict, Any, Optional, Callable

import os
import tempfile
from pathlib import Path

from Feedback.processors.pipeline import Result, map_error_to_message
from Orders.views.actions import collect_selected_orders
from Orders.processors.trendyol_pipeline import get_order_full_details_by_numbers

from docxtpl import DocxTemplate, InlineImage, RichText
from docx.shared import Mm
from docx import Document
import math
from Orders.signals.signals import order_signals  # noqa: F401
from io import BytesIO
from docxcompose.composer import Composer

# 🔴 Buraya dikkat: LABEL_ASSETS_DIR de import edildi
from Labels.constants.constants import get_label_model_config, LABEL_ASSETS_DIR


# ─────────────────────────────────────────
# 0) LABEL PAYLOAD SIRALAYICI
# ─────────────────────────────────────────
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

    Değişmez kural:
        - Aynı orderNumber'a sahip label'lar HER ZAMAN arka arkaya kalır.
          (Yani tek siparişin 2 etiketi birbirinden kopmaz.)
    """
    if not label_payload or mode == "none":
        return label_payload

    pages = label_payload.get("pages") or []
    labels_per_page = label_payload.get("labels_per_page") or 24
    max_items_per_label = label_payload.get("max_items_per_label") or 8

    # Tüm label'ları flatten et
    all_labels: List[Dict[str, Any]] = [lbl for page in pages for lbl in page]
    if not all_labels:
        return label_payload

    # 0️⃣ Aynı orderNumber'a sahipleri grupla, ama ilk görüldükleri sırayı koru
    groups: list[tuple[str, list[dict]]] = []
    group_map: dict[str, list[dict]] = {}

    for idx, lbl in enumerate(all_labels):
        order_no = (lbl.get("orderNumber") or "").strip()

        if order_no:
            key = order_no
        else:
            # orderNumber yoksa her label kendi başına grup olsun
            key = f"__SINGLE__{idx}"

        if key not in group_map:
            group_map[key] = []
            groups.append((key, group_map[key]))

        group_map[key].append(lbl)

    def extract_group_metrics(group_labels: list[dict]):
        """
        Bir sipariş grubundan:
          - primary_product: toplamdaki ilk dolu prodX
          - total_qty: tüm qtyX toplamı (TÜM etiketler dahil)
        """
        primary_product = ""
        total_qty = 0

        for lbl in group_labels:
            for i in range(1, max_items_per_label + 1):
                p = (lbl.get(f"prod{i}", "") or "").strip()
                q = lbl.get(f"qty{i}", 0)

                if not primary_product and p:
                    primary_product = p

                try:
                    q_int = int(q)
                except (TypeError, ValueError):
                    q_int = 0

                total_qty += q_int

        return primary_product.lower(), total_qty

    # Sıralama anahtarı (grup bazlı)
    def sort_key(group: tuple[str, list[dict]]):
        _, glabels = group
        prod_name, total_qty = extract_group_metrics(glabels)

        if mode == "product":
            # Ürün adına göre (A-Z), eşitlerde çok adedi öne
            return (prod_name, -total_qty)
        elif mode == "quantity":
            # Toplam adede göre (yüksekten düşüğe), sonra ürün adına göre
            return (-total_qty, prod_name)
        elif mode == "optimal":
            # Önce ürün adına göre grupla, her ürün grubunda çok adedi öne al
            return (prod_name, -total_qty)
        else:
            # Bilinmeyen mode → dokunma
            return (0,)

    sorted_groups = sorted(groups, key=sort_key)

    # Grupları tekrar tek listeye aç
    sorted_labels: list[dict] = []
    for _, glabels in sorted_groups:
        sorted_labels.extend(glabels)

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
    Seçili siparişlerden, Word şablonuna direkt gömülebilecek label payload üretir.

    DÖNEN Result.data:
        {
            "label_payload": {...},
            "order_numbers": [ ... ]   # ⬅ OrderHeader güncellemesi için
        }

    ÖNEMLİ:
        - Bir sipariş birden fazla etikete bölünürse:
            - İlk etiket: is_primary_for_order = True
            - Devam etiketleri: is_primary_for_order = False
          Bu bilgi Word'e dökerken barkod / uyarı görseli seçmekte kullanılır.
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
        label_index = 0  # debug için

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

                # kargo bilgileri (HAM veri)
                cargo_tracking = (getattr(latest, "cargoTrackingNumber", "") or "").strip()
                cargo_provider_name = (getattr(latest, "cargoProviderName", "") or "").strip()

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

            for chunk_idx, chunk in enumerate(chunks):
                label_index += 1

                label_dict: Dict[str, Any] = {
                    # ham alanlar
                    "orderNumber": order_no,
                    "cargoTrackingNumber": cargo_tracking,
                    "fullname": fullname,
                    "address": address,
                    "cargoProviderName": cargo_provider_name,
                    # debug
                    "debug_index": label_index,
                    # 🔴 Siparişin ilk etiketi mi?
                    "is_primary_for_order": (chunk_idx == 0),
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
            data={
                "label_payload": payload,
                "order_numbers": order_numbers,  # ⬅ OrderHeader update için
            },
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
        progress_cb: Optional[Callable[[int], None]] = None,
) -> Result:
    """
    Tüm label'ları, labels_per_page (örn. 24) adetlik sayfalara bölüp,
    her sayfa için ayrı docx üretir ve en sonunda TEK Word dosyasında birleştirir.

    Özel davranış:
        - Bir sipariş birden fazla etikete bölünmüşse:
            - is_primary_for_order == True  → normal barkod
            - is_primary_for_order == False → barkod yerine uyarı görseli:
                  assets/images/split_order_attention_img.png
    """
    try:
        def report_progress(pct: int):
            if progress_cb is not None:
                try:
                    pct_int = max(0, min(100, int(pct)))
                    progress_cb(pct_int)
                except Exception:
                    pass

        report_progress(0)

        if not label_payload:
            return Result.fail("Boş label_payload alındı.", close_dialog=False)

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

        cfg = get_label_model_config(brand_code, model_code)
        if not cfg:
            return Result.fail(
                f"Etiket konfigi bulunamadı: {brand_code}/{model_code}",
                close_dialog=False,
            )

        labels_per_page = cfg.get("labels_per_page", 24)
        max_items_per_label = cfg.get("max_items_per_label", 8)

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

        # 🔴 Barkod + uyarı görseli boyutları
        barcode_cfg = cfg.get("barcode", {}) or {}
        image_width_mm = barcode_cfg.get("image_width_mm", 44)

        attention_image_width_mm = barcode_cfg.get(
            "attention_image_width_mm",
            image_width_mm,  # tanımlı değilse barkodla aynı olsun
        )
        attention_image_height_mm = barcode_cfg.get("attention_image_height_mm")  # opsiyonel

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

        if template_path is None:
            tp = cfg.get("template_path")
        else:
            tp = Path(template_path)

        if not tp or not Path(tp).is_file():
            return Result.fail(
                f"Word şablonu bulunamadı: {tp}",
                close_dialog=False,
            )

        # 🔸 Uyarı görselinin yolu
        attention_img_path = LABEL_ASSETS_DIR / "images" / "split_order_attention_img.png"
        attention_img_exists = attention_img_path.is_file()

        pages = label_payload.get("pages") or []
        labels = [lbl for page in pages for lbl in page]

        total_labels = len(labels)
        if not total_labels:
            return Result.fail("Yazdırılacak label yok.", close_dialog=False)

        total_pages = math.ceil(total_labels / labels_per_page)

        report_progress(5)

        pages_tmp_dir = os.path.join(
            tempfile.gettempdir(), "orderscout_label_pages"
        )
        os.makedirs(pages_tmp_dir, exist_ok=True)

        page_files: list[str] = []

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

        for page_index in range(total_pages):
            doc = DocxTemplate(str(tp))
            context: Dict[str, object] = {}

            start = page_index * labels_per_page
            end = min(start + labels_per_page, total_labels)
            num_labels_this_page = end - start

            for slot, global_idx in enumerate(range(start, end), start=1):
                lbl = dict(labels[global_idx])
                n = slot  # 1..labels_per_page

                order_no = (lbl.get("orderNumber") or "").strip()
                full_name = (lbl.get("fullname") or "").strip()
                address = (lbl.get("address") or "").strip()
                cargo_raw = (lbl.get("cargoTrackingNumber") or "").strip()
                cargo_provider = (lbl.get("cargoProviderName") or "").strip()

                # 🔐 TEK KAYNAK: barkod değeri + görünen kargo takip numarası
                barcode_val = cargo_raw or order_no
                cargo_tr_no = barcode_val

                # Bu label siparişin ilk etiketi mi?
                is_primary_for_order = bool(lbl.get("is_primary_for_order", True))

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

                # --- Barkod görseli / Uyarı görseli ---
                if is_primary_for_order and barcode_val:
                    # ✅ İlk etiket → normal barkod
                    res_bar = generate_code128_barcode(
                        barcode_val,
                        save_path=None,
                        writer_options=writer_opts or None,
                    )
                    if isinstance(res_bar, Result) and res_bar.success:
                        png_bytes = res_bar.data.get("png_bytes")
                        if png_bytes:
                            stream = BytesIO(png_bytes)
                            context[f"barcode_{n}"] = InlineImage(
                                doc,
                                stream,
                                width=Mm(image_width_mm),
                            )
                        else:
                            context[f"barcode_{n}"] = barcode_val
                    else:
                        context[f"barcode_{n}"] = barcode_val
                else:
                    # ✅ Devam etiketi → barkod yerine uyarı görseli
                    if attention_img_exists:
                        attention_kwargs = {}
                        if attention_image_width_mm:
                            attention_kwargs["width"] = Mm(attention_image_width_mm)
                        if attention_image_height_mm:
                            attention_kwargs["height"] = Mm(attention_image_height_mm)

                        context[f"barcode_{n}"] = InlineImage(
                            doc,
                            str(attention_img_path),
                            **attention_kwargs,
                        )
                    else:
                        # Görsel bulunamazsa boş bırak (veya istersen sabit text)
                        context[f"barcode_{n}"] = ""

                # Debug için label indexini de taşıyalım istersen
                debug_idx = lbl.get("debug_index")
                context[f"debug_{n}"] = str(debug_idx) if debug_idx is not None else ""

                # Ürünler
                for i in range(1, max_items_per_label + 1):
                    prod_key = f"prod{i}"
                    qty_key = f"qty{i}"

                    prod_val = lbl.get(prod_key, "") or ""
                    qty_val = lbl.get(qty_key, "")

                    context[f"{prod_key}_{n}"] = style_text(prod_val, product_style)

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

            # Kullanılmayan slotlar
            for n in range(num_labels_this_page + 1, labels_per_page + 1):
                context[f"barcode_{n}"] = ""
                context[f"debug_{n}"] = ""
                context[f"ordernumber_{n}"] = ""
                context[f"name_{n}"] = ""
                context[f"surname_{n}"] = ""
                context[f"address_{n}"] = ""
                context[f"cargotrackingnumber_{n}"] = ""
                context[f"cargoprovidername_{n}"] = ""
                for i in range(1, max_items_per_label + 1):
                    context[f"prod{i}_{n}"] = ""
                    context[f"qty{i}_{n}"] = ""

            doc.render(context)
            page_path = os.path.join(
                pages_tmp_dir, f"orderscout_labels_page_{page_index + 1}.docx"
            )
            doc.save(page_path)
            page_files.append(page_path)

            if total_pages > 0:
                base = 5
                span = 90
                pct = base + span * ((page_index + 1) / total_pages)
                report_progress(pct)

        if not page_files:
            return Result.fail("Hiç sayfa üretilemedi.", close_dialog=False)

        # ✅ docxcompose ile sorunsuz merge
        main_doc = Document(page_files[0])
        composer = Composer(main_doc)

        for extra_path in page_files[1:]:
            sub_doc = Document(extra_path)
            composer.append(sub_doc)

        composer.save(output_path)

        report_progress(100)

        return Result.ok(
            f"{total_labels} etiket, {total_pages} Word sayfasına işlendi.",
            data={"output_path": output_path},
            close_dialog=False,
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)

