from __future__ import annotations

from Core.db.migration_builders import build_drop_columns_rebuild_migration
from Marketplaces.models.models import Marketplace

MIGRATIONS = [
    build_drop_columns_rebuild_migration(
        migration_id="marketplaces_0001_drop_capability_flags",
        domain="marketplaces",
        description="Drop legacy capability flags from marketplace table.",
        table_name=Marketplace.__tablename__,
        model=Marketplace,
        dropped_columns=(
            "supportsOrders",
            "supportsReturns",
            "supportsListings",
            "supportsCargoProviderChange",
            "supportsStockPush",
            "supportsPricePush",
            "supportsHealthCheck",
        ),
    ),
]
