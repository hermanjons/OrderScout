# Labels/pipeline.py

from __future__ import annotations

from Feedback.processors.pipeline import Result, map_error_to_message

# Seçili siparişleri toplamak için
from Orders.views.actions import collect_selected_orders

# Sipariş detaylarını (Header + Data + Item) getiren fonksiyon
from Orders.processors.trendyol_pipeline import get_order_full_details_by_numbers


def create_order_label_from_orders(list_widget) -> Result:
    """
    Seçili siparişlerden etiket üretimi için kullanılacak temel veriyi hazırlar.

    Adımlar:
      1) Orders.actions.collect_selected_orders(list_widget) ile
         kullanıcı tarafından seçilmiş siparişleri alır.
         -> selected_orders = [orderNumber, orderNumber, ...]

      2) Orders.pipeline.get_order_full_details_by_numbers(selected_orders)
         ile bu siparişlerin tüm detaylarını çeker.
         -> Header, OrderData, OrderItem seviyesinde full bilgi.

      3) Şimdilik sadece bu detayları Result.data içinde geri döner.
         İleride bu fonksiyon genişletilerek:
            - etiket satırlarını normalize eden,
            - seçilen marka/model'e göre layout hazırlayan
            bir label payload üreticisine dönüşecek.

    Dönüş (success durumunda):
        Result.data = {
            "selected_order_numbers": [...],
            "orders": [
                {
                    "header": OrderHeader,
                    "data": [OrderData, ...],
                    "items": [OrderItem, ...],
                },
                ...
            ],
            "headers": [OrderHeader, ...],
            "order_data_list": [OrderData, ...],
            "order_item_list": [OrderItem, ...],
        }
    """

    try:
        # 1️⃣ Seçili siparişleri al
        sel_res = collect_selected_orders(list_widget)
        if not sel_res or not isinstance(sel_res, Result):
            return Result.fail("Seçili siparişler okunamadı (geçersiz Result).", close_dialog=False)

        if not sel_res.success:
            # "Hiçbir sipariş seçilmedi." gibi mesajlar zaten içinde
            return sel_res

        selected_orders = sel_res.data.get("selected_orders", []) or []
        if not selected_orders:
            return Result.fail("Hiçbir sipariş seçilmedi.", close_dialog=False)

        # 2️⃣ Seçili siparişlerin tüm detaylarını çek
        detail_res = get_order_full_details_by_numbers(selected_orders)
        if not detail_res or not isinstance(detail_res, Result):
            return Result.fail("Sipariş detayları alınamadı (geçersiz Result).", close_dialog=False)

        if not detail_res.success:
            return detail_res

        detail_data = detail_res.data or {}

        # 3️⃣ Şimdilik sadece detayları geri sarıyoruz
        #    (ileride burada label payload üretimine geçeceğiz)
        return Result.ok(
            detail_res.message or "Seçili siparişlerin detayları alındı.",
            close_dialog=False,
            data={
                "selected_order_numbers": selected_orders,
                "orders": detail_data.get("orders", []),
                "headers": detail_data.get("headers", []),
                "order_data_list": detail_data.get("order_data_list", []),
                "order_item_list": detail_data.get("order_item_list", []),
            }
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
