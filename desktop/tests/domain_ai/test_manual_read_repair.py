"""A blocked write-as-read supplies a truthful next contract without executing it."""
from AI.processors import operation_runtime


def test_write_capability_read_is_blocked_with_prepare_hint_and_no_effect(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Write capability must never be resolved or called by a read")

    monkeypatch.setattr(operation_runtime, "_callable_for_capability", forbidden)
    result = operation_runtime.execute_manual_read_action(
        capability_id="listing.action_set_listing_stock_items", payload={},
        db_name=str(tmp_path / "business.sqlite3"), audit_path=tmp_path / "audit.jsonl")
    assert not result.success
    assert "write capability" in result.data["reasons"]
    assert result.data["effect_executed"] is False
    assert result.data["next_operation"] == "operations.manual_action.prepare"
    assert result.data["next_operation_executes"] is False
    assert not (tmp_path / "business.sqlite3").exists()
    assert not (tmp_path / "audit.jsonl").exists()
