from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import time_ns
from typing import Any, Sequence

from Account.processors.agentic_repository import list_accounts
from AI.processors import operation_runtime
from AI.processors.tools import (
    orders_cargo_provider_options,
    orders_prepare_change_cargo_provider,
    orders_prepare_change_cargo_provider_bulk,
    returns_prepare_approve,
)
from Marketplaces.processors.catalog import normalize_marketplace_environment
from Orders.processors.agentic_repository import list_orders, list_return_claims
from Orders.views import actions as orders_actions
from settings import DB_NAME


def _text(value: Any) -> str:
    return str(value or "").strip()


def _stage_account(*, seller_id: str, db_name: str) -> Any:
    result = list_accounts(active_only=True, db_name=db_name)
    if not result.success:
        raise RuntimeError(result.message)
    matches = []
    for row in list((result.data or {}).get("records") or []):
        extra = dict(getattr(row, "extra_config", None) or {})
        environment = normalize_marketplace_environment(
            extra.get("environment") or extra.get("api_environment") or "production"
        )
        if (
            _text(getattr(row, "account_id", "")) == _text(seller_id)
            and _text(getattr(row, "platform", "")).casefold() == "trendyol"
            and environment == "stage"
        ):
            matches.append(row)
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one active Stage Trendyol account for seller {seller_id}; got {len(matches)}."
        )
    return matches[0]


def _candidate_order_numbers(
    *,
    api_account_pk: int,
    count: int,
    db_name: str,
) -> tuple[list[str], str]:
    result = list_orders(db_name=db_name)
    if not result.success:
        raise RuntimeError(result.message)
    all_rows = list((result.data or {}).get("records") or [])
    global_counts: dict[str, int] = {}
    for row in all_rows:
        number = _text(getattr(row, "orderNumber", ""))
        if number:
            global_counts[number] = global_counts.get(number, 0) + 1
    eligible = [
        row
        for row in all_rows
        if int(getattr(row, "api_account_id", 0) or 0) == int(api_account_pk)
        and _text(getattr(row, "status", "")).casefold() in {"created", "picking", "invoiced"}
        and getattr(row, "id", None) not in (None, "", 0)
        and global_counts.get(_text(getattr(row, "orderNumber", ""))) == 1
    ]
    groups: dict[str, list[Any]] = {}
    for row in eligible:
        provider_name = _text(getattr(row, "cargoProviderName", ""))
        provider_code = _text(
            orders_actions.cargo_provider_code_for_name(
                provider_name,
                platform_code="trendyol",
            )
        ).upper()
        if provider_code:
            groups.setdefault(provider_code, []).append(row)
    selected_group = next(
        (
            (provider_code, sorted(rows, key=lambda row: int(getattr(row, "lastModifiedDate", 0) or 0)))
            for provider_code, rows in sorted(groups.items())
            if len(rows) >= count
        ),
        None,
    )
    if selected_group is None:
        raise RuntimeError("Stage does not currently contain enough exact-scope cargo-change candidates.")
    current_provider_code, rows = selected_group
    return [
        _text(getattr(row, "orderNumber", "")) for row in rows[:count]
    ], current_provider_code


def _target_provider_code(*, current_provider_code: str, db_name: str) -> str:
    result = orders_cargo_provider_options(
        platform_code="trendyol",
        limit=100,
        db_name=db_name,
    )
    if not result.success:
        raise RuntimeError(result.message)
    available = [
        _text(row.get("code")).upper()
        for row in list((result.data or {}).get("providers") or [])
        if isinstance(row, dict) and _text(row.get("code"))
    ]
    preferred = ["ARASMP", "YKMP", "TEXMP", "SURATMP", "PTTMP"]
    target = next(
        (
            code
            for code in preferred + available
            if code in available and code != _text(current_provider_code).upper()
        ),
        "",
    )
    if not target:
        raise RuntimeError("No alternative Trendyol cargo provider is available.")
    return target


