
class BaseTrendyolApi:
    def __init__(self, api_key_id, api_key_secret, supplier_id):
        self.api_key_id = api_key_id
        self.api_key_secret = api_key_secret
        self.supplier_id = supplier_id

        self.header = {
            "User-Agent": f"{supplier_id}-SelfIntegration",
            "Content-Type": "application/json"
        }

        self.auth = (self.api_key_id, self.api_key_secret)


