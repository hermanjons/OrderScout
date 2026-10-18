from __future__ import annotations

from datetime import datetime, timezone

from Account.constants import ACCOUNT_TABLE_NAME
from Account.models.models import ApiAccount
from Core.db.migration_builders import (
    SYNC_READY_EXTRA_COLUMNS,
    build_platform_id_backfill_migration,
    build_replace_columns_migration,
)


def _now_iso_text() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


MIGRATIONS = [
    build_replace_columns_migration(
        migration_id="account_0001_apiaccount_identity_columns",
        domain="account",
        description="Move legacy apiaccount seller/logo columns to account_id/logo_path.",
        table_name=ACCOUNT_TABLE_NAME,
        model=ApiAccount,
        old_suffix="__account_0001_old",
        replacements={
            "account_id": ("account_id", "seller_id"),
            "logo_path": ("logo_path", "logo"),
        },
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        required_non_blank=["account_id", "comp_name", "platform"],
        defaults={
            "created_at": lambda row: row.get("created_at") or _now_iso_text(),
            "encrypted": lambda row: row.get("encrypted") if row.get("encrypted") is not None else 0,
            "token_valid": lambda row: row.get("token_valid") if row.get("token_valid") is not None else 1,
            "is_active": lambda row: row.get("is_active") if row.get("is_active") is not None else 1,
            "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
        },
    ),
    build_platform_id_backfill_migration(
        migration_id="account_0002_add_apiaccount_platform_fk",
        domain="account",
        description="Add apiaccount.platform_id and backfill from marketplace code.",
        table_name=ACCOUNT_TABLE_NAME,
        pk_column="pk",
        source_platform_column="platform",
    ),
]
