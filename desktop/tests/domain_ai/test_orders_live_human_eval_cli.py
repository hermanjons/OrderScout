from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from AI.processors.orders_live_long_conversation_recheck_cli import (
    _run_turn as run_evidence_turn,
)
from AI.processors.orders_live_human_eval_cli import (
    _artifact_payload,
    finalize_conversation,
    run_turn,
    review_last_turn,
)
from AI.processors.orders_live_human_eval_checkpoint_cli import (
    create_reviewed_checkpoint,
)
from AI.processors.orders_live_transcript_review_cli import build_direct_review
from AI.processors.model_routing import stable_state_hash
from Feedback.processors.pipeline import Result


def _reviewed_turn(index: int) -> dict[str, object]:
    return {
        "turn": index,
        "user": f"user {index}",
        "answer": f"assistant {index}",
        "success": True,
        "human_review": {
            "status": "pass",
            "notes": "directly reviewed",
        },
    }


class OrdersLiveHumanEvalCliTests(unittest.TestCase):
    def test_checkpoint_keeps_only_directly_reviewed_accepted_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "source.state.json"
            target_path = root / "checkpoint.state.json"
            artifact_path = root / "checkpoint.json"
            history = [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "answer one"},
                {"role": "user", "content": "two"},
                {"role": "assistant", "content": "answer two"},
            ]
            first_hash = stable_state_hash({"history": history[:2]})
            second_hash = stable_state_hash({"history": history})
            source = {
                "name": "diagnostic",
                "provider_code": "gemini",
                "requested_model": "exact-model",
                "target_message_count": 100,
                "minimum_turns": 50,
                "history": history,
                "turns": [
                    {
                        "turn": 1,
                        "answer": "answer one",
                        "history_message_count_after_turn": 2,
                        "history_state_hash_after_turn": first_hash,
                        "human_review": {
                            "status": "accepted",
                            "notes": "Read directly.",
                            "reviewed_directly_by_closing_codex": True,
                        },
                    },
                    {
                        "turn": 2,
                        "answer": "answer two",
                        "history_message_count_after_turn": 4,
                        "history_state_hash_after_turn": second_hash,
                        "human_review": {
                            "status": "failed",
                            "notes": "Found a defect.",
                            "reviewed_directly_by_closing_codex": True,
                        },
                    },
                ],
                "final_assessment": {"status": "fail", "notes": "Stopped."},
            }
            source_path.write_text(
                json.dumps(source, ensure_ascii=False), encoding="utf-8"
            )

            result = create_reviewed_checkpoint(
                source_state_path=source_path,
                target_state_path=target_path,
                artifact_path=artifact_path,
                through_turn=1,
                reason="Continue after fixing the excluded diagnostic turn.",
                target_message_count=202,
            )

            checkpoint = json.loads(target_path.read_text(encoding="utf-8"))
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertTrue(result.get("success"))
            self.assertEqual(result.get("source_target_message_count"), 100)
            self.assertEqual(result.get("target_message_count"), 202)
            self.assertEqual(len(checkpoint.get("turns") or []), 1)
            self.assertEqual(len(checkpoint.get("history") or []), 2)
            self.assertEqual(checkpoint.get("target_message_count"), 202)
            self.assertNotIn("final_assessment", checkpoint)
            self.assertEqual(
                (checkpoint.get("checkpoint_source") or {}).get(
                    "excluded_turn_ids"
                ),
                [2],
            )
            self.assertEqual(
                (checkpoint.get("checkpoint_source") or {}).get(
                    "source_target_message_count"
                ),
                100,
            )
            self.assertEqual(
                (checkpoint.get("checkpoint_source") or {}).get(
                    "target_message_count"
                ),
                202,
            )
            self.assertEqual(
                (artifact.get("checkpoint_source") or {}).get(
                    "verified_history_state_hash"
                ),
                first_hash,
            )

    def test_checkpoint_rejects_non_increasing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "source.state.json"
            history = [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "answer one"},
            ]
            source_path.write_text(
                json.dumps(
                    {
                        "target_message_count": 100,
                        "history": history,
                        "turns": [
                            {
                                "turn": 1,
                                "history_message_count_after_turn": 2,
                                "history_state_hash_after_turn": (
                                    stable_state_hash({"history": history})
                                ),
                                "human_review": {
                                    "status": "accepted",
                                    "notes": "Read directly.",
                                    "reviewed_directly_by_closing_codex": True,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "buyuk olmalidir"):
                create_reviewed_checkpoint(
                    source_state_path=source_path,
                    target_state_path=root / "checkpoint.state.json",
                    artifact_path=root / "checkpoint.json",
                    through_turn=1,
                    reason="Invalid target regression.",
                    target_message_count=100,
                )

    def test_checkpoint_rejects_nonaccepted_included_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "source.state.json"
            history = [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "answer one"},
            ]
            source_path.write_text(
                json.dumps(
                    {
                        "history": history,
                        "turns": [
                            {
                                "turn": 1,
                                "history_message_count_after_turn": 2,
                                "history_state_hash_after_turn": (
                                    stable_state_hash({"history": history})
                                ),
                                "human_review": {
                                    "status": "needs_review",
                                    "notes": "Not accepted.",
                                    "reviewed_directly_by_closing_codex": True,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "accepted"):
                create_reviewed_checkpoint(
                    source_state_path=source_path,
                    target_state_path=root / "checkpoint.state.json",
                    artifact_path=root / "checkpoint.json",
                    through_turn=1,
                    reason="Must fail.",
                )

    def test_checkpoint_removes_transition_after_selected_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "source.state.json"
            target_path = root / "checkpoint.state.json"
            artifact_path = root / "checkpoint.json"
            history = [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "answer one"},
                {"role": "user", "content": "failed switch"},
                {"role": "assistant", "content": "wrong answer"},
            ]
            source_path.write_text(
                json.dumps(
                    {
                        "provider_code": "openrouter",
                        "requested_model": "new-model",
                        "initial_provider_code": "gemini",
                        "initial_requested_model": "old-model",
                        "runtime_transitions": [
                            {
                                "effective_turn": 2,
                                "from_provider_code": "gemini",
                                "from_model": "old-model",
                                "to_provider_code": "openrouter",
                                "to_model": "new-model",
                            }
                        ],
                        "history": history,
                        "turns": [
                            {
                                "turn": 1,
                                "provider_code": "gemini",
                                "requested_model": "old-model",
                                "runtime_plan": {
                                    "provider_code": "gemini",
                                    "requested_model": "old-model",
                                },
                                "history_message_count_after_turn": 2,
                                "history_state_hash_after_turn": (
                                    stable_state_hash({"history": history[:2]})
                                ),
                                "human_review": {
                                    "status": "accepted",
                                    "notes": "Read directly.",
                                    "reviewed_directly_by_closing_codex": True,
                                },
                            },
                            {
                                "turn": 2,
                                "provider_code": "openrouter",
                                "requested_model": "new-model",
                                "history_message_count_after_turn": 4,
                                "history_state_hash_after_turn": (
                                    stable_state_hash({"history": history})
                                ),
                                "human_review": {
                                    "status": "failed",
                                    "notes": "Distant context was lost.",
                                    "reviewed_directly_by_closing_codex": True,
                                },
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = create_reviewed_checkpoint(
                source_state_path=source_path,
                target_state_path=target_path,
                artifact_path=artifact_path,
                through_turn=1,
                reason="Retry the failed provider transition from the clean prefix.",
            )

            checkpoint = json.loads(target_path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint.get("provider_code"), "gemini")
            self.assertEqual(checkpoint.get("requested_model"), "old-model")
            self.assertEqual(checkpoint.get("runtime_transitions"), [])
            self.assertEqual(result.get("excluded_runtime_transition_count"), 1)
            self.assertEqual(result.get("retained_runtime_transition_count"), 0)

    def test_direct_review_binds_every_turn_and_per_turn_model_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "transcript.json"
            source_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "long_conversation",
                        "providers": [
                            {
                                "provider_code": "openrouter",
                                "requested_model": "best-free",
                                "machine_passed": True,
                                "turns": [
                                    {
                                        "turn": 1,
                                        "phase": "chat",
                                        "user": "hello",
                                        "answer": "answer one",
                                        "runtime_plan": {
                                            "requested_model": "best-free",
                                            "actual_model": "fallback-free",
                                            "fallback_used": True,
                                            "fallback_attempts": [
                                                {
                                                    "model": "best-free",
                                                    "reason": "http_429",
                                                }
                                            ],
                                        },
                                    },
                                    {
                                        "turn": 2,
                                        "phase": "orders",
                                        "user": "orders",
                                        "answer": "answer two",
                                        "runtime_plan": {
                                            "requested_model": "best-free",
                                            "actual_model": "best-free",
                                            "fallback_used": False,
                                        },
                                    },
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            review = build_direct_review(
                source_path=source_path,
                provider_code="openrouter",
                reviews=[
                    {"turn": 1, "status": "accepted", "notes": "Relevant."},
                    {"turn": 2, "status": "needs_review", "notes": "Awkward."},
                ],
                overall_notes="Every answer was read in order.",
            )

            self.assertEqual(review.get("turn_count"), 2)
            self.assertEqual(review.get("message_count"), 4)
            self.assertEqual(review.get("fallback_turn_count"), 1)
            self.assertEqual(
                review.get("actual_models_used"),
                ["fallback-free", "best-free"],
            )
            self.assertEqual(
                (review.get("human_review") or {}).get("status"),
                "partial",
            )
            self.assertFalse(review.get("passed"))
            self.assertTrue(
                (review.get("reviewed_turns") or [])[0].get(
                    "reviewed_directly_by_closing_codex"
                )
            )

    def test_direct_review_rejects_missing_turn_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "transcript.json"
            source_path.write_text(
                json.dumps(
                    {
                        "machine_passed": True,
                        "turns": [
                            {"turn": 1, "answer": "one"},
                            {"turn": 2, "answer": "two"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "Her assistant cevabi"):
                build_direct_review(
                    source_path=source_path,
                    reviews=[
                        {"turn": 1, "status": "accepted", "notes": "Read."}
                    ],
                    overall_notes="Incomplete.",
                )

    def test_live_turn_evidence_keeps_authoritative_results_and_history_hashes(self) -> None:
        history: list[dict[str, object]] = []

        def client(_prompt: str) -> str:
            return "Stok ozeti authoritative sonucuna gore hazir."

        client.resource_plan = {  # type: ignore[attr-defined]
            "provider_code": "gemini",
            "requested_model": "exact-model",
            "actual_model": "exact-model",
        }
        result = Result.ok(
            "Stok ozeti authoritative sonucuna gore hazir.",
            close_dialog=False,
            data={
                "answer": "Stok ozeti authoritative sonucuna gore hazir.",
                "mode": "tool",
                "decision_path": "intent_override",
                "model_invoked": True,
                "tool_calls": [
                    {"tool": "stock.inventory_overview", "arguments": {}}
                ],
                "tool_results": [
                    {
                        "tool": "stock.inventory_overview",
                        "arguments": {},
                        "message": "Stok ozeti getirildi.",
                        "data": {"total_item_count": 4},
                    }
                ],
                "conversation_context": {"domain": "stock"},
            },
        )
        with patch(
            "AI.processors.orders_live_long_conversation_recheck_cli.run_agent_turn",
            return_value=result,
        ):
            turn = run_evidence_turn(
                "stok ozetini getir",
                phase="evidence_contract",
                selection_reason="exercise authoritative result persistence",
                client=client,
                provider_code="gemini",
                model_name="exact-model",
                db_name="ignored.sqlite3",
                history=history,
            )

        self.assertEqual(
            turn.get("tool_results"),
            result.data.get("tool_results"),
        )
        self.assertEqual(turn.get("history_message_count_before_turn"), 0)
        self.assertEqual(turn.get("history_message_count_after_turn"), 2)
        self.assertNotEqual(
            turn.get("history_state_hash_before_turn"),
            turn.get("history_state_hash_after_turn"),
        )

    def test_artifact_reports_visible_message_counts_and_target(self) -> None:
        state = {
            "name": "100-message acceptance",
            "provider_code": "gemini",
            "requested_model": "gemini-3.5-flash",
            "target_message_count": 50,
            "turns": [_reviewed_turn(index) for index in range(1, 26)],
            "final_assessment": {
                "status": "pass",
                "notes": "Every answer was reviewed in order.",
            },
        }

        artifact = _artifact_payload(state)

        self.assertEqual(artifact.get("user_turn_count"), 25)
        self.assertEqual(artifact.get("assistant_turn_count"), 25)
        self.assertEqual(artifact.get("message_count"), 50)
        self.assertEqual(artifact.get("target_message_count"), 50)
        self.assertTrue(artifact.get("passed"))

    def test_artifact_cannot_pass_while_any_turn_needs_review(self) -> None:
        turns = [_reviewed_turn(index) for index in range(1, 26)]
        turns[7]["human_review"] = {
            "status": "needs_review",
            "notes": "Typed intent requires a fresh rerun.",
        }
        artifact = _artifact_payload(
            {
                "name": "strict review gate",
                "target_message_count": 50,
                "minimum_turns": 25,
                "turns": turns,
                "final_assessment": {
                    "status": "pass",
                    "notes": "Should not override a partial turn.",
                },
            }
        )

        self.assertFalse(artifact.get("passed"))
        self.assertTrue((artifact.get("human_review") or {}).get("complete"))
        self.assertFalse(
            (artifact.get("human_review") or {}).get("all_turns_accepted")
        )

    def test_review_last_turn_records_review_without_generating_a_new_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_path = root / "state.json"
            artifact_path = root / "artifact.json"
            state_path.write_text(
                json.dumps(
                    {
                        "name": "review only",
                        "requested_model": "exact-model",
                        "turns": [
                            {
                                "turn": 1,
                                "user": "hello",
                                "answer": "hi",
                                "success": True,
                                "model_invoked": True,
                                "runtime_plan": {
                                    "requested_model": "exact-model",
                                    "actual_model": "exact-model",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = review_last_turn(
                state_path=state_path,
                artifact_path=artifact_path,
                status="accepted",
                notes="Visible answer and runtime evidence inspected.",
            )

            self.assertEqual(result.get("turn"), 1)
            self.assertEqual(result.get("status"), "accepted")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(state.get("turns") or []), 1)
            self.assertEqual(
                ((state.get("turns") or [])[0].get("human_review") or {}).get("status"),
                "accepted",
            )

    def test_cross_domain_artifact_requires_authoritative_structured_coverage(self) -> None:
        turns = [_reviewed_turn(index) for index in range(1, 26)]
        turns[0]["provider_code"] = "gemini"
        turns[0]["requested_model"] = "gemini-3.5-flash"
        turns[0]["tools"] = ["stock.inventory_overview"]
        turns[0]["tool_results"] = [
            {"tool": "stock.inventory_overview", "data": {"total": 3}}
        ]
        state = {
            "name": "cross-domain target gate",
            "artifact_type": "ai_cross_domain_live_human_directed_conversation",
            "provider_code": "gemini",
            "requested_model": "gemini-3.5-flash",
            "required_domains": ["stock", "finance"],
            "target_message_count": 50,
            "turns": turns,
            "final_assessment": {
                "status": "pass",
                "notes": "Every visible answer was reviewed in order.",
            },
        }

        missing = _artifact_payload(state)
        self.assertFalse(missing.get("passed"))
        self.assertFalse(missing.get("domain_coverage_complete"))
        self.assertEqual(missing.get("domains_observed"), ["stock"])

        turns[1]["provider_code"] = "openrouter"
        turns[1]["requested_model"] = "free-model"
        turns[1]["tools"] = ["operations.manual_action.route"]
        turns[1]["tool_results"] = [
            {
                "tool": "operations.manual_action.route",
                "data": {
                    "action": {
                        "domain": "finance",
                        "capability_id": "finance.action_save_cost_item",
                    }
                },
            }
        ]
        complete = _artifact_payload(state)
        self.assertTrue(complete.get("domain_coverage_complete"))
        self.assertTrue(complete.get("passed"))
        self.assertEqual(complete.get("domains_observed"), ["finance", "stock"])
        self.assertEqual(
            complete.get("artifact_type"),
            "ai_cross_domain_live_human_directed_conversation",
        )

    def test_finalize_rejects_pass_before_campaign_message_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_path = root / "state.json"
            artifact_path = root / "artifact.json"
            turns = [_reviewed_turn(index) for index in range(1, 20)]
            turns.append(
                {
                    "turn": 20,
                    "user": "last user",
                    "answer": "last assistant",
                    "success": True,
                }
            )
            state_path.write_text(
                json.dumps(
                    {
                        "name": "target gate",
                        "provider_code": "gemini",
                        "requested_model": "gemini-3.5-flash",
                        "target_message_count": 50,
                        "turns": turns,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "hedef gorunur mesaj"):
                finalize_conversation(
                    state_path=state_path,
                    artifact_path=artifact_path,
                    status="pass",
                    notes="Reviewed but too short.",
                )

    def test_focused_campaign_uses_persisted_minimum_turn_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_path = root / "state.json"
            artifact_path = root / "artifact.json"
            turns = [_reviewed_turn(index) for index in range(1, 6)]
            turns.append(
                {
                    "turn": 6,
                    "user": "orphan approval",
                    "answer": "No pending action remains.",
                    "success": True,
                }
            )
            state_path.write_text(
                json.dumps(
                    {
                        "name": "focused regression acceptance",
                        "provider_code": "openrouter",
                        "requested_model": "exact-model",
                        "minimum_turns": 6,
                        "turns": turns,
                    }
                ),
                encoding="utf-8",
            )

            result = finalize_conversation(
                state_path=state_path,
                artifact_path=artifact_path,
                status="pass",
                notes="Exact six-turn regression chain was directly reviewed.",
            )

            self.assertTrue(result.get("passed"))
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(
                (artifact.get("evaluation_contract") or {}).get("minimum_turns"),
                6,
            )
            self.assertEqual(artifact.get("turn_count"), 6)

    def test_explicit_model_switch_preserves_history_and_per_turn_model_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_path = root / "state.json"
            artifact_path = root / "artifact.json"
            old_turn = {
                **_reviewed_turn(1),
                "provider_code": "gemini",
                "requested_model": "gemini-3.5-flash",
                "model_invoked": True,
                "runtime_plan": {
                    "provider_code": "gemini",
                    "requested_model": "gemini-3.5-flash",
                    "actual_model": "gemini-3.5-flash",
                    "fallback_used": False,
                },
            }
            state_path.write_text(
                json.dumps(
                    {
                        "name": "switch campaign",
                        "provider_code": "gemini",
                        "requested_model": "gemini-3.5-flash",
                        "initial_provider_code": "gemini",
                        "initial_requested_model": "gemini-3.5-flash",
                        "runtime_transitions": [],
                        "history": [
                            {"role": "user", "content": "first"},
                            {"role": "assistant", "content": "answer"},
                        ],
                        "turns": [old_turn],
                    }
                ),
                encoding="utf-8",
            )

            def fake_run_turn(_prompt: str, **kwargs: object) -> dict[str, object]:
                history = kwargs.get("history")
                assert isinstance(history, list)
                history.extend(
                    (
                        {"role": "user", "content": "second"},
                        {"role": "assistant", "content": "second answer"},
                    )
                )
                return {
                    "turn": 2,
                    "user": "second",
                    "answer": "second answer",
                    "success": True,
                    "model_invoked": True,
                    "visible_answer_conflicts_with_tool_data": False,
                    "unsupported_profit_claim": False,
                    "runtime_plan": {
                        "provider_code": "gemini",
                        "requested_model": "gemini-3-flash-preview",
                        "actual_model": "gemini-3-flash-preview",
                        "fallback_used": False,
                    },
                }

            with patch(
                "AI.processors.orders_live_human_eval_cli._run_turn",
                side_effect=fake_run_turn,
            ):
                result = run_turn(
                    state_path=state_path,
                    artifact_path=artifact_path,
                    provider_code="gemini",
                    model="gemini-3-flash-preview",
                    prompt="second",
                    selection_reason="quota continuation",
                    review_previous_status="pass",
                    review_previous_notes="directly reviewed",
                    switch_runtime=True,
                    switch_reason="exact model quota exhausted",
                    client_override=object(),
                )

            self.assertTrue(result.get("success"))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(state.get("history") or []), 4)
            self.assertEqual(state.get("requested_model"), "gemini-3-flash-preview")
            transitions = state.get("runtime_transitions") or []
            self.assertEqual(len(transitions), 1)
            self.assertEqual(transitions[0].get("effective_turn"), 2)
            self.assertEqual(
                transitions[0].get("history_message_count_before_switch"),
                2,
            )
            turns = state.get("turns") or []
            self.assertEqual(turns[0].get("requested_model"), "gemini-3.5-flash")
            self.assertTrue(turns[0].get("exact_model_responded"))
            self.assertEqual(
                (turns[0].get("human_review") or {}).get("status"),
                "accepted",
            )
            self.assertEqual(turns[1].get("requested_model"), "gemini-3-flash-preview")
            self.assertTrue(turns[1].get("exact_model_responded"))
            self.assertEqual(
                (turns[1].get("runtime_transition") or {}).get("from_model"),
                "gemini-3.5-flash",
            )
            transition = turns[1].get("runtime_transition") or {}
            self.assertTrue(transition.get("history_state_hash_before_switch"))
            self.assertEqual(
                transition.get("history_state_hash_before_switch"),
                transition.get("history_state_hash_at_runtime_start"),
            )
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertTrue(artifact.get("runtime_transition_integrity_complete"))


if __name__ == "__main__":
    unittest.main()
