from __future__ import annotations


from Marketplaces.processors.catalog import marketplace_api_scope_profile


TRENDYOL_STAGE_BASE_URL = str(marketplace_api_scope_profile("TRENDYOL", "orders", "stage").get("baseUrl") or "").rstrip("/")
if not TRENDYOL_STAGE_BASE_URL:
    raise RuntimeError("Trendyol Stage endpoint is absent from the canonical marketplace configuration.")

# Trendyol'un test siparişi dokümanında verdiği barkod. Ortak Stage hesabındaki
# sıradan ilanlar ödeme onayı bekleyen (Awaiting, packageId=0) bir kayıt
# üretebilirken bu ürün deterministik sipariş yaşam döngüsü testleri içindir.
TRENDYOL_STAGE_OFFICIAL_TEST_BARCODE = "9900000000486"
TRENDYOL_STAGE_VERIFY_ATTEMPTS = 30

TRENDYOL_STAGE_ORDER_STATUS_FLOW: tuple[str, ...] = (
    "Shipped",
    "AtCollectionPoint",
    "Delivered",
    "UnDelivered",
    "Returned",
)

# Trendyol'un resmi kargo şirketi kimlikleri. Bunlar yalnızca TestLab'in
# createClaim test verisi üretiminde kullanılır; uygulama tarifelerinin yerel
# source_id alanlarıyla aynı kavram değildir.
TRENDYOL_STAGE_CARGO_PROVIDER_IDS: dict[str, int] = {
    "YKMP": 4,
    "HOROZMP": 6,
    "ARASMP": 7,
    "SURATMP": 9,
    "DHLECOMMP": 10,
    "TEXMP": 17,
    "PTTMP": 19,
    "CEVAMP": 20,
    "CEVATEDARIK": 30,
    "SENDEOMP": 38,
    "KOLAYGELSINMP": 38,
}


__all__ = [
    "TRENDYOL_STAGE_BASE_URL",
    "TRENDYOL_STAGE_CARGO_PROVIDER_IDS",
    "TRENDYOL_STAGE_OFFICIAL_TEST_BARCODE",
    "TRENDYOL_STAGE_ORDER_STATUS_FLOW",
    "TRENDYOL_STAGE_VERIFY_ATTEMPTS",
]
