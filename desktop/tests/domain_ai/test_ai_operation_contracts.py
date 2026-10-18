from __future__ import annotations

import unittest

from AI.processors.agent import _agent_tool_operation_metadata, _agent_tool_result_envelope
from AI.processors.manual_capabilities import find_manual_capability
from AI.processors.operation_runtime import operation_coverage_report
from AI.processors.operation_policy import AgentOperationPolicy, build_approval_action, prepare_result
from AI.processors.tools import AgentTool
from Feedback.processors.pipeline import Result


class TestAiOperationContracts(unittest.TestCase):
    def test_manual_orders_capability_exposes_complete_operation_metadata(self) -> None:
        capability = find_manual_capability("orders.change_order_cargo_provider")
        self.assertIsNotNone(capability)

        metadata = capability.operation_metadata()

        self.assertEqual(metadata.owner_domain, "orders")
        self.assertEqual(metadata.effect_class, "external_mutation")
        self.assertEqual(metadata.risk_level, "R2")
        self.assertEqual(metadata.approval_policy, "prepare_then_confirm")
        self.assertIn("order", " ".join(metadata.record_ref_types))
        self.assertTrue(metadata.supports_prepare)
        self.assertTrue(metadata.supports_verify)

    def test_prepare_result_embeds_shared_contract_and_envelope(self) -> None:
        policy = AgentOperationPolicy(
            domain="labels",
            tool="labels.create.prepare",
            action_type="labels.create",
        )
        action = build_approval_action(
            policy=policy,
            title="Etiket",
            summary="İki kayıt",
            arguments={},
            rows=[{"order_number": "A"}, {"order_number": "B"}],
        )

        result = prepare_result(policy=policy, message="Hazır", action=action)

        self.assertTrue(result.success)
        self.assertEqual(action["operation_metadata"]["risk_level"], "R1")
        self.assertEqual(
            result.data["operation_result"]["status"],
            "pending_approval",
        )
        self.assertEqual(
            result.data["operation_result"]["invariant_problems"],
            [],
        )

    def test_read_tool_uses_same_metadata_and_result_envelope(self) -> None:
        tool = AgentTool(
            name="orders.ready_to_ship",
            description="Read ready orders",
            parameters={"type": "object", "properties": {}},
            handler=lambda **_kwargs: Result.ok("ok", data={"count": 7}),
            domain="orders",
            read_only=True,
            action_type="read",
        )

        metadata = _agent_tool_operation_metadata(tool)
        envelope = _agent_tool_result_envelope(
            tool,
            message="7 records",
            data={"count": 7},
            approval_required=False,
        )

        self.assertEqual(metadata.effect_class, "read")
        self.assertEqual(metadata.approval_policy, "none")
        self.assertEqual(envelope["status"], "completed")
        self.assertEqual(envelope["data"]["count"], 7)
        self.assertEqual(envelope["invariant_problems"], [])

    def test_manual_inventory_has_no_invalid_operation_contract(self) -> None:
        report = operation_coverage_report()

        self.assertEqual(report["operation_contract_total"], report["manual_total"])
        self.assertEqual(report["operation_contract_valid_total"], report["manual_total"])
        self.assertEqual(report["operation_contract_invalid_total"], 0)
        self.assertEqual(report["operation_contract_problems"], [])
        orders = report["domains"]["orders"]
        self.assertEqual(
            len(orders["operation_contract_ids"]),
            orders["total"],
        )


if __name__ == "__main__":
    unittest.main()
