from Core.api.Api_engine import BaseTrendyolApi
from Core.utils.request_utils import async_make_request
from Feedback.processors.pipeline import Result, map_error_to_message


class TrendyolApi(BaseTrendyolApi):
    """
    Trendyol sipariş API istemcisi.

    Bu sınıf yalnızca **tek sayfalık** sipariş verisini çeker.
    Sayfalama (page++) yönetimi pipeline tarafında yapılır (ör: fetch_orders_all).
    """

    async def find_orders(
        self,
        status: str,
        start_date: int,
        end_date: int,
        page: int,
        size: int = 50
    ) -> Result:
        """
        Belirli bir statü ve tarih aralığındaki siparişlerin **tek sayfasını** Trendyol API'den çeker.
        """
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

            # ✅ async_make_request artık Result döndürüyor
            res = await async_make_request(
                method="GET",
                url=url,
                headers=self.header,
                auth=self.auth,
                params=params,
            )

            if not res.success:
                # async_make_request zaten fail döndürdüyse direkt aynısını geri ver
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

