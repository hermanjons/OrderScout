from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from AI.constants.paths import AI_PACKAGE_ROOT
from AI.processors import operation_runtime
from Feedback.processors.pipeline import Result

DEFAULT_STAGING_EVIDENCE_DIR = AI_PACKAGE_ROOT / "docs" / "live_llm_transcripts" / "staging-marketplace"
STAGING_CAMPAIGN_ACTION_SPECS = (
    ("orders.change_order_cargo_provider", "single-cargo"),
    ("orders.change_orders_cargo_provider_bulk", "bulk-cargo"),
    ("orders.approve_return_claim", "return-approval"),
)


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _truthy_env(name: str) -> bool:
    return _compact_text(os.environ.get(name)).casefold() in {"1", "true", "yes", "on"}


def _read_action_payload(*, action_json: str = "", action_file: str = "") -> dict[str, Any]:
    if action_json and action_file:
        raise ValueError("--action-json ve --action-file ayni anda kullanilamaz.")
    if action_file:
        raw = Path(action_file).read_text(encoding="utf-8")
    elif action_json:
        raw = action_json
    else:
        raw = sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Action payload JSON object olmali.")
    return payload


def _read_external_proof_payload(*, proof_json: str = "", proof_file: str = "") -> dict[str, Any]:
    if proof_json and proof_file:
        raise ValueError("--external-proof-json ve --external-proof-file ayni anda kullanilamaz.")
    if proof_file:
        raw = Path(proof_file).read_text(encoding="utf-8")
    elif proof_json:
        raw = proof_json
    else:
        raw = sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("External proof JSON object olmali.")
    return payload


def _result_payload(result: Any) -> dict[str, Any]:
    data = result.data if isinstance(getattr(result, "data", None), dict) else {"value": getattr(result, "data", None)}
    return {
        "success": bool(getattr(result, "success", False)),
        "message": str(getattr(result, "message", "")),
        "data": data,
    }


def _default_manifest_path(evidence_path: str) -> str:
    evidence_text = _compact_text(evidence_path)
    if not evidence_text:
        return ""
    return str(Path(evidence_text).with_suffix(".manifest.json"))


def _default_staging_paths(args: argparse.Namespace) -> dict[str, str]:
    key = _compact_text(args.idempotency_key) or "<IDEMPOTENCY_KEY>"
    evidence_path = _compact_text(args.evidence_path) or str(DEFAULT_STAGING_EVIDENCE_DIR / f"{key}.json")
    audit_path = _compact_text(args.audit_path) or str(DEFAULT_STAGING_EVIDENCE_DIR / f"{key}.audit.jsonl")
    proof_path = _compact_text(args.proof_template_path) or str(Path(evidence_path).with_suffix(".external-proof.json"))
    manifest_path = _compact_text(args.manifest_path) or _default_manifest_path(evidence_path)
    action_path = _compact_text(args.action_file) or str(DEFAULT_STAGING_EVIDENCE_DIR / "prepared-action.json")
    return {
        "action_file": action_path,
        "audit_path": audit_path,
        "evidence_path": evidence_path,
        "external_proof_path": proof_path,
        "manifest_path": manifest_path,
    }


def _base_cli_args(mode: str) -> list[str]:
    return ["-m", "AI.processors.staging_marketplace_evidence_cli", "--mode", mode]


def _append_if(args: list[str], flag: str, value: str) -> None:
    if _compact_text(value):
        args.extend([flag, _compact_text(value)])


