from __future__ import annotations

from Core.db.migration_builders import (
    build_lookup_foreign_key_rebuild_migration,
    build_platform_id_backfill_migration,
)
from Logistics.models.models import LogisticsCargoProvider, LogisticsCargoTariff


MIGRATIONS = [
    build_platform_id_backfill_migration(
        migration_id="logistics_0001_add_cargo_provider_platform_fk",
        domain="logistics",
        description="Add logistics_cargo_provider.platform_id and backfill from marketplace table.",
        table_name=LogisticsCargoProvider.__tablename__,
        pk_column="pk",
        source_platform_column="platformCode",
    ),
    build_lookup_foreign_key_rebuild_migration(
        migration_id="logistics_0002_add_cargo_tariff_provider_fk",
        domain="logistics",
        description="Add cargo_tariff.cargo_provider_id foreign key and backfill from logistics_cargo_provider.",
        table_name=LogisticsCargoTariff.__tablename__,
        model=LogisticsCargoTariff,
        target_fk_column="cargo_provider_id",
        target_table=LogisticsCargoProvider.__tablename__,
        target_column="pk",
        lookup_table=LogisticsCargoProvider.__tablename__,
        lookup_id_column="pk",
        source_columns=("platform", "cargoProviderCode"),
        lookup_columns=("platformCode", "cargoProviderCode"),
        defaults={"sync_version": 1},
    ),
]
