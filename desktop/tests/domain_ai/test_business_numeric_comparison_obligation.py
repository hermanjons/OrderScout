"""Actual numeric comparisons satisfy provisional goals without inventing booleans."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from AI.processors import task_runtime
from AI.processors.observation_analysis_evidence import verified_observation_calculations
from AI.processors.semantic_verifier import calculation_goal_verification_fingerprint
from AI.processors.session_state import AgentSessionState


def captured_state(filename='business_glm_numeric_comparison_evidence.json'):
    captured = json.loads((Path(__file__).parent / 'fixtures' /
        filename).read_text(encoding='utf-8'))
    assert captured['requested_model'] == captured['actual_model'] == 'z-ai/glm-5.3-flash'
    return AgentSessionState.from_dict(deepcopy(captured['state_projection']))


def test_actual_later_observation_refreshes_the_bound_comparison_before_goal_completion():
    state = captured_state('business_glm_comparison_refresh_evidence.json')
    verified = verified_observation_calculations(state)
    receipt = state.active_entities['calculation_goal_verification']
    assert receipt['allowed'] and receipt['comparison_satisfied']
    assert receipt['evidence_fingerprint'] != calculation_goal_verification_fingerprint(state, verified)
    assert task_runtime._unmet_goal_obligations(state) == ['deferred_source_bound_calculation_missing']
    calls = []
    def verifier(prompt):
        calls.append(prompt)
        if prompt.startswith('OrderScout calculation goal verifier'):
            return json.dumps(receipt['model_verdict'])
        return json.dumps({'decision': 'complete', 'reason': 'Observed current exact sources cover the goal',
                           'steps': [], 'requires_clarification': False, 'clarification': ''})
    observation = next(row for row in reversed(state.observations) if row.success)
    task_runtime._reevaluate_goal_after_observation(state, state.completed_steps[-1], observation,
        planner_client=verifier, max_steps=24, max_replans=4)
    assert sum(prompt.startswith('OrderScout calculation goal verifier') for prompt in calls) == 1
    assert state.active_entities['calculation_goal_verification']['allowed']
    assert task_runtime._unmet_goal_obligations(state) == []


def test_actual_glm_verified_difference_and_ratio_complete_the_provisional_comparison():
    state = captured_state()
    verified = verified_observation_calculations(state)
    receipt = state.active_entities['calculation_goal_verification']
    assert receipt['allowed'] and receipt['comparison_satisfied']
    assert receipt['evidence_fingerprint'] == calculation_goal_verification_fingerprint(state, verified)
    assert {row['result'] for row in verified} == {'2200.00', '3.7500'}
    assert all(row.get('comparison_verified') is not True for row in verified)
    assert task_runtime._unmet_goal_obligations(state) == []


@pytest.mark.parametrize('mutation', ['denied', 'no_comparison', 'unbound_hash', 'boolean_required', 'changed_source'])
def test_numeric_comparison_never_overrides_missing_authority_or_explicit_boolean(mutation):
    state = captured_state()
    receipt = state.active_entities['calculation_goal_verification']
    if mutation == 'denied':
        receipt['allowed'] = False
    elif mutation == 'no_comparison':
        receipt['comparison_satisfied'] = False
    elif mutation == 'unbound_hash':
        receipt['accepted_evidence_hashes'] = ['invented']
    elif mutation == 'boolean_required':
        receipt['requested_result_kinds'] = ['boolean']
    else:
        state.completed_steps[1].result_data['tool_result']['total_gross_amount'] = 3100
    assert task_runtime._unmet_goal_obligations(state) == ['deferred_source_bound_calculation_missing']
