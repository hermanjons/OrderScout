"""Independent fixture checks over actual source-UI execution receipts.

This module never uses model plans or answer numbers as business evidence.
Its expected values come from the synthetic fixture, not product verifiers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any


def receipt_hash(value: Any) -> str:
    """Hash the JSON observation protocol without importing its producer."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def completed_observation_receipts(turn: dict[str, Any]) -> list[dict[str, Any]]:
    raw = turn.get("raw_turn_data") or {}
    state = raw.get("state") or raw.get("session_state") or (raw.get("tool_result") or {}).get("state") or {}
    receipts = []
    for step in state.get("completed_steps") or []:
        if not isinstance(step, dict) or step.get("status") != "completed" or step.get("verification_status") != "observed":
            continue
        result = (step.get("result_data") or {}).get("tool_result")
        if not isinstance(result, dict):
            continue
        actual_tools = step.get("tool_names") or []
        # File read payloads do not repeat the operation ID. For a completed
        # single-operation step, its actual execution receipt supplies the ID.
        operation = str(result.get("tool") or (actual_tools[0] if len(actual_tools) == 1 else ""))
        if not operation or operation not in (step.get("tool_names") or []):
            continue
        step_id = str(step.get("step_id") or "")
        if not step_id:
            continue
        receipts.append({"source_step_id": step_id, "operation_id": operation,
                         "result": result, "source_result_hash": receipt_hash(result),
                         "observation_ids": list(step.get("observation_ids") or [])})
    return receipts


def fixture_windows(fixture: dict[str, Any]) -> dict[str, dict[str, int]]:
    anchor = datetime.fromisoformat(fixture["as_of"])
    local = anchor.astimezone(timezone(timedelta(hours=3)))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    windows = {}
    for name, start_days, end_days in (("recent", 6, 0), ("previous", 13, 7)):
        start = midnight - timedelta(days=start_days)
        end = midnight - timedelta(days=end_days) + timedelta(days=1, milliseconds=-1)
        windows[name] = {"start_ms": int(start.timestamp() * 1000), "end_ms": int(end.timestamp() * 1000)}
    return windows


def _business_source_receipt(receipt: dict[str, Any]) -> dict[str, Any] | None:
    """Independently inspect historical wrappers; never recast them as fresh reads."""
    result, operation = receipt['result'], receipt['operation_id']
    history = []
    while operation == 'artifacts.read':
        if len(history) >= 16:
            return None
        ref, payload = result.get('artifact'), result.get('result')
        if not isinstance(ref, dict) or not isinstance(payload, dict):
            return None
        origin = ref.get('origin') or {}
        if not isinstance(origin, dict):
            return None
        try:
            timestamp = datetime.fromisoformat(str(result.get('observed_at')).replace('Z', '+00:00'))
        except ValueError:
            return None
        source_hash = receipt_hash(payload)
        if (result.get('tool') != 'artifacts.read' or result.get('verified') is not True
                or result.get('historical_observation') is not True or result.get('fresh_read') is not False
                or result.get('freshness') != 'historical_snapshot' or timestamp.tzinfo is None
                or ref.get('observed_at') != result.get('observed_at') or ref.get('scope') != result.get('scope')
                or ref.get('result_hash') != source_hash
                or any(not isinstance(origin.get(key), str) or not origin[key]
                       for key in ('task_id', 'step_id', 'operation_id'))
                or not any(row.get('step_id') == origin['step_id']
                           and row.get('operation_id') == origin['operation_id']
                           and row.get('result_hash') == source_hash
                           and row.get('observed_at') == result['observed_at']
                           for row in result.get('historical_source_receipts') or [] if isinstance(row, dict))):
            return None
        history.append({'origin': dict(origin), 'observed_at': result['observed_at'],
                        'fresh_read': False, 'original_result_hash': source_hash})
        operation, result = origin['operation_id'], payload
    if history and result.get('tool') not in (None, operation):
        return None
    return {**receipt, 'operation_id': operation, 'result': result,
            'actual_operation_id': receipt['operation_id'], 'historical_sources': history}


