"""Captured cloud failures retain historical evidence and public-read authority."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from AI.processors import task_runtime
from AI.processors.tools import available_tools


def case(name):
    return json.loads((Path(__file__).parent / 'fixtures' /
                       'live_source_binding_and_public_read.json').read_bytes())['cases'][name]


def test_actual_public_document_read_reaches_web_plan_without_label_prepare_authority():
    data = case('public-reference-deepseek-2')
    interpreted = task_runtime.interpret_agent_turn(data['prompt'],
        planner_client=lambda _: json.dumps(data['responses'][0]))
    assert interpreted.success and interpreted.data['valid'], interpreted.data
    current = interpreted.data
    assert (current['mode'], current['intent_kind'], current['domain']) == ('inspect', 'data_read', 'web')
    assert not any('prepare' in correction for correction in current['semantic_corrections'])
    ids, meta = task_runtime._domain_task_plan('web', data['prompt'],
        turn_interpretation=current, max_steps=8,
        planner_client=lambda _: json.dumps(data['responses'][1]))
    assert ids, meta
    assert [row['operation_id'] for row in meta['step_specs']] == ['web.open']
    assert meta['step_specs'][0]['arguments']['url'].startswith('https://developers.trendyol.com/')


@pytest.mark.parametrize('response_index', [1, 2])
def test_actual_historical_source_plan_repair_gets_exact_complete_wrapper_bindings(response_index):
    data = case('business-glm-4')
    bad = data['responses'][response_index]
    good = deepcopy(bad)
    by_id = {row['id']: row for row in good['steps']}
    for row in good['steps']:
        args = json.loads(row['arguments_json'])
        for source in args.get('sources') or []:
            source['operation_id'] = by_id[source['source_step_id']]['operation_id']
            source['result']['path'] = 'tool_result'
        row['arguments_json'] = json.dumps(args)
    calls = []
    def model(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return json.dumps(bad)
        assert 'required_source_bindings' in prompt
        assert 'SourceBindingContract' in prompt
        assert 'tool_result.result ile historical wrapper/receipt' in prompt
        return json.dumps(good)
    ids, meta = task_runtime._domain_task_plan('general', data['prompt'],
        turn_interpretation=data['interpretation'], max_steps=24, planner_client=model)
    assert len(calls) == 2 and meta['domain_plan_repair']['applied'], meta
    assert ids == [row['id'] for row in good['steps']]
    specs = {row['id']: row for row in meta['step_specs']}
    for row in specs.values():
        for source in row['arguments'].get('sources') or []:
            assert source['operation_id'] == specs[source['source_step_id']]['operation_id']
            assert source['result']['path'] == 'tool_result'
    # The original model graph was rejected; validation must never execute it.
    diagnostics = meta['domain_plan_repair']['initial_diagnostics']
    assert any(row.get('required_source_bindings') for row in diagnostics)
    first = next(row for row in diagnostics if row['step_id'] == 'step_7')
    assert first['required_source_bindings'][0] == {
        'source_step_id': 'step_1', 'operation_id': 'artifacts.read',
        'result': {'$from_step': 'step_1', 'path': 'tool_result'}}


def test_repeated_historical_source_wrapper_stripping_stays_rejected():
    data = case('business-glm-4')
    bad = data['responses'][2]
    calls = []
    def model(prompt):
        calls.append(prompt)
        return json.dumps(bad)
    ids, meta = task_runtime._domain_task_plan('general', data['prompt'],
        turn_interpretation=data['interpretation'], max_steps=24, planner_client=model)
    assert len(calls) == 2 and not ids
    assert not meta['domain_plan_repair']['applied']
    assert meta['domain_plan_repair']['repair_errors']


def test_direct_source_boundary_still_rejects_wrong_operation_and_stripped_wrapper():
    data = case('business-glm-4')
    for raw in data['responses'][1:]:
        diagnostics = []
        accepted, rejected = task_runtime._validate_direct_plan_specs('general',
            task_runtime._planner_step_specs(raw), data['prompt'], allowed_operations=available_tools(),
            max_steps=12, authorization_context=data['interpretation'], validation_diagnostics=diagnostics)
        assert not accepted and {'step_7', 'step_8'}.issubset(rejected)
        assert diagnostics
