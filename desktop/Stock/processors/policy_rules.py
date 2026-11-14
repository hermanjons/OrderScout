"""Document exactly what the shared low-stock read evaluates, not automation."""
THRESHOLD_FIELDS = ("min_stock", "max_stock", "safety_stock", "reorder_point", "reorder_qty")


def low_stock_policy_metadata():
    return {
        "capability": "stock.low_stock",
        "comparison": "less_than_or_equal",
        "evaluated_fields": ["balance", "min_stock"],
        "zero_or_negative_always_critical": True,
        "zero_minimum_disables_all_alerts": False,
        "stored_fields_not_evaluated_by_this_read": [name for name in THRESHOLD_FIELDS if name != "min_stock"],
        "notification_or_reorder_execution_proven": False,
        "description": "Bu okuma yalnız minimum stok ve sıfır/negatif bakiye kuralını değerlendirir. "
            "Emniyet stoku ve yeniden sipariş değerlerinin kaydedilmiş olması bir uyarı veya otomatik siparişin "
            "çalıştığını kanıtlamaz; bu alanlar düşük stok hesabına katılmaz.",
    }