def _equal_number(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or actual is None:
        return False
    try:
        value = Decimal(str(actual))
        return value.is_finite() and value == Decimal(str(expected))
    except InvalidOperation:
        return False


def _currency_rows(result: dict[str, Any], field: str, amount: str) -> dict[str, Any]:
    rows = result.get(field) or []
    values = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("currency") or "").upper()
        if not code or code in values:
            return {}  # Duplicate currency rows must not silently overwrite.
        values[code] = row.get(amount)
    return values


def validate_fixture_observations(turn: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    """Require both requested periods and the separately denominated domains."""
    receipts = [normalized for row in completed_observation_receipts(turn)
                for normalized in [_business_source_receipt(row)] if normalized is not None]
    windows = fixture_windows(fixture)
    expected_orders = fixture["orders"]
    matches: dict[str, list[dict[str, Any]]] = {}

    def complete_item_scope(result: dict[str, Any]) -> bool:
        # Item totals describe the complete canonical eligible order population
        # only when no identity subset or truncated projection was requested.
        counts = [result.get(key) for key in ("order_count", "matched_order_count", "population_order_count")]
        snapshot_hash = result.get("source_snapshot_hash")
        return (result.get("metrics_complete") is True and result.get("truncated") is False
                and type(result.get("identity_filter_count")) is int and result["identity_filter_count"] == 0
                and all(type(value) is int and value >= 0 for value in counts) and len(set(counts)) == 1
                and len(result.get("account_scopes") or []) == 1
                and isinstance(snapshot_hash, str) and len(snapshot_hash) == 64
                and all(character in "0123456789abcdef" for character in snapshot_hash))

    def item_window_matches(result: dict[str, Any], window: dict[str, int]) -> bool:
        observed = False
        for start_key, end_key in (("start_ms", "end_ms"), ("start_date_ms", "end_date_ms")):
            if start_key not in result and end_key not in result:
                continue
            if (type(result.get(start_key)) is not int or type(result.get(end_key)) is not int
                    or result[start_key] != window["start_ms"] or result[end_key] != window["end_ms"]):
                return False  # Conflicting or incomplete aliases cannot be ignored.
            observed = True
        return observed

    def item_revenue_matches(result: dict[str, Any], expected: int) -> bool:
        gross = result.get("gross_amount_by_currency")
        rows = result.get("rows")
        if (result.get("currency") != "TRY" or not isinstance(gross, dict) or set(gross) != {"TRY"}
                or not isinstance(rows, list) or not rows
                or type(result.get("total_gross_amount")) not in {int, float} or type(gross["TRY"]) not in {int, float}
                or not _equal_number(result.get("total_gross_amount"), expected)
                or not _equal_number(gross["TRY"], expected)):
            return False
        identities, row_total = set(), Decimal(0)
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get("identity"), str) or not row["identity"]
                    or row["identity"] in identities or row.get("currency") != "TRY"
                    or type(row.get("gross_amount")) not in {int, float}
                    or not _equal_number(row["gross_amount"], row["gross_amount"])):
                return False
            identities.add(row["identity"])
            row_total += Decimal(str(row["gross_amount"]))
        return row_total == Decimal(str(expected))

    for name, window in windows.items():
        scoped = []
        for receipt in receipts:
            result = receipt["result"]
            if not receipt["operation_id"].startswith("orders."):
                continue
            if result.get("requested_api_account_ids") != [expected_orders["primary_account_id"]]:
                continue
            scopes = result.get("account_scopes") or []
            if not scopes or any(row.get("api_account_id") != expected_orders["primary_account_id"]
                                 or row.get("environment") != "stage" for row in scopes):
                continue
            if receipt["operation_id"] == "orders.item_sales_summary":
                if not complete_item_scope(result) or not item_window_matches(result, window):
                    continue
            elif any(result.get(key) != value for key, value in window.items()):
                continue
            if not result.get("source_snapshot_hash"):
                continue
            scoped.append(receipt)
        matches[name] = scoped

    checks = {}
    proof = {}
    for name in windows:
        count = expected_orders[name + "_count"]
        revenue = expected_orders[name + "_revenue_try"]
        count_receipts = [row for row in matches[name] if
                          (row["operation_id"] == "orders.count" and _equal_number(row["result"].get("count"), count))
                          or (row["operation_id"] == "orders.summary" and _equal_number(row["result"].get("total_orders"), count))
                          or (row["operation_id"] == "orders.item_sales_summary" and _equal_number(row["result"].get("order_count"), count))]
        revenue_receipts = [row for row in matches[name] if row["operation_id"] in {"orders.summary", "orders.revenue_total"}
                            and row["result"].get("currency") == "TRY"
                            and _equal_number(row["result"].get("estimated_revenue"), revenue)
                            and (not row["result"].get("revenue_by_currency")
                                 or set(row["result"]["revenue_by_currency"]) == {"TRY"})]
        revenue_receipts.extend(row for row in matches[name] if row["operation_id"] == "orders.item_sales_summary"
                                and item_revenue_matches(row["result"], revenue))
        checks["orders_" + name + "_count"] = bool(count_receipts)
        checks["orders_" + name + "_revenue_try"] = bool(revenue_receipts)
        proof[name] = {"expected_window": windows[name], "expected_account_id": expected_orders["primary_account_id"],
                       "expected_count": count, "expected_revenue_try": revenue,
                       "count_receipts": [{key: row[key] for key in ("source_step_id", "operation_id", "source_result_hash")} for row in count_receipts],
                       "revenue_receipts": [{key: row[key] for key in ("source_step_id", "operation_id", "source_result_hash")} for row in revenue_receipts]}

    for domain, operation, field, amount, expected in (
        ("stock", "stock.inventory_overview", "stock_value_by_currency", "amount", fixture["stock"]["stock_value_by_currency"]),
        ("finance", "finance.cashflow_summary", "currency_totals", "combined_net", fixture["finance"]["movement_net_by_currency"]),
    ):
        candidates = []
        for row in receipts:
            if row["operation_id"] != operation:
                continue
            values = _currency_rows(row["result"], field, amount)
            if set(values) != set(expected) or any(not _equal_number(values[code], value) for code, value in expected.items()):
                continue
            if domain == "finance":
                result = row["result"]
                if result.get("combined_net") is not None:
                    continue
                transaction_ms = int((datetime.fromisoformat(fixture["as_of"]) - timedelta(days=1)).timestamp() * 1000)
                start, end = result.get("start_ms"), result.get("end_ms")
                # Finance was requested without a period. Check the actual
                # frame contains the fixture movements, and expose that frame.
                if (start is not None and start > transaction_ms) or (end is not None and end < transaction_ms):
                    continue
            candidates.append(row)
        checks[domain + "_separate_currency_values"] = bool(candidates)
        proof[domain] = {"expected_values": expected,
                         "receipts": [{key: row[key] for key in ("source_step_id", "operation_id", "source_result_hash")} for row in candidates]}
        if domain == "finance":
            proof[domain]["actual_frames"] = [{key: row["result"].get(key) for key in ("period", "start_ms", "end_ms")} for row in candidates]
    return {"passed": all(checks.values()), "checks": checks, "proof": proof,
            "problems": ["fixture_observation_missing_or_mismatched:" + key for key, passed in checks.items() if not passed],
            "boundary": "Actual completed tool results only. Visible answer quality and inference limits require direct review."}


