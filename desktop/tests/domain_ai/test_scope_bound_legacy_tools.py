from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from AI.processors.agent import AgentDecision, run_agent_turn
from AI.processors.tools import AgentTool, available_tools
from Feedback.processors.pipeline import Result


@pytest.mark.parametrize("operation_id", ["analysis.calculate", "analysis.table", "reports.build_snapshot", "reports.xlsx.prepare", "files.list", "files.read"])
@pytest.mark.parametrize("forged_inputs", [False, True])
def test_legacy_tool_execution_cannot_bypass_source_and_session_authorization(operation_id, forged_inputs):
    handler = Mock(side_effect=AssertionError("Scope-bound handler must never execute on legacy path"))
    tool = replace(available_tools()[operation_id], handler=handler)
    arguments = {} if not forged_inputs else {
        "session_id": "another-session", "attachment_id": "att_" + "0" * 32,
        "sources": [{"source_id": "fake", "source_step_id": "never-completed", "operation_id": "files.read",
                     "result": {"rows": [{"profit": 99999}]}}],
        "report_snapshot": {"source_domain": "reports", "report_type": "reports.observations", "content_hash": "fake"},
    }
    decision = Result.ok("Chosen legacy call", data={"decision": AgentDecision(mode="tool", tool_name=operation_id,
                                                                               arguments=arguments, source="llm")})
    with patch("AI.processors.agent.available_tools", return_value={operation_id: tool}), \
            patch("AI.processors.agent.choose_action", return_value=decision):
        result = run_agent_turn("Use the chosen source operation", db_name="unused-legacy-boundary.db")
    assert not result.success and result.data["reason"] == "task_runtime_required", result.data
    assert result.data["tool"] == operation_id and result.data["scope_bound_operation"] is True
    handler.assert_not_called()


def test_pure_catalog_discovery_can_execute_legacy_without_an_unsupported_db_parameter():
    registry = available_tools()
    decision = Result.ok("Chosen catalog call", data={"decision": AgentDecision(
        mode="tool", tool_name="operations.discover", arguments={"domains": ["files"], "limit": 32}, source="llm",
    )})
    with patch("AI.processors.agent.available_tools", return_value=registry), \
            patch("AI.processors.agent.choose_action", return_value=decision):
        result = run_agent_turn("Inspect available operations", db_name="unused-legacy-discovery.db")
    assert result.success, result.message
    assert {row["operation_id"] for row in result.data["tool_result"]["operations"]} == {"files.list", "files.read"}


def test_existing_db_aware_handler_keeps_its_authoritative_db_argument():
    observed = []

    def read(*, db_name, value):
        observed.append((db_name, value))
        return Result.ok("Observed zero", data={"count": value})

    tool = AgentTool(name="fixture.authoritative_read", description="Read the fixture", handler=read,
                     parameters={"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]})
    decision = Result.ok("Chosen read", data={"decision": AgentDecision(mode="tool", tool_name=tool.name,
                                                                         arguments={"value": 0}, source="llm")})
    with patch("AI.processors.agent.available_tools", return_value={tool.name: tool}), \
            patch("AI.processors.agent.choose_action", return_value=decision):
        result = run_agent_turn("Inspect the fixture", db_name="selected-fixture.db")
    assert result.success and result.data["tool_result"]["count"] == 0
    assert observed == [("selected-fixture.db", 0)]
