from Core.api.Api_engine import BaseTrendyolApi
from Core.utils.request_utils import async_make_request
from Feedback.processors.pipeline import Result, map_error_to_message


class TrendyolApi(BaseTrendyolApi):
    """
    Trendyol sipariş API istemcisi.

    Bu sınıf yalnızca **tek sayfalık** sipariş verisini çeker.
    Sayfalama (page++) yönetimi pipeline tarafında yapılır (ör: fetch_orders_all).
    """

    async def find_orders(self, status: str, start_date: int, end_date: int, page: int, size: int = 50) -> Result:
        """
        Belirli bir statü ve tarih aralığındaki siparişlerin **tek sayfasını** Trendyol API'den çeker.

        Args:
            status (str): Sipariş statüsü. (örn: "Created", "Picking", "Cancelled")
            start_date (int): Başlangıç zamanı (epoch ms, 13 haneli).
            end_date (int): Bitiş zamanı (epoch ms, 13 haneli).
            page (int): Getirilecek sayfa numarası (0-indexed).
            size (int, optional): Sayfa başına sipariş sayısı. Varsayılan=50.

        Returns:
            Result:
                - success (bool): İşlem başarılı mı.
                - message (str): Durum mesajı.
                - data (dict):
                    - content (list[dict]): Sipariş listesi.
                    - totalPages (int): Toplam sayfa sayısı.
                    - page (int): Şu anki sayfa numarası.
                    - totalElements (int): Toplam sipariş sayısı.
                    - status_code (int): HTTP yanıt kodu.

        Example:
            >>> api = TrendyolApi("supplierId", "apiKey", "apiSecret")
            >>> res = await api.find_orders("Created", 1695926400000, 1698531200000, 0)
            >>> if res.success:
            ...     print(f"{len(res.data['content'])} sipariş çekildi.")
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

            result, status_code = await async_make_request(
                method="GET",
                url=url,
                headers=self.header,
                auth=self.auth,
                params=params,
            )

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
                    "content": result.get("content", []),
                    "totalPages": result.get("totalPages", 0),
                    "page": result.get("page", 0),
                    "totalElements": result.get("totalElements", 0),
                    "status_code": status_code,
                }
            )

        except Exception as e:
            return Result.fail(
                map_error_to_message(e),
                error=e,
                close_dialog=False
            )
