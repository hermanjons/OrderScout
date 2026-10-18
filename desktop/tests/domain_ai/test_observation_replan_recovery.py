"""Actual failed observations recover through bounded, validated model plans."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from AI.processors import task_runtime
from AI.processors.session_state import AgentSessionState


def case(name):
    return json.loads((Path(__file__).parent / 'fixtures' /
                       'agentic_observation_recovery_evidence.json').read_bytes())['cases'][name]


def test_actual_source_copy_report_does_not_require_a_model_invented_calculation_tag():
    data = json.loads((Path(__file__).parent / 'fixtures' /
                      'attachment_unrequested_calculation_projection.json').read_bytes())
    result = task_runtime.interpret_agent_turn(data['prompt'],
        planner_client=lambda _: json.dumps(data['response']))
    assert result.success and result.data['valid'], result.data
    assert 'calculation' not in result.data['requested_fields']
    assert 'calculation' not in result.data['direct_output_fields']
    assert 'unrequested_artifact_calculation_projection_removed' in result.data['semantic_corrections']
    # An explicitly requested calculation still cannot disappear into a copy report.
    required = task_runtime.interpret_agent_turn('Dosyadaki revenue / quantity oranını hesapla ve Excel raporuna ekle.',
        planner_client=lambda _: json.dumps(data['response']))
    if required.data.get('valid') is True:
        contract = required.data.get('semantic_contract') or {}
        assert contract.get('deferred_calculation') or contract.get('derived_calculation') or contract.get('derived_calculations')
        assert 'unrequested_artifact_calculation_projection_removed' not in required.data['semantic_corrections']


def test_actual_skipped_web_node_id_is_rejected_and_repaired_to_a_runnable_new_node():
    data = json.loads((Path(__file__).parent / 'fixtures' / 'web_skipped_plan_recovery.json').read_bytes())
    state = AgentSessionState.from_dict(data['state_projection'])
    state.status = 'running'
    state.remaining_steps = []
    original = [row.to_dict() for row in state.completed_steps]
    bad = data['response']
    good = deepcopy(bad)
    good['steps'][0]['id'] = 'fresh_search_recovery'
    calls = []
    def model(prompt):
        calls.append(prompt)
        return json.dumps(bad if len(calls) == 1 else good)
    last = state.completed_steps[-1]
    observation = next(row for row in state.observations if row.observation_id in last.observation_ids)
    result = task_runtime._reevaluate_goal_after_observation(state, last, observation,
        planner_client=model, max_steps=8, max_replans=4)
    assert len(calls) == 2 and result['schema_repair']['applied']
    assert state.remaining_steps[0].step_id == 'fresh_search_recovery'
    assert 'fresh_search_recovery' in {row.step_id for row in state.active_goal_plan().ready_steps()}
    assert state.active_goal_plan().step('step_2').status == 'skipped'
    assert [row.to_dict() for row in state.completed_steps] == original


def test_pending_attachment_table_metadata_does_not_require_unrelated_order_sales_evidence():
    data = case('attachment')
    state = AgentSessionState.from_dict(data['state_projection'])
    original = state.to_dict()
    assert 'item_sales_rows' in data['interpretation']['requested_fields']
    result = task_runtime.run_existing_observation_read_turn(data['prompt'],
        interpretation=data['interpretation'], session_state=state)
    assert result.success, result.data
    assert all(value in result.data['answer'] for value in ('pilot-sales.json', '3 satır', 'TRY', 'USD'))
    assert result.data['tool_names'] == []
    assert result.data['state']['pending_actions'] == original['pending_actions']


def test_raw_quantity_subtraction_cannot_become_a_strict_per_order_ratio_hypothesis():
    data = case('business')
    initial = next(row for row in data['responses'] if row.get('mode') == 'inspect')
    interpreted = task_runtime.interpret_agent_turn(data['prompt'],
        planner_client=lambda _: json.dumps(initial))
    assert interpreted.success, interpreted.data
    deferred = interpreted.data['semantic_contract']['deferred_calculation']
    assert deferred['cardinality_authority'] == 'provisional_initial_interpretation'
    assert not deferred['expected_calculations']
    assert 'invalid_initial_formula_dimensions_provisional' in interpreted.data['semantic_corrections']


@pytest.mark.parametrize('valid_repair', [True, False])
def test_rejected_observation_plan_gets_one_schema_repair_and_never_executes_during_review(valid_repair):
    data = case('child')
    state = AgentSessionState.from_dict(data['state_projection'])
    state.status = 'running'
    before = [step.to_dict() for step in state.completed_steps]
    bad = next(row for row in data['responses'] if row.get('decision') == 'replan')
    repaired = deepcopy(bad)
    builder, prepare = repaired['steps']
    builder['depends_on'] = ['step_2']
    builder['expected_evidence'] = ['report_snapshot']
    prepare['expected_evidence'] = ['action']
    # Native source arrays cannot be recast as string-valued stock totals.
    arguments = json.loads(builder['arguments_json'])
    arguments['sheets'][0]['columns'][-1] = {'key': 'stock_value', 'label': 'Stok Değeri',
                                            'source_path': 'stock_value', 'data_type': 'number'}
    builder['arguments_json'] = json.dumps(arguments)
    calls = []
    def model(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return json.dumps(bad)
        assert 'Exact validation diagnostics' in prompt
        assert 'binding_source_not_dependency' in prompt
        assert 'result.top_balances' in prompt
        return json.dumps(repaired if valid_repair else bad)
    last = state.completed_steps[-1]
    observation = next(row for row in state.observations if row.observation_id in last.observation_ids)
    result = task_runtime._reevaluate_goal_after_observation(state, last, observation,
        planner_client=model, max_steps=12, max_replans=4)
    assert len(calls) == 2
    assert 'error_type' not in result['schema_repair'], result
    assert result['schema_repair']['applied'] is valid_repair, result
    assert [step.to_dict() for step in state.completed_steps] == before
    assert not state.pending_actions
    assert bool(state.remaining_steps) is valid_repair
    if valid_repair:
        assert [step.operation_candidates for step in state.remaining_steps] == [
            ['reports.build_snapshot'], ['reports.xlsx.prepare']]
