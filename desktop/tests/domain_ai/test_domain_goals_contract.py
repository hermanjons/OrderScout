from __future__ import annotations

import unittest
from pathlib import Path

from AI.processors.operation_runtime import operation_coverage_report


class DomainGoalsContractTests(unittest.TestCase):
    def test_primary_ecommerce_domains_have_binding_goals_matching_runtime_coverage(self) -> None:
        root = Path(__file__).resolve().parents[2]
        shared = root / "Core/docs/domain_goals_contract.md"
        self.assertTrue(shared.exists(), shared)
        shared_text = shared.read_text(encoding="utf-8")
        for required in (
            "Status: `binding`",
            "Manuel UI ile AI aynı",
            "Provider/model seçimi domain davranışını değiştirmez",
            "Ortak Kapanma Yasağı",
        ):
            self.assertIn(required, shared_text)

        report = operation_coverage_report()
        expected = {
            "stock": ("Stock", "stock_agentic_parity_matrix.md"),
            "finance": ("Finance", "finance_agentic_parity_matrix.md"),
            "listing": ("Listing", "listing_agentic_parity_matrix.md"),
            "logistics": ("Logistics", "logistics_agentic_parity_matrix.md"),
            "marketplaces": ("Marketplaces", "marketplaces_agentic_parity_matrix.md"),
            "labels": ("Labels", "labels_agentic_parity_matrix.md"),
        }
        task_evidence = {
            "stock": "test_stock_task_runtime_preserves_read_scope_then_executes_verifies_and_audits_local_write",
            "finance": "test_finance_task_runtime_prepares_approves_executes_verifies_and_audits_local_write",
            "listing": "test_listing_task_runtime_keeps_local_cache_write_separate_from_external_mutation_and_verifies_db",
            "logistics": "test_logistics_task_runtime_preserves_read_scope_then_executes_verifies_and_audits_local_write",
            "marketplaces": "test_marketplaces_task_runtime_preserves_read_scope_then_executes_verifies_and_audits_local_write",
        }
        domains = report.get("domains") or {}
        for domain, (folder, parity_name) in expected.items():
            with self.subTest(domain=domain):
                goals_path = root / folder / "docs/goals.md"
                parity_path = root / "AI/docs" / parity_name
                self.assertTrue(goals_path.exists(), goals_path)
                self.assertTrue(parity_path.exists(), parity_path)
                text = goals_path.read_text(encoding="utf-8")
                parity_text = parity_path.read_text(encoding="utf-8")
                coverage = domains.get(domain) or {}
                self.assertIn("../../Core/docs/domain_goals_contract.md", text)
                self.assertIn("../../AI/docs/goals.md", text)
                self.assertIn(parity_name, text)
                self.assertIn(f"read: {coverage.get('read_total')}", text)
                self.assertIn(f"write: {coverage.get('write_total')}", text)
                self.assertIn(f"total: {coverage.get('total')}", text)
                self.assertIn(f"read: {coverage.get('read_total')}", parity_text)
                self.assertIn(f"write: {coverage.get('write_total')}", parity_text)
                self.assertIn(f"total: {coverage.get('total')}", parity_text)
                self.assertIn(
                    "AI.processors.operation_runtime.operation_coverage_report",
                    parity_text,
                )
                for capability_id in coverage.get("capability_ids") or []:
                    self.assertIn(capability_id, parity_text)
                self.assertIn("## Agentic Kabul", text)
                self.assertIn("## Güncel Durum", text)
                self.assertTrue(
                    any(
                        status in text
                        for status in (
                            "`verified_baseline`",
                            "`partial`",
                            "`open`",
                            "`deferred_external`",
                            "`not_applicable`",
                        )
                    ),
                    "Domainin güncel kabul durumu görünür olmalı.",
                )
                if domain != "labels":
                    self.assertIn(
                        task_evidence[domain],
                        text,
                        "Local task approval/resume kabul kaniti goals.md icinde gorunur olmali.",
                    )
                    self.assertTrue(
                        any(status in text for status in ("`partial`", "`open`", "`deferred_external`")),
                        "Açık veya ertelenmiş domain işi dürüstçe görünür olmalı.",
                    )


if __name__ == "__main__":
    unittest.main()
