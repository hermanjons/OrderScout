"""Domain failures and argument repairs remain observations for the selected model."""
import json
from unittest.mock import patch

from sqlmodel import Session

from AI.processors import model_loop
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result
from Stock.models.models import StockItem
from Stock.processors import item_queries
from tests.support.db_case import IsolatedDbTestCase


class Model:
    resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}

    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.prompts = []

    def invoke_tools(self, prompt, *, tools):
        self.prompts.append(prompt)
        decision = next(self.decisions)
        return json.dumps(decision) if isinstance(decision, dict) else decision


def query(**arguments):
    return {"mode": "tool", "tool": "stock.search", "arguments": arguments}


class TestDomainToolRoundtrip(IsolatedDbTestCase):
    def setUp(self):
        super().setUp()
        with Session(get_engine(self.db_path)) as session:
            session.add(StockItem(sku="EXACT-17", name="Test Stock"))
            session.commit()

    def test_model_can_repair_arguments_before_the_real_domain_read(self):
        answer = "EXACT-17 kartını buldum; mevcut bakiye 0 adet."
        model = Model([query(query="EXACT-17", limit=0), query(query="EXACT-17", limit=1), answer])
        with patch.object(item_queries, "query_items_with_balances", wraps=item_queries.query_items_with_balances) as read:
            result = model_loop.run_model_loop("EXACT-17 stok kartını bul", client=model, db_name=self.db_path)
        assert result.success, result.data
        assert result.data["answer"] == answer
        assert read.call_count == 1
        records = result.data["direct_tool_results"]
        assert not records[0]["success"] and "arguments.limit:minimum" in records[0]["data"]["argument_problems"]
        assert records[1]["success"] and records[1]["data"]["items"][0]["sku"] == "EXACT-17"
        assert "arguments.limit:minimum" in model.prompts[1]
        assert "EXACT-17" in model.prompts[2] and '"balance":0.0' in model.prompts[2]

    def test_domain_failure_and_retry_are_returned_to_model_without_a_canned_answer(self):
        failure_message = "Stok değerleme kaynağı geçici olarak okunamadı."
        failure = Result.fail(failure_message, data={"reason": "valuation_unavailable", "retryable": True})
        original = item_queries.query_items_with_balances
        def read(**arguments):
            if not hasattr(read, "failed"):
                read.failed = True
                return failure
            return original(**arguments)
        answer = "İlk okumada kaynak hatası vardı. Tekrar denedim ve EXACT-17 kartını buldum."
        model = Model([query(query="EXACT-17"), query(query="EXACT-17"), answer])
        with patch.object(item_queries, "query_items_with_balances", side_effect=read):
            result = model_loop.run_model_loop("EXACT-17 kartına bak; geçici hata olursa tekrar dene",
                                               client=model, db_name=self.db_path)
        assert result.success and result.data["answer"] == answer
        records = result.data["direct_tool_results"]
        assert [row["success"] for row in records] == [False, True]
        assert records[0]["data"]["reason"] == "valuation_unavailable"
        assert failure_message in model.prompts[1]
        assert "valuation_unavailable" in model.prompts[1]
