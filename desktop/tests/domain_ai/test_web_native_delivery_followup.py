"""A real approved research XLSX can be explained without reopening the file."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from AI.processors import observation_context, task_runtime
from AI.processors.session_state import AgentSessionState


def captured():
    data = json.loads((Path(__file__).parent / 'fixtures' / 'web_native_delivery_followup.json').read_bytes())
    return data, AgentSessionState.from_dict(data['approved_state'])


def test_actual_native_web_export_delivery_uses_exact_recorded_readback_and_opened_source():
    data, state = captured()
    before = state.to_dict()
    current = task_runtime.interpret_agent_turn(data['followup_prompt'], session_state=state,
        planner_client=lambda _: json.dumps(data['response']))
    assert current.success and current.data['operation_policy'] == 'existing_observations_only', current.data
    result = task_runtime.run_existing_observation_read_turn(data['followup_prompt'],
        interpretation=current.data, session_state=state)
    assert result.success, result.data
    assert result.data['tool_names'] == []
    answer = result.data['answer']
    assert 'Excel raporu onayından sonra oluşturuldu' in answer
    assert 'xlsx' in answer and 'hücreleri' in answer and 'kaynak okuma zamanı' in answer
    assert 'developers.trendyol.com/docs/ortak-etiket-barkod-talebi-createcommonlabel' in answer
    assert 'dosyanın şu anki varlığı yeniden kontrol edilmedi' in answer
    assert 'Sayısal değerler kaynaktan aynen aktarıldı' not in answer
    for key in ('pending_actions', 'action_history', 'completed_steps', 'last_tool_results'):
        assert state.to_dict()[key] == before[key]


@pytest.mark.parametrize('change', ['observation', 'research_hash', 'snapshot', 'literal_binding', 'dependency',
                                  'source_status', 'source_wrapper', 'export_hash', 'approval'])
def test_drifted_or_unapproved_web_export_never_claims_verified_delivery(change):
    _, state = captured()
    read = state.completed_steps[0]
    report = next(row for row in state.completed_steps if row.tool_names == ['web.research_report'])
    if change == 'observation':
        report.result_data['tool_result']['research_snapshot']['observations'][0]['relevant_text'] = 'invented'
    elif change == 'research_hash':
        report.result_data['tool_result']['research_snapshot']['content_hash'] = '0' * 64
    elif change == 'snapshot':
        report.result_data['tool_result']['report_snapshot']['sheets'][0]['rows'][0][1] = 'invented'
    elif change == 'literal_binding':
        report.arguments['web_observations'] = deepcopy(report.result_data['tool_result']['research_snapshot']['observations'])
    elif change == 'dependency':
        report.depends_on = []
    elif change == 'source_status':
        read.verification_status = 'unknown'
    elif change == 'source_wrapper':
        read.result_data['tool_result']['fresh_read'] = True
    elif change == 'export_hash':
        next(row for row in state.last_tool_results if row['tool_names'] == ['execute_approved_operation'])['data']['verify']['file_sha256'] = '0' * 64
    else:
        state.action_history = []
    assert observation_context.verified_export_report_answer(state) == ''
