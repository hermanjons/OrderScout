from pathlib import Path

from AI.processors import report_builder, tools
from AI.processors.operation_runtime import execute_approved_operation
from Core.processors.report_artifacts import verify_report_snapshot_xlsx


def _snapshot():
    return report_builder.build_observation_report_snapshot(
        title="Source report",
        sources=[{"source_id": "source", "source_step_id": "read", "operation_id": "files.read",
                  "result": {"rows": [{"quantity": 4, "currency": "TRY"}]}}],
        sheets=[{"name": "Rows", "source_id": "source", "rows_path": "rows", "columns": [
            {"key": "quantity", "label": "Quantity", "source_path": "quantity", "data_type": "integer"},
            {"key": "currency", "label": "Currency", "source_path": "currency", "data_type": "string"},
        ]}],
    ).to_dict()


def test_relative_filename_is_reviewed_and_exported_in_configured_reports_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "MEDIA_EXPORTS", tmp_path / "exports")
    snapshot = _snapshot()
    prepared = tools.reports_prepare_xlsx(report_snapshot=snapshot, output_path="my-report.xlsx")
    target = (tmp_path / "exports" / "reports" / "my-report.xlsx").resolve()
    assert prepared.success and prepared.data["valid"], prepared.message
    action = prepared.data["action"]
    assert prepared.data["output_path"] == str(target)
    assert action["arguments"]["payload"]["output_path"] == str(target)
    assert action["rows"][0]["file"]["path"] == str(target)
    assert not target.exists()
    result = execute_approved_operation(action, approved_by="isolated-path-test",
                                        idempotency_key="relative-report-path", audit_path=tmp_path / "audit.jsonl")
    assert result.success, result.message
    assert result.data["verify"]["verified"] is True
    assert verify_report_snapshot_xlsx(snapshot, target)["verified"] is True


def test_relative_path_cannot_escape_configured_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "MEDIA_EXPORTS", tmp_path / "exports")
    prepared = tools.reports_prepare_xlsx(report_snapshot=_snapshot(), output_path="../../escape.xlsx")
    assert prepared.success and prepared.data["valid"] is False
    assert prepared.data["action"]["execute_enabled"] is False
    assert prepared.data["action"]["warnings"]
    assert not (tmp_path / "escape.xlsx").exists()


def test_explicit_absolute_output_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "MEDIA_EXPORTS", tmp_path / "exports")
    target = tmp_path / "selected" / "report.xlsx"
    prepared = tools.reports_prepare_xlsx(report_snapshot=_snapshot(), output_path=str(target))
    assert prepared.success and prepared.data["valid"]
    assert Path(prepared.data["output_path"]) == target
    assert not target.exists()
