"""Synthetic business records for live-model acceptance, never production data.

Application imports are lazy so the CLI can isolate settings before import.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


WORKFLOW_ACCEPTANCE_SPEC = {
    "schema_version": 1,
    "name": "Pilot Stok İncelemesi",
    "instructions": "Tüm aktif stok kayıtlarını güncel kaynaktan oku. Ürün, miktar, birim ve stok değerini göster; her para birimini ayrı tut. Mağaza bağlantısı kanıtı yoksa çıkarma. Excel dosyası oluşturmadan önce o çalışmanın tam raporunu onaya sun.",
    "objective_template": "Güncel stok için {{report_title}} başlıklı Excel raporunu hazırla ve kaydetmeden onayıma sun.",
    "parameter_schema": {"type": "object", "properties": {
        "report_title": {"type": "string", "maxLength": 80}},
        "required": ["report_title"], "additionalProperties": False},
    "source_policy": {"description": "Her çalıştırmada güncel stok kaynağını yeniden oku.", "requires_current_sources": True},
    "effect_policy": {"description": "Her dosya oluşturma için o çalışmanın tam rapor teklifini onaya sun.", "requires_current_approval": True},
}


def workflow_save_prompt() -> str:
    spec = WORKFLOW_ACCEPTANCE_SPEC
    return ("Şu tekrar kullanılabilir iş yönergesini kaydetmek için tam paketi onayıma hazırla; işi şimdi çalıştırma. "
            f"Adı: {spec['name']}. Talimat metnini aynen koru: «{spec['instructions']}» "
            f"Amaç şablonunu aynen koru: «{spec['objective_template']}» "
            "Tek parametre report_title olsun: zorunlu metin, en fazla 80 karakter. Başka parametre kabul etme. "
            f"Kaynak politikası aynen: «{spec['source_policy']['description']}» "
            f"İşlem onayı politikası aynen: «{spec['effect_policy']['description']}» "
            "Her çalıştırma güncel kaynak ve her dosya oluşturma güncel onay gerektirsin. Henüz kalıcı olarak kaydetme.")


def seed_business_fixture(
    db_name: str, *, isolation_root: str | Path, now: datetime | None = None,
) -> dict[str, Any]:
    """Compatibility entrypoint; Testing owns all synthetic domain writes."""
    from Testing.processors.business_agent_fixtures import seed_business_fixture as seed

    return seed(db_name, isolation_root=isolation_root, now=now)
