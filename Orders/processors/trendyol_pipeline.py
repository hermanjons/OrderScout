from Orders.api.trendyol_api import TrendyolApi
from Core.utils.model_utils import create_records, make_normalizer, get_records, get_engine
import asyncio
from typing import Optional, Callable
from Orders.models.trendyol_models import OrderItem, OrderData, OrderHeader
from Feedback.processors.pipeline import Result, map_error_to_message
from settings import DB_NAME
from Orders.constants.trendyol_constants import ORDERDATA_UNIQ,ORDERITEM_UNIQ,ORDERDATA_NORMALIZER,ORDERITEM_NORMALIZER


async def normalize_order_data(order_data: dict, comp_api_account_id: int):
    """
    Tek bir order verisini normalize eder ve (order, items) tuple döner.
    """
    orders = []
    items = []

    # Şirket id ekle
    order_data["api_account_id"] = comp_api_account_id

    # packageHistories fix
    if len(order_data.get("packageHistories", [])) == 1:
        order_data["packageHistories"].insert(
            0, {"createdDate": 0, "status": "Awaiting"}
        )

    orders.append(order_data)

    # OrderItem doldurma
    for order_item in order_data.get("lines", []):
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

    return orders, items


async def fetch_orders_for_status(api, status: str, comp_api_account_id: int,
                                  start_page: int, final_ep_time: int, start_ep_time: int,
                                  progress_callback=None, total_steps=1, current_step_ref=None):
    orders, items = [], []
    page = start_page

    while True:
        res = await api.find_orders(status, final_ep_time, start_ep_time, page)
        if not res.success:
            return Result.fail(f"API hatası ({status}) → {res.message}",
                               error=res.error, close_dialog=False)

        content = res.data.get("content", [])
        if not content:
            break

        for order_data in content:
            norm_orders, norm_items = await normalize_order_data(order_data, comp_api_account_id)
            orders.extend(norm_orders)
            items.extend(norm_items)

        page += 1

    # ✅ Progress bildirimi buraya alındı
    if current_step_ref is not None:
        current_step_ref[0] += 1
        if progress_callback:
            progress_callback(current_step_ref[0], total_steps)

    return Result.ok(
        f"{status} için siparişler çekildi.",
        close_dialog=False,
        data={"orders": orders, "items": items}
    )


async def fetch_orders_all(
        status_list: list,
        final_ep_time: int,
        start_ep_time: int,
        comp_api_account_list: list,
        start_page: int = 0,
        progress_callback: Optional[Callable[[int, int], None]] = None
) -> Result:
    try:
        all_orders, all_items = [], []
        total_steps = len(comp_api_account_list) * len(status_list)
        current_step_ref = [0]  # ✅ referans tutucu

        for comp_api_account in comp_api_account_list:
            api = TrendyolApi(comp_api_account[1], comp_api_account[2], comp_api_account[3])
            tasks = [
                fetch_orders_for_status(api, status, comp_api_account[0],
                                        start_page, final_ep_time, start_ep_time,
                                        progress_callback, total_steps, current_step_ref)
                for status in status_list
            ]
            results = await asyncio.gather(*tasks)

            for res in results:
                if not res.success:
                    return res

                all_orders.extend(res.data.get("orders", []))
                all_items.extend(res.data.get("items", []))

        return Result.ok(
            "Siparişler başarıyla çekildi.",
            data={
                "order_data_list": all_orders,
                "order_item_list": all_items,
            }
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


def save_orders_to_db(result: Result, db_name: str = DB_NAME) -> Result:
    """
    worker.result_ready -> Result.success + Result.data = {"order_data_list": [...], "order_item_list": [...]}
    """
    try:
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
            res_data = create_records(
                model=OrderData,
                data_list=order_data_list,
                db_name=db_name,
                conflict_keys=ORDERDATA_UNIQ,
                mode="ignore",
                normalizer=ORDERDATA_NORMALIZER,
                chunk_size=100,
                drop_unknown=True,
                rename_map={},
            )
            if not res_data.success:
                return res_data  # hata varsa direkt dön

        # 4) OrderItem → insert-ignore
        if order_item_list:
            res_items = create_records(
                model=OrderItem,
                data_list=order_item_list,
                db_name=db_name,
                conflict_keys=ORDERITEM_UNIQ,
                mode="ignore",
                normalizer=ORDERITEM_NORMALIZER,
                chunk_size=200,
                drop_unknown=True,
                rename_map={"3pByTrendyol": "byTrendyol3"}
            )
            if not res_items.success:
                return res_items

        # 5) OrderHeader → orderNumber + api_account_id
        header_map = {
            od.get("orderNumber"): od.get("api_account_id")
            for od in order_data_list
            if od.get("orderNumber") and od.get("api_account_id") is not None
        }

        if header_map:
            res_headers = create_records(
                model=OrderHeader,
                data_list=[
                    {"orderNumber": order_number, "api_account_id": api_account_id}
                    for order_number, api_account_id in header_map.items()
                ],
                db_name=db_name,
                conflict_keys=["orderNumber", "api_account_id"],
                mode="ignore",
            )
            if not res_headers.success:
                return res_headers

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
            db_engine=get_engine(DB_NAME)
        )
        if not raw_data.success:
            return raw_data

        records = raw_data.data.get("records", [])

        latest_snapshots = {}
        for record in records:
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

        return Result.ok(
            "ReadyToShip siparişler başarıyla çekildi.",
            data={"orders": filtered}
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)

