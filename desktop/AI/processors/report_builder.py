"""Build immutable report projections from runtime-bound operation results.

The runtime owns source identity and binding authorization. This module copies
source fields into a model-selected layout; it never calculates domain metrics
or treats a model-authored number as an observed value.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping

from Core.processors.report_artifacts import ReportColumn, ReportSnapshot, make_report_sheet
from AI.processors.observation_projection import (
    normalize_projection_value as _json_value,
    observed_source_payload,
    source_path_value as _path_value,
    source_projection_hash,
)


_NOTE_SHEET = "Model Notları"
_SOURCE_SHEET = "Kaynak Kanıtı"
_MAX_DATA_ROWS = 10_000
_MAX_DATA_CELLS = 100_000
_MAX_DIAGNOSTIC_PATHS = 96
_MAX_DIAGNOSTIC_DEPTH = 4
_MAX_DIAGNOSTIC_PATH_LENGTH = 256


class ReportProjectionError(ValueError):
    """Keep the exact rejection reason and bounded structural recovery evidence."""

    def __init__(self, reason_code: str, diagnostic: dict[str, Any]):
        super().__init__(reason_code)
        self._diagnostic = deepcopy(diagnostic)

    @property
    def diagnostic(self) -> dict[str, Any]:
        return deepcopy(self._diagnostic)


def projection_failure_diagnostic(error: Exception) -> dict[str, Any]:
    return error.diagnostic if isinstance(error, ReportProjectionError) else {}


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, (float, Decimal)):
        return "number"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "unsupported"


def _structural_shape(value: Any) -> dict[str, Any]:
    """Describe paths and types, never cell values or samples of strings."""
    paths: list[dict[str, str]] = []
    truncated = False

    def visit(node: Any, path: str, depth: int) -> None:
        nonlocal truncated
        if len(paths) >= _MAX_DIAGNOSTIC_PATHS or len(path) > _MAX_DIAGNOSTIC_PATH_LENGTH:
            truncated = True
            return
        paths.append({"path": path, "type": _value_type(node)})
        if depth >= _MAX_DIAGNOSTIC_DEPTH:
            truncated = truncated or isinstance(node, (Mapping, list, tuple)) and bool(node)
            return
        if isinstance(node, Mapping):
            for key, child in node.items():
                if len(paths) >= _MAX_DIAGNOSTIC_PATHS:
                    truncated = True
                    break
                name = str(key)
                # Credentials are not report fields. Do not echo their names
                # or descendants if an upstream result contains them.
                compact = name.casefold().replace("_", "").replace("-", "")
                if any(part in compact for part in ("password", "secret", "token", "credential", "authorization", "cookie", "apikey")):
                    continue
                escaped = name.replace("~", "~0").replace("/", "~1")
                visit(child, f"{path}/{escaped}", depth + 1)
        elif isinstance(node, (list, tuple)) and node:
            # A structural sample of the first row is bounded independently
            # of the source row count. A failing row has its own shape below.
            visit(node[0], f"{path}/0", depth + 1)

    visit(value, "", 0)
    return {"paths": paths, "truncated": bool(truncated), "array_items": "first_item_structure"}


def _projection_error(
    reason_code: str, *, source: dict[str, Any], projection_kind: str,
    sheet_index: int, rows_path: str, selected: Any,
    source_path: str = "", column_index: int | None = None,
    row_index: int | None = None,
) -> ReportProjectionError:
    return ReportProjectionError(reason_code, {
        "version": 1, "reason_code": reason_code[:512],
        "projection_kind": projection_kind,
        "source_id": str(source["source_id"])[:128],
        "source_step_id": str(source["source_step_id"])[:128],
        "operation_id": str(source["operation_id"])[:128],
        "source_result_hash": source_projection_hash(source["result"]),
        "sheet_index": sheet_index, "column_index": column_index, "row_index": row_index,
        "rows_path": rows_path[:_MAX_DIAGNOSTIC_PATH_LENGTH],
        "source_path": source_path[:_MAX_DIAGNOSTIC_PATH_LENGTH],
        "source_shape": _structural_shape(source["result"]),
        "projection_shape": _structural_shape(selected),
        "path_guidance": {
            "rows_path": "relative_to_bound_source_result; empty_string_selects_source_root",
            "source_path": "relative_to_selected_row",
            "shape_paths": "JSON_pointer; scalar_values_are_omitted",
        },
    })


def report_builder_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "sources": {"type": "array", "minItems": 1, "maxItems": 64, "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "minLength": 1},
                    "source_step_id": {"type": "string", "minLength": 1},
                    "operation_id": {"type": "string", "minLength": 1},
                    "result": {"type": "object"},
                },
                "required": ["source_id", "source_step_id", "operation_id", "result"],
                "additionalProperties": False,
            }},
            "sheets": {"type": "array", "minItems": 1, "maxItems": 20, "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "source_id": {"type": "string", "minLength": 1},
                    "rows_path": {"type": "string", "description": (
                        "Path relative to the bound sources[].result, without another tool_result prefix. "
                        "Use an empty string to select the source root as one row; arrays select their record rows."
                    )},
                    "rows_mode": {"type": "string", "enum": ["records", "object_entries"], "description": (
                        "Default records selects one object or an array of records. object_entries converts "
                        "a selected dictionary into exact {key: original_key, value: original_value} rows; "
                        "use source_path=key or value (or value.field). Never invent status/count fields."
                    )},
                    "columns": {"type": "array", "minItems": 1, "maxItems": 100, "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "minLength": 1},
                            "label": {"type": "string", "minLength": 1},
                            "source_path": {"type": "string", "minLength": 1, "description": (
                                "Exact observed field path relative to each selected row, not to the full tool result."
                            )},
                            "data_type": {"type": "string", "enum": ["string", "integer", "number", "boolean", "date", "datetime"]},
                            "number_format": {"type": "string"},
                            "width": {"type": "number", "minimum": 8, "maximum": 60},
                        },
                        "required": ["key", "label", "source_path", "data_type"],
                        "additionalProperties": False,
                    }},
                },
                "required": ["name", "source_id", "rows_path", "columns"],
                "additionalProperties": False,
            }},
            "notes": {"type": "array", "maxItems": 100, "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "enum": ["hypothesis", "assumption", "recommendation"]},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "kind", "source_ids"],
                "additionalProperties": False,
            }},
        },
        "required": ["title", "sources", "sheets"],
        "additionalProperties": False,
    }


def _validate_cell(value: Any, data_type: str, path: str) -> None:
    if value is None:
        return  # An observed null stays null; it is never converted to zero.
    valid = (
        data_type == "string" and isinstance(value, str)
        or data_type == "boolean" and isinstance(value, bool)
        or data_type == "integer" and isinstance(value, int) and not isinstance(value, bool)
        or data_type == "number" and isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
        or data_type in {"date", "datetime"} and isinstance(value, (str, date, datetime))
    )
    if not valid:
        raise ValueError(f"report_column_source_type_mismatch:{path}:{data_type}")


def build_observation_report_snapshot(
    *,
    title: str,
    sources: list[dict[str, Any]],
    sheets: list[dict[str, Any]],
    notes: list[dict[str, Any]] | None = None,
) -> ReportSnapshot:
    if not sources or not sheets:
        raise ValueError("report_sources_and_sheets_required")
    if len(sources) > 64 or len(sheets) > 20:
        raise ValueError("report_source_or_sheet_limit_exceeded")
    sources_by_id: dict[str, dict[str, Any]] = {}
    receipts: list[dict[str, Any]] = []
    for source in sources:
        source_id = str(source.get("source_id") or "").strip()
        step_id = str(source.get("source_step_id") or "").strip()
        operation_id = str(source.get("operation_id") or "").strip()
        result = source.get("result")
        if not source_id or not step_id or not operation_id or not isinstance(result, Mapping):
            raise ValueError("report_source_identity_and_result_required")
        if source_id in sources_by_id:
            raise ValueError("report_source_ids_must_be_unique")
        sources_by_id[source_id] = source
        _, original, provenance = observed_source_payload(result, operation_id)
        receipts.append({
            "source_id": source_id, "source_step_id": step_id, "operation_id": operation_id,
            "source_result_hash": source_projection_hash(result),
            "coverage": _json_value(original.get("data_coverage", original.get("coverage"))),
            **({"source_provenance": provenance,
                "source_freshness": provenance["freshness"],
                "source_observed_at": "; ".join(provenance["observed_at"]) if isinstance(provenance["observed_at"], list) else provenance["observed_at"],
                "original_operation_id": "; ".join(provenance["original_operation_ids"]) if "original_operation_ids" in provenance else provenance["original_operation_id"],
                "source_is_fresh_read": False} if provenance else {}),
        })

    projected_sheets = []
    projections = []
    data_row_count = 0
    data_cell_count = 0
    null_cell_count = 0
    for sheet_index, specification in enumerate(sheets):
        source_id = str(specification.get("source_id") or "").strip()
        if source_id not in sources_by_id:
            raise ValueError("report_sheet_source_not_bound")
        name = str(specification.get("name") or "").strip()
        if name.casefold() in {_NOTE_SHEET.casefold(), _SOURCE_SHEET.casefold()}:
            raise ValueError("report_sheet_name_reserved")
        rows_path = str(specification.get("rows_path") or "")
        source = sources_by_id[source_id]
        try:
            selected = _path_value(source["result"], rows_path)
        except ValueError as exc:
            raise _projection_error(str(exc), source=source, projection_kind="rows",
                                    sheet_index=sheet_index, rows_path=rows_path,
                                    selected=source["result"]) from exc
        rows_mode = specification.get("rows_mode", "records")
        if rows_mode not in {"records", "object_entries"}:
            raise ValueError("report_rows_mode_invalid")
        if rows_mode == "object_entries":
            if not isinstance(selected, Mapping) or any(not isinstance(key, str) for key in selected):
                raise _projection_error("report_object_entries_requires_string_key_mapping", source=source,
                                        projection_kind="rows", sheet_index=sheet_index,
                                        rows_path=rows_path, selected=selected)
            source_rows = [{"key": key, "value": value} for key, value in selected.items()]
        else:
            source_rows = [selected] if isinstance(selected, Mapping) else selected
        if not isinstance(source_rows, (list, tuple)) or any(not isinstance(row, Mapping) for row in source_rows):
            raise _projection_error("report_source_rows_must_be_records", source=source,
                                    projection_kind="rows", sheet_index=sheet_index,
                                    rows_path=rows_path, selected=selected)
        column_specs = specification.get("columns") or []
        if not isinstance(column_specs, list) or not column_specs or len(column_specs) > 100:
            raise ValueError("report_column_schema_required")
        columns = tuple(ReportColumn.from_dict(column) for column in column_specs)
        data_row_count += len(source_rows)
        data_cell_count += len(source_rows) * len(columns)
        if data_row_count > _MAX_DATA_ROWS or data_cell_count > _MAX_DATA_CELLS:
            raise ValueError("report_projection_limit_exceeded")
        rows = []
        for row_index, source_row in enumerate(source_rows):
            projected = {}
            for column_index, (column, specification_column) in enumerate(zip(columns, column_specs)):
                source_path = str(specification_column.get("source_path") or "")
                try:
                    value = _path_value(source_row, source_path)
                    _validate_cell(value, column.data_type, source_path)
                except ValueError as exc:
                    raise _projection_error(str(exc), source=source, projection_kind="column",
                                            sheet_index=sheet_index, rows_path=rows_path,
                                            selected=source_row, source_path=source_path,
                                            column_index=column_index, row_index=row_index) from exc
                null_cell_count += int(value is None)
                projected[column.key] = value
            rows.append(projected)
        projected_sheets.append(make_report_sheet(name=name, columns=columns, rows=rows))
        projections.append({
            "sheet": name, "source_id": source_id, "rows_path": rows_path,
            "row_count": len(rows), "columns": _json_value(column_specs),
            **({"rows_mode": rows_mode} if rows_mode != "records" else {}),
        })

    note_rows = []
    if len(notes or []) > 100:
        raise ValueError("report_note_limit_exceeded")
    for note in notes or []:
        kind = str(note.get("kind") or "").strip()
        text = str(note.get("text") or "").strip()
        source_ids = note.get("source_ids")
        if kind not in {"hypothesis", "assumption", "recommendation"} or not text:
            raise ValueError("report_note_kind_and_text_required")
        if not isinstance(source_ids, list) or any(source_id not in sources_by_id for source_id in source_ids):
            raise ValueError("report_note_source_not_bound")
        note_rows.append({"kind": kind, "text": text, "sources": ", ".join(source_ids),
                          "basis": "Model inference; not a verified source fact"})
    if note_rows:
        projected_sheets.append(make_report_sheet(
            name=_NOTE_SHEET,
            columns=(ReportColumn("kind", "Tür"), ReportColumn("text", "Model notu", width=60),
                     ReportColumn("sources", "Dayanak kaynakları", width=36),
                     ReportColumn("basis", "Kanıt sınırı", width=48)), rows=note_rows,
        ))
    source_columns = (ReportColumn("source_id", "Kaynak"), ReportColumn("source_step_id", "Gözlem adımı", width=28),
                      ReportColumn("operation_id", "Operasyon", width=40),
                      ReportColumn("source_result_hash", "Kaynak sonucu SHA256", width=60))
    if any("source_provenance" in receipt for receipt in receipts):
        source_columns += (ReportColumn("source_freshness", "Kaynak güncelliği", width=36),
                           ReportColumn("source_observed_at", "Asıl gözlem zamanı", width=40),
                           ReportColumn("original_operation_id", "Asıl kaynak operasyonu", width=40),
                           ReportColumn("source_is_fresh_read", "Yeni kaynak sorgusu", data_type="boolean"))
    projected_sheets.append(make_report_sheet(
        name=_SOURCE_SHEET,
        columns=source_columns, rows=receipts,
    ))
    return ReportSnapshot.create(
        title=title, source_domain="reports", report_type="reports.observations",
        filters={"source_ids": list(sources_by_id)},
        metadata={"source_receipts": receipts, "projections": projections,
                  "data_row_count": data_row_count, "data_cell_count": data_cell_count,
                  "null_cell_count": null_cell_count, "model_note_count": len(note_rows),
                  "model_notes_are_verified_facts": False, "domain_calculations_performed": False},
        sheets=projected_sheets,
    )
