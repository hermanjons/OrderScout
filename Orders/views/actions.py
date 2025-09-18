# Orders/views/actions.py
from Core.threads.async_worker import AsyncWorker
from Orders.processors.trendyol_pipeline import fetch_orders_all, save_orders_to_db
from Orders.constants.trendyol_constants import trendyol_status_list
from Core.utils.time_utils import time_for_now, time_stamp_calculator
from PyQt6.QtWidgets import QListWidgetItem
from Core.views.views import SwitchButton, ListSmartItemWidget
import os
from settings import MEDIA_ROOT
from Core.utils.model_utils import get_records
from Account.models import ApiAccount
from Core.utils.model_utils import get_engine  # engine değişkeni nerede tanımlıysa onu import et




def get_company_names_from_db() -> list[str]:
    """
    Veritabanından tüm şirket isimlerini çeker.
    """
    company_objs = get_records(model=ApiAccount, db_engine=get_engine("orders.db"))
    return [c.comp_name for c in company_objs]


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

        view_instance.worker.result_ready.connect(save_orders_to_db)
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


