# Orders/views/actions.py
from Core.threads.async_worker import AsyncWorker
from Orders.processors.pipeline import fetch_orders_all
from Orders.constants.constants import status_list
from Core.utils.time_utils import time_for_now, time_stamp_calculator


# Bu fonksiyon view içinden çağrılır
def fetch_with_worker(view_instance):
    try:
        search_range_hour = 12
        start_ep_time = time_for_now()
        final_ep_time = time_for_now() - time_stamp_calculator(search_range_hour)

        # Test için dummy hesap: supplier_id, key, secret
        comp_api_account_list = [
            ["MCN8sNGNPfCs18KzzvT", "z1XHEgSvr9qRUo018y31","784195"]
        ]

        # 🔥 BURASI KRİTİK — referansı view_instance içinde tutuyoruz
        view_instance.worker = AsyncWorker(fetch_orders_all, status_list, final_ep_time, start_ep_time, comp_api_account_list, parent=view_instance)
        view_instance.worker.finished.connect(view_instance.on_orders_fetched)
        view_instance.worker.start()
    except Exception as e:
        print("fetch_with_worker hatası:", e)

