"""Revalidate source-bound arithmetic before exposing it to final answers."""
from __future__ import annotations

from typing import Any

from AI.processors.observation_projection import source_path_value, source_projection_hash
from AI.processors.analysis_operations import calculate_observations
from AI.processors.session_state import AgentSessionState
from Core.processors.verified_calculations import evaluate_verified_calculation, evaluate_verified_comparison


def verified_observation_tables(state: AgentSessionState) -> list[dict[str, Any]]:
    from AI.processors.tabular_analysis import analyze_observation_table

    completed = {step.step_id: step for step in state.completed_steps
                 if step.status == "completed" and step.verification_status in {"observed", "verified"}}
    tables = []
    for step in state.completed_steps:
        if step.step_id not in completed or step.tool_names != ["analysis.table"]:
            continue
        payload = (step.result_data or {}).get("tool_result") or {}
        try:
            if payload.get("verified") is not True or payload.get("tool") != "analysis.table":
                continue
            if payload.get("evidence_hash") != source_projection_hash({key: value for key, value in payload.items() if key != "evidence_hash"}):
                continue
            sources = []
            for receipt in payload["source_receipts"]:
                source_step = completed.get(receipt["source_step_id"])
                result = (source_step.result_data or {}).get("tool_result") if source_step else None
                if (source_step is None or source_step.tool_names != [receipt["operation_id"]]
                        or not isinstance(result, dict) or source_projection_hash(result) != receipt["source_result_hash"]):
                    raise ValueError("table_source_receipt_drift")
                sources.append({**{key: receipt[key] for key in ("source_id", "source_step_id", "operation_id")}, "result": result})
            recomputed = analyze_observation_table(sources=sources, **payload["analysis_contract"])
            if recomputed.success and recomputed.data["evidence_hash"] == payload["evidence_hash"]:
                tables.append(payload)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    return tables


def verified_observation_calculations(state: AgentSessionState) -> list[dict[str, Any]]:
    completed = {step.step_id: step for step in state.completed_steps
                 if step.status == "completed" and step.verification_status in {"observed", "verified"}}
    all_verified = []
    for step in state.completed_steps:
        if step.step_id not in completed or step.tool_names != ["analysis.calculate"]:
            continue
        payload = (step.result_data or {}).get("tool_result") or {}
        if not isinstance(payload, dict) or payload.get("verified") is not True:
            continue
        try:
            if payload.get("evidence_hash") != source_projection_hash({key: value for key, value in payload.items() if key != "evidence_hash"}):
                continue
            sources = []
            for source_receipt in payload.get("source_receipts") or []:
                source_step = completed.get(source_receipt.get("source_step_id"))
                result = (source_step.result_data or {}).get("tool_result") if source_step else None
                if (source_step is None or source_step.tool_names != [source_receipt.get("operation_id")]
                        or not isinstance(result, dict)
                        or source_receipt.get("source_result_hash") != source_projection_hash(result)):
                    raise ValueError("analysis_source_receipt_not_bound")
                sources.append({**{key: source_receipt[key] for key in ("source_id", "source_step_id", "operation_id")},
                                "result": result})
            calculations, comparisons = [], []
            for raw in payload.get("verified_calculations") or []:
                calculations.append({"calculation_id": raw["calculation_id"], "operator": raw["operator"],
                                     "precision": raw["precision"], "result_unit": raw.get("result_unit", "native"),
                                     "operands": [{"source_id": ref["source_id"], "path": ref["path"]} for ref in raw["operand_receipts"]]})
            for raw in payload.get("verified_comparisons") or []:
                references = [{"source_id": ref["source_id"], "path": ref["path"]} for ref in raw["operand_receipts"]]
                comparisons.append({"comparison_id": raw["comparison_id"], "operator": raw["operator"],
                                    "left": references[0], "right": references[1]})
            recomputed = calculate_observations(sources=sources, calculations=calculations, comparisons=comparisons)
            if not recomputed.success or recomputed.data["evidence_hash"] != payload.get("evidence_hash"):
                raise ValueError("analysis_measure_or_source_contract_drift")
            verified = []
            for raw in [*list(payload.get("verified_calculations") or []), *list(payload.get("verified_comparisons") or [])]:
                if raw.get("verified") is not True or raw.get("evidence_hash") != source_projection_hash({key: value for key, value in raw.items() if key != "evidence_hash"}):
                    raise ValueError("analysis_receipt_corrupt")
                operands = []
                for receipt in raw.get("operand_receipts") or []:
                    source = completed.get(receipt.get("source_step_id"))
                    result = (source.result_data or {}).get("tool_result") if source else None
                    if (source is None or source.tool_names != [receipt.get("operation_id")]
                            or not isinstance(result, dict)
                            or receipt.get("source_result_hash") != source_projection_hash(result)):
                        raise ValueError("analysis_source_receipt_not_bound")
                    value = source_path_value(result, receipt.get("path", ""))
                    if value != receipt.get("value"):
                        raise ValueError("analysis_operand_receipt_drift")
                    operands.append({"value": value, "label": f"{receipt['source_step_id']}:{receipt['path']}",
                                     "unit": receipt["unit"], "source_step_id": receipt["source_step_id"],
                                     "operation_id": receipt["operation_id"], "path": receipt["path"]})
                is_comparison = "comparison_id" in raw
                scaling = {}
                if raw.get("result_unit") == "percentage":
                    if raw["operator"] not in {"divide", "percentage"} or len({row["unit"] for row in operands}) != 1:
                        raise ValueError("analysis_invalid_percentage_conversion")
                    if raw["operator"] == "divide":
                        scaling = {"operand_scales": [1] * len(operands), "result_scale": "0.01"}
                checked = (evaluate_verified_comparison(operator=raw["operator"], left=operands[0]["value"], right=operands[1]["value"])
                           if is_comparison else evaluate_verified_calculation(operator=raw["operator"], operands=[row["value"] for row in operands], precision=raw["precision"], **scaling))
                if not checked.success or checked.data["evidence_hash"] != raw.get("arithmetic_evidence_hash"):
                    raise ValueError("analysis_arithmetic_receipt_drift")
                expected = "holds" if is_comparison else "result"
                if raw.get(expected) != checked.data[expected]:
                    raise ValueError("analysis_result_receipt_drift")
                row = {**raw, "operands": operands, "display_expression": raw["expression"],
                       "result": raw[expected], "source_bound": True,
                       "result_label": raw.get("calculation_id", raw.get("comparison_id"))}
                if is_comparison:
                    row.update({"comparison_verified": True, "comparison_expression": raw["expression"],
                                "comparison_label": "doğru" if raw["holds"] else "yanlış",
                                "comparison_difference": raw["difference"],
                                "comparison_absolute_difference": raw["absolute_difference"]})
                verified.append(row)
            if verified:
                all_verified.extend(verified)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            # Never project a partially verified analysis receipt.
            continue
    return all_verified
