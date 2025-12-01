from Orders.api.trendyol_api import TrendyolApi
from Core.utils.model_utils import create_records, get_records, get_engine,update_records
import asyncio
from typing import Optional, Callable
from Orders.models.trendyol.trendyol_models import OrderItem, OrderData, OrderHeader
from Account.models import ApiAccount
from Feedback.processors.pipeline import Result, map_error_to_message
from settings import DB_NAME
from Orders.constants.trendyol_constants import ORDERDATA_UNIQ, ORDERITEM_UNIQ, ORDERDATA_NORMALIZER, \
    ORDERITEM_NORMALIZER
from Orders.models.trendyol.trendyol_custom_queries import latest_ready_to_ship_query
from sqlmodel import Session, select
from Orders.signals.signals import order_signals
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased
from sqlalchemy.orm import selectinload
from Core.utils.time_utils import time_for_now


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


def update_last_used_at_for_accounts(comp_api_account_list: list[list]):
    """
    ApiAccount.last_used_at alanını datetime olarak günceller.
    """
    from datetime import datetime, timezone
    from Core.utils.model_utils import update_records
    from Account.models import ApiAccount

    now_dt = datetime.now(timezone.utc)

    for acc in comp_api_account_list:
        if not isinstance(acc, (list, tuple)) or not acc:
            continue

        api_pk = acc[0]  # ApiAccount.pk

        update_records(
            model=ApiAccount,
            filters={"pk": api_pk},
            update_data={"last_used_at": now_dt},
            db_name="orders.db",
        )



def save_orders_to_db(result: Result, db_name: str = DB_NAME) -> Result:
    """
    worker.result_ready -> Result.success + Result.data = {"order_data_list": [...], "order_item_list": [...]}
    """
    try:
        if not result or not isinstance(result, Result):
            return Result.fail("Geçersiz result objesi alındı.")

        if not result.success:
            return result

        order_data_list = result.data.get("order_data_list", [])
        order_item_list = result.data.get("order_item_list", [])

        # 1️⃣ Önce OrderHeader upsert
        header_map = {
            (od["orderNumber"], od["api_account_id"])
            for od in order_data_list
            if od.get("orderNumber") and od.get("api_account_id") is not None
        }

        if header_map:
            res_headers = create_records(
                model=OrderHeader,
                data_list=[
                    {"orderNumber": order_number, "api_account_id": api_account_id}
                    for order_number, api_account_id in header_map
                ],
                db_name=DB_NAME,
                conflict_keys=["orderNumber", "api_account_id"],
                mode="ignore",
            )
            if not res_headers.success:
                return res_headers

        # 2️⃣ Header PK map’i çıkar (get_records ile → Result pipeline içinde)
        res_header_rows = get_records(model=OrderHeader, db_name=DB_NAME)
        if not res_header_rows.success:
            return res_header_rows

        header_rows = res_header_rows.data.get("records", [])
        header_pk_map = {
            (h.orderNumber, h.api_account_id): h.pk
            for h in header_rows
        }

        # 3️⃣ OrderData’ya order_header_id ekle
        for od in order_data_list:
            key = (od.get("orderNumber"), od.get("api_account_id"))
            od["order_header_id"] = header_pk_map.get(key)

        if order_data_list:
            res_data = create_records(
                model=OrderData,
                data_list=order_data_list,
                db_name=DB_NAME,
                conflict_keys=ORDERDATA_UNIQ,
                mode="ignore",
                normalizer=ORDERDATA_NORMALIZER,
                chunk_size=30,
                drop_unknown=True,
                rename_map={},
            )
            if not res_data.success:
                return res_data

        # 4️⃣ OrderItem’a order_header_id ekle
        for oi in order_item_list:
            key = (oi.get("orderNumber"), oi.get("api_account_id"))
            oi["order_header_id"] = header_pk_map.get(key)

        if order_item_list:
            res_items = create_records(
                model=OrderItem,
                data_list=order_item_list,
                db_name=DB_NAME,
                conflict_keys=ORDERITEM_UNIQ,
                mode="ignore",
                normalizer=ORDERITEM_NORMALIZER,
                chunk_size=30,
                drop_unknown=True,
                rename_map={"3pByTrendyol": "byTrendyol3"},
            )
            if not res_items.success:
                return res_items
        order_signals.orders_changed.emit()
        return Result.ok("Siparişler başarıyla veritabanına kaydedildi.")

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


import copy


