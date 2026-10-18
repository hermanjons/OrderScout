from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from AI.processors.live_evidence import write_live_evidence_file
from AI.processors.model_routing import stable_state_hash
from AI.processors.orders_live_human_eval_cli import (
    _artifact_payload,
    _canonical_review_status,
    _compact_text,
    _load_json,
    _utcnow_iso,
    _write_raw_state,
)


def _source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_reviewed_checkpoint(
    *,
    source_state_path: Path,
    target_state_path: Path,
    artifact_path: Path,
    through_turn: int,
    reason: str,
    target_message_count: int = 0,
) -> dict[str, Any]:
    if through_turn < 1:
        raise RuntimeError("Checkpoint turu en az 1 olmali.")
    clean_reason = _compact_text(reason)
    if not clean_reason:
        raise RuntimeError("Checkpoint olusturma gerekcesi gerekir.")

    source = _load_json(source_state_path)
    if not source:
        raise RuntimeError("Kaynak kampanya state dosyasi bulunamadi veya bos.")
    source_turns = [
        dict(turn)
        for turn in list(source.get("turns") or [])
        if isinstance(turn, dict)
    ]
    selected_turns = [
        turn
        for turn in source_turns
        if int(turn.get("turn") or 0) <= through_turn
    ]
    selected_ids = [int(turn.get("turn") or 0) for turn in selected_turns]
    expected_ids = list(range(1, through_turn + 1))
    if selected_ids != expected_ids:
        raise RuntimeError(
            "Checkpoint yalniz kesintisiz 1..N tur dizisinden olusturulabilir."
        )

    for turn in selected_turns:
        review = dict(turn.get("human_review") or {})
        turn_id = int(turn.get("turn") or 0)
        if _canonical_review_status(review.get("status")) != "accepted":
            raise RuntimeError(
                f"Checkpoint turu {turn_id} accepted olarak incelenmemis."
            )
        if not _compact_text(review.get("notes")):
            raise RuntimeError(
                f"Checkpoint turu {turn_id} inceleme gerekcesi icermiyor."
            )
        if not bool(review.get("reviewed_directly_by_closing_codex")):
            raise RuntimeError(
                f"Checkpoint turu {turn_id} dogrudan Codex incelemesi tasimiyor."
            )

    last_turn = selected_turns[-1]
    history_message_count = int(
        last_turn.get("history_message_count_after_turn") or 0
    )
    if history_message_count <= 0:
        raise RuntimeError("Son checkpoint turunda history mesaj sayisi yok.")
    source_history = [
        dict(row)
        for row in list(source.get("history") or [])
        if isinstance(row, dict)
    ]
    if history_message_count > len(source_history):
        raise RuntimeError("Kaynak history checkpoint sinirindan daha kisa.")
    selected_history = source_history[:history_message_count]
    calculated_hash = stable_state_hash({"history": selected_history})
    recorded_hash = _compact_text(
        last_turn.get("history_state_hash_after_turn")
    )
    if not recorded_hash or calculated_hash != recorded_hash:
        raise RuntimeError(
            "Checkpoint history hash'i kaynak tur kaydiyla eslesmiyor."
        )

    excluded_turn_ids = [
        int(turn.get("turn") or 0)
        for turn in source_turns
        if int(turn.get("turn") or 0) > through_turn
    ]
    source_runtime_transitions = [
        dict(row)
        for row in list(source.get("runtime_transitions") or [])
        if isinstance(row, dict)
    ]
    selected_runtime_transitions = [
        row
        for row in source_runtime_transitions
        if int(row.get("effective_turn") or 0) <= through_turn
    ]
    excluded_runtime_transitions = [
        row
        for row in source_runtime_transitions
        if int(row.get("effective_turn") or 0) > through_turn
    ]
    created_at = _utcnow_iso()
    checkpoint = dict(source)
    checkpoint["name"] = (
        f"{_compact_text(source.get('name'))} checkpoint through turn "
        f"{through_turn}"
    ).strip()
    checkpoint["history"] = selected_history
    checkpoint["turns"] = selected_turns
    checkpoint["runtime_transitions"] = selected_runtime_transitions
    last_runtime_plan = (
        dict(last_turn.get("runtime_plan") or {})
        if isinstance(last_turn.get("runtime_plan"), dict)
        else {}
    )
    checkpoint["provider_code"] = _compact_text(
        last_turn.get("provider_code")
        or last_runtime_plan.get("provider_code")
        or source.get("initial_provider_code")
        or source.get("provider_code")
    ).casefold()
    checkpoint["requested_model"] = _compact_text(
        last_turn.get("requested_model")
        or last_runtime_plan.get("requested_model")
        or source.get("initial_requested_model")
        or source.get("requested_model")
    )
    checkpoint.pop("final_assessment", None)
    checkpoint["updated_at"] = created_at
    source_target_message_count = max(
        0,
        int(source.get("target_message_count") or 0),
    )
    requested_target_message_count = max(0, int(target_message_count or 0))
    if requested_target_message_count:
        if requested_target_message_count <= source_target_message_count:
            raise RuntimeError(
                "Checkpoint hedef mesaj sayisi kaynak hedeften buyuk olmalidir."
            )
        if requested_target_message_count <= history_message_count:
            raise RuntimeError(
                "Checkpoint hedef mesaj sayisi mevcut history'den buyuk olmalidir."
            )
        checkpoint["target_message_count"] = requested_target_message_count
    checkpoint["checkpoint_source"] = {
        "source_state_path": str(source_state_path),
        "source_state_sha256": _source_sha256(source_state_path),
        "source_turn_count": len(source_turns),
        "through_turn": through_turn,
        "excluded_turn_ids": excluded_turn_ids,
        "excluded_runtime_transitions": excluded_runtime_transitions,
        "retained_runtime_transition_count": len(
            selected_runtime_transitions
        ),
        "history_message_count": history_message_count,
        "verified_history_state_hash": calculated_hash,
        "all_included_turns_directly_reviewed_and_accepted": True,
        "reason": clean_reason,
        "created_at": created_at,
        "source_target_message_count": source_target_message_count,
        "target_message_count": max(
            0,
            int(checkpoint.get("target_message_count") or 0),
        ),
    }

    _write_raw_state(target_state_path, checkpoint)
    artifact = _artifact_payload(checkpoint)
    write_live_evidence_file(artifact_path, artifact)
    return {
        "success": True,
        "through_turn": through_turn,
        "history_message_count": history_message_count,
        "verified_history_state_hash": calculated_hash,
        "excluded_turn_ids": excluded_turn_ids,
        "excluded_runtime_transition_count": len(
            excluded_runtime_transitions
        ),
        "retained_runtime_transition_count": len(
            selected_runtime_transitions
        ),
        "source_state_sha256": checkpoint["checkpoint_source"][
            "source_state_sha256"
        ],
        "source_target_message_count": source_target_message_count,
        "target_message_count": max(
            0,
            int(checkpoint.get("target_message_count") or 0),
        ),
        "state_path": str(target_state_path),
        "artifact_path": str(artifact_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create an auditable continuation checkpoint from a sequential "
            "prefix of directly reviewed and accepted live conversation turns."
        )
    )
    parser.add_argument("--source-state", required=True)
    parser.add_argument("--target-state", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--through-turn", required=True, type=int)
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--target-message-count",
        type=int,
        default=0,
        help=(
            "Optional larger visible-message target for an audited continuation. "
            "The value must exceed both the source target and checkpoint history."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = create_reviewed_checkpoint(
            source_state_path=Path(args.source_state),
            target_state_path=Path(args.target_state),
            artifact_path=Path(args.artifact),
            through_turn=args.through_turn,
            reason=args.reason,
            target_message_count=max(0, int(args.target_message_count or 0)),
        )
    except Exception as exc:
        print(
            json.dumps(
                {"success": False, "error": str(exc)},
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
