from __future__ import annotations

from unittest.mock import patch

import pytest

from AI.processors.business_agent_acceptance_cli import ObservedCloudClient, finalize_campaign_source_evidence


def test_final_text_and_repair_are_retained_as_original_wire_responses_without_prompts():
    rows = []
    responses = ["Original candidate: 3 orders; 3000 TRY.\n", "Original repaired candidate: 2 orders; 800 TRY.\n"]
    received = []

    class Client:
        model_name = "regression/model"
        resource_plan = {"requested_model": "regression/model", "actual_model": "regression/model", "fallback_used": False}
        def invoke_final_text(self, prompt):
            received.append(prompt)
            return responses[len(received) - 1]

    observed = ObservedCloudClient(Client(), rows.append)
    assert observed.invoke_final_text("PRIVATE FIRST PROMPT") == responses[0]
    assert observed.invoke_final_text("PRIVATE REPAIR PROMPT") == responses[1]
    assert [row["response"] for row in rows] == responses
    assert [row["method"] for row in rows] == ["invoke_final_text", "invoke_final_text"]
    assert all(row["response_received"] and not row["fallback_used"] for row in rows)
    assert all("prompt" not in row for row in rows)
    assert "PRIVATE" not in str(rows)


@pytest.mark.parametrize("status", ["automated_checks_passed", "failed", "running"])
def test_final_source_change_invalidates_even_a_single_or_last_phase_campaign(status):
    artifact = {"status": status, "source_snapshot": {"fingerprint": "original"}}
    with patch("AI.processors.business_agent_acceptance_cli._source_snapshot", return_value={
        "fingerprint": "changed", "missing_requested_sources": [], "files": [{"path": "actual/source.py", "sha256": "different"}],
    }):
        assert not finalize_campaign_source_evidence(artifact)
    assert artifact["status"] == "source_changed_restart_required"
    assert artifact["status_before_source_recheck"] == status
    assert artifact["source_snapshot_unchanged"] is False
    assert artifact["end_source_snapshot"]["fingerprint"] == "changed"


def test_missing_registered_source_cannot_pass_despite_equal_fingerprint():
    artifact = {"status": "automated_checks_passed", "source_snapshot": {"fingerprint": "same"}}
    with patch("AI.processors.business_agent_acceptance_cli._source_snapshot", return_value={
        "fingerprint": "same", "missing_requested_sources": ["missing/test.py"], "files": [],
    }):
        assert not finalize_campaign_source_evidence(artifact)
    assert artifact["status"] == "source_changed_restart_required"


def test_frozen_final_source_preserves_actual_campaign_outcome():
    artifact = {"status": "automated_checks_passed", "source_snapshot": {"fingerprint": "same"}}
    with patch("AI.processors.business_agent_acceptance_cli._source_snapshot", return_value={
        "fingerprint": "same", "missing_requested_sources": [], "files": [],
    }):
        assert finalize_campaign_source_evidence(artifact)
    assert artifact["status"] == "automated_checks_passed"
    assert artifact["source_snapshot_unchanged"] is True
