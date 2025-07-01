import requests


class TrendyolApi:
    """
    Trendyol API bağlantı sınıfı

    :return: içerik, toplam sayfa sayısı, mevcut sayfa, toplam içerik sayısı ve HTTP durum kodu
    """

    def __init__(self, api_key_id, api_key_secret, supplier_id):
        self.api_key_id = api_key_id
        self.api_key_secret = api_key_secret
        self.supplier_id = supplier_id

        self.header = {
            "User-Agent": f"{supplier_id}-SelfIntegration",
            "Content-Type": "application/json"
        }

        self.auth = (self.api_key_id, self.api_key_secret)


        self.session = requests.Session()

    def find_orders(self, mode: str, final_ep_time: int, start_ep_time: int, page: int):
        link_query = (
            f'https://api.trendyol.com/sapigw/suppliers/{self.supplier_id}/orders?'
            f'status={mode}&'
            f'startDate={final_ep_time}&'
            f'endDate={start_ep_time}&'
            f'orderByField=PackageLastModifiedDate&'
            f'orderByDirection=DESC&'
            f'page={page}&'
            f'size=200'
        )

        try:
            response = self.session.get(link_query, headers=self.header, auth=self.auth)
            response.raise_for_status()
            text_data = response.json()

            return (
                text_data.get("content", []),
                text_data.get("totalPages", 0),
                text_data.get("page", 0),
                text_data.get("totalElements", 0),
                response.status_code
            )

        except Exception as e:
            print(f"[find_orders] Hata oluştu: {e}")
            return [], 0, 0, 0, 500

    def find_product_with_barcode(self, barcode: str):
        link_query = (
            f'https://api.trendyol.com/sapigw/suppliers/{self.supplier_id}/products?'
            f'page=0&size=50&approved=True&barcode={barcode}'
        )

        try:
            response = self.session.get(link_query, headers=self.header, auth=self.auth)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[find_product_with_barcode] Hata oluştu: {e}")
            return {}
