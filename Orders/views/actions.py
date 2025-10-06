# ============================================================
# 🧠 CORE IMPORTS
# ============================================================
from __future__ import annotations

from PyQt6.QtWidgets import QListWidgetItem, QLabel
from PyQt6.QtCore import Qt
from Core.views.views import SwitchButton, ListSmartItemWidget
from Core.threads.async_worker import AsyncWorker
from Core.threads.sync_worker import SyncWorker
from Core.utils.model_utils import get_engine
from Core.utils.time_utils import time_for_now, time_stamp_calculator
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message
from settings import MEDIA_ROOT

# ============================================================
# 🧩 DOMAIN IMPORTS
# ============================================================
from Orders.processors.trendyol_pipeline import (
    fetch_orders_all,
    save_orders_to_db,
    get_latest_ready_to_ship_orders
)
from Orders.constants.trendyol_constants import TRENDYOL_STATUS_LIST
from Account.models import ApiAccount
from Account.views.actions import collect_selected_companies, get_company_by_id
from datetime import datetime, date


# ============================================================
# 🔹 1. OrdersListWidget — Liste render ve seçim yönetimi
# ============================================================

def resolve_order_logo_path(order) -> str:
    """
    Siparişin bağlı olduğu hesabın logosunu döndürür.
    Hesapta logo yoksa varsayılan sipariş görseli kullanılır.
    """
    if getattr(order, "api_account", None) and getattr(order.api_account, "logo_path", None):
        return order.api_account.logo_path
    return "images/orders_img.png"


def format_order_summary(order) -> dict:
    """
    Siparişin UI’da gösterilecek metinlerini biçimlendirir.
    Bu fonksiyon farklı alanlarda (liste, detay, PDF, e-posta vb.)
    tekrar kullanılabilir.
    """
    return {
        "title": f"Order: {getattr(order, 'orderNumber', '—')}",
        "subtitle": f"Müşteri: {getattr(order, 'customerFirstName', '—')} "
                    f"{getattr(order, 'customerLastName', '')}",
        "extra": f"Kargo: {getattr(order, 'cargoProviderName', '-')} | "
                 f"Tutar: {getattr(order, 'totalPrice', 0)} ₺",
        "identifier": getattr(order, "orderNumber", "—"),
        "logo_path": resolve_order_logo_path(order)
    }


