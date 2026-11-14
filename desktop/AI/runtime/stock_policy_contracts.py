"""Single-card stock policy proposals over the shared Stock primitives."""
from AI.processors.operation_policy import AgentOperationPolicy, build_approval_action, prepare_result
from AI.runtime.contracts import AgentTool
from Stock.processors.item_updates import THRESHOLD_FIELDS, preview_item_threshold_update
from settings import DB_NAME


def stock_thresholds_prepare(*, item_id: int, updates: dict, db_name: str = DB_NAME):
    preview = preview_item_threshold_update(item_id=item_id, updates=updates, db_name=db_name)
    if not preview.success or not preview.data["write_required"]:
        return preview
    policy = AgentOperationPolicy(domain="stock", tool="stock.thresholds.prepare", action_type="stock.item_update", risk_level="medium")
    data = preview.data
    action = build_approval_action(policy=policy, title="Stok eşikleri güncellemesi",
        summary=f"{data['record']['name']} ({data['record']['sku']}) stok eşikleri güncellenecek.",
        arguments={"item_id": item_id, "updates": data["requested"]}, rows=[data["row"]], execute_enabled=True)
    return prepare_result(policy=policy, message="Stok eşikleri için eski/yeni değerler onaya hazır.",
        action=action, data={"item_id": item_id, "requested": data["requested"], "write_required": True, "valid": True,
                            "zero_minimum_disables_all_alerts": data["zero_minimum_disables_all_alerts"],
                            "low_stock_policy": data["low_stock_policy"]})


def stock_policy_tools():
    return {"stock.thresholds.prepare": AgentTool(name="stock.thresholds.prepare",
        description="Tek bir stok kartinin minimum/maksimum, emniyet, yeniden siparis esigi veya miktarini degistirmek icin onay teklifi hazirlar. "
            "item_id gercek stock.search/items_list sonucundan gelir. updates icinde yalniz degisecek alanlari gonder: "
            "0 gecerli bir miktardir, null esigi kaldirir, atlanan alanlar korunur. Bu islem eldeki stogu veya hareketleri degistirmez. "
            "Minimumu 0 yapmak tum stok uyarilarini kapatmaz: sifir/negatif bakiye kurali yine gecerlidir. "
            "Emniyet/yeniden siparis ayarlari yalniz konfigurasyondur; bu yazim otomatik bildirim veya siparis calistirildigini kanitlamaz. "
            "Eski/yeni degerler onayda gosterilir; kayit bu arada degisirse eski teklif uygulanmaz. "
            "write_required=false ise istenen degerler zaten kayitlidir, yeni onay gerekmez.",
        parameters={"type": "object", "properties": {"item_id": {"type": "integer", "minimum": 1},
            "updates": {"type": "object", "properties": {name: {"type": ["number", "null"], "minimum": 0}
                for name in THRESHOLD_FIELDS}, "minProperties": 1, "additionalProperties": False}},
            "required": ["item_id", "updates"], "additionalProperties": False},
        handler=stock_thresholds_prepare, domain="stock", requires_approval=True, risk_level="medium", action_type="prepare_write",
        canonical_callable="Stock.processors.item_updates.preview_item_threshold_update",
        result_schema={"type": "object", "properties": {"action": {"type": "object"},
            "item_id": {"type": "integer"}, "requested": {"type": "object"}, "record": {"type": "object"},
            "zero_minimum_disables_all_alerts": {"type": "boolean", "const": False},
            "low_stock_policy": {"type": "object"},
            "write_required": {"type": "boolean"}, "valid": {"type": "boolean"}}})}
