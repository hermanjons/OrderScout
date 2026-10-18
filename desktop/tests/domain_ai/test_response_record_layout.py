from __future__ import annotations

import json

import pytest

from AI.processors import response_verifier
from AI.processors.response_layout import presentation_numeric_text, record_answer_blocks, response_layout_receipt
from AI.processors.session_state import AgentSessionState, AgentTaskStep


def record_state(count=48):
    contexts = []
    for index in range(count):
        suffix = chr(65 + index // 26) + chr(65 + index % 26)
        contexts.append({
            "order": {"order_number": f"ORD-LAYOUT-{suffix}", "status": "ReadyToShip", "cargo_provider": "Aras"},
            "items": [{"product_name": f"Urun {suffix}", "quantity": 1}],
            "returns": [],
        })
    state = AgentSessionState(goal="Siparisleri sira ve siparis numarasi, urun ve kargoyla listele.", active_domain="orders", status="complete")
    state.active_entities["turn_interpretation"] = {
        "mode": "inspect", "domain": "orders", "intent_kind": "data_read",
        "request_shape": "record_list", "identifier_display": "ordinal",
        "requested_fields": ["order_number", "item", "cargo"],
        "semantic_contract": {"entity": "order", "metric": "list", "status_codes": ["ReadyToShip"],
                              "record_scope": "all_matching", "projection": ["order_number", "item", "cargo"]},
    }
    state.completed_steps = [AgentTaskStep(
        index=1, prompt=state.goal, status="completed", verification_status="observed",
        tool_names=["orders.full_context"],
        result_data={"tool_result": {"contexts": contexts, "filters": {"statuses": ["ReadyToShip"]},
                                     "count": count, "total_count": count, "listed_count": count, "truncated": False,
                                     "order_numbers": [c["order"]["order_number"] for c in contexts]}},
    )]
    return state, contexts


def table_answer(contexts, *, ordinal_heading="#"):
    return "\n".join([
        f"| {ordinal_heading} | Siparis | Urun | Kargo |", "| --- | --- | --- | --- |",
        *[f"| {i} | {c['order']['order_number']} | {c['items'][0]['product_name']} | Aras |"
          for i, c in enumerate(contexts, 1)],
    ])


@pytest.mark.parametrize("count,heading", [(7, "Sıra"), (48, "#")])
def test_table_ordinals_are_layout_not_business_values(count, heading):
    state, contexts = record_state(count)
    answer = table_answer(contexts, ordinal_heading=heading)
    result = response_verifier.verify_response_projection(answer, state, source="test_model_candidate")
    assert result.success, result.data
    assert response_layout_receipt(answer)["table_ordinal_rows"] == count


def test_equal_number_elsewhere_is_not_exempted_by_a_table_ordinal():
    state, contexts = record_state()
    result = response_verifier.verify_response_projection(
        table_answer(contexts) + "\nEk tutar: 33 TRY.", state, source="test_model_candidate",
    )
    assert not result.success
    assert "ungrounded_number:33" in result.data["response_verification"]["reason_codes"]


def test_numeric_data_column_is_not_an_ordinal_column():
    answer = "| Tutar | Aciklama |\n| --- | --- |\n| 1 | A |\n| 2 | B |\n"
    assert presentation_numeric_text(answer) == answer
    assert "-74" in presentation_numeric_text("1. Deger: -74\n2. Oran: 17.37%")


def test_item_presence_elsewhere_cannot_prove_its_record_binding():
    state, contexts = record_state(7)
    correct = table_answer(contexts)
    wrong = correct.replace("Urun AA", "TEMP").replace("Urun AG", "Urun AA").replace("TEMP", "Urun AG")
    result = response_verifier.verify_response_projection(wrong, state, source="test_model_candidate")
    assert not result.success
    assert any(code.startswith("item_projection_missing:ORD-LAYOUT-AA") for code in result.data["response_verification"]["reason_codes"])


def test_detached_detail_blocks_and_missing_ordinals_fail_projection():
    state, contexts = record_state(7)
    detached = "\n".join(f"{i}. {c['order']['order_number']} | kargo: Aras" for i, c in enumerate(contexts, 1))
    detached += "\n\nUrunler:\n" + "\n".join(c["items"][0]["product_name"] for c in contexts)
    assert not response_verifier.verify_response_projection(detached, state, source="test_fallback").success
    no_ordinals = "\n".join(f"- {c['order']['order_number']} | {c['items'][0]['product_name']} | Aras" for c in contexts)
    result = response_verifier.verify_response_projection(no_ordinals, state, source="test_fallback")
    assert not result.success
    assert any(code.startswith("requested_order_ordinal_missing:") for code in result.data["response_verification"]["reason_codes"])


def test_fallback_and_model_evidence_keep_items_inside_their_order_rows():
    state, contexts = record_state()
    projected = response_verifier.response_evidence_projection(state)
    assert len(projected["order_rows"]) == len(contexts)
    assert projected["order_rows"][32]["ordinal"] == 33
    assert projected["order_rows"][32]["items"] == [{"product_name": contexts[32]["items"][0]["product_name"]}]
    assert "quantity" not in json.dumps(projected["order_rows"])
    answer = response_verifier.project_fallback_response(state, "")
    blocks = record_answer_blocks(answer, [c["order"]["order_number"] for c in contexts])
    assert all(block["ordinal"] == i and c["items"][0]["product_name"] in block["text"]
               for i, (block, c) in enumerate(zip(blocks, contexts), 1))
    verified = response_verifier.verify_response_projection(answer, state, source="test_fallback")
    assert verified.success, verified.data
