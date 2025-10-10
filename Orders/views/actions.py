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
    logo = getattr(getattr(order, "api_account", None), "logo_path", None)
    if logo:
        return logo
    return "images/orders_img.png"


def format_order_summary(order) -> dict:
    """
    Siparişin UI’da gösterilecek metinlerini biçimlendirir.
    Farklı katmanlarda (liste, detay, PDF) tekrar kullanılabilir.
    """
    total = getattr(order, "totalPrice", 0)
    try:
        total_fmt = f"{float(total):,.2f}".replace(",", ".")  # 1.234,50 ₺ formatına yakın
    except Exception:
        total_fmt = total

    date_part = getattr(order, "orderDate", None)
    if isinstance(date_part, datetime):
        date_str = date_part.strftime("%d.%m.%Y")
    else:
        date_str = str(date_part or "—")

    return {
        "title": f"Sipariş: {getattr(order, 'orderNumber', '—')}",
        "subtitle": f"Müşteri: {getattr(order, 'customerFirstName', '—')} {getattr(order, 'customerLastName', '')}",
        "extra": f"Kargo: {getattr(order, 'cargoProviderName', '-')} | "
                 f"Tarih: {date_str} | Tutar: {total_fmt} ₺",
        "identifier": getattr(order, "orderNumber", "—"),
        "logo_path": resolve_order_logo_path(order),
    }


def build_order_list(list_widget, orders: list, interaction_cb=None, selection_cb=None) -> Result:
    """
    Sipariş listesini verilen QListWidget içine inşa eder.
    UI elemanlarını oluşturur ve sinyalleri bağlar.
    """
    try:
        # 🧽 Qt leak fix (widgetları temizle)
        for i in range(list_widget.count()):
            w = list_widget.itemWidget(list_widget.item(i))
            if w:
                w.deleteLater()
        list_widget.clear()

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
                optional_widget=switch,
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


def update_selected_count_label(list_widget, label: QLabel | None = None) -> Result:
    """
    SwitchButton durumlarına bakarak seçili sipariş sayısını hesaplar.
    İstenirse label üzerinde gösterir.
    """
    try:
        count = sum(
            1 for i in range(list_widget.count())
            if getattr(list_widget.itemWidget(list_widget.item(i)), "right_widget", None)
            and list_widget.itemWidget(list_widget.item(i)).right_widget.isChecked()
        )

        if label:
            label.setText(f"Seçili: {count}")

        return Result.ok("Seçili sayısı güncellendi.", data={"count": count}, close_dialog=False)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def collect_selected_orders(list_widget) -> Result:
    """
    QListWidget içindeki SwitchButton'lara bakarak seçili siparişleri döndürür.
    """
    try:
        selected = []
        for i in range(list_widget.count()):
            w = list_widget.itemWidget(list_widget.item(i))
            if not w:
                continue
            btn = getattr(w, "right_widget", None)
            if btn and btn.isChecked():
                selected.append(w.identifier)

        if not selected:
            return Result.fail("Hiçbir sipariş seçilmedi.", close_dialog=False)

        return Result.ok(f"{len(selected)} sipariş seçildi.", data={"selected_orders": selected}, close_dialog=False)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def extract_cargo_names(orders: list) -> list[str]:
    """Sipariş listesinden tekrarsız ve alfabetik sıralı kargo firma adlarını döndürür."""
    return sorted(
        {getattr(o, "cargoProviderName", "").strip() for o in orders if getattr(o, "cargoProviderName", None)})


# ============================================================
# 🔹 2. OrdersManagerWindow — Pipeline’dan veri yükleme
# ============================================================

def load_ready_to_ship_orders() -> Result:
    """ReadyToShip siparişleri pipeline’dan çeker ve UI için döndürür."""
    try:
        result = get_latest_ready_to_ship_orders()
        if not result.success:
            return result
        return Result.ok("ReadyToShip siparişler yüklendi.", data={"records": result.data.get("orders", [])})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


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
    Çok büyük datasetlerde de CPU dostu.
    """
    try:
        filtered = list(orders)

        gtxt = filters.get("global", "").lower()
        order_no = filters.get("order_no", "").lower()
        cargo = filters.get("cargo")
        customer = filters.get("customer", "").lower()
        date_enabled = filters.get("date_enabled", False)
        df = filters.get("date_from")
        dt = filters.get("date_to")

        def get_order_date(o) -> date | None:
            for attr in ("shipmentDate", "orderDate", "createdDate"):
                d = getattr(o, attr, None)
                if isinstance(d, datetime):
                    return d.date()
                if isinstance(d, date):
                    return d
            return None

        if gtxt:
            gtxt = gtxt.strip()
            new = []
            for o in filtered:
                items = getattr(o, "items", [])
                if any(gtxt in str(getattr(it, "productName", "")).lower() or gtxt in str(
                        getattr(it, "productSku", "")).lower() for it in items) \
                        or any(gtxt in str(getattr(o, f, "")).lower() for f in
                               ("orderNumber", "cargoProviderName", "customerFirstName")):
                    new.append(o)
            filtered = new

        if order_no:
            filtered = [o for o in filtered if order_no in str(getattr(o, "orderNumber", "")).lower()]

        if cargo and cargo != "Tümü":
            filtered = [o for o in filtered if getattr(o, "cargoProviderName", None) == cargo]

        if customer:
            filtered = [o for o in filtered if customer in str(getattr(o, "customerFirstName", "")).lower()]

        if date_enabled and df and dt:
            filtered = [o for o in filtered if (d := get_order_date(o)) and df <= d <= dt]

        return Result.ok("Filtre uygulandı.", data={"filtered": filtered})

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


# actions.py içine (örneğin "🔹 4. UI yardımcıları" altına)

def refresh_cargo_filter(cargo_combobox, orders: list) -> Result:
    """Sipariş listesinden kargo isimlerini çekip combobox’a ekler."""
    try:
        cargo_combobox.blockSignals(True)
        cargo_combobox.clear()
        cargo_combobox.addItem("Tümü")

        cargos = extract_cargo_names(orders)
        cargo_combobox.addItems(cargos)

        return Result.ok("Kargo filtreleri güncellendi.", close_dialog=False)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)
    finally:
        cargo_combobox.blockSignals(False)


# actions.py içine (örneğin "🔹 5. Filtreleme yönetimi" altına)
def start_filter_worker(parent_widget, list_widget, filters: dict) -> SyncWorker:
    """Filtre işlemini SyncWorker ile başlatır ve sonuç sinyali döner."""
    worker = SyncWorker(filter_orders, list_widget.orders, filters)

    def handle_filter_result(result: Result):
        if not result.success:
            MessageHandler.show(parent_widget, result, only_errors=True)
            parent_widget.selected_count_label.setText("⚠️ Filtreleme başarısız.")
            return

        filtered = result.data.get("filtered", [])
        list_widget.apply_filter_result(filtered)
        parent_widget._update_label()
        parent_widget.selected_count_label.setText(f"✅ Filtre tamamlandı. (Kalan: {len(filtered)})")

    worker.result_ready.connect(handle_filter_result)
    return worker
