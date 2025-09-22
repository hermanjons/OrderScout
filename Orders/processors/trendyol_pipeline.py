from Orders.api.trendyol_api import TrendyolApi
from Core.utils.model_utils import create_records, make_normalizer,get_records,get_engine
import asyncio
from typing import Optional, Callable
from Orders.models.trendyol_models import OrderItem, OrderData, OrderHeader
from Feedback.processors.pipeline import Result, map_error_to_message


async def fetch_orders_all(
        status_list: list,
        final_ep_time: int,
        start_ep_time: int,
        comp_api_account_list: list,
        start_page: int = 0,
        progress_callback: Optional[Callable[[int, int], None]] = None
) -> Result:
    """
    Seçili şirket + statü listesi için tüm siparişleri Trendyol API'den çeker.
    Sonuç: Result.success + data = {"order_data_list": [...], "order_item_list": [...]}
    """
    try:
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
                # Trendyol API çağrısı (Artık Result dönüyor!)
                res = await api.find_orders(status, final_ep_time, start_ep_time, page)

                if not res.success:
                    print(f"API hatası: {res.message}")
                    break

                content = res.data.get("orders", [])
                if not content:
                    break

                for order_data in content:
                    order_data["api_account_id"] = comp_api_account_id

                    # packageHistories fix
                    if len(order_data.get("packageHistories", [])) == 1:
                        order_data["packageHistories"].insert(
                            0, {"createdDate": 0, "status": "Awaiting"}
                        )
                    orders.append(order_data)

                    # OrderItem doldurma
                    for order_item in order_data["lines"]:
                        order_item["api_account_id"] = comp_api_account_id
                        order_item["orderNumber"] = order_data["orderNumber"]
                        order_item["order_data_id"] = order_data["id"]
                        order_item["packageHistories"] = order_data["packageHistories"]

                        # taskDate belirle
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

        # 🔄 Tüm şirketler için çalıştır
        for comp_api_account in comp_api_account_list:
            api = TrendyolApi(comp_api_account[1], comp_api_account[2], comp_api_account[3])
            tasks = [
                fetch_orders_for_status(api, status, comp_api_account[0])
                for status in status_list
            ]
            results = await asyncio.gather(*tasks)
            for orders, items in results:
                all_orders.extend(orders)
                all_items.extend(items)

        # ✅ Feedback uyumlu dönüş
        return Result.ok(
            "Siparişler başarıyla çekildi.",
            data={
                "order_data_list": all_orders,
                "order_item_list": all_items,
            }
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)



ORDERDATA_UNIQ = ["orderNumber", "lastModifiedDate", "api_account_id"]
ORDERITEM_UNIQ = ["orderNumber", "productCode", "orderLineItemStatusName", "api_account_id"]

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


def save_orders_to_db(result: Result, db_name: str = "orders.db") -> Result:
    """
    worker.result_ready -> Result.success + Result.data = {"order_data_list": [...], "order_item_list": [...]}
    """
    try:
        print("sonuçlar kaydediliyor")

        # 1) Eğer geçersiz veya başarısız result geldiyse
        if not result or not isinstance(result, Result):
            return Result.fail("Geçersiz result objesi alındı.")

        if not result.success:
            return result  # direkt hatayı yukarıya ilet

        # 2) Data içinden listeleri çek
        order_data_list = result.data.get("order_data_list", [])
        order_item_list = result.data.get("order_item_list", [])

        # 3) OrderData → upsert
        if order_data_list:
            create_records(
                model=OrderData,
                data_list=order_data_list,
                db_name=db_name,
                conflict_keys=ORDERDATA_UNIQ,
                mode="ignore",
                normalizer=orderdata_normalizer,
                chunk_size=1,
                drop_unknown=True,
                rename_map={},
            )

        # 4) OrderItem → insert-ignore
        if order_item_list:
            create_records(
                model=OrderItem,
                data_list=order_item_list,
                db_name=db_name,
                conflict_keys=ORDERITEM_UNIQ,
                mode="ignore",
                normalizer=orderitem_normalizer,
                chunk_size=500,
                drop_unknown=True,
                rename_map={"3pByTrendyol": "byTrendyol3"}
            )

        # 5) OrderHeader → orderNumber + api_account_id
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
                mode="ignore",
            )

        return Result.ok("Siparişler başarıyla veritabanına kaydedildi.")

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


def get_latest_ready_to_ship_orders() -> Result:
    """
    En güncel 'ReadyToShip' sipariş snapshotlarını döner.
    """
    try:
        raw_data = get_records(
            model=OrderData,
            db_engine=get_engine("orders.db")
        )

        latest_snapshots = {}
        for record in raw_data:
            key = record.orderNumber
            if (
                    key not in latest_snapshots or
                    record.lastModifiedDate > latest_snapshots[key].lastModifiedDate
            ):
                latest_snapshots[key] = record

        filtered = [
            rec for rec in latest_snapshots.values()
            if rec.shipmentPackageStatus == "ReadyToShip"
        ]

        return Result.ok("ReadyToShip siparişler başarıyla çekildi.", data={"orders": filtered})

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)
