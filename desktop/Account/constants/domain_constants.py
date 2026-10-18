from __future__ import annotations

from Account.models.models import ApiAccount
from Core.utils.model_utils import get_model_columns

ACCOUNT_TABLE_NAME = "apiaccount"

ACCOUNT_HEALTH_BATCH_CONCURRENCY = 8
ACCOUNT_HEALTH_GATHER_BATCH_SIZE = 100
ACCOUNT_DELETE_CHUNK_SIZE = 10_000
ACCOUNT_CREATE_FIELDS = frozenset(get_model_columns(ApiAccount)) - {"pk"}
ACCOUNT_UPDATE_FIELDS = ACCOUNT_CREATE_FIELDS - {"created_at", "encrypted", "token_valid"}
ACCOUNT_REQUIRED_IDENTITY_FIELDS = ("account_id", "comp_name", "platform")
ACCOUNT_HEALTH_IDENTITY_FIELDS = frozenset(
    {"platform", "account_id", "api_key", "api_secret", "integration_code", "token", "extra_config"}
)
ACCOUNT_EMPTY_TO_NONE_FIELDS = {
    "account_id": None,
    "comp_name": None,
    "platform": None,
    "logo_path": None,
    "integration_code": None,
    "api_key": None,
    "api_secret": None,
    "token": None,
}
ACCOUNT_LOGO_ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
ACCOUNT_REQUIRED_FIELD_MESSAGES = {
    "account_id": "Satıcı ID boş olamaz.",
    "comp_name": "Şirket adı boş olamaz.",
    "platform": "Platform boş olamaz.",
}

__all__ = [
    "ACCOUNT_TABLE_NAME",
    "ACCOUNT_HEALTH_BATCH_CONCURRENCY",
    "ACCOUNT_HEALTH_GATHER_BATCH_SIZE",
    "ACCOUNT_DELETE_CHUNK_SIZE",
    "ACCOUNT_CREATE_FIELDS",
    "ACCOUNT_UPDATE_FIELDS",
    "ACCOUNT_REQUIRED_IDENTITY_FIELDS",
    "ACCOUNT_HEALTH_IDENTITY_FIELDS",
    "ACCOUNT_EMPTY_TO_NONE_FIELDS",
    "ACCOUNT_LOGO_ALLOWED_EXTENSIONS",
    "ACCOUNT_REQUIRED_FIELD_MESSAGES",
]