def _planned_command(
    command_id: str,
    *,
    mode: str,
    summary: str,
    paths: dict[str, str],
    args: argparse.Namespace,
    requires_env: bool = False,
    include_action: bool = True,
    include_staging_reason: bool = True,
    include_audit: bool = False,
    include_evidence: bool = False,
    include_external_proof: bool = False,
    include_manifest: bool = False,
    include_proof_template: bool = False,
    closure_cli: bool = False,
) -> dict[str, Any]:
    cli_args = (
        ["-m", "AI.processors.orders_goal_closure_cli"]
        if closure_cli
        else _base_cli_args(mode)
    )
    if closure_cli:
        cli_args.extend(["--checklist-path", str(AI_PACKAGE_ROOT / "docs" / "orders_agentic_goal_closure_checklist.json")])
    if include_action:
        cli_args.extend(["--action-file", paths["action_file"]])
    if include_external_proof:
        cli_args.extend(["--external-proof-file", paths["external_proof_path"]])
    if not closure_cli:
        _append_if(cli_args, "--idempotency-key", _compact_text(args.idempotency_key) or "<IDEMPOTENCY_KEY>")
    _append_if(cli_args, "--staging-account-id", _compact_text(args.staging_account_id) or "<STAGING_SELLER_ID>")
    if include_staging_reason and not closure_cli:
        _append_if(cli_args, "--staging-reason", _compact_text(args.staging_reason) or "<CONTROLLED_STAGING_REASON>")
    if include_audit:
        cli_args.extend(["--audit-path", paths["audit_path"]])
    if include_evidence:
        cli_args.extend(["--evidence-path", paths["evidence_path"]])
    if include_proof_template:
        cli_args.extend(["--proof-template-path", paths["external_proof_path"]])
    if include_manifest:
        cli_args.extend(["--manifest-path", paths["manifest_path"]])
    if closure_cli:
        cli_args.extend(
            [
                "--staging-evidence-dir",
                str(Path(paths["evidence_path"]).parent),
                "--apply-verified-staging-evidence",
                "--require-complete",
                "--report-path",
                str(Path(paths["evidence_path"]).parent / "orders-staging-campaign.closure.json"),
            ]
        )
    return {
        "id": command_id,
        "summary": summary,
        "requires_env": requires_env,
        "env": {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"} if requires_env else {},
        "python_args": cli_args,
    }


def _plan_result(args: argparse.Namespace) -> Result:
    paths = _default_staging_paths(args)
    doctor_args = argparse.Namespace(**vars(args))
    doctor_args.audit_path = paths["audit_path"]
    doctor_args.evidence_path = paths["evidence_path"]
    doctor_args.proof_template_path = paths["external_proof_path"]
    doctor_args.manifest_path = paths["manifest_path"]
    if not _compact_text(doctor_args.action_file) and not _compact_text(doctor_args.action_json):
        doctor_args.action_file = paths["action_file"]
    doctor = _doctor_result(doctor_args)
    commands = [
        _planned_command(
            "doctor",
            mode="doctor",
            summary="Readiness check only; no API call and no DB write.",
            paths=paths,
            args=args,
            requires_env=True,
            include_audit=True,
            include_evidence=True,
            include_proof_template=True,
            include_manifest=True,
        ),
        _planned_command(
            "preflight",
            mode="preflight",
            summary="Guarded preflight; no API call and no DB write.",
            paths=paths,
            args=args,
            requires_env=True,
        ),
        _planned_command(
            "execute",
            mode="execute",
            summary="Controlled staging execute; writes only when all guards pass.",
            paths=paths,
            args=args,
            requires_env=True,
            include_audit=True,
            include_evidence=True,
        ),
        _planned_command(
            "proof_template",
            mode="proof-template",
            summary="Generate identifier-free external proof template from evidence.",
            paths=paths,
            args=args,
            include_action=False,
            include_staging_reason=False,
            include_evidence=True,
            include_proof_template=True,
        ),
        _planned_command(
            "attach_external_proof",
            mode="attach-external-proof",
            summary="Attach operator-filled external marketplace proof after validation.",
            paths=paths,
            args=args,
            include_action=False,
            include_staging_reason=False,
            include_evidence=True,
            include_external_proof=True,
        ),
        _planned_command(
            "validate",
            mode="validate",
            summary="Validate evidence, audit, redaction, and external proof.",
            paths=paths,
            args=args,
            include_action=False,
            include_staging_reason=False,
            include_evidence=True,
        ),
        _planned_command(
            "manifest",
            mode="manifest",
            summary="Write SHA-256 manifest for evidence, audit, and external proof.",
            paths=paths,
            args=args,
            include_action=False,
            include_staging_reason=False,
            include_evidence=True,
            include_external_proof=True,
            include_manifest=True,
        ),
        _planned_command(
            "verify_manifest",
            mode="verify-manifest",
            summary="Verify evidence manifest before closure.",
            paths=paths,
            args=args,
            include_action=False,
            include_staging_reason=False,
            include_evidence=True,
            include_manifest=True,
        ),
        _planned_command(
            "apply_closure",
            mode="",
            summary="Apply the complete three-action staging evidence campaign to Orders closure checklist.",
            paths=paths,
            args=args,
            include_action=False,
            include_staging_reason=False,
            closure_cli=True,
        ),
    ]
    data = {
        "mode": "plan",
        "api_call_performed": False,
        "db_write_performed": False,
        "paths": paths,
        "doctor": _result_payload(doctor),
        "ready_for_execute": bool((doctor.data or {}).get("ready_for_execute")) if isinstance(doctor.data, dict) else False,
        "commands": commands,
        "safety_notes": [
            "Run execute only in a controlled staging shell.",
            f"Set {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV}=1 only for doctor/preflight/execute.",
            "Do not put customer/order/claim/tracking identifiers into external proof.",
            "Do not overwrite existing evidence, proof, or manifest unless intentionally regenerating after validation failure.",
            "Closure requires independent evidence packages for single cargo, bulk cargo, and return approval on one staging account.",
        ],
    }
    return Result.ok("Staging marketplace evidence plan hazirlandi.", close_dialog=False, data=data)


def _campaign_plan_result(args: argparse.Namespace) -> Result:
    campaign_id = _compact_text(args.campaign_id) or "<CAMPAIGN_ID>"
    campaign_dir = Path(_compact_text(args.campaign_dir) or DEFAULT_STAGING_EVIDENCE_DIR)
    account_id = _compact_text(args.staging_account_id) or "<STAGING_SELLER_ID>"
    staging_reason = _compact_text(args.staging_reason) or "<CONTROLLED_STAGING_REASON>"
    problems: list[str] = []
    if operation_runtime.looks_like_staging_marketplace_placeholder(campaign_id):
        problems.append("campaign_id")
    elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}", campaign_id):
        problems.append("campaign_id_format")
    if operation_runtime.looks_like_staging_marketplace_placeholder(account_id):
        problems.append("staging_account_id")
    if operation_runtime.looks_like_staging_marketplace_placeholder(staging_reason):
        problems.append("staging_reason")

    action_rows: list[dict[str, Any]] = []
    all_doctors_ready = True
    for expected_action_type, slug in STAGING_CAMPAIGN_ACTION_SPECS:
        idempotency_key = f"{campaign_id}-{slug}"
        action_path = campaign_dir / f"{slug}.prepared-action.json"
        evidence_path = campaign_dir / f"{idempotency_key}.json"
        child_args = argparse.Namespace(**vars(args))
        child_args.action_json = ""
        child_args.action_file = str(action_path)
        child_args.idempotency_key = idempotency_key
        child_args.staging_reason = f"{staging_reason} ({expected_action_type})"
        child_args.audit_path = str(evidence_path.with_suffix(".audit.jsonl"))
        child_args.evidence_path = str(evidence_path)
        child_args.proof_template_path = str(evidence_path.with_suffix(".external-proof.json"))
        child_args.manifest_path = str(evidence_path.with_suffix(".manifest.json"))
        child_plan = _plan_result(child_args)
        child_data = dict(child_plan.data or {}) if isinstance(child_plan.data, dict) else {}
        doctor = dict(child_data.get("doctor") or {})
        doctor_data = dict(doctor.get("data") or {}) if isinstance(doctor.get("data"), dict) else {}
        doctor_ready = bool(doctor_data.get("ready_for_execute"))
        all_doctors_ready = all_doctors_ready and doctor_ready

        action_type = _compact_text(doctor_data.get("action_type"))
        action_exists = action_path.exists() and action_path.is_file()
        action_type_matches = bool(action_exists and action_type == expected_action_type)
        if not action_exists:
            problems.append(f"missing_action_file:{slug}")
        elif not action_type_matches:
            problems.append(f"action_type_mismatch:{slug}")

        action_rows.append(
            {
                "action_type": expected_action_type,
                "slug": slug,
                "idempotency_key": idempotency_key,
                "action_file": str(action_path),
                "action_file_exists": action_exists,
                "loaded_action_type": action_type,
                "action_type_matches": action_type_matches,
                "paths": child_data.get("paths"),
                "doctor": doctor,
                "ready_for_execute": bool(doctor_ready and action_type_matches),
                "commands": [
                    row
                    for row in list(child_data.get("commands") or [])
                    if isinstance(row, dict) and row.get("id") != "apply_closure"
                ],
            }
        )

    unique_problems = sorted(set(problems))
    closure_report_path = campaign_dir / f"{campaign_id}.closure.json"
    closure_command = {
        "id": "apply_campaign_closure",
        "summary": "Apply closure only after all three action evidence packages and manifests validate.",
        "requires_env": False,
        "env": {},
        "python_args": [
            "-m",
            "AI.processors.orders_goal_closure_cli",
            "--checklist-path",
            str(AI_PACKAGE_ROOT / "docs" / "orders_agentic_goal_closure_checklist.json"),
            "--staging-evidence-dir",
            str(campaign_dir),
            "--staging-account-id",
            account_id,
            "--apply-verified-staging-evidence",
            "--require-complete",
            "--report-path",
            str(closure_report_path),
        ],
    }
    data = {
        "mode": "campaign-plan",
        "artifact_type": "orders_staging_marketplace_campaign_plan",
        "api_call_performed": False,
        "db_write_performed": False,
        "campaign_id": campaign_id,
        "campaign_dir": str(campaign_dir),
        "staging_account_id": account_id,
        "required_action_types": [action_type for action_type, _slug in STAGING_CAMPAIGN_ACTION_SPECS],
        "actions": action_rows,
        "problems": unique_problems,
        "campaign_ready_for_execute": bool(not unique_problems and all_doctors_ready),
        "closure_command": closure_command,
        "safety_notes": [
            "Generate every prepared action through the source agent/domain prepare flow; do not hand-edit target ids.",
            "Each action uses a distinct idempotency key and evidence package.",
            "Execute only in a controlled staging shell after every action doctor is ready.",
            "Apply campaign closure only after all three external proofs and manifests validate.",
        ],
    }
    return Result.ok("Staging marketplace uc aksiyonlu kampanya plani hazirlandi.", close_dialog=False, data=data)


