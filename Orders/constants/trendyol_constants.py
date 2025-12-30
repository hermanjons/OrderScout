# 📂 Orders/constants.py

from Core.utils.model_utils import make_normalizer

# -------------------------------------------------
# 📦 Trendyol API Sipariş Statüleri
# -------------------------------------------------
TRENDYOL_STATUS_LIST = [
    "Created",
    "Delivered",
    "UnDelivered",
    "Invoiced",
    "Picking",
    "Shipped",
    "AtCollectionPoint",
    "Cancelled",
]

# -------------------------------------------------
# 🔑 Unique Key Tanımları
# -------------------------------------------------
ORDERDATA_UNIQ = ["orderNumber", "lastModifiedDate", "api_account_id"]
ORDERITEM_UNIQ = ["orderNumber", "productCode", "orderLineItemStatusName", "api_account_id"]

# -------------------------------------------------
# 🧹 Normalizer Tanımları
# -------------------------------------------------
ORDERDATA_NORMALIZER = make_normalizer(strip_strings=True)

ORDERITEM_NORMALIZER = make_normalizer(
    coalesce_none={
        "productCode": 0,
        "orderLineItemStatusName": "Unknown",
    },
    strip_strings=True,
)

