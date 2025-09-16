from Core.api.Api_engine import TrendyolApi
from Core.utils.model_utils import create_records, make_normalizer
import asyncio
from typing import Optional,Callable
from Orders.models.trendyol_models import OrderItem, OrderData, OrderHeader


async def fetch_orders_all(
        status_list: list,
        final_ep_time: int,
        start_ep_time: int,
        comp_api_account_list: list,
        start_page: int = 0,
        progress_callback: Optional[Callable[[int, int], None]] = None
) -> tuple[list, list]:
    all_orders = []
    all_items = []
    total_steps = len(comp_api_account_list) * len(status_list)
    current_step = 0

    async def fetch_orders_for_status(api, status, comp_api_account_id):
        nonlocal current_step
        orders = []
        items = []
        page = start_page

        while True:
            content, _, _, _, status_code = await api.find_orders(status, final_ep_time, start_ep_time, page)
            if not content:
                break

            for order_data in content:
                order_data["api_account_id"] = comp_api_account_id
                if len(order_data.get("packageHistories", [])) == 1:
                    order_data["packageHistories"].insert(0, {"createdDate": 0, "status": "Awaiting"})
                orders.append(order_data)

                for order_item in order_data["lines"]:
                    order_item["api_account_id"] = comp_api_account_id
                    order_item["orderNumber"] = order_data["orderNumber"]
                    order_item["order_data_id"] = order_data["id"]
                    order_item["packageHistories"] = order_data["packageHistories"]
                    for history in order_data["packageHistories"]:
                        if history["status"] == order_data["status"]:
                            order_item["taskDate"] = history["createdDate"]
                            break
                    else:
                        order_item["taskDate"] = 0
                    items.append(order_item)
            page += 1

        # ✅ Her statü işlemi bitince ilerleme bildir
        current_step += 1
        if progress_callback:
            progress_callback(current_step, total_steps)

        return orders, items

    for comp_api_account in comp_api_account_list:
        print(comp_api_account)
        api = TrendyolApi(comp_api_account[1], comp_api_account[2], comp_api_account[3])
        tasks = [fetch_orders_for_status(api, status, comp_api_account[0]) for status in status_list]
        results = await asyncio.gather(*tasks)
        for orders, items in results:
            all_orders.extend(orders)
            all_items.extend(items)

    return all_orders, all_items



ORDERDATA_UNIQ = ["orderNumber", "lastModifiedDate", "api_account_id"]
ORDERITEM_UNIQ = ["orderNumber", "productCode","orderLineItemStatusName","api_account_id"]

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
    print("sonuçlar kaydediliyor")
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
            chunk_size=1,
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

    # 3) OrderHeader → orderNumber ve api_account_id alanlarıyla birlikte
    header_map = {
        od["orderNumber"]: od.get("api_account_id")
        for od in order_data_list
        if od.get("orderNumber") and od.get("api_account_id") is not None
    }

    if header_map:
        create_records(
            model=OrderHeader,
            data_list=[
                {
                    "orderNumber": order_number,
                    "api_account_id": api_account_id
                }
                for order_number, api_account_id in header_map.items()
            ],
            db_name=db_name,
            conflict_keys=["orderNumber", "api_account_id"],
            mode="ignore",  # varsa ekleme
        )



