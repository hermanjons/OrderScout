from __future__ import annotations

class _LazyList(list):
    def __init__(self, loader):
        super().__init__()
        self._loader = loader
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        super().clear()
        super().extend(self._loader() or [])
        self._loaded = True

    def __bool__(self):
        self._ensure_loaded()
        return super().__len__() > 0

    def __contains__(self, item):
        self._ensure_loaded()
        return super().__contains__(item)

    def __getitem__(self, index):
        self._ensure_loaded()
        return super().__getitem__(index)

    def __iter__(self):
        self._ensure_loaded()
        return super().__iter__()

    def __len__(self):
        self._ensure_loaded()
        return super().__len__()

    def __repr__(self):
        self._ensure_loaded()
        return super().__repr__()

    def copy(self):
        self._ensure_loaded()
        return super().copy()


def _load_trendyol_api_status_list() -> list[str]:
    from Marketplaces.processors.catalog import marketplace_scope_status_list

    return marketplace_scope_status_list("TRENDYOL", "orders")


def _load_trendyol_cargo_provider_options() -> list[dict[str, str]]:
    from Logistics.processors.catalog import cargo_provider_simple_records

    return cargo_provider_simple_records("TRENDYOL")


TRENDYOL_API_STATUS_LIST = _LazyList(_load_trendyol_api_status_list)
TRENDYOL_MAX_STATUS_QUERY_WINDOW_DAYS = 14

TRENDYOL_STATUS_LABELS: dict[str, str] = {
    "Awaiting": "Askıda",
    "Created": "Kargoya Hazır",
    "Picking": "Hazırlanıyor",
    "Invoiced": "Faturalandı",
    "Shipped": "Kargoda",
    "AtCollectionPoint": "Teslimat Noktasında",
    "Cancelled": "İptal Edildi",
    "UnPacked": "Paket Bölündü",
    "Delivered": "Teslim Edildi",
    "UnDelivered": "Teslim Edilemedi",
    "Returned": "İade Edildi",
}
TRENDYOL_STATUS_LIST = list(TRENDYOL_STATUS_LABELS.keys())
TRENDYOL_ORDER_STATUS_ALIASES: dict[str, str] = {
    "ReadyToShip": "Created",
    "Unsupplied": "Cancelled",
}

TRENDYOL_RETURN_STATUS_LABELS: dict[str, str] = {
    "Created": "Oluşturuldu",
    "WaitingInAction": "Aksiyon Bekliyor",
    "Accepted": "Kabul Edildi",
    "Cancelled": "İptal Edildi",
    "Rejected": "Reddedildi",
    "Unresolved": "Çözümsüz",
    "InAnalysis": "İncelemede",
    "WaitingFraudCheck": "Sahtecilik Kontrolünde",
}
TRENDYOL_RETURN_STATUS_LIST = list(TRENDYOL_RETURN_STATUS_LABELS.keys())
TRENDYOL_RETURN_STATUS_PRIORITY = (
    "WaitingInAction",
    "WaitingFraudCheck",
    "Created",
    "InAnalysis",
    "Unresolved",
    "Accepted",
    "Rejected",
    "Cancelled",
)

TRENDYOL_CARGO_PROVIDER_OPTIONS = _LazyList(_load_trendyol_cargo_provider_options)

ORDERDATA_UNIQ = ["id", "lastModifiedDate", "api_account_id"]
ORDERITEM_UNIQ = [
    "order_data_id",
    "snapshotLastModifiedDate",
    "lineId",
    "api_account_id",
]
RETURNCLAIM_UNIQ = ["claimId", "lastModifiedDate", "api_account_id"]
