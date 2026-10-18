from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Feedback.processors.pipeline import Result

from AI.processors import orders_stage_bulk_cargo_acceptance_cli as stage_cli


class TestOrdersStageMarketplaceAcceptanceCli(unittest.TestCase):
    def test_shared_stage_executor_writes_and_verifies_redacted_package(self) -> None:
        action = {
            "action_type": "orders.change_order_cargo_provider",
            "execute_enabled": True,
            "selected_record_count": 1,
        }
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            stage_cli.operation_runtime,
            "execute_staging_marketplace_evidence_run",
            return_value=Result.ok(
                "executed",
                close_dialog=False,
                data={"verify": {"verified": True, "rows": [{}]}},
            ),
        ) as execute, patch.object(
            stage_cli.operation_runtime,
            "attach_staging_marketplace_external_proof",
            return_value=Result.ok("attached", close_dialog=False),
        ) as attach, patch.object(
            stage_cli.operation_runtime,
            "staging_marketplace_evidence_manifest",
            return_value=Result.ok("manifest", close_dialog=False),
        ) as manifest, patch.object(
            stage_cli.operation_runtime,
            "verify_staging_marketplace_evidence_manifest",
            return_value=Result.ok("verified", close_dialog=False),
        ) as verify_manifest:
            result = stage_cli._execute_prepared_stage_action(
                action,
                expected_action_type="orders.change_order_cargo_provider",
                exact_count=1,
                seller_id="2738",
                output_dir=tmp,
                slug="single-cargo",
                staging_reason="Stage-only acceptance.",
                mutation_summary="Remote state matched.",
            )
            proof = json.loads(
                Path(result["external_proof_path"]).read_text(encoding="utf-8")
            )

        self.assertTrue(result["passed"])
        self.assertEqual(result["staging_account_id"], "2738")
        self.assertTrue(proof["verified"])
        self.assertTrue(proof["staging_account_only"])
        self.assertEqual(proof["staging_account_id"], "2738")
        self.assertNotIn("order_number", proof)
        self.assertNotIn("claim_id", proof)
        execute.assert_called_once()
        attach.assert_called_once()
        manifest.assert_called_once()
        verify_manifest.assert_called_once()

    def test_shared_stage_executor_rejects_scope_mismatch_before_runtime(self) -> None:
        action = {
            "action_type": "orders.change_order_cargo_provider",
            "execute_enabled": True,
            "selected_record_count": 2,
        }
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            stage_cli.operation_runtime,
            "execute_staging_marketplace_evidence_run",
        ) as execute:
            with self.assertRaisesRegex(
                RuntimeError,
                "exact record scope",
            ):
                stage_cli._execute_prepared_stage_action(
                    action,
                    expected_action_type="orders.change_order_cargo_provider",
                    exact_count=1,
                    seller_id="2738",
                    output_dir=tmp,
                    slug="single-cargo",
                    staging_reason="Stage-only acceptance.",
                    mutation_summary="Remote state matched.",
                )

        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