def _persist_plan_result(result: Result, args: argparse.Namespace) -> Result:
    plan_path = _compact_text(getattr(args, "plan_path", ""))
    if not plan_path:
        return result
    target = Path(plan_path)
    if target.exists() and not bool(getattr(args, "overwrite_plan", False)):
        data = dict(result.data or {}) if isinstance(result.data, dict) else {"value": result.data}
        data.update(
            {
                "mode": "plan",
                "api_call_performed": False,
                "db_write_performed": False,
                "plan_path": str(target),
                "problems": sorted(set(list(data.get("problems") or []) + ["plan_path_exists"])),
            }
        )
        return Result.fail(
            "Staging marketplace plan dosyasi zaten var; overwrite edilmeden yeni path secin veya acik overwrite isteyin.",
            close_dialog=False,
            data=data,
        )

    data = dict(result.data or {}) if isinstance(result.data, dict) else {"value": result.data}
    data["plan_path"] = str(target)
    result.data = data
    payload = {
        "artifact_type": (
            "orders_staging_marketplace_campaign_plan"
            if _compact_text(data.get("mode")) == "campaign-plan"
            else "orders_staging_marketplace_plan"
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result": _result_payload(result),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return result


def _doctor_result(args: argparse.Namespace) -> Result:
    problems: list[str] = []
    next_actions: list[dict[str, str]] = []
    action: dict[str, Any] | None = None
    env_enabled = _truthy_env(operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV)
    manifest_path = _compact_text(args.manifest_path) or _default_manifest_path(args.evidence_path)
    data: dict[str, Any] = {
        "mode": "doctor",
        "api_call_performed": False,
        "db_write_performed": False,
        "env": operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV,
        "env_enabled": env_enabled,
        "action_provided": bool(_compact_text(args.action_json) or _compact_text(args.action_file)),
        "idempotency_key_provided": bool(_compact_text(args.idempotency_key)),
        "staging_reason_provided": bool(_compact_text(args.staging_reason)),
        "staging_account_id_provided": bool(_compact_text(args.staging_account_id)),
        "idempotency_key_placeholder": operation_runtime.looks_like_staging_marketplace_placeholder(args.idempotency_key),
        "staging_reason_placeholder": operation_runtime.looks_like_staging_marketplace_placeholder(args.staging_reason),
        "staging_account_id_placeholder": operation_runtime.looks_like_staging_marketplace_placeholder(args.staging_account_id),
        "audit_path": _compact_text(args.audit_path),
        "evidence_path": _compact_text(args.evidence_path),
        "manifest_path": manifest_path,
        "manifest_path_defaulted": bool(manifest_path and not _compact_text(args.manifest_path)),
        "proof_template_path": _compact_text(args.proof_template_path),
    }

    if not data["action_provided"]:
        problems.append("action")
        next_actions.append({"id": "provide_action", "summary": "Provide the prepared approval action with --action-file or --action-json."})
    else:
        try:
            action = _read_action_payload(action_json=args.action_json, action_file=args.action_file)
            data["action_loaded"] = True
            data["action_type"] = _compact_text(action.get("action_type"))
        except Exception as exc:
            problems.append("action")
            data["action_loaded"] = False
            data["action_error"] = f"{type(exc).__name__}: {exc}"
            next_actions.append({"id": "fix_action_json", "summary": "Fix the prepared action JSON before running staging preflight or execute."})

    if not env_enabled:
        problems.append("env")
        next_actions.append(
            {
                "id": "enable_env",
                "summary": f"Run the controlled staging shell with {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV}=1 before execute.",
            }
        )
    if not data["idempotency_key_provided"]:
        problems.append("idempotency_key")
        next_actions.append({"id": "provide_idempotency_key", "summary": "Provide the explicit idempotency key for this staging evidence run."})
    elif data["idempotency_key_placeholder"]:
        problems.append("idempotency_key_placeholder")
        next_actions.append({"id": "replace_idempotency_key_placeholder", "summary": "Replace the idempotency key placeholder with the exact key for this staging run."})
    if not data["staging_reason_provided"]:
        problems.append("staging_reason")
        next_actions.append({"id": "provide_staging_reason", "summary": "Provide a human-readable staging reason of at least 12 characters."})
    elif data["staging_reason_placeholder"]:
        problems.append("staging_reason_placeholder")
        next_actions.append({"id": "replace_staging_reason_placeholder", "summary": "Replace the staging reason placeholder with a real controlled-run reason."})
    if not data["staging_account_id_provided"]:
        problems.append("staging_account_id")
        next_actions.append({"id": "provide_staging_account_id", "summary": "Provide the controlled staging/sandbox seller account id."})
    elif data["staging_account_id_placeholder"]:
        problems.append("staging_account_id_placeholder")
        next_actions.append({"id": "replace_staging_account_id_placeholder", "summary": "Replace the staging account placeholder with the controlled staging/sandbox seller account id."})
    if data["idempotency_key_provided"] and data["audit_path"]:
        previous = operation_runtime._previous_success(args.idempotency_key, audit_path=args.audit_path)
        data["idempotency_already_executed"] = previous is not None
        if previous is not None:
            problems.append("idempotency_already_executed")
            data["previous_audit"] = operation_runtime._without_secretish_keys(previous)
            next_actions.append(
                {
                    "id": "validate_existing_evidence",
                    "summary": "This idempotency key already has a successful audit entry; validate/attach existing evidence or choose a new idempotency key.",
                }
            )
    if data["evidence_path"]:
        evidence_path = Path(str(data["evidence_path"]))
        data["evidence_path_exists"] = evidence_path.exists()
        if evidence_path.exists():
            problems.append("evidence_path_exists")
            next_actions.append(
                {
                    "id": "choose_new_evidence_path",
                    "summary": "The evidence path already exists; validate/attach that artifact or choose a new path to avoid overwriting evidence.",
                }
            )
    if data["manifest_path"]:
        manifest_path = Path(str(data["manifest_path"]))
        data["manifest_path_exists"] = manifest_path.exists()
        if manifest_path.exists():
            problems.append("manifest_path_exists")
            next_actions.append(
                {
                    "id": "verify_existing_manifest",
                    "summary": "The manifest path already exists; run verify-manifest or choose a new manifest path to avoid replacing evidence metadata.",
                }
            )
    if data["proof_template_path"]:
        proof_template_path = Path(str(data["proof_template_path"]))
        data["proof_template_path_exists"] = proof_template_path.exists()
        if proof_template_path.exists():
            problems.append("proof_template_path_exists")
            next_actions.append(
                {
                    "id": "choose_new_proof_template_path",
                    "summary": "The proof template path already exists; choose a new path or use proof-template with explicit overwrite only when intentionally regenerating.",
                }
            )

    preflight_inputs_ready = (
        action is not None
        and data["idempotency_key_provided"]
        and data["staging_reason_provided"]
        and data["staging_account_id_provided"]
        and not data["idempotency_key_placeholder"]
        and not data["staging_reason_placeholder"]
        and not data["staging_account_id_placeholder"]
    )
    if action is not None and not preflight_inputs_ready:
        data["preflight_skipped"] = "staging_inputs_incomplete_or_placeholder"
    if preflight_inputs_ready:
        preflight = operation_runtime.preflight_staging_marketplace_operation(
            action,
            idempotency_key=args.idempotency_key,
            staging_reason=args.staging_reason,
            marketplace=args.marketplace,
            staging_account_id=args.staging_account_id,
            require_env=False,
        )
        data["preflight"] = _result_payload(preflight)
        if preflight.success:
            preflight_data = dict(preflight.data or {}) if isinstance(preflight.data, dict) else {}
            proof = dict(preflight_data.get("staging_proof") or {}) if isinstance(preflight_data.get("staging_proof"), dict) else {}
            data["target_account_verified"] = True
            data["target_account_ids"] = list(proof.get("target_account_ids") or [])
            data["verified_references_count"] = len(list(proof.get("verified_references") or []))
        else:
            problems.append("preflight")
            data["target_account_verified"] = False
            next_actions.append({"id": "fix_preflight", "summary": preflight.message})

    unique_problems = sorted(set(problems))
    data["problems"] = unique_problems
    data["next_actions"] = next_actions
    data["ready_for_execute"] = not unique_problems
    if unique_problems:
        return Result.fail("Staging marketplace doctor execute icin hazir degil.", close_dialog=False, data=data)
    return Result.ok("Staging marketplace doctor execute icin hazir.", close_dialog=False, data=data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Orders staging marketplace preflight/evidence execution for a prepared approval action."
    )
    parser.add_argument(
        "--mode",
        choices=(
            "plan",
            "campaign-plan",
            "doctor",
            "preflight",
            "execute",
            "proof-template",
            "attach-external-proof",
            "validate",
            "manifest",
            "verify-manifest",
        ),
        default="preflight",
    )
    parser.add_argument("--action-json", default="", help="Prepared approval action JSON. Use --action-file for larger payloads.")
    parser.add_argument("--action-file", default="", help="Path to a prepared approval action JSON file.")
    parser.add_argument("--external-proof-json", default="", help="External staging marketplace verification JSON.")
    parser.add_argument("--external-proof-file", default="", help="Path to external staging marketplace verification JSON.")
    parser.add_argument("--proof-template-path", default="", help="Optional output path for an identifier-free external proof template.")
    parser.add_argument("--plan-path", default="", help="Optional output path for the no-write staging command plan artifact.")
    parser.add_argument("--campaign-id", default="", help="Unique campaign prefix used to derive the three action idempotency keys.")
    parser.add_argument("--campaign-dir", default="", help="Directory containing the three prepared-action files and generated evidence packages.")
    parser.add_argument(
        "--overwrite-plan",
        action="store_true",
        help="Allow --mode plan to replace an existing plan artifact. Prefer a new path unless intentionally regenerating.",
    )
    parser.add_argument(
        "--overwrite-proof-template",
        action="store_true",
        help="Allow --mode proof-template to replace an existing proof template file. Prefer a new path unless intentionally regenerating.",
    )
    parser.add_argument(
        "--overwrite-external-proof",
        action="store_true",
        help="Allow --mode attach-external-proof to replace an existing external_verification. Prefer validate/manifest unless intentionally fixing proof.",
    )
    parser.add_argument("--approved-by", default="staging-cli")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--staging-reason", default="")
    parser.add_argument("--staging-account-id", default="")
    parser.add_argument("--marketplace", default="trendyol")
    parser.add_argument("--audit-path", default="")
    parser.add_argument("--evidence-path", default="")
    parser.add_argument("--manifest-path", default="", help="Optional output path for a validated evidence hash manifest.")
    parser.add_argument(
        "--overwrite-manifest",
        action="store_true",
        help="Allow --mode manifest to replace an existing manifest. Prefer verify-manifest unless intentionally regenerating after fixing evidence.",
    )
    parser.add_argument(
        "--allow-preflight-without-env",
        action="store_true",
        help="Only for dry preflight diagnostics; execute mode always requires the staging mutation env gate.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.mode == "plan":
            result = _plan_result(args)
            result = _persist_plan_result(result, args)
        elif args.mode == "campaign-plan":
            result = _campaign_plan_result(args)
            result = _persist_plan_result(result, args)
        elif args.mode == "doctor":
            result = _doctor_result(args)
        elif args.mode == "manifest":
            if not args.evidence_path:
                raise ValueError("--mode manifest icin --evidence-path gerekir.")
            result = operation_runtime.staging_marketplace_evidence_manifest(
                args.evidence_path,
                manifest_path=args.manifest_path or None,
                external_proof_path=args.external_proof_file or None,
                idempotency_key=args.idempotency_key or None,
                staging_account_id=args.staging_account_id or None,
                overwrite=bool(args.overwrite_manifest),
            )
        elif args.mode == "verify-manifest":
            if not args.manifest_path:
                raise ValueError("--mode verify-manifest icin --manifest-path gerekir.")
            result = operation_runtime.verify_staging_marketplace_evidence_manifest(
                args.manifest_path,
                evidence_path=args.evidence_path or None,
                idempotency_key=args.idempotency_key or None,
                staging_account_id=args.staging_account_id or None,
            )
        elif args.mode == "validate":
            if not args.evidence_path:
                raise ValueError("--mode validate icin --evidence-path gerekir.")
            result = operation_runtime.verify_staging_marketplace_evidence_artifact(
                args.evidence_path,
                idempotency_key=args.idempotency_key or None,
                staging_account_id=args.staging_account_id or None,
            )
        elif args.mode == "attach-external-proof":
            if not args.evidence_path:
                raise ValueError("--mode attach-external-proof icin --evidence-path gerekir.")
            external_proof = _read_external_proof_payload(
                proof_json=args.external_proof_json,
                proof_file=args.external_proof_file,
            )
            result = operation_runtime.attach_staging_marketplace_external_proof(
                args.evidence_path,
                external_proof,
                idempotency_key=args.idempotency_key or None,
                staging_account_id=args.staging_account_id or None,
                overwrite=bool(args.overwrite_external_proof),
            )
        elif args.mode == "proof-template":
            if not args.evidence_path:
                raise ValueError("--mode proof-template icin --evidence-path gerekir.")
            result = operation_runtime.staging_marketplace_external_proof_template(
                args.evidence_path,
                idempotency_key=args.idempotency_key or None,
                staging_account_id=args.staging_account_id or None,
            )
            if result.success and args.proof_template_path:
                target = Path(args.proof_template_path)
                if target.exists() and not args.overwrite_proof_template:
                    result = Result.fail(
                        "External proof template dosyasi zaten var; overwrite edilmeden yeni path secin veya acik overwrite isteyin.",
                        close_dialog=False,
                        data={
                            "verified": False,
                            "proof_template_path": str(target),
                            "problems": ["proof_template_path_exists"],
                        },
                    )
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    template = (result.data or {}).get("template") if isinstance(result.data, dict) else None
                    target.write_text(json.dumps(template, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
                    data = dict(result.data or {})
                    data["proof_template_path"] = str(target)
                    result.data = data
        else:
            if not args.idempotency_key:
                raise ValueError("--idempotency-key gerekir.")
            if not args.staging_reason:
                raise ValueError("--staging-reason gerekir.")
            if not args.staging_account_id:
                raise ValueError("--staging-account-id gerekir.")
            action = _read_action_payload(action_json=args.action_json, action_file=args.action_file)
        if args.mode == "preflight":
            result = operation_runtime.preflight_staging_marketplace_operation(
                action,
                idempotency_key=args.idempotency_key,
                staging_reason=args.staging_reason,
                marketplace=args.marketplace,
                staging_account_id=args.staging_account_id,
                require_env=not bool(args.allow_preflight_without_env),
            )
        elif args.mode == "execute":
            result = operation_runtime.execute_staging_marketplace_evidence_run(
                action,
                approved_by=args.approved_by,
                idempotency_key=args.idempotency_key,
                audit_path=args.audit_path or None,
                evidence_path=args.evidence_path or None,
                staging_reason=args.staging_reason,
                marketplace=args.marketplace,
                staging_account_id=args.staging_account_id,
            )
        sys.stdout.write(json.dumps(_result_payload(result), ensure_ascii=False, indent=2, sort_keys=True, default=str))
        sys.stdout.write("\n")
        return 0 if result.success else 2
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
