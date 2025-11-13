# Labels/pipeline.py
from __future__ import annotations

from Feedback.processors.pipeline import Result, map_error_to_message
from Core.utils.model_utils import batch_iter  # 8'li kırpmak için
# Seçili siparişleri toplamak için
from Orders.views.actions import collect_selected_orders
# Sipariş detaylarını (Header+Data+Item) getiren fonksiyon
from Orders.processors.trendyol_pipeline import get_order_full_details_by_numbers


def create_order_label_from_orders(list_widget, *, max_items_per_label: int = 8) -> Result:
    """
    Seçili siparişlerden **Word şablonuna yazdırılmaya hazır** label payload üretir.

    DÖNÜŞ (success):
    Result.data = {
        # ham
        "selected_order_numbers": [...],
        "orders": [{ "header": H, "data":[...], "items":[...] }, ...],
        "headers": [...],
        "order_data_list": [...],
        "order_item_list": [...],

        # basıma hazır
        "label_payload": {
            "max_items_per_label": 8,
            "total_labels": N,
            "labels": [
                {
                    "order_number": "...",
                    "api_account_id": 123,
                    "barcode_text": "...",    # üstteki büyük barkod alanı
                    "items": [                 # alttaki 8 küçük kutu
                        {
                            "qty": 1,
                            "size": "Tek Ebat",
                            "merchant_sku": "ANTSTTK234MDBS22",
                            "product_name": "Anti Statik Esnek Uçlu ...",
                            "order_line_status": "ReadyToShip",
                            "product_code": "784195",
                            "order_item_id": 1127192619,
                        },
                        ...
                    ],
                    "item_count": 6,
                    "page_index": 1,          # aynı siparişin 2. etiketi vs.
                    "page_count": 2
                },
                ...
            ]
        }
    }
    """
    try:
        # 1) Seçili siparişleri al
        sel_res = collect_selected_orders(list_widget)
        if not sel_res or not isinstance(sel_res, Result):
            return Result.fail("Seçili siparişler okunamadı (geçersiz Result).", close_dialog=False)
        if not sel_res.success:
            return sel_res

        selected_orders = sel_res.data.get("selected_orders") or []
        if not selected_orders:
            return Result.fail("Hiçbir sipariş seçilmedi.", close_dialog=False)

        # 2) Seçili siparişlerin tüm detaylarını çek
        detail_res = get_order_full_details_by_numbers(selected_orders)
        if not detail_res or not isinstance(detail_res, Result):
            return Result.fail("Sipariş detayları alınamadı (geçersiz Result).", close_dialog=False)
        if not detail_res.success:
            return detail_res

        detail_data = detail_res.data or {}
        orders = detail_data.get("orders", []) or []

        # 3) Her siparişi 8'li item bloklarına bölerek label listesi üret
        labels = []
        for o in orders:
            header = o.get("header")
            items = o.get("items") or []

            order_number = getattr(header, "orderNumber", None) if header else None
            api_account_id = getattr(header, "api_account_id", None) if header else None

            # OrderItem'tan gerekli alanları sadeleştir
            norm_items = []
            for oi in items:
                # hem SQLModel objesi hem dict olabilir:
                def g(x, name, alt=None):
                    if hasattr(x, name):
                        return getattr(x, name)
                    if isinstance(x, dict):
                        return x.get(name, alt)
                    return alt

                qty = g(oi, "quantity", 1)
                size = g(oi, "size") or g(oi, "variantName") or g(oi, "skuOption") or ""
                merchant_sku = g(oi, "merchantSku") or g(oi, "merchantSKU") or g(oi, "sku") or g(oi, "stockCode") or ""
                product_name = g(oi, "productName") or g(oi, "name") or g(oi, "title") or ""
                order_line_status = g(oi, "orderLineItemStatusName", "")
                product_code = g(oi, "productCode") or g(oi, "barcode") or ""
                order_item_id = g(oi, "id") or g(oi, "orderItemId")

                try:
                    qty = int(qty)
                except Exception:
                    pass

                norm_items.append({
                    "qty": qty,
                    "size": size,
                    "merchant_sku": merchant_sku,
                    "product_name": product_name,
                    "order_line_status": order_line_status,
                    "product_code": product_code,
                    "order_item_id": order_item_id,
                })

            # hiç item yoksa da barkodlu boş label (opsiyonel—şimdilik üretiyoruz)
            if not norm_items:
                labels.append({
                    "order_number": order_number,
                    "api_account_id": api_account_id,
                    "barcode_text": str(order_number) if order_number is not None else "",
                    "items": [],
                    "item_count": 0,
                    "page_index": 1,
                    "page_count": 1,
                })
                continue

            chunks = list(batch_iter(norm_items, size=max_items_per_label))
            page_count = len(chunks) or 1

            for idx, chunk in enumerate(chunks, start=1):
                labels.append({
                    "order_number": order_number,
                    "api_account_id": api_account_id,
                    "barcode_text": str(order_number) if order_number is not None else "",
                    "items": chunk,
                    "item_count": len(chunk),
                    "page_index": idx,
                    "page_count": page_count,
                })

        # 4) Sonucu sar ve dön
        out = {
            # ham
            "selected_order_numbers": selected_orders,
            "orders": orders,
            "headers": detail_data.get("headers", []),
            "order_data_list": detail_data.get("order_data_list", []),
            "order_item_list": detail_data.get("order_item_list", []),

            # basıma hazır
            "label_payload": {
                "max_items_per_label": max_items_per_label,
                "total_labels": len(labels),
                "labels": labels,
            }
        }

        return Result.ok(
            detail_res.message or "Seçili siparişler hazırlandı ve etiket payload'ı üretildi.",
            close_dialog=False,
            data=out
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
