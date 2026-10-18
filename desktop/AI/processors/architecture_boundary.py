from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any


DOMAIN_MODEL_PREFIXES = (
    "Account.models",
    "Finance.models",
    "Labels.models",
    "Listing.models",
    "Logistics.models",
    "Marketplaces.models",
    "Orders.models",
    "Stock.models",
    "Testing.models",
    "Update.models",
)

PRODUCT_PACKAGE_NAMES = (
    "Account",
    "AI",
    "Core",
    "Feedback",
    "Finance",
    "Labels",
    "Support",
    "Listing",
    "Logistics",
    "Main_interface",
    "Marketplaces",
    "Orders",
    "Stock",
    "Testing",
    "Update",
)

CANONICAL_SHARED_SYMBOL_OWNERS = {
    "RecordWorkspaceBehaviorAdapter": "Core/views/record_workspace.py",
    "RecordWorkspaceCardRecord": "Core/views/record_workspace.py",
    "RecordWorkspaceScaffold": "Core/views/record_workspace.py",
    "OperationMetadata": "Core/processors/operation_contracts.py",
    "OperationResultEnvelope": "Core/processors/operation_contracts.py",
    "RecordRef": "Core/processors/record_refs.py",
    "coalesce_credential_bundle_reference": "Core/processors/credential_store.py",
    "is_credential_reference": "Core/processors/credential_store.py",
    "resolve_credential_bundle": "Core/processors/credential_store.py",
    "store_credential_bundle": "Core/processors/credential_store.py",
    "TZ_GMT3": "Core/constants/time_constants.py",
    "TZ_ISTANBUL": "Core/constants/time_constants.py",
}

PROVIDER_API_ORIGIN_MARKERS = (
    "api.anthropic.com",
    "api.groq.com",
    "api.mistral.ai",
    "api.openai.com",
    "api.together.xyz",
    "generativelanguage.googleapis.com",
    "openrouter.ai/api",
)

MARKETPLACE_API_ORIGIN_MARKERS = (
    "apigw.trendyol.com",
    "stageapigw.trendyol.com",
)


