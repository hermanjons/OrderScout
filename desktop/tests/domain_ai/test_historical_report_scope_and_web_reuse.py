"""Actual report failures keep period meaning and authentic opened sources."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from AI.processors import task_runtime, semantic_verifier
from AI.processors.session_state import AgentSessionState
from AI.processors.tools import available_tools
from AI.processors.business_acceptance_evidence import validate_fixture_observations, validate_general_report_sources


def cases():
    return json.loads((Path(__file__).parent / 'fixtures' /
                       'historical_report_scope_and_web_reuse.json').read_bytes())


def repaired_web_plan():
    data = cases()['web']
    plan = deepcopy(data['model_plan'])
    args = json.loads(plan['steps'][1]['arguments_json'])
    args['web_observations'] = [{'$from_step': 'step_1', 'path': 'tool_result.result.web_observation'}]
    plan['steps'][1]['arguments_json'] = json.dumps(args)
    return data, plan


def test_real_historical_web_export_graph_is_repaired_without_new_search_or_fabricated_observation():
    data, repaired = repaired_web_plan()
    calls = []
    def model(prompt):
        calls.append(prompt)
        if len(calls) > 1:
            assert 'available_web_observation_bindings' in prompt
            assert 'WebObservationBindingContract' in prompt
        return json.dumps(data['model_plan'] if len(calls) == 1 else repaired)
    ids, meta = task_runtime._domain_task_plan('web', data['prompt'], planner_client=model,
        max_steps=24, turn_interpretation=data['interpretation'], typed_context=data['typed_context'])
    assert len(calls) == 2 and meta['domain_plan_repair']['applied'], meta
    assert meta['historical_opened_web_sources_reused']
    assert ids == ['step_1', 'step_2', 'step_3']
    assert [row['operation_id'] for row in meta['step_specs']] == [
        'artifacts.read', 'web.research_report', 'web.research_report_xlsx.prepare']
    assert not meta.get('semantic_compiler_reconciled')


def test_public_metadata_or_an_unused_grant_cannot_substitute_for_bound_report_source():
    data, repaired = repaired_web_plan()
    specs = task_runtime._planner_step_specs(repaired)
    assert not task_runtime._web_report_uses_granted_observations(specs, [])
    assert task_runtime._web_report_uses_granted_observations(specs, data['typed_context'])
    specs[0]['arguments']['artifact_id'] = 'unknown'
    assert not task_runtime._web_report_uses_granted_observations(specs, data['typed_context'])
    specs[0]['arguments']['artifact_id'] = json.loads(repaired['steps'][0]['arguments_json'])['artifact_id']
    specs[1]['arguments']['web_observations'] = []
    assert not task_runtime._web_report_uses_granted_observations(specs, data['typed_context'])


def test_literal_web_source_and_snapshot_cannot_cross_the_native_plan_boundary():
    data, repaired = repaired_web_plan()
    for mutate in ('observation', 'snapshot'):
        raw = deepcopy(repaired if mutate == 'snapshot' else data['model_plan'])
        if mutate == 'snapshot':
            args = json.loads(raw['steps'][-1]['arguments_json'])
            args['report_snapshot'] = {'snapshot_id': 'invented', 'content_hash': '0' * 64}
            raw['steps'][-1]['arguments_json'] = json.dumps(args)
        specs, rejected = task_runtime._validate_direct_plan_specs('web', task_runtime._planner_step_specs(raw),
            data['prompt'], allowed_operations=available_tools(), max_steps=24,
            authorization_context=data['interpretation'])
        assert not specs and rejected


def test_actual_swapped_finance_sheets_reach_prepare_reviewer_with_actual_periods_without_source_cells():
    state = AgentSessionState.from_dict(cases()['business']['state'])
    step = state.completed_steps[-1]
    seen = []
    def reviewer(prompt):
        seen.append(prompt)
        evidence = json.loads(prompt.split('Actual source lineage evidence: ', 1)[1].split('\n', 1)[0])
        sources = {row['source_id']: row for row in evidence['sources']}
        current_label = sources['fin_last7']
        prior_label = sources['fin_prev7']
        assert current_label['observed_period']['period_label'] == '2026-10-02..2026-10-08'
        assert prior_label['observed_period']['period_label'] == '2026-10-09..2026-10-15'
        assert current_label['report_projections'][0]['sheet'] == 'Finans Son 7 Gun'
        assert prior_label['report_projections'][0]['sheet'] == 'Finans Onceki 7 Gun'
        assert 'reject current/prior period swaps' in prompt
        assert 'PILOT-KUPA' not in prompt and 'capability_token' not in prompt
        return json.dumps({'verdict': 'deny', 'objective_aligned': False, 'domain_aligned': True,
                          'unwanted_effect': False, 'reason': 'Finance sheet names invert actual source periods.'})
    checked = semantic_verifier.verify_plan_step_semantics(state, step,
        available_tools()['reports.xlsx.prepare'], verifier_client=reviewer)
    assert not checked.success and len(seen) == 1


def test_actual_historical_business_sources_prove_coverage_without_claiming_sheet_meaning_acceptance():
    data = cases()['business']
    turn = {'raw_turn_data': {'state': data['state']}}
    checked = validate_fixture_observations(turn, data['fixture'])
    assert checked['passed'], checked
    sources = validate_general_report_sources(turn)
    assert sources['passed'], sources
    bound = sources['proof'][0]['bound_sources']
    assert all(row['operation_id'] == 'artifacts.read' and row['historical_sources'] for row in bound)
    assert all(row['historical_sources'][0]['fresh_read'] is False for row in bound)
    # Exact native source coverage cannot accept the actual swapped sheet labels;
    # the separate prepare-review regression above rejects that meaning.


@pytest.mark.parametrize('change', ['payload', 'hash', 'time', 'freshness', 'origin', 'source_receipt'])
def test_changed_historical_receipt_cannot_prove_fixture_values(change):
    data = cases()['business']
    turn = {'raw_turn_data': {'state': deepcopy(data['state'])}}
    read = turn['raw_turn_data']['state']['completed_steps'][0]['result_data']['tool_result']
    if change == 'payload':
        read['result']['total_gross_amount'] = 999
    elif change == 'hash':
        read['artifact']['result_hash'] = '0' * 64
    elif change == 'time':
        read['observed_at'] = '2026-10-01T00:00:00+00:00'
    elif change == 'freshness':
        read['fresh_read'] = True
    elif change == 'origin':
        read['artifact']['origin']['operation_id'] = 'orders.summary'
    else:
        read['historical_source_receipts'] = []
    result = validate_fixture_observations(turn, data['fixture'])
    assert not result['passed'] and not result['checks']['orders_recent_revenue_try']
