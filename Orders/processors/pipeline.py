from Core.api.Api_engine import TrendyolApi
from Core.utils.time_utils import time_stamp_calculator, time_for_now
from Core.utils.model_utils import get_engine, create_records, make_normalizer
import asyncio
from typing import List
from sqlmodel import Session
from Orders.models import OrderItem, OrderData, ScrapData


async def fetch_orders_all(
        status_list: list,
        final_ep_time: int,
        start_ep_time: int,
        comp_api_account_list: list,
        start_page: int = 0
) -> tuple[list, list]:
    """
    Şirketleri sırayla dolaşır.
    Her şirket için status_list'teki statülere paralel istek atar.
    Tüm sipariş ve ürünleri toplar ve döner.
    """
    all_orders = []
    all_items = []

    async def fetch_orders_for_status(api, status):
        orders = []
        items = []
        page = start_page
        while True:
            content, _, _, _, status_code = await api.find_orders(status, final_ep_time, start_ep_time, page)

            if not content:
                break
            for order_data in content:
                if len(order_data.get("packageHistories", [])) == 1:
                    order_data["packageHistories"].insert(0, {"createdDate": 0, "status": "Awaiting"})
                orders.append(order_data)
                for order_item in order_data["lines"]:
                    order_item["orderNumber"] = order_data["orderNumber"]
                    order_item["id"] = order_data["id"]
                    order_item["packageHistories"] = order_data["packageHistories"]
                    for history in order_data["packageHistories"]:
                        if history["status"] == order_data["status"]:
                            order_item["taskDate"] = history["createdDate"]
                            break
                    else:
                        order_item["taskDate"] = 0
                    items.append(order_item)
            page += 1
        return orders, items

    for comp_api_account in comp_api_account_list:
        api = TrendyolApi(comp_api_account[0], comp_api_account[1], comp_api_account[2])
        tasks = [fetch_orders_for_status(api, status) for status in status_list]
        results = await asyncio.gather(*tasks)
        for orders, items in results:
            all_orders.extend(orders)
            all_items.extend(items)

    return all_orders, all_items


ORDERDATA_UNIQ = ["orderNumber", "status", "taskDate"]
ORDERITEM_UNIQ = ["id", "orderNumber", "productCode", "orderLineItemStatusName"]

# OrderData: metinleri temizle
orderdata_normalizer = make_normalizer(strip_strings=True)

# OrderItem: unique anahtarlar için None/"" değerleri toparla + metinleri temizle
orderitem_normalizer = make_normalizer(
    coalesce_none={
        "productCode": 0,
        "orderLineItemStatusName": "Unknown",
    },
    strip_strings=True,
)


def save_orders_to_db(result, db_name: str = "orders.db"):
    """
    worker.result_ready -> (order_data_list, order_item_list)
    """
    if not result:
        return

    order_data_list, order_item_list = result

    # 1) OrderData → upsert (orderNumber çakışırsa güncelle)
    if order_data_list:
        create_records(
            model=OrderData,
            data_list=order_data_list,
            db_name=db_name,
            conflict_keys=ORDERDATA_UNIQ,
            mode="ignore",  # DO NOTHING (append-only)
            normalizer=orderdata_normalizer,
            chunk_size=300,
            drop_unknown=True,
            rename_map={},
        )

    # 2) OrderItem → insert-ignore (4'lü aynıysa ekleme)
    if order_item_list:
        create_records(
            model=OrderItem,
            data_list=order_item_list,
            db_name=db_name,
            conflict_keys=ORDERITEM_UNIQ,
            mode="ignore",
            normalizer=orderitem_normalizer,
            chunk_size=500,
            drop_unknown=True,  # modelde olmayan kolonları at
            rename_map={
                # API’den gelen key → modeldeki alan adı
                "3pByTrendyol": "byTrendyol3"
            }
        )