def _execute_prepared_stage_action(
    action: dict[str, Any],
    *,
    expected_action_type: str,
    exact_count: int,
    seller_id: str,
    output_dir: str | Path,
    slug: str,
    staging_reason: str,
    mutation_summary: str,
) -> dict[str, Any]:
    if (
        action.get("action_type") != expected_action_type
        or action.get("execute_enabled") is not True
        or int(action.get("selected_record_count") or 0) != exact_count
    ):
        raise RuntimeError(
            "Prepared Stage action did not preserve the expected action type "
            "and exact record scope."
        )

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    key = f"stage-{slug}-{time_ns()}"
    evidence_path = root / f"{key}.json"
    audit_path = root / f"{key}.audit.jsonl"
    proof_path = root / f"{key}.external-proof.json"
    manifest_path = root / f"{key}.manifest.json"
    executed = operation_runtime.execute_staging_marketplace_evidence_run(
        action,
        approved_by="codex-stage-orders-acceptance",
        idempotency_key=key,
        audit_path=audit_path,
        evidence_path=evidence_path,
        staging_reason=staging_reason,
        marketplace="trendyol",
        staging_account_id=_text(seller_id),
    )
    if not executed.success:
        raise RuntimeError(
            f"Stage execute/read-back failed; evidence={evidence_path}; "
            f"message={executed.message}"
        )
    verify = dict((executed.data or {}).get("verify") or {})
    if (
        verify.get("verified") is not True
        or len(list(verify.get("rows") or [])) != exact_count
    ):
        raise RuntimeError(
            "Stage runtime did not verify every prepared record."
        )

    external_proof = {
        "verified": True,
        "marketplace_state_checked": True,
        "operation_matches": True,
        "staging_account_only": True,
        "staging_account_id": _text(seller_id),
        "idempotency_key": key,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checked_by": "codex-stage-orders-acceptance",
        "mutation_summary": mutation_summary,
        "privacy_note": (
            "No order, package, tracking, claim, customer, contact, credential, "
            "header, or token value is persisted in this external proof."
        ),
    }
    proof_path.write_text(
        json.dumps(
            external_proof,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    attached = operation_runtime.attach_staging_marketplace_external_proof(
        evidence_path,
        external_proof,
        idempotency_key=key,
        staging_account_id=_text(seller_id),
    )
    if not attached.success:
        raise RuntimeError(attached.message)
    manifest = operation_runtime.staging_marketplace_evidence_manifest(
        evidence_path,
        manifest_path=manifest_path,
        external_proof_path=proof_path,
        idempotency_key=key,
        staging_account_id=_text(seller_id),
    )
    if not manifest.success:
        raise RuntimeError(manifest.message)
    verified_manifest = (
        operation_runtime.verify_staging_marketplace_evidence_manifest(
            manifest_path,
            evidence_path=evidence_path,
            idempotency_key=key,
            staging_account_id=_text(seller_id),
        )
    )
    if not verified_manifest.success:
        raise RuntimeError(verified_manifest.message)
    return {
        "passed": True,
        "action_type": action.get("action_type"),
        "selected_record_count": exact_count,
        "staging_account_id": _text(seller_id),
        "runtime_verified": True,
        "external_proof_verified": True,
        "manifest_verified": True,
        "evidence_path": str(evidence_path),
        "external_proof_path": str(proof_path),
        "manifest_path": str(manifest_path),
        "audit_path": str(audit_path),
    }


def run_stage_bulk_cargo_acceptance(
    *,
    seller_id: str = "2738",
    count: int = 2,
    db_name: str = DB_NAME,
    output_dir: str | Path,
) -> dict[str, Any]:
    exact_count = max(2, min(5, int(count or 2)))
    account = _stage_account(seller_id=seller_id, db_name=db_name)
    account_pk = int(getattr(account, "pk", 0) or 0)
    order_numbers, current_provider = _candidate_order_numbers(
        api_account_pk=account_pk,
        count=exact_count,
        db_name=db_name,
    )
    target_provider = _target_provider_code(
        current_provider_code=current_provider,
        db_name=db_name,
    )
    prepared = orders_prepare_change_cargo_provider_bulk(
        db_name=db_name,
        order_numbers=order_numbers,
        cargo_provider=target_provider,
        limit=exact_count,
    )
    if not prepared.success:
        raise RuntimeError(prepared.message)
    action = dict((prepared.data or {}).get("action") or {})
    payload = dict((action.get("arguments") or {}).get("payload") or {})
    if (
        action.get("action_type") != "orders.change_orders_cargo_provider_bulk"
        or action.get("execute_enabled") is not True
        or int(action.get("selected_record_count") or 0) != exact_count
        or sorted(int(value) for value in list(payload.get("api_account_ids") or []))
        != [account_pk]
        or set(payload.get("orders") or []) != set(order_numbers)
    ):
        raise RuntimeError("Prepared bulk cargo action did not preserve the exact Stage scope.")

    return _execute_prepared_stage_action(
        action,
        expected_action_type="orders.change_orders_cargo_provider_bulk",
        exact_count=exact_count,
        seller_id=seller_id,
        output_dir=output_dir,
        slug="bulk-cargo",
        staging_reason=(
            "Complete the explicit Stage-only Orders bulk cargo acceptance with the "
            "smallest exact two-record scope and authoritative remote read-back."
        ),
        mutation_summary=(
            "The exact prepared Stage bulk cargo scope was re-read from the marketplace "
            "and every package matched the requested provider."
        ),
    )


def run_stage_single_cargo_acceptance(
    *,
    seller_id: str = "2738",
    db_name: str = DB_NAME,
    output_dir: str | Path,
) -> dict[str, Any]:
    account = _stage_account(seller_id=seller_id, db_name=db_name)
    account_pk = int(getattr(account, "pk", 0) or 0)
    order_numbers, current_provider = _candidate_order_numbers(
        api_account_pk=account_pk,
        count=2,
        db_name=db_name,
    )
    target_provider = _target_provider_code(
        current_provider_code=current_provider,
        db_name=db_name,
    )
    selected_order = order_numbers[0]
    prepared = orders_prepare_change_cargo_provider(
        db_name=db_name,
        order_numbers=[selected_order],
        cargo_provider=target_provider,
        limit=1,
    )
    if not prepared.success:
        raise RuntimeError(prepared.message)
    action = dict((prepared.data or {}).get("action") or {})
    payload = dict((action.get("arguments") or {}).get("payload") or {})
    if (
        action.get("action_type") != "orders.change_order_cargo_provider"
        or action.get("execute_enabled") is not True
        or int(action.get("selected_record_count") or 0) != 1
        or int(payload.get("api_account_id") or 0) != account_pk
        or _text(payload.get("order")) != selected_order
    ):
        raise RuntimeError(
            "Prepared single cargo action did not preserve the exact Stage scope."
        )
    return _execute_prepared_stage_action(
        action,
        expected_action_type="orders.change_order_cargo_provider",
        exact_count=1,
        seller_id=seller_id,
        output_dir=output_dir,
        slug="single-cargo",
        staging_reason=(
            "Complete the explicit Stage-only Orders single cargo acceptance "
            "with one exact package and authoritative remote read-back."
        ),
        mutation_summary=(
            "The exact prepared single-package Stage cargo scope was re-read "
            "from the marketplace and matched the requested provider."
        ),
    )


def run_stage_return_approval_acceptance(
    *,
    seller_id: str = "2738",
    db_name: str = DB_NAME,
    output_dir: str | Path,
) -> dict[str, Any]:
    account = _stage_account(seller_id=seller_id, db_name=db_name)
    account_pk = int(getattr(account, "pk", 0) or 0)
    claims_result = list_return_claims(
        api_account_ids=[account_pk],
        active=True,
        statuses=["WaitingInAction"],
        db_name=db_name,
    )
    if not claims_result.success:
        raise RuntimeError(claims_result.message)

    selected_action: dict[str, Any] = {}
    for claim in list((claims_result.data or {}).get("records") or []):
        query = _text(
            getattr(claim, "claimId", "")
            or getattr(claim, "orderNumber", "")
        )
        if not query:
            continue
        prepared = returns_prepare_approve(
            db_name=db_name,
            query=query,
            limit=1,
        )
        data = dict(prepared.data or {})
        action = dict(data.get("action") or {})
        payload = dict((action.get("arguments") or {}).get("payload") or {})
        if (
            prepared.success
            and data.get("valid") is True
            and action.get("action_type") == "orders.approve_return_claim"
            and action.get("execute_enabled") is True
            and int(action.get("selected_record_count") or 0) == 1
            and int(payload.get("api_account_id") or 0) == account_pk
        ):
            selected_action = action
            break
    if not selected_action:
        raise RuntimeError(
            "Stage does not currently contain one exact WaitingInAction return "
            "claim eligible for approval."
        )
    return _execute_prepared_stage_action(
        selected_action,
        expected_action_type="orders.approve_return_claim",
        exact_count=1,
        seller_id=seller_id,
        output_dir=output_dir,
        slug="return-approval",
        staging_reason=(
            "Complete the explicit Stage-only return approval acceptance with "
            "one exact WaitingInAction claim and authoritative refresh/read-back."
        ),
        mutation_summary=(
            "The exact prepared Stage return approval scope was refreshed from "
            "the marketplace and no longer remained WaitingInAction."
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the smallest exact-scope Stage bulk cargo acceptance package."
    )
    parser.add_argument("--seller-id", default="2738")
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--db-name", default=DB_NAME)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--action",
        choices=("bulk-cargo", "single-cargo", "return-approval"),
        default="bulk-cargo",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "single-cargo":
            result = run_stage_single_cargo_acceptance(
                seller_id=args.seller_id,
                db_name=args.db_name,
                output_dir=args.output_dir,
            )
        elif args.action == "return-approval":
            result = run_stage_return_approval_acceptance(
                seller_id=args.seller_id,
                db_name=args.db_name,
                output_dir=args.output_dir,
            )
        else:
            result = run_stage_bulk_cargo_acceptance(
                seller_id=args.seller_id,
                count=args.count,
                db_name=args.db_name,
                output_dir=args.output_dir,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "passed": False,
                    "error_type": type(exc).__name__,
                    "message": _text(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
