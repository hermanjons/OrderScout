from Core.api.Api_engine import BaseTrendyolApi
from Core.utils.request_utils import async_make_request
from Feedback.processors.pipeline import Result, map_error_to_message
from License.decorators.license_check import require_valid_license_async


class TrendyolApi(BaseTrendyolApi):
    """
    Trendyol sipariş API istemcisi.

    Bu sınıf yalnızca **tek sayfalık** sipariş verisini çeker.
    Sayfalama pipeline tarafında yapılır.
    """

    @require_valid_license_async(force=False)
    async def find_orders(
        self,
        status: str,
        start_date: int,
        end_date: int,
        page: int,
        size: int = 50
    ) -> Result:
        try:
            url = f"https://apigw.trendyol.com/integration/order/sellers/{self.supplier_id}/orders"

            params = {
                "status": status,
                "startDate": start_date,
                "endDate": end_date,
                "orderByField": "PackageLastModifiedDate",
                "orderByDirection": "DESC",
                "page": page,
                "size": size,
            }

            res = await async_make_request(
                method="GET",
                url=url,
                headers=self.header,
                auth=self.auth,
                params=params,
            )

            if not res.success:
                return res

            data = res.data.get("json", {})
            status_code = res.data.get("status_code", 0)

            if status_code != 200:
                return Result.fail(
                    f"API isteği başarısız oldu (status={status_code})",
                    close_dialog=False,
                    data={"status_code": status_code}
                )

            return Result.ok(
                "Siparişler başarıyla alındı.",
                close_dialog=False,
                data={
                    "content": data.get("content", []),
                    "totalPages": data.get("totalPages", 0),
                    "page": data.get("page", 0),
                    "totalElements": data.get("totalElements", 0),
                    "status_code": status_code,
                }
            )

        except Exception as e:
            return Result.fail(
                map_error_to_message(e),
                error=e,
                close_dialog=False
            )

    # 🔽 Tek sipariş çekme
    @require_valid_license_async(force=False)
    async def get_order_by_number(
        self,
        order_number: str,
        page: int = 0,
        size: int = 50,
    ) -> Result:
        try:
            order_number = (order_number or "").strip()
            if not order_number:
                return Result.fail("Geçersiz orderNumber.", close_dialog=False)

            url = f"https://apigw.trendyol.com/integration/order/sellers/{self.supplier_id}/orders"

            params = {
                "orderNumber": order_number,
                "page": page,
                "size": size,
            }

            res = await async_make_request(
                method="GET",
                url=url,
                headers=self.header,
                auth=self.auth,
                params=params,
            )

            if not res.success:
                return res

            data = res.data.get("json", {})
            status_code = res.data.get("status_code", 0)

            if status_code != 200:
                return Result.fail(
                    f"API isteği başarısız oldu (status={status_code})",
                    close_dialog=False,
                    data={"status_code": status_code}
                )

            content = data.get("content", []) or []
            msg = "Sipariş başarıyla alındı." if content else "Bu orderNumber için sipariş bulunamadı."

            return Result.ok(
                msg,
                close_dialog=False,
                data={
                    "content": content,
                    "totalPages": data.get("totalPages", 0),
                    "page": data.get("page", 0),
                    "totalElements": data.get("totalElements", 0),
                    "status_code": status_code,
                }
            )

        except Exception as e:
            return Result.fail(
                map_error_to_message(e),
                error=e,
                close_dialog=False
            )
