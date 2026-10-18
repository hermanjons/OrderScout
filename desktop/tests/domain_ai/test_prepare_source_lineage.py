"""Prepare reviewers see proven parent/child provenance, without source cells."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from AI.processors import semantic_verifier
from AI.processors.session_state import AgentSessionState
from AI.processors.tools import available_tools


def captured():
    fixture = json.loads((Path(__file__).parent / 'fixtures' /
                          'child_deepseek_report_lineage_denial.json').read_bytes())
    state = AgentSessionState.from_dict(fixture['state_projection'])
    return state, state.completed_steps[-1]


def test_actual_child_report_review_receives_parent_and_proven_child_origin_without_cells():
    state, step = captured()
    delegate = state.completed_steps[0].result_data['tool_result']
    child_id = delegate['child_task_id']
    assert child_id != state.session_id
    seen = []
    def review(prompt):
        seen.append(prompt)
        assert 'Actual source lineage evidence' in prompt
        evidence = json.loads(prompt.split('Actual source lineage evidence: ', 1)[1].split('\n', 1)[0])
        assert evidence['parent_task_id'] == state.session_id
        sources = evidence['sources']
        assert len(sources) == 1
        assert sources[0]['delegated_child_task_id'] == child_id
        assert sources[0]['read_by_parent_step_id'] == 'step_2'
        assert sources[0]['delegated_by_step_id'] == 'step_1'
        assert sources[0]['fresh_read_by_parent'] is False
        assert 'PILOT-KUPA' not in prompt and 'Pilot Kupa' not in prompt
        assert 'capability_token' not in prompt
        return json.dumps({'verdict': 'allow', 'objective_aligned': True,
                           'domain_aligned': True, 'unwanted_effect': False,
                           'reason': 'Exact completed child origin and parent historical read are proven.'})
    checked = semantic_verifier.verify_plan_step_semantics(state, step,
        available_tools()['reports.xlsx.prepare'], verifier_client=review)
    assert checked.success, checked.data
    assert len(seen) == 1
    assert checked.data['semantic_verification']['evidence']['source_lineage']['sources'][0]['delegated_child_task_id'] == child_id


@pytest.mark.parametrize('change', ['child_id', 'artifact_id', 'artifact_hash', 'result_hash',
                                   'failed_delegate', 'unverified_read', 'missing_dependency', 'snapshot_source_hash'])
def test_drifted_or_unlinked_receipts_never_claim_a_proven_child_source(change):
    state, step = captured()
    delegate, read, builder = state.completed_steps[:3]
    if change in {'child_id', 'artifact_id', 'artifact_hash', 'result_hash'}:
        result = delegate.result_data['tool_result']
        if change == 'child_id':
            result['child_task_id'] = 'other-task'
        else:
            result['artifact_refs'][0][change] = 'forged-value'
    elif change == 'failed_delegate':
        delegate.status = 'failed'
    elif change == 'unverified_read':
        read.verification_status = 'unknown'
    elif change == 'missing_dependency':
        read.depends_on = []
    else:
        builder.result_data['tool_result']['report_snapshot']['metadata']['source_receipts'][0]['source_result_hash'] = '0' * 64
    evidence = semantic_verifier._prepare_source_lineage_evidence(state, step)
    assert not any(row.get('delegated_child_task_id') for row in evidence.get('sources', []))