def get_latest_ready_to_ship_orders() -> Result:
    """
    ReadyToShip siparişlerin son snapshot'ını OrderHeader JOIN ile döndürür.
    Runtime olarak OrderData instance'larına şu alanlar eklenir:
        - is_extracted
        - is_printed
        - extracted_at
        - printed_at
    Deepcopy KALDIRILMIŞTIR (runtime attribute'lar kaybolmasın diye).
    Dönen tüm OrderData nesneleri Session kapandığı için detached'tır → UI'da güvenlidir.
    """

    try:
        engine = get_engine(DB_NAME)
        with Session(engine) as session:

            # 1️⃣ Son snapshot subquery
            subq = (
                select(
                    OrderData.api_account_id,
                    OrderData.orderNumber,
                    func.max(OrderData.lastModifiedDate).label("max_date"),
                )
                .group_by(OrderData.api_account_id, OrderData.orderNumber)
                .subquery()
            )

            OD = aliased(OrderData)

            # 2️⃣ Son snapshot + ReadyToShip + Header JOIN
            stmt = (
                select(OD)
                .join(
                    subq,
                    (OD.api_account_id == subq.c.api_account_id)
                    & (OD.orderNumber == subq.c.orderNumber)
                    & (OD.lastModifiedDate == subq.c.max_date),
                )
                .join(
                    OrderHeader,
                    (OrderHeader.api_account_id == OD.api_account_id)
                    & (OrderHeader.orderNumber == OD.orderNumber),
                )
                .where(OD.shipmentPackageStatus == "ReadyToShip")
                .options(
                    selectinload(OD.api_account),  # logo için
                    selectinload(OD.header),  # extracted/printed için
                    # ❗ items lazy, ama UI'da lazy kaldığında sorun olmuyor
                )
            )

            rows: list[OrderData] = session.exec(stmt).all() or []

            # 3️⃣ Runtime flag'leri ekle
            for od in rows:
                h = od.header
                if h:
                    object.__setattr__(od, "is_extracted", bool(h.is_extracted))
                    object.__setattr__(od, "is_printed", bool(h.is_printed))
                    object.__setattr__(od, "extracted_at", h.extracted_at)
                    object.__setattr__(od, "printed_at", h.printed_at)
                else:
                    object.__setattr__(od, "is_extracted", False)
                    object.__setattr__(od, "is_printed", False)
                    object.__setattr__(od, "extracted_at", None)
                    object.__setattr__(od, "printed_at", None)

        # 4️⃣ Session kapandı → tüm objeler artık detached → UI için güvenli
        # deepcopy YOK → runtime flag'ler kaybolmaz

        return Result.ok(
            f"ReadyToShip çekildi (toplam: {len(rows)})",
            data={"orders": rows},
            close_dialog=False
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_order_full_details_by_numbers(order_numbers: list) -> Result:
    """
    Verilen sipariş numaraları için:
    - OrderHeader
    - OrderData
    - OrderItem
    - ApiAccount (store_name + platform için)

    hepsini tek seferde toplar ve Result içinde döner.

    data yapısı:
        {
            "orders": [
                {
                    "header": OrderHeader,
                    "data": [OrderData, ...],
                    "items": [OrderItem, ...],
                    "store_name": str,
                    "platform": str,
                },
                ...
            ],
            "headers": [OrderHeader, ...],
            "order_data_list": [OrderData, ...],
            "order_item_list": [OrderItem, ...],
        }
    """
    try:
        if not order_numbers:
            return Result.fail(
                "Sipariş numarası listesi boş.",
                close_dialog=False
            )

        # normalize et (str'e çevir, trimle, boşları at)
        normalized = {
            str(num).strip()
            for num in order_numbers
            if str(num).strip()
        }
        if not normalized:
            return Result.fail(
                "Geçerli sipariş numarası bulunamadı.",
                close_dialog=False
            )

        # 1️⃣ Header kayıtları
        res_headers = get_records(
            model=OrderHeader,
            db_name=DB_NAME,
            filters={"orderNumber": list(normalized)},
        )
        if not res_headers.success:
            return res_headers

        headers: list[OrderHeader] = res_headers.data.get("records", []) or []
        if not headers:
            return Result.ok(
                "Verilen sipariş numaraları için kayıt bulunamadı.",
                close_dialog=False,
                data={
                    "orders": [],
                    "headers": [],
                    "order_data_list": [],
                    "order_item_list": [],
                }
            )

        header_pks = [h.pk for h in headers if getattr(h, "pk", None) is not None]
        if not header_pks:
            # teorik edge case
            return Result.ok(
                "Header bulundu ancak PK bilgisi alınamadı.",
                close_dialog=False,
                data={
                    "orders": [],
                    "headers": headers,
                    "order_data_list": [],
                    "order_item_list": [],
                }
            )

        # 🔹 ApiAccount'ları header'lardaki FK üzerinden çek (lazy ilişkiye DOKUNMADAN)
        api_account_ids = {
            getattr(h, "api_account_id", None)
            for h in headers
            if getattr(h, "api_account_id", None) is not None
        }

        api_accounts_by_id: dict[int, ApiAccount] = {}
        if api_account_ids:
            res_acc = get_records(
                model=ApiAccount,
                db_name=DB_NAME,
                filters={"pk": list(api_account_ids)},
            )
            if not res_acc.success:
                return res_acc

            api_list: list[ApiAccount] = res_acc.data.get("records", []) or []
            api_accounts_by_id = {
                acc.pk: acc
                for acc in api_list
                if getattr(acc, "pk", None) is not None
            }

        # 2️⃣ OrderData kayıtları
        res_data = get_records(
            model=OrderData,
            db_name=DB_NAME,
            filters={"order_header_id": header_pks},
        )
        if not res_data.success:
            return res_data
        order_data_list: list[OrderData] = res_data.data.get("records", []) or []

        # 3️⃣ OrderItem kayıtları
        res_items = get_records(
            model=OrderItem,
            db_name=DB_NAME,
            filters={"order_header_id": header_pks},
        )
        if not res_items.success:
            return res_items
        order_item_list: list[OrderItem] = res_items.data.get("records", []) or []

        # 4️⃣ Map'leri kur
        data_by_header: dict[int, list[OrderData]] = {}
        for od in order_data_list:
            hid = getattr(od, "order_header_id", None)
            if hid is not None:
                data_by_header.setdefault(hid, []).append(od)

        items_by_header: dict[int, list[OrderItem]] = {}
        for oi in order_item_list:
            hid = getattr(oi, "order_header_id", None)
            if hid is not None:
                items_by_header.setdefault(hid, []).append(oi)

        # 5️⃣ Tek tek paketle (DetachedInstanceError YOK ➜ api_account ilişkisinden veri çekmiyoruz)
        orders = []
        for h in headers:
            api_acc = None
            store_name = ""
            platform = ""

            acc_id = getattr(h, "api_account_id", None)
            if acc_id is not None:
                api_acc = api_accounts_by_id.get(acc_id)

            if api_acc is not None:
                store_name = (getattr(api_acc, "comp_name", "") or "").strip()
                platform = (getattr(api_acc, "platform", "") or "").strip()

            orders.append({
                "header": h,
                "data": data_by_header.get(h.pk, []),
                "items": items_by_header.get(h.pk, []),
                "store_name": store_name,
                "platform": platform,
            })

        return Result.ok(
            f"{len(orders)} siparişin detayları getirildi.",
            close_dialog=False,
            data={
                "orders": orders,
                "headers": headers,
                "order_data_list": order_data_list,
                "order_item_list": order_item_list,
            }
        )

    except Exception as e:
        return Result.fail(
            map_error_to_message(e),
            error=e,
            close_dialog=False
        )


def get_nonfinal_order_numbers(
        final_statuses: Optional[list[str]] = None
) -> Result:
    """
    Her sipariş için en güncel OrderData kaydını bulur.
    Bu kaydın status değeri final_statuses içinde DEĞİLSE
    o siparişin orderNumber'ını döner.

    Varsayılan final statüler:
        - Delivered
        - Cancelled

    Dönüş:
        Result.data = {
            "order_numbers": ["10627509219", "10703754325", ...]
        }

    NOT:
    - Hiç non-final sipariş yoksa bile SUCCESS döner, sadece liste boş olur.
    """
    try:
        # Dışarıdan liste gelmezse default final statüler
        if final_statuses is None:
            final_statuses = ["Delivered", "Cancelled"]

        engine = get_engine(DB_NAME)
        with Session(engine) as session:
            # 1️⃣ Her header için en son OrderData.lastModifiedDate'i bul
            subq = (
                select(
                    OrderData.order_header_id,
                    func.max(OrderData.lastModifiedDate).label("max_last_modified"),
                )
                .group_by(OrderData.order_header_id)
                .subquery()
            )

            # 2️⃣ Bu en güncel snapshot'ı OrderData ile join'le,
            #    status final_statuses içinde OLMAYANları seç.
            stmt = (
                select(OrderHeader.orderNumber)
                .join(subq, subq.c.order_header_id == OrderHeader.pk)
                .join(
                    OrderData,
                    (OrderData.order_header_id == OrderHeader.pk)
                    & (OrderData.lastModifiedDate == subq.c.max_last_modified),
                )
                .where(~OrderData.status.in_(final_statuses))  # 🔴 BURASI ÖNEMLİ: not_in DEĞİL!
            )

            rows = session.exec(stmt).all()

        # OrderNumber'ları normalize et (str'e çevir, trimle, tekrarı at)
        order_numbers_set = {
            str(num).strip()
            for num in rows
            if num is not None and str(num).strip()
        }
        order_numbers = sorted(order_numbers_set)

        return Result.ok(
            f"{len(order_numbers)} adet final olmayan sipariş bulundu.",
            close_dialog=False,
            data={"order_numbers": order_numbers},
        )

    except Exception as e:
        # Eğer hâlâ patlıyorsa buradan anlayacağız
        return Result.fail(
            map_error_to_message(e),
            error=e,
            close_dialog=False
        )
