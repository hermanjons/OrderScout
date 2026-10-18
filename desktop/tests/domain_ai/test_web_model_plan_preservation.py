"""Web graph reconciliation preserves the model's validated public queries."""
import json

from AI.processors import task_runtime


def plan(extra_search=False):
    steps = [{'id': 'find_docs', 'operation_id': 'web.search',
              'arguments': {'query': 'Trendyol kargo etiketi barkod', 'limit': 5},
              'depends_on': [], 'objective': 'Find public seller documentation', 'expected_evidence': ['results']}]
    if extra_search:
        steps.extend([
            {'id': 'find_help', 'operation_id': 'web.search',
             'arguments': {'query': 'Trendyol satıcı yardım kargo etiketi', 'limit': 5},
             'depends_on': [], 'objective': 'Find public help', 'expected_evidence': ['results']},
            {'id': 'open_docs', 'operation_id': 'web.open', 'arguments': {'url': {
                '$from_step': 'find_docs', 'path': 'tool_result.primary_url'}},
             'depends_on': ['find_docs'], 'objective': 'Open the actual discovered source',
             'expected_evidence': ['web_observation']},
        ])
    return {'steps': steps}


def test_search_only_reconciliation_keeps_the_authored_query_instead_of_the_whole_user_message():
    goal = 'Trendyol kargo etiketi barkodunu araştır ve kaynağı aç. Özel müşteri verisi gönderme.'
    ids, metadata = task_runtime._domain_task_plan('web', goal,
        planner_client=lambda _: json.dumps(plan()), max_steps=8)
    assert ids and metadata.get('semantic_compiler_reconciled')
    search = next(row for row in metadata['step_specs'] if row['operation_id'] == 'web.search')
    assert search['arguments'] == plan()['steps'][0]['arguments']
    assert 'müşteri' not in search['arguments']['query']
    assert any(row['operation_id'] == 'web.open' for row in metadata['step_specs'])


def test_valid_multi_search_graph_is_not_replaced_by_a_fixed_two_step_template():
    goal = 'Trendyol kargo etiketi barkodunu araştır ve kaynağı aç.'
    authored = plan(extra_search=True)
    ids, metadata = task_runtime._domain_task_plan('web', goal,
        planner_client=lambda _: json.dumps(authored), max_steps=8)
    assert ids == ['find_docs', 'find_help', 'open_docs']
    assert not metadata.get('atomic_web_template')
    assert [row['arguments'] for row in metadata['step_specs']] == [row['arguments'] for row in authored['steps']]