def validate_general_report_sources(
    turn: dict[str, Any], *, required_domains: tuple[str, ...] = ("orders", "stock", "finance"),
    required_source_operations: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Report provenance must refer to exact completed business observations."""
    receipts = completed_observation_receipts(turn)
    by_id = {row["source_step_id"]: row for row in receipts}
    reports = [row for row in receipts if row["operation_id"] == "reports.build_snapshot"]
    problems = []
    proof = []
    if not reports:
        problems.append("general_report_snapshot_not_observed")
    for report in reports:
        result = report["result"]
        snapshot = result.get("report_snapshot") or {}
        source_rows = (snapshot.get("metadata") or {}).get("source_receipts") or []
        domains = set()
        bound = []
        for source in source_rows:
            actual = by_id.get(str(source.get("source_step_id") or ""))
            exact = bool(actual and source.get("operation_id") == actual["operation_id"]
                         and source.get("source_result_hash") == actual["source_result_hash"])
            if not exact:
                problems.append("general_report_source_not_exact_completed_observation")
                continue
            normalized = _business_source_receipt(actual)
            if normalized is None:
                problems.append('general_report_historical_source_invalid')
                continue
            domains.add(actual["operation_id"].split(".", 1)[0])
            domains.add(normalized["operation_id"].split(".", 1)[0])
            bound.append({**{key: source[key] for key in ("source_step_id", "operation_id", "source_result_hash")},
                          'original_operation_id': normalized['operation_id'],
                          'historical_sources': normalized['historical_sources']})
        for domain in required_domains:
            if domain not in domains:
                problems.append("general_report_source_domain_missing:" + domain)
        bound_operations = {row[key] for row in bound for key in ('operation_id', 'original_operation_id')}
        for operation in required_source_operations:
            if operation not in bound_operations:
                problems.append("general_report_required_source_operation_missing:" + operation)
        if snapshot.get("source_domain") != "reports" or snapshot.get("report_type") != "reports.observations":
            problems.append("general_report_family_mismatch")
        if not snapshot.get("snapshot_id") or not snapshot.get("content_hash"):
            problems.append("general_report_immutable_identity_missing")
        if not (snapshot.get("metadata") or {}).get("data_row_count"):
            problems.append("general_report_data_rows_missing")
        pending = turn.get("pending_action") or turn.get("action_proposal") or {}
        if pending:
            arguments = pending.get("arguments") or {}
            prepared_snapshot = (arguments.get("payload") or pending.get("safe_payload") or {}).get("report_snapshot") or {}
            if (prepared_snapshot.get("snapshot_id") != snapshot.get("snapshot_id")
                    or prepared_snapshot.get("content_hash") != snapshot.get("content_hash")
                    or receipt_hash(prepared_snapshot) != receipt_hash(snapshot)):
                problems.append("general_report_proposal_not_exact_built_snapshot")
        proof.append({"build_step_id": report["source_step_id"], "snapshot_id": snapshot.get("snapshot_id"),
                      "content_hash": snapshot.get("content_hash"), "bound_sources": bound})
    return {"passed": not problems, "problems": list(dict.fromkeys(problems)), "proof": proof,
            "boundary": "Exact source provenance and report family; usefulness and visible layout require direct review."}


def _file_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("format") == "json":
        return result.get("rows") or []
    columns = result.get("columns") or []
    labels = {column["key"]: column["label"] for column in columns}
    return [{labels[key]: value for key, value in row.items() if key in labels}
            for row in result.get("rows") or []]


def validate_attachment_observations(
    turn: dict[str, Any], fixtures: dict[str, dict[str, Any]], selected_metadata: list[dict[str, Any]],
    *, required_formats: tuple[str, ...],
) -> dict[str, Any]:
    receipts = completed_observation_receipts(turn)
    problems, proof = [], []
    for kind in required_formats:
        expected = fixtures[kind]
        selected = [row for row in selected_metadata if row.get("name") == expected["name"]
                    and row.get("sha256") == expected["sha256"] and row.get("format") == kind]
        if not selected:
            problems.append("attachment_not_imported_through_source_ui:" + kind)
            continue
        valid = []
        for receipt in receipts:
            result = receipt["result"]
            if receipt["operation_id"] != "files.read" or result.get("verified") is not True:
                continue
            owner = next((row for row in selected if row.get("attachment_id") == result.get("attachment_id")
                          and row.get("session_id") == result.get("session_id")), None)
            if not owner or result.get("source_hash") != expected["sha256"]:
                continue
            if result.get("source_type") != "user_selected_attachment" or result.get("content_is_untrusted_data") is not True:
                continue
            coverage = result.get("data_coverage") or {}
            scope = result.get("read_scope") or {}
            if coverage.get("status") != "complete" or scope.get("truncated") or scope.get("row_offset") != 0:
                continue
            rows = _file_rows(result)
            if receipt_hash(rows) != receipt_hash(expected["rows"]):
                continue
            if any(isinstance(row.get("quantity"), bool) or not isinstance(row.get("quantity"), (int, float))
                   or isinstance(row.get("revenue"), bool) or not isinstance(row.get("revenue"), (int, float))
                   or row.get("discount") is not None for row in rows):
                continue
            valid.append(receipt)
        if not valid:
            problems.append("attachment_actual_native_rows_not_proven:" + kind)
        proof.append({"format": kind, "expected_sha256": expected["sha256"], "expected_rows": expected["rows"],
                      "actual_receipts": [{key: row[key] for key in ("source_step_id", "operation_id", "source_result_hash")} for row in valid]})
    return {"passed": not problems, "problems": problems, "proof": proof,
            "boundary": "Actual user-selected immutable file rows and native numbers/nulls; visible analysis still requires direct review."}


def validate_attachment_export_cells(
    retained_export: dict[str, Any], fixtures: dict[str, dict[str, Any]], *, required_formats: tuple[str, ...],
    report_snapshot: dict[str, Any] | None = None, source_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bind original fields to exact projected columns and independently read cells."""
    actual_sheets = retained_export.get("sheets") or []
    required_fields = ("sku", "quantity", "unit", "revenue", "currency", "discount")
    problems, matches = [], []
    snapshot = report_snapshot or {}
    metadata = snapshot.get("metadata") or {}
    content = {key: snapshot.get(key) for key in (
        "schema_version", "title", "source_domain", "report_type", "filters", "metadata", "sheets",
    )}
    if (not snapshot or snapshot.get("source_domain") != "reports"
            or snapshot.get("report_type") != "reports.observations"
            or snapshot.get("content_hash") != receipt_hash(content)
            or snapshot.get("snapshot_id") != "rpt_" + receipt_hash(content)[:24]):
        return {"passed": False, "problems": ["attachment_report_projection_identity_missing_or_changed"], "proof": []}
    if (retained_export.get("approved_snapshot_id", snapshot["snapshot_id"]) != snapshot["snapshot_id"]
            or retained_export.get("approved_content_hash", snapshot["content_hash"]) != snapshot["content_hash"]):
        problems.append("attachment_saved_report_not_exact_approved_snapshot")
    actual_by_name = {sheet.get("name"): sheet for sheet in actual_sheets if isinstance(sheet, dict)}
    schema_by_name = {sheet.get("name"): sheet for sheet in snapshot.get("sheets") or [] if isinstance(sheet, dict)}
    receipts_by_step = {row.get("source_step_id"): row for row in source_receipts or [] if isinstance(row, dict)}
    bound_sources = {}
    for source in metadata.get("source_receipts") or []:
        actual = receipts_by_step.get(source.get("source_step_id"))
        if (actual and source.get("operation_id") == actual.get("operation_id") == "files.read"
                and source.get("source_result_hash") == actual.get("source_result_hash") == receipt_hash(actual.get("result"))):
            bound_sources[source.get("source_id")] = actual["result"]

    def equal_cell(actual, expected):
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            return isinstance(actual, (int, float)) and not isinstance(actual, bool) and actual == expected
        return type(actual) is type(expected) and actual == expected

    for kind in required_formats:
        expected_file = fixtures[kind]
        expected_rows = expected_file["rows"]
        candidates_by_sku = {row["sku"]: [] for row in expected_rows}
        for projection in metadata.get("projections") or []:
            result = bound_sources.get(projection.get("source_id"))
            if not result or result.get("format") != kind:
                continue
            attachment = result.get("attachment") or {}
            if (result.get("verified") is not True or result.get("source_hash") != expected_file["sha256"]
                    or attachment.get("name") != expected_file["name"]
                    or attachment.get("sha256") != expected_file["sha256"]
                    or attachment.get("attachment_id") != result.get("attachment_id")
                    or attachment.get("session_id") != result.get("session_id")
                    or result.get("source_type") != "user_selected_attachment"
                    or result.get("content_is_untrusted_data") is not True
                    or (result.get("data_coverage") or {}).get("status") != "complete"
                    or (result.get("read_scope") or {}).get("row_offset") != 0
                    or (result.get("read_scope") or {}).get("truncated")
                    or receipt_hash(_file_rows(result)) != receipt_hash(expected_rows)):
                continue
            name = projection.get("sheet")
            actual_sheet, schema = actual_by_name.get(name), schema_by_name.get(name)
            columns = projection.get("columns") or []
            if not actual_sheet or not schema or len(columns) != len(schema.get("columns") or []):
                problems.append("attachment_projected_sheet_schema_missing:" + str(name))
                continue
            if any(any(column.get(key) != declared.get(key) for key in ("key", "label", "data_type"))
                   for column, declared in zip(columns, schema["columns"])):
                problems.append("attachment_projected_column_schema_changed:" + str(name))
                continue
            # File row fields are flat. XLSX uses immutable column_N keys whose
            # original header labels supply their field identities. Report labels
            # and column ordering may differ without changing these bindings.
            source_fields = ({column["key"]: column["label"] for column in result.get("columns") or []}
                             if kind == "xlsx" else {field: field for field in required_fields})
            field_columns = {}
            for index, column in enumerate(columns):
                path = str(column.get("source_path") or "")
                key = path[1:].replace("~1", "/").replace("~0", "~") if path.startswith("/") else path
                field = source_fields.get(key)
                if field in required_fields:
                    if field in field_columns:
                        problems.append("attachment_original_field_projected_twice:" + field)
                    field_columns[field] = index
                    if column.get("key") in required_fields and column["key"] != field:
                        problems.append("attachment_declared_field_source_mismatch:" + column["key"])
            if set(field_columns) != set(required_fields):
                problems.append("attachment_original_field_column_binding_missing:" + str(name))
                continue
            if projection.get("rows_path") not in {"rows", "/rows"}:
                problems.append("attachment_original_records_not_in_single_table:" + str(name))
                continue
            rows = actual_sheet.get("rows") or []
            offset = 0 if actual_sheet.get("columns") else 1
            if offset and (not rows or rows[0] != [column["label"] for column in schema["columns"]]):
                problems.append("attachment_saved_headers_changed:" + str(name))
                continue
            for row_number, row in enumerate(rows[offset:], offset + 1):
                if not isinstance(row, list) or len(row) != len(columns):
                    problems.append("attachment_saved_row_width_changed:" + str(name))
                    continue
                sku = row[field_columns["sku"]]
                if isinstance(sku, str) and sku in candidates_by_sku:
                    expected = next(record for record in expected_rows if record["sku"] == sku)
                    if all(equal_cell(row[field_columns[field]], expected[field]) for field in required_fields):
                        candidates_by_sku[sku].append({"sheet": name, "row": row_number,
                            "field_columns": {field: index + 1 for field, index in field_columns.items()}})
            if len(rows[offset:]) != len(expected_rows):
                problems.append("attachment_saved_record_count_changed:" + str(name))
        for expected in expected_rows:
            candidates = candidates_by_sku[expected["sku"]]
            if not candidates:
                problems.append("attachment_saved_record_cells_missing_or_changed:" + expected["sku"])
            elif len(candidates) != 1:
                problems.append("attachment_saved_record_duplicated:" + expected["sku"])
            matches.append({"format": kind, "expected_record": expected, "saved_rows": candidates})
    return {"passed": not problems, "problems": problems, "proof": matches,
            "boundary": "Exact immutable source receipt and field-to-column-to-cell comparison, preserving native numbers, nulls, units and currencies."}
