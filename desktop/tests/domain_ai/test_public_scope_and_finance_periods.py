"""Real source receipts survive public-document and multiple finance reads."""
from copy import deepcopy
import json
from pathlib import Path

from AI.processors import task_runtime, response_verifier, web_research
from AI.processors.session_state import AgentSessionState


def case(name):
    return json.loads((Path(__file__).parent / 'fixtures' /
                       'public_scope_and_finance_periods.json').read_bytes())['cases'][name]


def test_real_public_document_scope_does_not_require_a_private_marketplace_account():
    data = case('public-reference-deepseek-3')
    current = task_runtime.interpret_agent_turn(data['prompt'],
        planner_client=lambda _: json.dumps(data['responses'][0])).data
    assert 'scope' not in current['requested_fields']
    assert current['domain'] == 'web' and current['mode'] == 'inspect'
    state = AgentSessionState.from_dict(data['state'])
    state.active_entities['turn_interpretation'] = current
    state.conversation_turns = []
    answer = data['responses'][2]
    verified = response_verifier.verify_response_projection(answer, state)
    assert verified.success, verified.data
    # Citing a real URL is still insufficient without the actual opened source.
    state.completed_steps = []
    state.last_tool_results = []
    assert not response_verifier.verify_response_projection(answer, state).success


def test_document_article_and_its_links_reach_the_evidence_before_long_navigation():
    menu = ''.join(f'<li><a href="/menu/{i}">Unrelated navigation {i}</a></li>' for i in range(140))
    page = ('<html><head><title>Public service</title></head><body><main><nav>' + menu +
        '</nav><article><header>Site branding</header><h1>Service purpose</h1>'
        '<p>This service requests a document; this page describes its input scope.</p>'
        '<a href="/docs/result">Read the generated document</a></article></main></body></html>')
    result = web_research._html_payload(page.encode(), 'text/html; charset=utf-8', 'https://example.com/docs/service')
    assert result['text'].startswith('Service purpose This service requests a document')
    assert 'Unrelated navigation' not in result['text'] and 'Site branding' not in result['text']
    assert result['links'][0]['url'] == 'https://example.com/docs/result'
    assert len(result['links']) == 100


def test_all_observed_finance_periods_reach_the_independent_assessment_with_separate_currencies():
    data = case('business-glm-5')
    state = AgentSessionState.from_dict(data['state'])
    before = [row.to_dict() for row in state.completed_steps]
    cross = response_verifier.response_evidence_projection(state)['cross_business_read']
    receipts = [row.result_data['tool_result'] for row in state.completed_steps
                if row.status == 'completed' and row.tool_names == ['finance.cashflow_summary']]
    summaries = cross['finance']['summaries']
    assert len(summaries) == len(receipts) == 2
    assert [row['currency_totals'] for row in summaries] == [row['currency_totals'] for row in receipts]
    assert [{r['currency']: r['combined_net'] for r in row['currency_totals']} for row in summaries] == [
        {'TRY': 200.0, 'USD': 20.0}, {'TRY': 0.0}]
    assert summaries[0]['period_label'] != summaries[1]['period_label']
    assert 'no company/account join or bank balance established' in cross['finance']['scope']
    assert [row.to_dict() for row in state.completed_steps] == before


def test_real_business_fallback_retains_authoritative_scope_after_model_rejection():
    data = case('business-glm-5')
    state = AgentSessionState.from_dict(data['state'])
    state.status = 'complete'
    fallback = response_verifier.project_fallback_response(state, task_runtime._fallback_task_final_answer(state))
    assert 'Kapsam: 2738 (TRENDYOL / stage)' in fallback
    result = response_verifier.verify_response_projection(fallback, state)
    assert result.success, result.data


def test_actual_zero_result_web_replan_discloses_every_reserved_skipped_id_and_accepts_fresh_ids():
    data = case('public-web-deepseek-4')
    state = AgentSessionState.from_dict(data['state'])
    state.status = 'running'
    state.remaining_steps = []
    before = [row.to_dict() for row in state.completed_steps]
    last = state.completed_steps[-1]
    observation = next(row for row in state.observations if row.observation_id in last.observation_ids)
    bad = data['responses'][2]
    good = deepcopy(data['responses'][3])
    renames = {row['id']: 'web_retry_' + str(index) for index, row in enumerate(good['steps'])}
    def rename(value):
        if isinstance(value, dict):
            return {key: rename(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rename(item) for item in value]
        return renames.get(value, value) if isinstance(value, str) else value
    for row in good['steps']:
        row['arguments_json'] = rename(json.loads(row['arguments_json']))
    good = rename(good)
    for row in good['steps']:
        row['arguments_json'] = json.dumps(row['arguments_json'])
    calls = []
    def model(prompt):
        calls.append(prompt)
        line = next(line for line in prompt.splitlines() if line.startswith('Reserved immutable step IDs'))
        assert all(identity in line for identity in task_runtime._nonreplaceable_plan_step_ids(state))
        return json.dumps(bad if len(calls) == 1 else good)
    result = task_runtime._reevaluate_goal_after_observation(state, last, observation,
        planner_client=model, max_steps=6, max_replans=4)
    assert len(calls) == 2 and result['schema_repair']['applied'] and result['applied'], result
    assert state.remaining_steps[0].step_id == 'web_retry_0'
    assert 'web_retry_0' in {row.step_id for row in state.active_goal_plan().ready_steps()}
    assert [row.to_dict() for row in state.completed_steps] == before
