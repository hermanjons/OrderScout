"""Replay actual source-bound projections while keeping explicit proof boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from AI.processors import response_verifier, task_runtime
from AI.processors.session_state import AgentSessionState, AgentTaskStep


def captured(filename):
    return json.loads((Path(__file__).parent / 'fixtures' / filename).read_text(encoding='utf-8'))


def test_actual_delivered_report_does_not_restore_fields_removed_from_the_requested_projection():
    fixture = captured('attachment_deepseek_delivery_projection.json')
    state = AgentSessionState.from_dict(fixture['state_projection'])
    interpretation = fixture['interpretation']
    assert 'sku' in interpretation['direct_output_fields'] and 'sku' not in interpretation['requested_fields']
    original = state.to_dict()
    result = task_runtime.run_existing_observation_read_turn(fixture['prompt'],
        interpretation=interpretation, session_state=state)
    assert result.success, result.data
    assert all(value in result.data['answer'] for value in ('pilot-sales.json', 'TRY', 'USD', '3 veri satırı'))
    assert 'sıfıra çevrilmedi' in result.data['answer']
    assert 'şu anki varlığı yeniden kontrol edilmedi' in result.data['answer']
    assert result.data['tool_names'] == []
    for key in ('completed_steps', 'action_history', 'pending_actions'):
        assert result.data['state'][key] == original[key]


def test_actual_native_quantity_per_order_fallback_names_its_dimension_instead_of_a_model_id():
    state = AgentSessionState.from_dict(captured('business_glm_quantity_per_order_labels.json')['state_projection'])
    calculations = response_verifier.verified_derived_calculations(state)
    assert sum(row.get('result_kind') == 'quantity_per_order' for row in calculations) == 2
    candidate = response_verifier.project_fallback_response(state, '')
    candidate += '\n\n' + task_runtime._cross_business_safe_summary(response_verifier.response_evidence_projection(state))
    checked = response_verifier.verify_response_projection(candidate, state, source='constructed_regression_candidate')
    assert checked.success, checked.data
    assert candidate.count('Sipariş başına ortalama adet') == 2
    wrong = candidate.replace('Sipariş başına ortalama adet', 'Hesaplanan sonuç')
    checked = response_verifier.verify_response_projection(wrong, state)
    assert not checked.success
    assert any(code.startswith('derived_calculation_quantity_per_order_label_missing')
               for code in checked.data['response_verification']['reason_codes'])


def test_actual_attachment_metadata_is_the_scope_of_its_exact_pending_report():
    fixture = captured('attachment_deepseek_pending_scope_projection.json')
    state = AgentSessionState.from_dict(fixture['state_projection'])
    original = state.to_dict()
    result = task_runtime.run_existing_observation_read_turn(fixture['prompt'],
        interpretation=fixture['interpretation'], session_state=state)
    assert result.success, result.data
    assert all(value in result.data['answer'] for value in ('pilot-sales.json', '3 satır', 'TRY', 'USD'))
    assert result.data['tool_names'] == []
    for key in ('goal', 'active_domain', 'pending_actions', 'action_history', 'completed_steps'):
        assert result.data['state'][key] == original[key]
    state.pending_actions[0]['summary'] += ' altered'
    result = task_runtime.run_existing_observation_read_turn(fixture['prompt'],
        interpretation=fixture['interpretation'], session_state=state)
    assert not result.success and result.data['tool_names'] == []


def test_actual_goal_evaluator_sees_existing_child_bindings_and_keeps_private_inputs_hidden():
    from AI.processors.tools import available_tools
    fixture = captured('child_deepseek_pending_bindings_projection.json')
    state = AgentSessionState.from_dict(fixture['state_projection'])
    child = state.completed_steps[0]
    state.completed_steps = [child]
    state.remaining_steps = [AgentTaskStep(index=i+2, step_id=row['id'],
        operation_candidates=[row['operation_id']], arguments=deepcopy(row['arguments']),
        depends_on=row['depends_on'], objective=row.get('objective'), prompt=row.get('objective') or '')
        for i, row in enumerate(state.active_entities['task_plan']['step_specs'][1:])]
    state.remaining_steps[0].arguments['apiKey'] = 'NEVER-DISCLOSE-THIS-KEY'
    observation = next(row for row in state.observations if row.observation_id in child.observation_ids)
    prompt = task_runtime._goal_evaluation_prompt(state, child, observation,
        operation_candidates=available_tools(), max_steps=12)
    assert '"$from_step": "step_1"' in prompt
    assert 'tool_result.artifact_refs[0].artifact_id' in prompt
    assert 'NEVER-DISCLOSE-THIS-KEY' not in prompt


def test_actual_saved_workflow_cannot_claim_it_is_still_unpersisted_or_awaiting_approval():
    fixture = captured('schedule_glm_saved_workflow_contradiction.json')
    state = AgentSessionState.from_dict(fixture['state_projection'])
    assert response_verifier._has_verified_execute(state) == (True, True)
    assert state.status == 'complete' and not state.pending_actions
    for candidate in (fixture['actual_model_answer'], fixture['actual_visible_answer']):
        checked = response_verifier.verify_response_projection(candidate, state)
        assert not checked.success
        assert 'executed_action_claimed_pending' in checked.data['response_verification']['reason_codes']
    safe_policy = ('Pilot Stok İncelemesi yönergesi kaydedildi ve doğrulandı. '
                   'Her çalıştırmada güncel stok okunacak; gelecekteki her dosya oluşturma '
                   'işlemi ayrıca o çalışmanın güncel onayına sunulacak.')
    checked = response_verifier.verify_response_projection(safe_policy, state)
    assert checked.success, checked.data
    projected = task_runtime._final_answer_with_execute_evidence(fixture['actual_model_answer'], state)
    assert 'onayinizi bekliyor' not in task_runtime._normalized(projected)
    assert 'kaydedilmedi' not in task_runtime._normalized(projected)
    from AI.processors.business_agent_acceptance_cli import validate_business_turn
    event = next(row for row in state.action_history if row['phase'] == 'execute')
    turn = {'success': True, 'answer': fixture['actual_visible_answer'],
            'execute': {'success': True, 'data': {'state': state.to_dict(), 'execute': {
                'verified': True, 'verify': event['verify'], 'executed': True}}}}
    problems = validate_business_turn(turn, {'phase': 'approve', 'effect_kind': 'workflow_save'}, model='unused')
    assert 'executed_action_claimed_pending' in problems


def test_actual_local_business_summary_does_not_require_unrequested_product_rows_or_web():
    fixture = captured('business_glm_local_research_projection.json')
    state = AgentSessionState.from_dict(fixture['state_projection'])
    checked = response_verifier.verify_response_projection(fixture['actual_repair_text'], state)
    assert checked.success, checked.data


def test_actual_read_only_child_projects_canonical_stock_values_without_orders_revenue_keys():
    fixture = captured('child_deepseek_stock_amount_projection.json')
    state = AgentSessionState.from_dict(fixture['state_projection'])
    checked = response_verifier.verify_response_projection(fixture['actual_repair_text'], state)
    assert checked.success, checked.data
    wrong_currency = fixture['actual_repair_text'].replace('30.00 USD', '30.00 TRY')
    assert wrong_currency != fixture['actual_repair_text']
    checked = response_verifier.verify_response_projection(wrong_currency, state)
    assert not checked.success
    assert 'cross_stock_value_currency_pair_missing' in checked.data['response_verification']['reason_codes']
    state.completed_steps[0].status = 'failed'
    checked = response_verifier.verify_response_projection(fixture['actual_repair_text'], state)
    assert not checked.success
    assert 'amount_evidence_missing' in checked.data['response_verification']['reason_codes']


@pytest.mark.parametrize('requirement', ['record_rows', 'public_research'])
def test_explicit_record_rows_and_public_research_still_require_their_actual_sources(requirement):
    fixture = captured('business_glm_local_research_projection.json')
    state = AgentSessionState.from_dict(deepcopy(fixture['state_projection']))
    interpretation = state.active_entities['turn_interpretation']
    contract = interpretation['semantic_contract']
    if requirement == 'record_rows':
        interpretation['request_shape'] = contract['request_shape'] = 'record_list'
        interpretation['direct_output_fields'] = ['item_sales_rows']
        expected = 'item_sales_report_evidence_missing'
    else:
        interpretation['information_source'] = contract['information_source'] = 'public_web'
        expected = 'opened_web_source_evidence_missing'
    checked = response_verifier.verify_response_projection(fixture['actual_repair_text'], state)
    assert not checked.success
    assert expected in checked.data['response_verification']['reason_codes']


def test_actual_pending_file_currency_question_uses_the_exact_prepared_source_without_tools():
    fixture = captured('attachment_glm_currency_projection.json')
    state = AgentSessionState.from_dict(fixture['state_projection'])
    result = task_runtime.run_existing_observation_read_turn(fixture['prompt'],
        interpretation=fixture['interpretation'], session_state=state)
    assert result.success, result.data
    assert 'TRY' in result.data['answer'] and 'USD' in result.data['answer']
    assert result.data['tool_names'] == []
    assert result.data['state']['pending_actions'] == state.to_dict()['pending_actions']
    assert result.data['state']['goal'] == state.goal


def test_actual_unprepared_delivery_cannot_close_an_action_goal_or_claim_completion():
    state = AgentSessionState.from_dict(captured('child_deepseek_unprepared_delivery.json')['state_projection'])
    assert state.status == 'complete' and not state.pending_actions and not state.action_history
    assert task_runtime._unmet_goal_obligations(state) == ['requested_artifact_preparation_missing']
    state.status = 'running'
    task_runtime._complete_state_if_idle(state)
    assert state.status == 'failed'
    assert state.active_entities['goal_progress']['complete'] is False
    assert state.active_entities['goal_progress']['reason'] == 'requested_artifact_preparation_missing'


def test_stock_child_record_projection_uses_stock_rows_and_never_borrows_order_context():
    fixture = captured('child_deepseek_stock_records_projection.json')
    state = AgentSessionState.from_dict(fixture['state_projection'])
    checked = response_verifier.verify_response_projection(fixture['actual_repair_text'], state)
    assert not checked.success
    reasons = checked.data['response_verification']['reason_codes']
    assert 'full_order_context_evidence_missing' not in reasons
    assert 'stock_record_projection_missing:name' in reasons
    candidate = response_verifier.project_fallback_response(state, '')
    assert all(value in candidate for value in ('PILOT-KUPA', 'PILOT-FILTRE', 'PILOT-BOS', 'TRY', 'USD')), candidate
    checked = response_verifier.verify_response_projection(candidate, state, source='constructed_regression_candidate')
    assert checked.success, checked.data
    state.active_entities['turn_interpretation']['semantic_contract'] = {'entity': 'order'}
    assert not response_verifier._stock_detail_rows(state)
    checked = response_verifier.verify_response_projection(candidate, state)
    assert not checked.success
    assert 'full_order_context_evidence_missing' in checked.data['response_verification']['reason_codes']


def test_local_existing_delivery_followup_never_infers_public_web_from_the_word_source():
    fixture = captured('schedule_glm_local_delivery_followup.json')
    state = AgentSessionState.from_dict(fixture['state_projection'])
    assert 'web_sources' not in response_verifier.requested_response_fields(state)
    result = task_runtime.run_existing_observation_read_turn(fixture['prompt'],
        interpretation=fixture['interpretation'], session_state=state)
    assert result.success, result.data
    assert result.data['tool_names'] == []


def test_actual_formatted_comparisons_are_valid_but_omitted_native_stock_and_finance_remain_rejected():
    fixture = captured('business_glm_formatted_comparison_projection.json')
    state = AgentSessionState.from_dict(fixture['state_projection'])
    checked = response_verifier.verify_response_projection(fixture['actual_repair_text'], state)
    reasons = checked.data['response_verification']['reason_codes']
    assert not any(code.startswith('comparison_boolean_projection_mismatch') for code in reasons), reasons
    assert not checked.success
    assert 'cross_stock_value_omitted' in reasons
    assert 'cross_stock_value_currency_pair_missing' in reasons
    evidence = response_verifier.response_evidence_projection(state)
    assert evidence['cross_business_read']['observed_domains'] == ['finance', 'stock']
    # Constructed repair, clearly separate from the original live answer.
    candidate = fixture['actual_repair_text'] + '\n\n' + task_runtime._cross_business_safe_summary(evidence)
    checked = response_verifier.verify_response_projection(candidate, state, source='constructed_regression_candidate')
    assert checked.success, checked.data


@pytest.mark.parametrize('bad_relation', ['3.000 < 800 → doğru', '3.000 > 800 → yanlış', '3.000 > 800 → doğru değil'])
def test_localized_boolean_relation_preserves_operator_and_truth(bad_relation):
    fixture = captured('business_glm_formatted_comparison_projection.json')
    state = AgentSessionState.from_dict(fixture['state_projection'])
    candidate = fixture['actual_repair_text'].replace('3.000 > 800 → doğru', bad_relation)
    assert candidate != fixture['actual_repair_text']
    candidate += '\n\n' + task_runtime._cross_business_safe_summary(response_verifier.response_evidence_projection(state))
    checked = response_verifier.verify_response_projection(candidate, state)
    assert not checked.success
    assert 'comparison_boolean_projection_mismatch:3' in checked.data['response_verification']['reason_codes']
