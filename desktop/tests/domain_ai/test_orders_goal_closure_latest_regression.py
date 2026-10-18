from __future__ import annotations

import json
import hashlib
import os
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from AI.processors import acceptance_manifest, orders_goal_closure_cli
from Feedback.processors.pipeline import Result


class OrdersGoalClosureLatestRegressionTests(unittest.TestCase):
    @staticmethod
    def _desktop_root() -> Path:
        return Path(__file__).resolve().parents[2]

    def _isolated_acceptance_fixture(self, root: Path) -> dict:
        from AI.processors.orders_source_ui_human_recheck_cli import (
            _runtime_source_evidence, validate_source_ui_acceptance_artifact,
        )
        from tests.domain_ai.test_orders_phase8a_acceptance_semantics import (
            _pending_artifact, _v6_quota_runtime,
        )

        docs = root / "desktop/AI/docs"
        docs.mkdir(parents=True)
        guard_path = root / "desktop/tests/domain_ai/test_orders_goal_closure_latest_regression.py"
        guard_path.parent.mkdir(parents=True)
        guard_path.write_bytes(Path(__file__).read_bytes())
        guard = "tests/domain_ai/test_orders_goal_closure_latest_regression.py"
        guards = [guard + "::OrdersGoalClosureLatestRegressionTests::" + name for name in (
            "test_current_runtime_change_and_openrouter_quota_keep_orders_open", "test_manifest_rejects_evidence_hash_drift")]

        fingerprint = _runtime_source_evidence()["fingerprint"]
        current = _pending_artifact()
        current.update({"evidence_contract_version": 6, "runtime_source_fingerprint": fingerprint,
                        "runtime_source_fingerprint_current": fingerprint,
                        "privacy_redaction": {"redacted": True, "original_values_persisted": False, "version": 1}})
        normalized_success = {"error_category": "", "quota_scope": "", "status_code": None,
                              "model_fallback_allowed": None, "fallback_blocked_reason": "",
                              "retry_after_seconds": None, "normalized_error_history": []}
        for turn in current["turns"]:
            turn["runtime"].update(deepcopy(normalized_success))
            for outcome in turn["runtime"]["invocation_outcome_history"]:
                outcome.update(deepcopy(normalized_success))
                outcome["fallback_attempts"] = []
        accepted = validate_source_ui_acceptance_artifact(current, require_fresh_execute=False,
            require_current_runtime_source=True, minimum_turns=4,
            semantic_contract="phase_8a_pending_read_live_revalidation")
        self.assertEqual(accepted, [])
        current["acceptance_validation"] = {"accepted": True, "problems": accepted}
        stale = deepcopy(current)
        stale["runtime_source_fingerprint"] = stale["runtime_source_fingerprint_current"] = "previous-runtime-snapshot"

        quota = deepcopy(current)
        quota.update({"provider_code": "openrouter", "requested_model": "fixture/openrouter-quota-model", "final_status": "open"})
        runtime = _v6_quota_runtime(quota_scope="account")
        runtime["requested_model"] = quota["requested_model"]
        for outcome in runtime["invocation_outcome_history"]:
            outcome["requested_model"] = quota["requested_model"]
            for attempt in outcome["fallback_attempts"]:
                attempt["model"] = quota["requested_model"]
            for error in outcome["normalized_error_history"]:
                error["provider_code"] = "openrouter"
        for error in runtime["normalized_error_history"]:
            error["provider_code"] = "openrouter"
        for turn in quota["turns"]:
            turn.update({"runtime": deepcopy(runtime), "success": False, "turn_outcome": "provider_unavailable",
                         "tool_call": {}, "tool_calls": [], "tool_result": {}, "pending_action": {}, "approval_required": False})
        quota["acceptance_validation"] = {"accepted": False, "problems": ["provider_account_quota"]}

        isolated_appdata = root / "appdata"
        quota_path = isolated_appdata / "OrderScout/stage-acceptance/quota.json"
        quota_path.parent.mkdir(parents=True)
        paths = {"current_slice": docs / "current.json", "stale_pending": docs / "stale.json", "account_quota": quota_path}
        for identity, payload in (("current_slice", current), ("stale_pending", stale), ("account_quota", quota)):
            paths[identity].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        artifacts = [{"id": identity, "kind": "file" if identity == "account_quota" else "source_ui_regression",
                      "path": "%LOCALAPPDATA%/OrderScout/stage-acceptance/quota.json" if identity == "account_quota" else paths[identity].name,
                      "sha256": hashlib.sha256(paths[identity].read_bytes()).hexdigest(),
                      "expect": {"minimum_evidence_contract_version": 6, "minimum_turn_count": 4,
                                 "requested_model": current["requested_model"]}}
                     for identity in paths]
        regression_id = "runtime_and_provider_revalidation_open"
        regression = {"artifact_type": "orders_real_user_regression", "regression_id": regression_id,
                      "status": "open", "observed_at": "2026-10-11T12:00:00Z", "redacted": True,
                      "invariant_failures": [{"id": identity} for identity in ("runtime_source_not_current", "provider_account_quota")],
                      "invariant_resolution_contract": [{"invariant_id": identity, "owner_layer": "AI shared runtime",
                          "bounded_status": "guarded_pending_live_revalidation", "live_acceptance_gate": "phase_8a_pending_read_live_revalidation",
                          "guard_tests": guards} for identity in ("runtime_source_not_current", "provider_account_quota")]}
        (docs / "regression.json").write_text(json.dumps(regression), encoding="utf-8")
        manifest = {"artifact_type": acceptance_manifest.EXPECTED_ARTIFACT_TYPE, "schema_version": 2,
                    "scope_status": acceptance_manifest.EXPECTED_SCOPE_STATUS, "acceptance_status": "open",
                    "closure_ready": False, "current_phase": "current_runtime_and_account_quota_revalidation",
                    "latest_binding_regression_id": regression_id, "current_regression_ids": [regression_id],
                    "current_proven_slice_artifact_ids": ["current_slice"], "current_diagnostic_artifact_ids": ["account_quota"],
                    "historical_baseline_artifact_ids": ["stale_pending"], "open_gates": [{"id": "phase_8a_current_source_ui_semantics"}],
                    "artifacts": artifacts, "regressions": [{"id": regression_id, "status": "open", "guard_tests": guards,
                                                              "current_evidence_ids": ["current_slice", "account_quota"]}]}
        manifest_path = docs / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        item = "phase_8a_pending_read_live_revalidation"
        checklist = {"name": "isolated-runtime-and-quota-closure", "overall_status": "open", "broader_ai_goal_status": "open",
                     "current_focus": "orders_only", "current_orders_scope_required_items": [item],
                     "required_items": [{"id": item, "status": "open", "evidence": ["stale.json", str(quota_path)],
                         "minimum_turns": 4, "require_fresh_execute": False, "require_current_runtime_source": True,
                         "minimum_evidence_contract_version": 6}], "blocking_items": [], "goals_section_audit_required": False,
                     "source_ui_acceptance_validation": {"required": True, "item_ids": [item], "minimum_valid_artifacts_per_item": 2,
                         "minimum_distinct_models_per_item": 2, "required_provider_codes": ["gemini", "openrouter"]},
                     "acceptance_manifest_validation": {"required": True, "manifest": "manifest.json", "require_closure_ready": True},
                     "real_user_regression_validation": {"required": True, "artifacts": ["regression.json"],
                                                         "require_invariant_resolution_contract": True},
                     "domain_runtime_source_app_validation": {"required": False}, "atomic_dry_validation": {"required": False}}
        checklist_path = docs / "checklist.json"
        checklist_path.write_text(json.dumps(checklist), encoding="utf-8")
        return {"manifest_path": manifest_path, "checklist_path": checklist_path, "manifest": manifest,
                "quota_path": quota_path, "quota": quota, "stale_path": paths["stale_pending"],
                "isolated_appdata": isolated_appdata, "regression_id": regression_id}

    def test_current_runtime_change_and_openrouter_quota_keep_orders_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture = self._isolated_acceptance_fixture(Path(tmp_dir))
            # Only this temporary fixture is mapped to LOCALAPPDATA. Historical
            # manifests and actual user evidence are never read or overwritten.
            with patch.dict(os.environ, {"LOCALAPPDATA": str(fixture["isolated_appdata"])}):
                validation = acceptance_manifest.validate_current_acceptance_manifest(fixture["manifest_path"])
                closure = orders_goal_closure_cli.evaluate_orders_goal_closure(checklist_path=fixture["checklist_path"])
            self.assertTrue(validation["valid"], validation)
            self.assertEqual(validation["schema_version"], 2)
            self.assertEqual(validation["artifact_count"], 3)
            self.assertEqual(validation["valid_artifact_count"], 3)
            self.assertEqual(validation["current_proven_slice_artifact_ids"], ["current_slice"])
            self.assertEqual(validation["current_diagnostic_artifact_ids"], ["account_quota"])
            self.assertEqual(validation["scope_status"], "orders_phase_8a_open_ai_goal_open")
            self.assertFalse(validation["closure_ready"])
            self.assertFalse(validation["ready_for_closure"])
            self.assertEqual(validation["open_gate_count"], 1)
            self.assertTrue(closure.success, closure.message)
            data = closure.data
            self.assertFalse(data["ready_to_complete"], data)
            self.assertEqual(data["overall_status"], "open")
            self.assertEqual(data["unresolved_blockers"], [fixture["regression_id"]])
            self.assertIn("unresolved_real_user_regressions", data["problems"])
            self.assertIn("acceptance_manifest_not_ready", data["problems"])
            self.assertTrue(data["acceptance_manifest_validation"]["valid"])
            self.assertFalse(data["acceptance_manifest_validation"]["ready_for_closure"])
            regression = data["real_user_regression_validation"]
            self.assertTrue(regression["valid"], regression)
            self.assertEqual(regression["unresolved_ids"], [fixture["regression_id"]])
            self.assertEqual(regression["artifacts"][0]["invariant_resolution_contract_count"], 2)
            self.assertEqual(regression["artifacts"][0]["invariant_resolution_guard_test_count"], 4)
            source = data["source_ui_evidence_validation"]
            self.assertTrue(source["required"])
            gate = source["items"]["phase_8a_pending_read_live_revalidation"]
            self.assertEqual(gate["minimum_evidence_contract_version"], 6)
            self.assertEqual(gate["minimum_valid_artifacts"], 2)
            self.assertEqual(gate["minimum_distinct_models"], 2)
            self.assertFalse(gate["require_fresh_execute"])
            self.assertTrue(gate["require_current_runtime_source"])
            self.assertEqual(gate["valid_artifact_count"], 0)
            coverage = gate["required_model_coverage"]
            self.assertEqual(set(coverage["required_provider_codes"]), {"gemini", "openrouter"})
            self.assertEqual(coverage["observed_provider_codes"], [])
            self.assertEqual(coverage["observed_models"], [])
            rows = {Path(row["path"]).name: row for row in gate["artifacts"]}
            self.assertIn("runtime_source_not_current", rows["stale.json"]["problems"])
            self.assertNotIn("final_status", rows["stale.json"]["problems"])
            self.assertIn("final_status", rows["quota.json"]["problems"])
            self.assertIn("model_not_proven_invoked", rows["quota.json"]["problems"])
            for row in rows.values():
                self.assertFalse(any(problem.startswith("turn_model_provenance:") for problem in row["problems"]), row)
            quota_runtime = fixture["quota"]["turns"][0]["runtime"]
            self.assertEqual(quota_runtime["quota_scope"], "account")
            self.assertEqual(quota_runtime["status_code"], 429)
            self.assertFalse(quota_runtime["model_fallback_allowed"])
            self.assertEqual(quota_runtime["fallback_blocked_reason"], "provider_quota")
            self.assertEqual(acceptance_manifest.validate_turn_model_provenance(quota_runtime,
                requested_model=fixture["quota"]["requested_model"], require_outcome_history=True,
                require_normalized_error_evidence=True), [])

    def test_verified_staging_campaign_applies_to_current_alias_item(self) -> None:
        campaign_rows = [
            {
                "action_type": action_type,
                "evidence_path": f"{action_type}.json",
                "manifest_path": f"{action_type}.manifest.json",
            }
            for action_type in orders_goal_closure_cli.REQUIRED_ORDERS_STAGING_ACTION_TYPES
        ]
        before = Result.ok(
            "verified",
            data={
                "staging_campaign_verified": True,
                "staging_campaign_evidence": campaign_rows,
                "staging_inputs": {},
            },
        )
        after = Result.ok(
            "open",
            data={
                "ready_to_complete": False,
                "overall_status": "open",
            },
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            checklist_path = Path(tmp_dir) / "checklist.json"
            checklist_path.write_text(
                json.dumps(
                    {
                        "overall_status": "open",
                        "current_orders_scope_required_items": [
                            "stage_bulk_cargo_acceptance"
                        ],
                        "blocking_items": ["stage_bulk_cargo_acceptance"],
                        "next_evidence_needed": [
                            "Complete staging marketplace acceptance."
                        ],
                        "required_items": [
                            {
                                "id": "stage_bulk_cargo_acceptance",
                                "status": "open",
                                "evidence": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(
                orders_goal_closure_cli,
                "evaluate_orders_goal_closure",
                side_effect=(before, after),
            ):
                result = (
                    orders_goal_closure_cli.apply_verified_staging_evidence_to_checklist(
                        checklist_path=checklist_path,
                        staging_evidence_dir=Path(tmp_dir),
                        staging_account_id="2738",
                    )
                )

            self.assertTrue(result.success, result.message)
            updated = json.loads(checklist_path.read_text(encoding="utf-8"))
            item = updated["required_items"][0]
            self.assertEqual(item["status"], "proven")
            self.assertEqual(
                item["verified_action_types"],
                list(
                    orders_goal_closure_cli.REQUIRED_ORDERS_STAGING_ACTION_TYPES
                ),
            )
            self.assertNotIn(
                "stage_bulk_cargo_acceptance",
                updated["blocking_items"],
            )

    @unittest.skipUnless((Path(__file__).resolve().parents[2] / "AI/docs/current_acceptance_manifest.json").is_file(),
                         "Requires a private local acceptance manifest; synthetic contract tests still run.")
    def test_open_manifest_cannot_claim_closure_ready(self) -> None:
        source_path = (
            self._desktop_root() / "AI/docs/current_acceptance_manifest.json"
        )
        manifest = json.loads(source_path.read_text(encoding="utf-8"))
        manifest["closure_ready"] = True

        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = Path(tmp_dir) / "current_acceptance_manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            validation = acceptance_manifest.validate_current_acceptance_manifest(
                manifest_path
            )

        self.assertFalse(validation.get("valid"), validation)
        self.assertIn(
            "closure_ready_open_status",
            validation.get("problems") or [],
        )

    @unittest.skipUnless((Path(__file__).resolve().parents[2] / "AI/docs/live_llm_transcripts/source-ui/orders-agentic-control-plane-real-user-regression-2026-07-19.json").is_file(),
                         "Requires a private local live-service artifact.")
    def test_open_real_user_regression_requires_one_resolution_contract_per_failure(
        self,
    ) -> None:
        root = self._desktop_root()
        checklist_path = root / "AI/docs/orders_agentic_goal_closure_checklist.json"
        source_path = (
            root
            / "AI/docs/live_llm_transcripts/source-ui/"
            "orders-agentic-control-plane-real-user-regression-2026-07-19.json"
        )
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        payload["invariant_resolution_contract"] = list(
            payload.get("invariant_resolution_contract") or []
        )[:-1]

        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact_path = Path(tmp_dir) / "regression.json"
            artifact_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            validation = (
                orders_goal_closure_cli._validate_real_user_regression_evidence(
                    {
                        "_checklist_path": str(checklist_path),
                        "real_user_regression_validation": {
                            "required": True,
                            "require_invariant_resolution_contract": True,
                            "artifacts": [str(artifact_path)],
                        },
                    }
                )
            )

        self.assertFalse(validation.get("valid"), validation)
        self.assertIn(
            "invariant_resolution_contract_ids",
            validation.get("problems") or [],
        )

    @unittest.skipUnless((Path(__file__).resolve().parents[2] / "AI/docs/current_acceptance_manifest.json").is_file(),
                         "Requires a private local acceptance manifest.")
    def test_historical_schema_cannot_validate_as_current_acceptance(self) -> None:
        source_path = (
            self._desktop_root() / "AI/docs/current_acceptance_manifest.json"
        )
        manifest = json.loads(source_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = 1
        manifest["scope_status"] = "orders_milestone_proven_ai_goal_open"

        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = Path(tmp_dir) / "current_acceptance_manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            validation = acceptance_manifest.validate_current_acceptance_manifest(
                manifest_path
            )

        self.assertFalse(validation.get("valid"), validation)
        self.assertIn("schema_version", validation.get("problems") or [])
        self.assertIn("scope_status", validation.get("problems") or [])

    @unittest.skipUnless((Path(__file__).resolve().parents[2] / "AI/docs/agentic_control_plane_inventory_2026-07-20.json").is_file(),
                         "Requires a private local runtime inventory.")
    def test_phase_zero_inventory_records_control_plane_blockers_without_secrets(self) -> None:
        root = self._desktop_root()
        inventory_path = root / "AI/docs/agentic_control_plane_inventory_2026-07-20.json"
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))

        self.assertEqual(
            inventory.get("artifact_type"),
            "orderscout_agentic_control_plane_inventory",
        )
        self.assertEqual(inventory.get("status"), "diagnostic_baseline")
        self.assertTrue(inventory.get("redacted"))
        measurements = inventory.get("measurements") or {}
        self.assertGreaterEqual(measurements.get("registered_tool_count") or 0, 80)
        self.assertGreaterEqual(measurements.get("manual_capability_count") or 0, 170)
        self.assertGreaterEqual(measurements.get("raw_history_order_helper_call_sites") or 0, 1)
        blockers = {
            row.get("id")
            for row in inventory.get("critical_blockers") or []
            if isinstance(row, dict)
        }
        self.assertTrue(
            {
                "regex_first_business_routing",
                "generic_fuzzy_router_in_production_path",
                "raw_history_as_operational_state",
                "template_driven_task_runtime",
                "semantic_verifier_gap",
            }
            <= blockers,
            blockers,
        )
        raw = inventory_path.read_text(encoding="utf-8")
        for forbidden in ("api_secret", "api_key\"", "customer_name", "tracking_number"):
            self.assertNotIn(forbidden, raw.casefold())

    def test_manifest_rejects_evidence_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture = self._isolated_acceptance_fixture(Path(tmp_dir))
            environment = {"LOCALAPPDATA": str(fixture["isolated_appdata"])}
            before = acceptance_manifest.validate_current_acceptance_manifest(fixture["manifest_path"], environ=environment)
            self.assertTrue(before["valid"], before)
            expected = next(row for row in fixture["manifest"]["artifacts"] if row["id"] == "account_quota")
            self.assertTrue(expected["path"].startswith("%LOCALAPPDATA%/"))
            self.assertEqual(expected["sha256"], hashlib.sha256(fixture["quota_path"].read_bytes()).hexdigest())
            # Alter the real evidence file after the reviewed digest was saved.
            # Keep the manifest unchanged; this is content drift, not a missing
            # historical external file or an intentionally incorrect digest.
            changed = deepcopy(fixture["quota"])
            changed["turns"][0]["answer"] = "changed after the recorded evidence digest"
            fixture["quota_path"].write_text(json.dumps(changed), encoding="utf-8")
            validation = acceptance_manifest.validate_current_acceptance_manifest(fixture["manifest_path"], environ=environment)
            artifact = next(row for row in validation["artifact_results"] if row["id"] == "account_quota")
            self.assertFalse(validation["valid"], validation)
            self.assertFalse(validation["ready_for_closure"])
            self.assertFalse(artifact["valid"])
            self.assertEqual(artifact["problems"], ["sha256_mismatch"])
            self.assertEqual(Path(artifact["resolved_path"]), fixture["quota_path"])
            self.assertEqual(validation["valid_artifact_count"], 2)
            self.assertIn("artifact:account_quota", validation["problems"])

    def test_localappdata_reference_is_portable_and_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = Path(tmp_dir) / "manifest.json"
            expected = Path(tmp_dir) / "OrderScout/stage-acceptance/evidence.json"
            resolved = acceptance_manifest.resolve_evidence_path(
                "%LOCALAPPDATA%/OrderScout/stage-acceptance/evidence.json",
                manifest_path=manifest_path,
                environ={"LOCALAPPDATA": tmp_dir},
            )

        self.assertEqual(resolved, expected)

    def test_unresolved_newer_user_failure_overrides_ready_checklist(self) -> None:
        regression = {
            "artifact_type": "orders_real_user_regression",
            "regression_id": "orders_ready_selection_followup_2026_07_15",
            "status": "open",
            "observed_at": "2026-07-15T10:00:00Z",
            "redacted": True,
            "invariant_failures": [
                {"id": "selection_scope_broadened"},
            ],
        }
        checklist = {
            "name": "orders-goal-closure-newer-user-failure-fixture",
            "overall_status": "ready",
            "current_focus": "orders_only",
            "current_orders_scope_required_items": ["selection_scope_guard"],
            "required_items": [
                {
                    "id": "selection_scope_guard",
                    "status": "proven",
                    "evidence": ["older-passing-artifact.json"],
                }
            ],
            "acceptance_manifest_validation": {"required": False},
            "source_ui_acceptance_validation": {"required": False},
            "domain_runtime_source_app_validation": {"required": False},
            "atomic_dry_validation": {"required": False},
            "goals_section_audit_required": False,
            "real_user_regression_validation": {
                "required": True,
                "artifacts": ["latest-regression.json"],
            },
            "blocking_items": [],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            checklist_path = tmp / "checklist.json"
            artifact_path = tmp / "latest-regression.json"
            checklist_path.write_text(
                json.dumps(checklist, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            artifact_path.write_text(
                json.dumps(regression, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            result = orders_goal_closure_cli.evaluate_orders_goal_closure(
                checklist_path=checklist_path
            )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertFalse(data.get("ready_to_complete"), data)
        validation = data.get("real_user_regression_validation") or {}
        self.assertTrue(validation.get("valid"), validation)
        self.assertEqual(
            validation.get("unresolved_ids"),
            ["orders_ready_selection_followup_2026_07_15"],
        )
        self.assertIn("unresolved_real_user_regressions", data.get("problems") or [])
        self.assertIn(
            "orders_ready_selection_followup_2026_07_15",
            data.get("unresolved_blockers") or [],
        )
        next_actions = {row.get("id"): row for row in data.get("next_actions") or []}
        self.assertIn("resolve_latest_real_user_regressions", next_actions)


if __name__ == "__main__":
    unittest.main()
