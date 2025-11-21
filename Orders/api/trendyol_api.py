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

    # 🔽 YENİ: orderNumber ile tek sipariş(ler) çek
    async def get_order_by_number(
        self,
        order_number: str,
        page: int = 0,
        size: int = 50,
    ) -> Result:
        """
        orderNumber üzerinden sipariş paketlerini çeker.

        Trendyol dokümandaki 'Sipariş Paketlerini Çekme (getShipmentPackages)'
        servisini, tarih aralığı yerine doğrudan orderNumber ile filtreleyerek kullanır.

        Dönüş yapısı, find_orders ile uyumlu tutuldu:
            data = {
                "content": [...],
                "totalPages": ...,
                "page": ...,
                "totalElements": ...,
                "status_code": 200
            }

        Not:
        - Aynı orderNumber'a bağlı birden fazla paket varsa, hepsi content listesinde gelir.
        """
        try:
            order_number = (order_number or "").strip()
            if not order_number:
                return Result.fail("Geçersiz orderNumber.", close_dialog=False)

            url = f"https://apigw.trendyol.com/integration/order/sellers/{self.supplier_id}/orders"

            # Burada tarih, status vs göndermiyoruz; sadece orderNumber ile filtreliyoruz.
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

            # İstersen burada "hiç bulunamadı" durumunu ayrı mesajlayabilirsin
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