def build_order_list(list_widget, orders: list, interaction_cb=None, selection_cb=None) -> Result:
    """
    Sipariş listesini verilen QListWidget içine inşa eder.
    UI elemanlarını oluşturur ve sinyalleri bağlar.
    """
    try:
        list_widget.clear()

        # 📭 Boş liste durumu
        if not orders:
            info_item = QListWidgetItem("Gösterilecek sipariş bulunamadı.")
            info_item.setFlags(info_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            list_widget.addItem(info_item)
            return Result.ok("Liste boş, sipariş bulunamadı.", data={"count": 0})

        added = 0
        for order in orders:
            display = format_order_summary(order)
            switch = SwitchButton()

            item_widget = ListSmartItemWidget(
                title=display["title"],
                subtitle=display["subtitle"],
                extra=display["extra"],
                identifier=display["identifier"],
                icon_path=display["logo_path"],
                optional_widget=switch
            )

            if interaction_cb:
                item_widget.interaction.connect(interaction_cb)
            if selection_cb:
                item_widget.selectionRequested.connect(selection_cb)

            item = QListWidgetItem(list_widget)
            item.setSizeHint(item_widget.sizeHint())
            list_widget.setItemWidget(item, item_widget)
            added += 1

        return Result.ok(f"{added} sipariş başarıyla listelendi.", data={"count": added})

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


def update_selected_count_label(list_widget, label: QLabel) -> Result:
    """
    SwitchButton durumlarına bakarak seçili sipariş sayısını hesaplar
    ve label üzerinde gösterir.
    """
    try:
        if list_widget.count() == 0:
            if label:
                label.setText("Seçili sipariş sayısı: 0")
            return Result.fail("Listede sipariş bulunamadı.", close_dialog=False)

        count = 0
        for i in range(list_widget.count()):
            widget = list_widget.itemWidget(list_widget.item(i))
            if widget and getattr(widget, "right_widget", None):
                if widget.right_widget.isChecked():
                    count += 1

        if label:
            label.setText(f"Seçili sipariş sayısı: {count}")

        return Result.ok(
            f"Seçili sipariş sayısı güncellendi: {count}",
            close_dialog=False,
            data={"count": count}
        )

    except Exception as e:
        msg = map_error_to_message(e)
        return Result.fail(msg, error=e, close_dialog=False)


def collect_selected_orders(list_widget) -> Result:
    """
    QListWidget içindeki SwitchButton'lara bakarak seçili siparişleri döndürür.
    """
    try:
        if list_widget.count() == 0:
            return Result.fail("Listede sipariş bulunamadı.", close_dialog=False)

        selected = []
        for i in range(list_widget.count()):
            widget = list_widget.itemWidget(list_widget.item(i))
            if widget and isinstance(widget.right_widget, SwitchButton):
                if widget.right_widget.isChecked():
                    selected.append(widget.identifier)

        if not selected:
            return Result.fail("Hiçbir sipariş seçilmedi.", close_dialog=False)

        return Result.ok(
            f"{len(selected)} sipariş seçildi.",
            close_dialog=False,
            data={"selected_orders": selected}
        )

    except Exception as e:
        msg = map_error_to_message(e)
        return Result.fail(msg, error=e, close_dialog=False)


def extract_cargo_names(orders: list) -> list[str]:
    """
    Sipariş listesinden kargo firma isimlerini çıkarır (tekrarsız, sıralı).
    """
    return sorted({
        getattr(o, "cargoProviderName", None)
        for o in orders if getattr(o, "cargoProviderName", None)
    })


# ============================================================
# 🔹 2. OrdersManagerWindow — Pipeline’dan veri yükleme
# ============================================================

def load_ready_to_ship_orders() -> Result:
    """
    Pipeline'dan ReadyToShip siparişleri alır ve UI için hazırlar.
    Bu katman yalnızca veri düzenleme/filtreleme yapar, UI mesajı göstermez.
    """
    result = get_latest_ready_to_ship_orders()

    if not result.success:
        return result

    orders = result.data.get("orders", [])
    return Result.ok("ReadyToShip siparişler başarıyla yüklendi.", data={"records": orders})


# ============================================================
# 🔹 3. OrdersTab — API'den sipariş çekme (Trendyol)
# ============================================================

def get_orders_from_companies(parent_widget, company_list_widget, progress_target) -> Result:
    """
    Seçilen şirketlerden API bilgilerini alır ve worker başlatır.
    UI ile ilgili mesaj/Popup işlemleri sadece views.py'de yapılmalı.
    """
    try:
        # 1️⃣ Seçilen şirketleri topla
        result = collect_selected_companies(company_list_widget)
        if not result.success:
            return result

        selected_company_pks = result.data["selected_company_pks"]

        # 2️⃣ API credential’ları getir
        res_creds = get_company_by_id(selected_company_pks)
        if not res_creds.success:
            return res_creds

        comp_api_account_list = res_creds.data.get("accounts", [])
        if not comp_api_account_list:
            return Result.fail("Seçili şirketler için API bilgisi bulunamadı.", close_dialog=False)

        # 3️⃣ Zaman aralığını belirle
        search_range_hour = 200
        start_ep_time = time_for_now()
        final_ep_time = time_for_now() - time_stamp_calculator(search_range_hour)

        # 4️⃣ Async Worker başlat (API)
        parent_widget.api_worker = AsyncWorker(
            fetch_orders_all,
            TRENDYOL_STATUS_LIST,
            final_ep_time,
            start_ep_time,
            comp_api_account_list,
            kwargs={"progress_callback": lambda c, t: update_progress(progress_target, c, t)},
            parent=parent_widget
        )

        # 📌 Callback zinciri
        def handle_api_result(res: Result):
            if not res.success:
                parent_widget.on_orders_failed(res, progress_target)
                return

            # ✅ API başarılı → DB Worker başlat
            parent_widget.db_worker = SyncWorker(save_orders_to_db, res)

            def handle_db_result(db_res: Result):
                if not db_res.success:
                    parent_widget.on_orders_failed(db_res, progress_target)
                else:
                    parent_widget.on_orders_fetched(db_res)

            parent_widget.db_worker.result_ready.connect(handle_db_result)
            parent_widget.db_worker.start()

        parent_widget.api_worker.result_ready.connect(handle_api_result)
        parent_widget.api_worker.start()

        return Result.ok("Worker başlatıldı.", close_dialog=False)

    except Exception as e:
        msg = map_error_to_message(e)
        return Result.fail(msg, error=e, close_dialog=False)


def update_progress(view_instance, current: int, total: int):
    """
    İşlem ilerlemesini hesapla ve UI'daki progress butonunu güncelle.
    """
    try:
        percent = int(current / total * 100) if total else 0
        view_instance.setProgress(percent)
        return Result.ok(f"Progress {percent}% olarak güncellendi.", close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def filter_orders(orders: list, filters: dict) -> Result:
    """
    Sipariş listesini verilen filtrelere göre süzer.

    Args:
        orders (list): Tam sipariş listesi
        filters (dict): {
            "global": "aranan",
            "order_no": "123",
            "cargo": "Yurtiçi Kargo",
            "customer": "Ali",
            "date_enabled": True,
            "date_from": date,
            "date_to": date
        }
    """
    try:
        filtered = list(orders)

        global_text = filters.get("global", "").lower()
        search_text = filters.get("order_no", "").lower()
        cargo_text = filters.get("cargo")
        customer_text = filters.get("customer", "").lower()
        date_enabled = filters.get("date_enabled", False)
        df = filters.get("date_from")
        dt = filters.get("date_to")

        def coerce_date(v) -> date | None:
            if v is None:
                return None
            if isinstance(v, date) and not isinstance(v, datetime):
                return v
            if isinstance(v, datetime):
                return v.date()
            if isinstance(v, (int, float)):
                return datetime.fromtimestamp(v).date()
            if isinstance(v, str):
                for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y", "%Y/%m/%d"):
                    try:
                        return datetime.strptime(v, fmt).date()
                    except Exception:
                        pass
            return None

        def get_order_date(o) -> date | None:
            for attr in ("shipmentDate", "orderDate", "createdDate"):
                d = coerce_date(getattr(o, attr, None))
                if d:
                    return d
            return None

        # --- global search
        if global_text:
            temp = []
            for o in filtered:
                items = getattr(o, "items", None) or []
                in_items = any(
                    global_text in str(getattr(it, "productName", "")).lower()
                    or global_text in str(getattr(it, "productSku", "")).lower()
                    for it in items
                )
                if (
                        global_text in str(getattr(o, "orderNumber", "")).lower()
                        or global_text in str(getattr(o, "cargoProviderName", "")).lower()
                        or global_text in str(getattr(o, "customerFirstName", "")).lower()
                        or in_items
                ):
                    temp.append(o)
            filtered = temp

        if search_text:
            filtered = [o for o in filtered if search_text in str(getattr(o, "orderNumber", "")).lower()]

        if cargo_text and cargo_text != "Tümü":
            filtered = [o for o in filtered if getattr(o, "cargoProviderName", None) == cargo_text]

        if customer_text:
            filtered = [o for o in filtered if customer_text in str(getattr(o, "customerFirstName", "")).lower()]

        if date_enabled and df and dt:
            tmp = []
            for o in filtered:
                od = get_order_date(o)
                if od and df <= od <= dt:
                    tmp.append(o)
            filtered = tmp

        return Result.ok("Filtre uygulandı.", data={"filtered": filtered})

    except Exception as e:
        from Feedback.processors.pipeline import map_error_to_message
        return Result.fail(map_error_to_message(e), error=e)
