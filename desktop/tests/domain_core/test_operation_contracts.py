from __future__ import annotations

import unittest

from Core.processors.operation_contracts import OperationMetadata, OperationResultEnvelope


class TestOperationContracts(unittest.TestCase):
    def test_effectful_operation_requires_explicit_approval_policy(self) -> None:
        with self.assertRaises(ValueError):
            OperationMetadata(
                name="orders.change_cargo",
                version="1.0",
                owner_domain="orders",
                effect_class="external_mutation",
                risk_level="R2",
                approval_policy="none",
            )

    def test_metadata_round_trip_preserves_discovery_fields(self) -> None:
        metadata = OperationMetadata(
            name="orders.ready_to_ship",
            version="1.0",
            owner_domain="orders",
            effect_class="read",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            record_ref_types=("orders.order",),
            environment_scope=("production", "stage"),
            account_scope="marketplace_account",
            risk_level="R0",
            approval_policy="none",
        )

        restored = OperationMetadata.from_dict(metadata.to_dict())

        self.assertEqual(restored, metadata)

    def test_result_envelope_rejects_selection_count_drift(self) -> None:
        envelope = OperationResultEnvelope(
            operation_name="labels.create",
            operation_version="1.0",
            success=True,
            status="pending_approval",
            record_refs=({"record_id": "A"}, {"record_id": "B"}),
            selected_record_count=2,
            preview_item_count=1,
            execute_input_count=2,
        )

        self.assertEqual(
            envelope.invariant_problems(),
            ["selection_preview_execute_count_mismatch"],
        )


if __name__ == "__main__":
    unittest.main()
