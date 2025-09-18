from Core.api.Api_engine import BaseTrendyolApi
from Core.utils.request_utils import async_make_request




class TrendyolApi(BaseTrendyolApi):


    async def find_orders(self, status: str, start_date: int, end_date: int, page: int):
        # Yeni API endpoint (apigw.trendyol.com ve sellers/{sellerId})
        url = f"https://apigw.trendyol.com/integration/order/sellers/{self.supplier_id}/orders"

        # Trendyol yeni API milisaniye epoch ister (13 hane)
        params = {
            "status": status,
            "startDate": start_date,  # saniyeyi milisaniyeye çevir
            "endDate": end_date,
            "orderByField": "PackageLastModifiedDate",
            "orderByDirection": "DESC",
            "page": page,
            "size": 50
        }

        result, status_code = await async_make_request(
            method="GET",
            url=url,
            headers=self.header,
            auth=self.auth,
            params=params
        )
        return (
            result.get("content", []),
            result.get("totalPages", 0),
            result.get("page", 0),
            result.get("totalElements", 0),
            status_code
        )