def _relative_key(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _product_python_files(project_root: str | Path) -> list[Path]:
    root = Path(project_root).resolve()
    paths: list[Path] = []
    for package_name in PRODUCT_PACKAGE_NAMES:
        package_root = root / package_name
        if not package_root.exists():
            continue
        paths.extend(
            path
            for path in package_root.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    return sorted(set(paths), key=lambda path: _relative_key(path, root).casefold())


def _parse_python(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _assigned_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets = list(node.targets) if isinstance(node, ast.Assign) else [node.target]
    out: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            out.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            out.extend(value.id for value in target.elts if isinstance(value, ast.Name))
    return out


def audit_shared_primitive_ownership(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    definitions: dict[str, list[dict[str, Any]]] = {
        name: [] for name in CANONICAL_SHARED_SYMBOL_OWNERS
    }
    parse_problems: list[dict[str, Any]] = []
    paths = _product_python_files(root)
    for path in paths:
        relative = _relative_key(path, root)
        try:
            tree = _parse_python(path)
        except Exception as exc:
            parse_problems.append(
                {
                    "path": relative,
                    "line": 0,
                    "symbol": "",
                    "reason": f"parse_error:{type(exc).__name__}",
                }
            )
            continue
        for node in tree.body:
            names: list[str] = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names = [node.name]
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                names = _assigned_names(node)
            for name in names:
                if name not in definitions:
                    continue
                definitions[name].append(
                    {"path": relative, "line": int(getattr(node, "lineno", 0) or 0)}
                )

    violations = list(parse_problems)
    for symbol, expected_path in CANONICAL_SHARED_SYMBOL_OWNERS.items():
        owners = definitions.get(symbol) or []
        if not owners:
            violations.append(
                {
                    "path": expected_path,
                    "line": 0,
                    "symbol": symbol,
                    "reason": "canonical_symbol_missing",
                }
            )
            continue
        for owner in owners:
            if owner["path"] != expected_path:
                violations.append(
                    {
                        **owner,
                        "symbol": symbol,
                        "reason": "shared_primitive_defined_outside_canonical_owner",
                        "expected_path": expected_path,
                    }
                )
        if not any(owner["path"] == expected_path for owner in owners):
            violations.append(
                {
                    "path": expected_path,
                    "line": 0,
                    "symbol": symbol,
                    "reason": "canonical_owner_does_not_define_symbol",
                }
            )
    return {
        "valid": not violations,
        "scanned_file_count": len(paths),
        "canonical_symbols": CANONICAL_SHARED_SYMBOL_OWNERS,
        "definitions": definitions,
        "violation_count": len(violations),
        "violations": violations,
    }


def _is_thin_delegate(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    if not body or len(body) > 3:
        return False
    non_imports = [row for row in body if not isinstance(row, (ast.Import, ast.ImportFrom))]
    if len(non_imports) != 1:
        return False
    terminal = non_imports[0]
    if isinstance(terminal, ast.Return):
        value = terminal.value
        return isinstance(value, (ast.Call, ast.Await))
    return isinstance(terminal, ast.Expr) and isinstance(terminal.value, (ast.Call, ast.Await))


def audit_duplicate_public_implementations(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    paths = _product_python_files(root)
    groups: dict[str, list[dict[str, Any]]] = {}
    parse_problems: list[dict[str, Any]] = []
    for path in paths:
        relative = _relative_key(path, root)
        try:
            tree = _parse_python(path)
        except Exception as exc:
            parse_problems.append(
                {
                    "path": relative,
                    "line": 0,
                    "symbol": "",
                    "reason": f"parse_error:{type(exc).__name__}",
                }
            )
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_") or _is_thin_delegate(node):
                continue
            line_span = int(getattr(node, "end_lineno", node.lineno) or node.lineno) - int(node.lineno) + 1
            if line_span < 5:
                continue
            body_hash = hashlib.sha256(
                ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False).encode("utf-8")
            ).hexdigest()
            groups.setdefault(body_hash, []).append(
                {
                    "path": relative,
                    "line": int(node.lineno),
                    "symbol": node.name,
                    "line_span": line_span,
                }
            )

    duplicates = [
        {"body_sha256": body_hash, "definitions": definitions}
        for body_hash, definitions in sorted(groups.items())
        if len({row["path"] for row in definitions}) > 1
    ]
    violations = list(parse_problems)
    for group in duplicates:
        for row in group["definitions"]:
            violations.append(
                {
                    **row,
                    "reason": "duplicate_public_implementation",
                    "body_sha256": group["body_sha256"],
                }
            )
    return {
        "valid": not violations,
        "scanned_file_count": len(paths),
        "duplicate_group_count": len(duplicates),
        "duplicate_groups": duplicates,
        "violation_count": len(violations),
        "violations": violations,
    }


def audit_endpoint_catalog_ownership(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    paths = _product_python_files(root)
    violations: list[dict[str, Any]] = []
    provider_owner = "AI/processors/cloud_runtime.py"
    for path in paths:
        relative = _relative_key(path, root)
        if relative == "AI/processors/architecture_boundary.py":
            continue
        try:
            tree = _parse_python(path)
        except Exception as exc:
            violations.append(
                {
                    "path": relative,
                    "line": 0,
                    "value": "",
                    "reason": f"parse_error:{type(exc).__name__}",
                }
            )
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            text = node.value.casefold()
            if any(marker.casefold() in text for marker in PROVIDER_API_ORIGIN_MARKERS):
                if relative != provider_owner:
                    violations.append(
                        {
                            "path": relative,
                            "line": int(getattr(node, "lineno", 0) or 0),
                            "value": node.value,
                            "reason": "provider_api_origin_outside_catalog_owner",
                            "expected_path": provider_owner,
                        }
                    )
            if any(marker.casefold() in text for marker in MARKETPLACE_API_ORIGIN_MARKERS):
                violations.append(
                    {
                        "path": relative,
                        "line": int(getattr(node, "lineno", 0) or 0),
                        "value": node.value,
                        "reason": "marketplace_api_origin_hard_coded_in_python",
                        "expected_owner": "Marketplaces/constants/files/*/platform_api_config.json",
                    }
                )
    return {
        "valid": not violations,
        "scanned_file_count": len(paths),
        "provider_catalog_owner": provider_owner,
        "marketplace_catalog_owner": "Marketplaces/constants/files/*/platform_api_config.json",
        "violation_count": len(violations),
        "violations": violations,
    }


def audit_ai_workspace_scaffold(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    required_tokens = {
        "AI/views/ai_manager_dialog.py": (
            "RecordWorkspaceBehaviorAdapter",
            "RecordWorkspaceScaffold",
            "compose_record_workspace_style",
        ),
        "AI/views/chat_tab.py": (
            "ResettableSplitter",
            "SplitPanelSidebar",
        ),
    }
    violations: list[dict[str, Any]] = []
    evidence: dict[str, dict[str, bool]] = {}
    for relative, tokens in required_tokens.items():
        path = root / relative
        text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        evidence[relative] = {token: token in text for token in tokens}
        for token in tokens:
            if token in text:
                continue
            violations.append(
                {
                    "path": relative,
                    "line": 0,
                    "symbol": token,
                    "reason": "required_core_workspace_primitive_missing",
                }
            )
    return {
        "valid": not violations,
        "required_tokens": required_tokens,
        "evidence": evidence,
        "violation_count": len(violations),
        "violations": violations,
    }


def audit_manual_ai_operation_parity() -> dict[str, Any]:
    import re

    from AI.processors.operation_runtime import operation_coverage_report

    report = operation_coverage_report()
    violations: list[dict[str, Any]] = []
    manual_total = int(report.get("manual_total") or 0)
    contract_total = int(report.get("operation_contract_total") or 0)
    valid_total = int(report.get("operation_contract_valid_total") or 0)
    invalid_total = int(report.get("operation_contract_invalid_total") or 0)
    if manual_total != contract_total or contract_total != valid_total or invalid_total:
        violations.append(
            {
                "path": "AI/processors/operation_runtime.py",
                "line": 0,
                "symbol": "operation_coverage_report",
                "reason": "manual_ai_operation_contract_parity",
                "manual_total": manual_total,
                "operation_contract_total": contract_total,
                "operation_contract_valid_total": valid_total,
                "operation_contract_invalid_total": invalid_total,
            }
        )
    safe_capability_ids = {
        str(row.get("capability_id") or "").strip()
        for key in ("generic_execute_safe", "generic_read_safe")
        for row in list(report.get(key) or [])
        if str(row.get("capability_id") or "").strip()
    }
    blocked_rows = [
        dict(row)
        for key in ("generic_execute_blocked", "generic_read_blocked")
        for row in list(report.get(key) or [])
        if isinstance(row, dict)
    ]
    blocked_contracts: list[dict[str, Any]] = []
    for row in blocked_rows:
        capability_id = str(row.get("capability_id") or "").strip()
        reasons = [str(value or "").strip() for value in list(row.get("blocked_reasons") or []) if str(value or "").strip()]
        replacements = {
            match
            for reason in reasons
            for match in re.findall(r"\buse\s+([a-z][a-z0-9_.]+)", reason, flags=re.IGNORECASE)
        }
        unresolved_replacements = sorted(replacements - safe_capability_ids)
        blocked_contracts.append(
            {
                "capability_id": capability_id,
                "blocked_reasons": reasons,
                "safe_replacements": sorted(replacements),
                "unresolved_replacements": unresolved_replacements,
            }
        )
        if not reasons or unresolved_replacements:
            violations.append(
                {
                    "path": "AI/processors/operation_runtime.py",
                    "line": 0,
                    "symbol": capability_id,
                    "reason": "blocked_manual_operation_without_safe_contract",
                    "blocked_reasons": reasons,
                    "unresolved_replacements": unresolved_replacements,
                }
            )

    domain_summary: dict[str, dict[str, Any]] = {}
    for domain, raw in dict(report.get("domains") or {}).items():
        row = dict(raw or {})
        blocked_write = list(row.get("generic_execute_blocked_ids") or [])
        blocked_read = list(row.get("generic_read_blocked_ids") or [])
        problem_ids = list(row.get("operation_contract_problem_ids") or [])
        domain_summary[str(domain)] = {
            "total": int(row.get("total") or 0),
            "read_total": int(row.get("read_total") or 0),
            "write_total": int(row.get("write_total") or 0),
            "generic_execute_blocked_ids": blocked_write,
            "generic_read_blocked_ids": blocked_read,
            "operation_contract_problem_ids": problem_ids,
        }
        if problem_ids:
            violations.append(
                {
                    "path": "AI/processors/operation_runtime.py",
                    "line": 0,
                    "symbol": str(domain),
                    "reason": "domain_operation_not_shared_by_manual_and_ai",
                    "generic_execute_blocked_ids": blocked_write,
                    "generic_read_blocked_ids": blocked_read,
                    "operation_contract_problem_ids": problem_ids,
                }
            )
    return {
        "valid": not violations,
        "manual_total": manual_total,
        "operation_contract_total": contract_total,
        "operation_contract_valid_total": valid_total,
        "operation_contract_invalid_total": invalid_total,
        "domains": domain_summary,
        "blocked_contracts": blocked_contracts,
        "violation_count": len(violations),
        "violations": violations,
    }


def audit_core_dry_architecture(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    ai_paths = [
        path
        for area in (root / "AI" / "processors", root / "AI" / "views")
        for path in area.rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    ai_model_boundary = audit_ai_domain_model_imports(ai_paths)
    ai_model_boundary["scanned_files"] = [
        _relative_key(Path(path), root)
        for path in list(ai_model_boundary.get("scanned_files") or [])
    ]
    for violation in list(ai_model_boundary.get("violations") or []):
        raw_path = Path(str(violation.get("path") or ""))
        if raw_path.is_absolute():
            try:
                violation["path"] = _relative_key(raw_path, root)
            except ValueError:
                violation["path"] = raw_path.name
    checks = {
        "ai_domain_model_boundary": ai_model_boundary,
        "shared_primitive_ownership": audit_shared_primitive_ownership(root),
        "duplicate_public_implementations": audit_duplicate_public_implementations(root),
        "endpoint_catalog_ownership": audit_endpoint_catalog_ownership(root),
        "ai_workspace_scaffold": audit_ai_workspace_scaffold(root),
        "manual_ai_operation_parity": audit_manual_ai_operation_parity(),
    }
    violations = [
        {"check": check_name, **violation}
        for check_name, result in checks.items()
        for violation in list(result.get("violations") or [])
    ]
    repository_files = [
        _relative_key(path, root)
        for path in _product_python_files(root)
        if path.name == "agentic_repository.py"
    ]
    return {
        "artifact_type": "orderscout_core_dry_architecture_audit",
        "schema_version": 1,
        "valid": not violations and all(bool(result.get("valid")) for result in checks.values()),
        "project_root": ".",
        "product_python_file_count": len(_product_python_files(root)),
        "agentic_repository_files": repository_files,
        "checks": checks,
        "violation_count": len(violations),
        "violations": violations,
    }


def audit_ai_domain_model_imports(paths: list[str | Path]) -> dict[str, Any]:
    """Find AI runtime code that bypasses domain functions and imports models."""
    violations: list[dict[str, Any]] = []
    scanned: list[str] = []
    for value in paths:
        path = Path(value)
        if not path.exists() or not path.is_file():
            violations.append({"path": str(path), "line": 0, "module": "", "reason": "missing_file"})
            continue
        scanned.append(str(path))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except Exception as exc:
            violations.append(
                {
                    "path": str(path),
                    "line": 0,
                    "module": "",
                    "reason": f"parse_error:{type(exc).__name__}",
                }
            )
            continue
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom):
                modules = [str(node.module or "")]
            elif isinstance(node, ast.Import):
                modules = [str(alias.name or "") for alias in node.names]
            for module in modules:
                if not any(module == prefix or module.startswith(prefix + ".") for prefix in DOMAIN_MODEL_PREFIXES):
                    continue
                violations.append(
                    {
                        "path": str(path),
                        "line": int(getattr(node, "lineno", 0) or 0),
                        "module": module,
                        "reason": "direct_domain_model_import",
                    }
                )
    return {
        "valid": not violations,
        "scanned_files": scanned,
        "violation_count": len(violations),
        "violations": violations,
    }
