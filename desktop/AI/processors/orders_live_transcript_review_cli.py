from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from AI.processors.cloud_runtime import provider_invocation_provenance
from AI.processors.live_evidence import write_live_evidence_file
from AI.processors.orders_live_human_eval_cli import _canonical_review_status


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Transcript artifact bir JSON object olmali.")
    return dict(payload)


def _provider_payload(
    payload: dict[str, Any],
    provider_code: str,
) -> dict[str, Any]:
    providers = [
        dict(row)
        for row in list(payload.get("providers") or [])
        if isinstance(row, dict)
    ]
    if not providers and isinstance(payload.get("turns"), list):
        return payload
    requested = _compact_text(provider_code).casefold()
    matches = [
        row
        for row in providers
        if not requested
        or _compact_text(row.get("provider_code")).casefold() == requested
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Transcript icinden tek provider secilemedi; --provider kullanin."
        )
    return matches[0]


def _review_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RuntimeError("Review payload bir JSON listesi olmali.")
    rows: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise RuntimeError("Her review satiri JSON object olmali.")
        turn = int(raw.get("turn") or 0)
        status = _canonical_review_status(raw.get("status"))
        notes = _compact_text(raw.get("notes"))
        if turn <= 0 or not status or not notes:
            raise RuntimeError(
                "Her review turn, accepted/needs_review/failed status ve notes tasimali."
            )
        rows.append({"turn": turn, "status": status, "notes": notes})
    if len({row["turn"] for row in rows}) != len(rows):
        raise RuntimeError("Ayni tur birden fazla kez review edilemez.")
    return rows


def build_direct_review(
    *,
    source_path: Path,
    reviews: Sequence[dict[str, Any]],
    provider_code: str = "",
    overall_notes: str,
) -> dict[str, Any]:
    payload = _load_payload(source_path)
    provider = _provider_payload(payload, provider_code)
    turns = [
        dict(row)
        for row in list(provider.get("turns") or [])
        if isinstance(row, dict)
    ]
    if not turns:
        raise RuntimeError("Transcript icinde incelenecek assistant turu yok.")
    normalized_reviews = _review_rows(list(reviews))
    reviews_by_turn = {int(row["turn"]): row for row in normalized_reviews}
    source_turn_ids = [int(turn.get("turn") or index) for index, turn in enumerate(turns, 1)]
    if set(source_turn_ids) != set(reviews_by_turn):
        missing = sorted(set(source_turn_ids) - set(reviews_by_turn))
        extra = sorted(set(reviews_by_turn) - set(source_turn_ids))
        raise RuntimeError(
            "Her assistant cevabi tam bir kez incelenmeli; "
            f"missing={missing or '-'} extra={extra or '-'}"
        )

    reviewed_turns: list[dict[str, Any]] = []
    actual_models: list[str] = []
    fallback_turn_count = 0
    for index, turn in enumerate(turns, 1):
        turn_id = int(turn.get("turn") or index)
        runtime_plan = dict(turn.get("runtime_plan") or {})
        provenance = provider_invocation_provenance(runtime_plan)
        actual_model = _compact_text(
            provenance.get("last_successful_actual_model")
        )
        requested_model = _compact_text(
            runtime_plan.get("requested_model")
            or turn.get("requested_model")
            or provider.get("requested_model")
        )
        fallback_used = bool(provenance.get("any_model_fallback_used"))
        if fallback_used:
            fallback_turn_count += 1
        if actual_model and actual_model not in actual_models:
            actual_models.append(actual_model)
        review = reviews_by_turn[turn_id]
        answer = _compact_text(turn.get("answer"))
        reviewed_turns.append(
            {
                "turn": turn_id,
                "phase": _compact_text(turn.get("phase")),
                "user": _compact_text(turn.get("user")),
                "answer": answer,
                "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
                "requested_model": requested_model,
                "actual_model": actual_model,
                "fallback_used": fallback_used,
                "fallback_attempts": list(runtime_plan.get("fallback_attempts") or []),
                "next_prompt_selection_reason": _compact_text(
                    turn.get("next_prompt_selection_reason")
                ),
                "status": review["status"],
                "notes": review["notes"],
                "reviewed_directly_by_closing_codex": True,
            }
        )

    accepted = sum(row["status"] == "accepted" for row in reviewed_turns)
    needs_review = sum(row["status"] == "needs_review" for row in reviewed_turns)
    failed = sum(row["status"] == "failed" for row in reviewed_turns)
    machine_passed = bool(provider.get("machine_passed", payload.get("machine_passed")))
    status = "fail" if failed else "partial" if needs_review else "pass"
    passed = machine_passed and status == "pass"
    message_count = len(turns) + sum(bool(row.get("answer")) for row in turns)
    return {
        "name": f"Direct Codex review: {source_path.name}",
        "artifact_type": "orders_live_direct_transcript_review",
        "created_at": _utcnow_iso(),
        "source_artifact": {
            "filename": source_path.name,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "artifact_type": _compact_text(payload.get("artifact_type")),
        },
        "provider_code": _compact_text(provider.get("provider_code") or provider_code),
        "requested_model": _compact_text(provider.get("requested_model")),
        "actual_models_used": actual_models,
        "fallback_turn_count": fallback_turn_count,
        "machine_passed": machine_passed,
        "turn_count": len(turns),
        "user_turn_count": len(turns),
        "assistant_turn_count": sum(bool(row.get("answer")) for row in turns),
        "message_count": message_count,
        "reviewed_turns": reviewed_turns,
        "human_review": {
            "reviewer": "closing_codex",
            "direct_sequential_review": True,
            "reviewed_turn_count": len(reviewed_turns),
            "accepted_turn_count": accepted,
            "needs_review_turn_count": needs_review,
            "failed_turn_count": failed,
            "status": status,
            "notes": _compact_text(overall_notes),
        },
        "passed": passed,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bind a direct turn-by-turn Codex review to a live transcript."
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider", default="")
    parser.add_argument("--reviews-json", required=True)
    parser.add_argument("--overall-notes", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    raw_reviews = sys.stdin.read() if args.reviews_json == "-" else args.reviews_json
    reviews = json.loads(raw_reviews)
    payload = build_direct_review(
        source_path=Path(args.source),
        reviews=reviews,
        provider_code=args.provider,
        overall_notes=args.overall_notes,
    )
    target = write_live_evidence_file(Path(args.output), payload)
    print(f"artifact={target}")
    print(f"status={(payload.get('human_review') or {}).get('status')}")
    print(f"passed={bool(payload.get('passed'))}")
    return 0 if payload.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
