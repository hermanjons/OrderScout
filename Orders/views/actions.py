# Orders/views/actions.py
from Core.threads.async_worker import AsyncWorker
from Orders.processors.trendyol_pipeline import fetch_orders_all, save_orders_to_db, get_latest_ready_to_ship_orders
from Orders.constants.trendyol_constants import trendyol_status_list
from Core.utils.time_utils import time_for_now, time_stamp_calculator
from PyQt6.QtWidgets import QListWidgetItem
from Core.views.views import SwitchButton, ListSmartItemWidget
import os
from settings import MEDIA_ROOT
from Core.utils.model_utils import get_records
from Account.models import ApiAccount
from Core.utils.model_utils import get_engine  # engine değişkeni nerede tanımlıysa onu import et
from Feedback.processors.pipeline import MessageHandler, Result
from PyQt6.QtWidgets import QLabel




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
            switch = SwitchButton()
            item_widget = ListSmartItemWidget(
                title=f"Order: {getattr(order, 'orderNumber', '—')}",
                subtitle=f"Müşteri: {getattr(order, 'customerFirstName', '—')} "
                         f"{getattr(order, 'customerLastName', '')}",
                extra=f"Kargo: {getattr(order, 'cargoProviderName', '-')} | "
                      f"Tutar: {getattr(order, 'totalPrice', 0)} ₺",
                identifier=getattr(order, 'orderNumber', '—'),
                icon_path="images/orders_img.png",
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





def get_company_names_from_db() -> list[str]:
    """
    Veritabanından tüm şirket isimlerini çeker.
    """
    company_objs = get_records(model=ApiAccount, db_engine=get_engine("orders.db"))
    return [c.comp_name for c in company_objs]


def get_orders_from_companies(parent_widget, selected_names: list[str]):
    comp_api_account_list = get_api_credentials_by_names(selected_names)

    if not comp_api_account_list:
        parent_widget.info_label.setText("❌ Seçili şirketler için API bilgisi bulunamadı.")
        return

    fetch_with_worker(parent_widget, comp_api_account_list)


def get_api_credentials_by_names(names: list[str]) -> list[list[str]]:
    """
    Belirtilen şirket isimlerine karşılık gelen api hesabı bilgilerini getirir.
    Geriye [pk, api_key, api_secret, seller_id] sırasıyla bir liste döner.
    """
    engine = get_engine("orders.db")
    all_records = get_records(model=ApiAccount, db_engine=engine)

    selected = [r for r in all_records if r.comp_name in names]

    return [[r.pk, r.api_key, r.api_secret, str(r.account_id)] for r in selected]


# Bu fonksiyon view içinden çağrılır
def fetch_with_worker(view_instance, comp_api_account_list):
    try:
        search_range_hour = 240
        start_ep_time = time_for_now()
        final_ep_time = time_for_now() - time_stamp_calculator(search_range_hour)

        view_instance.worker = AsyncWorker(
            fetch_orders_all,
            trendyol_status_list,
            final_ep_time,
            start_ep_time,
            comp_api_account_list,
            kwargs={"progress_callback": view_instance.update_progress},
            parent=view_instance
        )

        view_instance.worker.result_ready.connect(
            lambda res: MessageHandler.show(view_instance, save_orders_to_db(res))
        )
        view_instance.worker.finished.connect(view_instance.on_orders_fetched)
        view_instance.worker.start()

    except Exception as e:
        print("fetch_with_worker hatası:", e)


def populate_company_list(list_widget, company_names: list[str], interaction_callback):
    list_widget.clear()

    for name in company_names:
        item = QListWidgetItem()
        switch = SwitchButton()
        switch.setChecked(True)

        sanitized_name = name.lower().replace(" ", "_")
        icon_path = os.path.join(MEDIA_ROOT, f"{sanitized_name}.png")
        if not os.path.exists(icon_path):
            icon_path = None

        widget = ListSmartItemWidget(
            title=name,
            identifier=name,
            icon_path=icon_path,
            optional_widget=switch,
        )
        widget.interaction.connect(interaction_callback)
        item.setSizeHint(widget.sizeHint())
        list_widget.addItem(item)
        list_widget.setItemWidget(item, widget)

        # 🔥 EKLENDİ: başlangıçta aktif olduğunu sinyalle!
        interaction_callback(name, True)
