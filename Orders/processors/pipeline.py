from Core.api.Api_engine import TrendyolApi
from Core.utils.time_utils import time_stamp_calculator, time_for_now
from dbase_set import get_last_scrap_date, get_product_sc_from_dbase, get_product_price_from_dbase



status_list = ["Created", "Delivered", "unDelivered", "Invoiced", "Picking",
               "Shipped", "AtCollectionPoint", "UnDeliveredAndReturned",
               "Cancelled"]  # aranacak statü listesi



async def find_orders_to_list(
    mode: str,
    final_ep_time: int,
    start_ep_time: int,
    comp_api_account_list: list,
    start_page: int = 0
) -> tuple[list, list]:
    """
    Tüm hesaplar için sipariş verilerini ve ürünlerini listelere döker.
    Global liste KULLANMAZ. Asenkron çalışır.
    """
    all_order_data = []
    all_order_items = []

    for comp_api_account in comp_api_account_list:
        page_counter = start_page
        trendy_api = TrendyolApi(comp_api_account[1], comp_api_account[2], comp_api_account[0])

        while True:
            content, _, _, _, status_code = await trendy_api.find_orders(
                mode, final_ep_time, start_ep_time, page_counter
            )

            if not content:
                break

            for order_data in content:
                if len(order_data.get("packageHistories", [])) == 1:
                    order_data["packageHistories"].insert(0, {"createdDate": 0, "status": "Awaiting"})

                all_order_data.append(order_data)

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

                    all_order_items.append(order_item)

            page_counter += 1

    return all_order_data, all_order_items
