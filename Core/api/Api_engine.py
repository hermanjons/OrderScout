from Core.utils.request_utils import async_make_request


class TrendyolApi:
    def __init__(self, api_key_id, api_key_secret, supplier_id):
        self.api_key_id = api_key_id
        self.api_key_secret = api_key_secret
        self.supplier_id = supplier_id

        self.header = {
            "User-Agent": f"{supplier_id}-SelfIntegration",
            "Content-Type": "application/json"
        }

        self.auth = (self.api_key_id, self.api_key_secret)

    async def find_orders(self, status: str, start_date: int, end_date: int, page: int):
        url = f"https://api.trendyol.com/sapigw/suppliers/{self.supplier_id}/orders"
        params = {
            "status": status,
            "startDate": start_date,
            "endDate": end_date,
            "orderByField": "PackageLastModifiedDate",
            "orderByDirection": "DESC",
            "page": page,
            "size": 200
        }

        result, status_code = await async_make_request("GET", url, headers=self.header, auth=self.auth, params=params)
        return (
            result.get("content", []),
            result.get("totalPages", 0),
            result.get("page", 0),
            result.get("totalElements", 0),
            status_code
        )

    async def find_product_with_barcode(self, barcode: str):
        url = f"https://api.trendyol.com/sapigw/suppliers/{self.supplier_id}/products"
        params = {
            "page": 0,
            "size": 50,
            "approved": True,
            "barcode": barcode
        }

        result, status_code = await async_make_request("GET", url, headers=self.header, auth=self.auth, params=params)
        return result
