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
from datetime import datetime
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
        - Her label'da ayrıca:
            - storeName
            - platform
            - agreedDeliveryDate_ms  (ms cinsinden son teslim tarihi)
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

        # 1️⃣ Seçili siparişler → önce OrdersListWidget.get_selected_orders, sonra fallback collect_selected_orders
        order_numbers: List[str] = []

        # 🆕 A) OrdersListWidget ise model tabanlı seçim (_selected flag, tüm sayfalar)
        if hasattr(list_widget, "get_selected_orders"):
            try:
                selected_objs = list_widget.get_selected_orders() or []
                for o in selected_objs:
                    num = getattr(o, "orderNumber", None)
                    if num is None:
                        num = getattr(o, "order_number", None)
                    if num is None:
                        continue
                    order_numbers.append(str(num).strip())
            except Exception:
                # bir şey patlarsa fallback'e geçeceğiz
                order_numbers = []

        # 🧯 B) Fallback: Eski davranış (collect_selected_orders)
        if not order_numbers:
            sel_res = collect_selected_orders(list_widget)
            if not sel_res or not isinstance(sel_res, Result):
                return Result.fail("Seçili siparişler okunamadı.", close_dialog=False)
            if not sel_res.success:
                return sel_res

            raw_list = sel_res.data.get("selected_orders", []) or []
            for v in raw_list:
                # obje ise
                if hasattr(v, "orderNumber") or hasattr(v, "order_number"):
                    num = getattr(v, "orderNumber", getattr(v, "order_number", None))
                    if num is not None:
                        order_numbers.append(str(num).strip())
                else:
                    # direkt string/num verilmişse
                    order_numbers.append(str(v).strip())

        # Hâlâ yoksa → gerçekten seçim yok
        order_numbers = [n for n in order_numbers if n]
        if not order_numbers:
            return Result.fail("Hiçbir sipariş seçilmedi.", close_dialog=False)

        # 2️⃣ Detaylar (header + data + items + store_name/platform)
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

            # 🔹 get_order_full_details_by_numbers içinde eklediğimiz alanlar:
            store_name = (pkg.get("store_name") or "").strip()
            platform = (pkg.get("platform") or "").strip()

            if not header:
                continue

            order_no = str(getattr(header, "orderNumber", "")).strip()

            # 2.a) Fullname, address, cargoTrackingNumber, cargoProviderName
            fullname = ""
            address = ""
            cargo_tracking = ""
            cargo_provider_name = ""
            agreed_delivery_ms = None  # ✅ yeni: agreedDeliveryDate (ms)

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

                # ✅ son teslim tarihi (ms)
                agreed_delivery_ms = getattr(latest, "agreedDeliveryDate", None)
                try:
                    if agreed_delivery_ms is not None:
                        agreed_delivery_ms = int(agreed_delivery_ms)
                except (TypeError, ValueError):
                    agreed_delivery_ms = None

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
                    # 🔹 yeni alanlar
                    "storeName": store_name,
                    "platform": platform,
                    "agreedDeliveryDate_ms": agreed_delivery_ms,
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
        # create_order_label_from_orders sonunda, Result.ok'tan HEMEN ÖNCE:
        import json
        print("DEBUG LABEL PAYLOAD:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))

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
        progress_cb=None,
) -> Result:
    try:
        # ---------------------------------
        # PROGRESS CB
        # ---------------------------------
        def report(p):
            if progress_cb:
                try:
                    progress_cb(max(0, min(100, int(p))))
                except Exception:
                    Result.ok("Progress callback hatası.")

        report(0)

        # ---------------------------------
        # KONTROLLER
        # ---------------------------------
        if not label_payload:
            return Result.fail("Boş etiket payload alındı.")

        if brand_code is None:
            brand_code = label_payload.get("brand_code")

        if model_code is None:
            model_code = label_payload.get("model_code")

        cfg = get_label_model_config(brand_code, model_code)
        if not cfg:
            return Result.fail("Etiket konfigi bulunamadı.")

        labels_per_page = cfg.get("labels_per_page", 24)
        max_items = cfg.get("max_items_per_label", 8)

        # Template
        tp = template_path or cfg.get("template_path")
        if not tp or not Path(tp).is_file():
            return Result.fail(f"Word şablonu bulunamadı: {tp}")

        # Split görseli (uyarı)
        attention_info = cfg["barcode"]
        attention_w = attention_info.get("attention_image_width_mm", 30)
        attention_h = attention_info.get("attention_image_height_mm")

        attention_path = LABEL_ASSETS_DIR / "images" / "split_order_attention_img.png"
        has_attention_image = attention_path.is_file()
        if not has_attention_image:
            Result.ok("Split uyarı görseli bulunamadı.")

        # Barkod config
        barcode_cfg = cfg["barcode"]
        barcode_width = barcode_cfg.get("image_width_mm", 44)

        writer_opts = {
            k: barcode_cfg[k]
            for k in ("module_width", "module_height", "font_size", "text_distance", "quiet_zone")
            if k in barcode_cfg
        }

        # Kargo logo mapping
        cargo_logo_cfg = cfg.get("cargo_provider_logos", {}) or {}

        # SLA görselleri
        sla_width_mm = cfg.get("sla_image_width_mm", 10)
        finish_img_path = LABEL_ASSETS_DIR / "images" / "finish_time_attention.png"
        enough_img_path = LABEL_ASSETS_DIR / "images" / "enough_time_info.png"
        has_finish_img = finish_img_path.is_file()
        has_enough_img = enough_img_path.is_file()

        # Styles
        field_styles = cfg.get("fields", {}) or {}

        def fs(k: str):
            return field_styles.get(k, {}) or {}

        style_order = fs("ordernumber")
        style_name = fs("name")
        style_surname = fs("surname")
        style_address = fs("address")
        style_cargo_tr = fs("cargotrackingnumber")
        style_product = fs("product")
        style_qty = fs("qty")
        style_store = fs("storename")
        style_platform = fs("platform")
        # sla_hours_left için style gerekmiyor (görsel basıyoruz)

        # Flatten labels
        pages = label_payload["pages"]
        labels = [lbl for page in pages for lbl in page]
        total = len(labels)

        if not total:
            return Result.fail("Yazdırılacak etiket bulunamadı.")

        total_pages = math.ceil(total / labels_per_page)

        # Temp dir
        tmp_dir = Path(tempfile.gettempdir()) / "orderscout_label_pages"
        tmp_dir.mkdir(exist_ok=True)

        page_files = []

        # Style helper
        def style_text(value, st):
            if not value:
                return ""
            return _make_rich_text(
                value,
                font_name=st.get("font_name"),
                font_size=st.get("font_size"),
                color=st.get("color"),
                bold=st.get("bold"),
            )

        # ---------------------------------
        # PAGE LOOP
        # ---------------------------------
        for pidx in range(total_pages):
            try:
                doc = DocxTemplate(str(tp))
            except Exception as e:
                return Result.fail("Şablon yüklenemedi.", error=e)

            ctx = {}

            start = pidx * labels_per_page
            end = min(start + labels_per_page, total)
            num_this_page = end - start

            # ---------------------------------
            # LABEL LOOP
            # ---------------------------------
            for slot, global_idx in enumerate(range(start, end), start=1):
                lbl = labels[global_idx]
                n = slot

                order_no = (lbl.get("orderNumber") or "").strip()
                fullname = (lbl.get("fullname") or "").strip()
                address_val = (lbl.get("address") or "").strip()
                cargo_provider = (lbl.get("cargoProviderName") or "").strip()
                cargo_raw = (lbl.get("cargoTrackingNumber") or "").strip()

                store_name = (lbl.get("storeName") or "").strip()
                platform_val = (lbl.get("platform") or "").strip()

                # agreedDeliveryDate (ms)
                agreed_ms = lbl.get("agreedDeliveryDate_ms")

                barcode_val = cargo_raw or order_no
                is_primary = lbl.get("is_primary_for_order", True)

                # --------------------
                # İSİM (TEK STRING OLARAK)
                # --------------------
                # Eskiden fullname'i name + surname diye bölerdik.
                # Artık etikette tam ad tek parça gözükecek.
                full_name_display = fullname.strip()

                # --------------------
                # METİN ALANLARI
                # --------------------
                ctx[f"ordernumber_{n}"] = style_text(order_no, style_order)
                ctx[f"name_{n}"] = style_text(full_name_display, style_name)
                # surname placeholder'ı şablonda kalsa bile boş gönderiyoruz.
                ctx[f"surname_{n}"] = ""

                ctx[f"address_{n}"] = style_text(address_val, style_address)
                ctx[f"cargotrackingnumber_{n}"] = style_text(barcode_val, style_cargo_tr)

                ctx[f"storename_{n}"] = style_text(store_name, style_store)
                ctx[f"platform_{n}"] = style_text(platform_val, style_platform)

                # --------------------
                # SLA GÖRSELİ
                # --------------------
                sla_img = None
                if agreed_ms is not None:
                    try:
                        agreed_ms_int = int(agreed_ms)
                        deadline_utc = datetime.utcfromtimestamp(agreed_ms_int / 1000.0)
                        now_utc = datetime.utcnow()
                        delta_hours = (deadline_utc - now_utc).total_seconds() / 3600.0

                        if delta_hours <= 24 and has_finish_img:
                            sla_img = InlineImage(
                                doc,
                                str(finish_img_path),
                                width=Mm(sla_width_mm),
                            )
                        elif delta_hours > 24 and has_enough_img:
                            sla_img = InlineImage(
                                doc,
                                str(enough_img_path),
                                width=Mm(sla_width_mm),
                            )
                    except Exception:
                        sla_img = None

                ctx[f"sla_hours_left_{n}"] = sla_img if sla_img else ""

                # ---------------------------------
                # CARGO LOGO — yazı YOK, logo yoksa BOŞ
                # ---------------------------------
                cargo_logo_el = None

                if cargo_provider:
                    info = cargo_logo_cfg.get(cargo_provider)

                    if info:
                        logo_path = LABEL_ASSETS_DIR / "images" / info["filename"]

                        if logo_path.is_file():
                            try:
                                cargo_logo_el = InlineImage(
                                    doc,
                                    str(logo_path),
                                    width=Mm(info.get("width_mm", 12))
                                )
                            except Exception:
                                Result.ok(f"Kargo logosu işlenemedi: {cargo_provider}")
                        else:
                            Result.ok(f"Kargo logosu bulunamadı: {logo_path}")
                    else:
                        Result.ok(f"Kargo provider mapping bulunamadı: {cargo_provider}")

                ctx[f"cargoprovidername_{n}"] = cargo_logo_el if cargo_logo_el else ""

                # ---------------------------------
                # BARKOD / SPLIT UYARI
                # ---------------------------------
                if is_primary:
                    # Ana etiket → barkod bas
                    res_bar = generate_code128_barcode(
                        barcode_val,
                        writer_options=writer_opts,
                        save_path=None
                    )

                    if not res_bar.success:
                        Result.ok(f"Barkod üretilemedi: {barcode_val}")
                        ctx[f"barcode_{n}"] = ""
                    else:
                        ctx[f"barcode_{n}"] = InlineImage(
                            doc,
                            BytesIO(res_bar.data["png_bytes"]),

                            width=Mm(barcode_width),
                        )

                else:
                    # Split etiket → uyarı görseli
                    if has_attention_image:
                        kwargs = {"width": Mm(attention_w)}
                        if attention_h:
                            kwargs["height"] = Mm(attention_h)

                        ctx[f"barcode_{n}"] = InlineImage(
                            doc,
                            str(attention_path),
                            **kwargs
                        )
                    else:
                        Result.ok("Split uyarı görseli yok.")
                        ctx[f"barcode_{n}"] = ""

                # ---------------------------------
                # ÜRÜNLER
                # ---------------------------------
                for i in range(1, max_items + 1):
                    pkey = f"prod{i}"
                    qkey = f"qty{i}"

                    pv = lbl.get(pkey, "") or ""
                    qv = lbl.get(qkey, "")

                    ctx[f"{pkey}_{n}"] = style_text(pv, style_product)

                    if not qv:
                        ctx[f"{qkey}_{n}"] = ""
                    else:
                        try:
                            qint = int(qv)
                        except Exception:
                            qint = 0

                        color = "FF0000" if qint > 1 else style_qty.get("color")
                        bold = True if qint > 1 else style_qty.get("bold")

                        ctx[f"{qkey}_{n}"] = _make_rich_text(
                            str(qv),
                            font_name=style_qty.get("font_name"),
                            font_size=style_qty.get("font_size"),
                            color=color,
                            bold=bold,
                        )

            # ---------------------------------
            # BOŞ SLOT TEMİZLE
            # ---------------------------------
            for n in range(num_this_page + 1, labels_per_page + 1):
                ctx[f"ordernumber_{n}"] = ""
                ctx[f"name_{n}"] = ""
                ctx[f"surname_{n}"] = ""
                ctx[f"address_{n}"] = ""
                ctx[f"cargotrackingnumber_{n}"] = ""
                ctx[f"cargoprovidername_{n}"] = ""
                ctx[f"barcode_{n}"] = ""
                ctx[f"storename_{n}"] = ""
                ctx[f"platform_{n}"] = ""
                ctx[f"sla_hours_left_{n}"] = ""
                for i in range(1, max_items + 1):
                    ctx[f"prod{i}_{n}"] = ""
                    ctx[f"qty{i}_{n}"] = ""

            # ---------------------------------
            # SAYFAYI KAYDET
            # ---------------------------------
            try:
                doc.render(ctx)
                outp = tmp_dir / f"page_{pidx + 1}.docx"
                doc.save(outp)
                page_files.append(str(outp))
            except Exception as e:
                return Result.fail("Sayfa oluşturulamadı.", error=e)

            report(5 + (pidx + 1) * 90 / total_pages)

        # ---------------------------------
        # MERGE
        # ---------------------------------
        try:
            main_doc = Document(page_files[0])
            comp = Composer(main_doc)

            for pf in page_files[1:]:
                comp.append(Document(pf))

            comp.save(output_path)

        except Exception as e:
            return Result.fail("Word dosyaları birleştirilirken hata oluştu.", error=e)

        report(100)

        return Result.ok(
            f"{total} etiket başarıyla oluşturuldu.",
            close_dialog=False,
            data={"output_path": output_path}
        )

    except Exception as e:
        return Result.fail("Beklenmeyen hata.", error=e)
