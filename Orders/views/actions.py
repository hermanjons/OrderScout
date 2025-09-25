# Orders/views/actions.py
from Core.threads.async_worker import AsyncWorker
from Core.threads.sync_worker import SyncWorker
from Orders.processors.trendyol_pipeline import fetch_orders_all, save_orders_to_db, get_latest_ready_to_ship_orders
from Orders.constants.trendyol_constants import TRENDYOL_STATUS_LIST
from Core.utils.time_utils import time_for_now, time_stamp_calculator
from PyQt6.QtWidgets import QListWidgetItem
from Core.views.views import SwitchButton, ListSmartItemWidget
import os
from settings import MEDIA_ROOT
from Core.utils.model_utils import get_records
from Account.models import ApiAccount
from Core.utils.model_utils import get_engine  # engine değişkeni nerede tanımlıysa onu import et
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message
from PyQt6.QtWidgets import QLabel
from Account.views.actions import collect_selected_companies, get_company_by_id


def fetch_ready_to_ship_orders(parent_widget):
    """
    ReadyToShip siparişleri DB'den çek ve UI'ya aktar.
    """
    result = get_latest_ready_to_ship_orders()
    if not result.success:
        MessageHandler.show(parent_widget, result, only_errors=True)
        return []

    return result.data.get("orders", [])


def build_orders_list(list_widget, orders, interaction_cb, selection_cb) -> Result:
    """
    Sipariş listesini QListWidget içine inşa eder.
    """
    try:
        if not orders:
            list_widget.clear()
            return Result.fail("Gösterilecek sipariş bulunamadı.", close_dialog=False)

        list_widget.clear()

        for order in orders:
            # 🔑 API logosunu doğrudan ilişki üzerinden al
            logo_path = "images/orders_img.png"
            if getattr(order, "api_account", None) and getattr(order.api_account, "logo_path", None):
                logo_path = order.api_account.logo_path

            switch = SwitchButton()
            item_widget = ListSmartItemWidget(
                title=f"Order: {getattr(order, 'orderNumber', '—')}",
                subtitle=f"Müşteri: {getattr(order, 'customerFirstName', '—')} "
                         f"{getattr(order, 'customerLastName', '')}",
                extra=f"Kargo: {getattr(order, 'cargoProviderName', '-')} | "
                      f"Tutar: {getattr(order, 'totalPrice', 0)} ₺",
                identifier=getattr(order, 'orderNumber', '—'),
                icon_path=logo_path,
                optional_widget=switch
            )

            # Etkileşimler
            item_widget.interaction.connect(interaction_cb)
            item_widget.selectionRequested.connect(selection_cb)

            # Listeye ekle
            item = QListWidgetItem(list_widget)
            item.setSizeHint(item_widget.sizeHint())
            list_widget.setItemWidget(item, item_widget)

        return Result.ok("Siparişler başarıyla listeye eklendi.", close_dialog=False)

    except Exception as e:
        msg = map_error_to_message(e)
        return Result.fail(msg, error=e)



def update_selected_count_label(list_widget, label: QLabel) -> Result:
    """
    SwitchButton durumlarına bakarak seçili sipariş sayısını hesaplar
    ve label üzerinde gösterir.
    """
    try:
        if list_widget.count() == 0:
            label.setText("Seçili sipariş sayısı: 0")
            return Result.fail("Listede sipariş bulunamadı.", close_dialog=False)

        count = 0
        for i in range(list_widget.count()):
            widget = list_widget.itemWidget(list_widget.item(i))
            if widget and getattr(widget, "right_widget", None):
                if widget.right_widget.isChecked():
                    count += 1

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


# actions.py
def get_orders_from_companies(parent_widget, company_list_widget, progress_target):
    """
    Seçilen şirketlerden API bilgilerini alır ve worker başlatır.
    UI ile ilgili mesaj/Popup işlemleri views.py'de yapılmalı.
    """

    try:
        # 1) Listeden seçilen PK’leri topla
        result = collect_selected_companies(company_list_widget)
        if not result.success:
            return result  # ❌ Hata → views.py handle eder

        selected_company_pks = result.data["selected_company_pks"]

        # 2) API credential’ları pk listesi ile getir
        res_creds = get_company_by_id(selected_company_pks)
        if not res_creds.success:
            return res_creds  # ❌ API bilgisi bulunamadı

        comp_api_account_list = res_creds.data.get("accounts", [])
        if not comp_api_account_list:
            return Result.fail("Seçili şirketler için API bilgisi bulunamadı.", close_dialog=False)

        # 3) Worker başlat
        search_range_hour = 200
        start_ep_time = time_for_now()
        final_ep_time = time_for_now() - time_stamp_calculator(search_range_hour)

        # 1️⃣ API Worker (async)
        parent_widget.api_worker = AsyncWorker(
            fetch_orders_all,
            TRENDYOL_STATUS_LIST,
            final_ep_time,
            start_ep_time,
            comp_api_account_list,
            kwargs={"progress_callback": lambda c, t: update_progress(progress_target, c, t)},
            parent=parent_widget
        )

        def handle_api_result(res: Result):
            if not res.success:
                MessageHandler.show(parent_widget, res, only_errors=True)
                return

            # 2️⃣ DB Worker (sync)
            parent_widget.db_worker = SyncWorker(save_orders_to_db, res)
            parent_widget.db_worker.result_ready.connect(
                lambda db_res: MessageHandler.show(parent_widget, db_res)
            )
            parent_widget.db_worker.finished.connect(parent_widget.on_orders_fetched)
            parent_widget.db_worker.start()

        # API Worker tamamlandığında handle_api_result çağrılır
        parent_widget.api_worker.result_ready.connect(handle_api_result)
        parent_widget.api_worker.start()

        return Result.ok("Worker başlatıldı.", close_dialog=False)

    except Exception as e:
        res = Result.fail(map_error_to_message(e), error=e, close_dialog=False)
        MessageHandler.show(parent_widget, res, only_errors=True)
        return res


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
