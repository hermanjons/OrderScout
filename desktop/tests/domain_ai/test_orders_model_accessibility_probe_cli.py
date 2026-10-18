from __future__ import annotations

import unittest
from unittest.mock import patch

from AI.processors import orders_model_accessibility_probe_cli as probe_cli


class _ProbeClient:
    def __init__(self, *, response: str = "", error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.resource_plan: dict[str, object] = {}

    def __call__(self, _prompt: str) -> str:
        if self.error is not None:
            self.resource_plan = {
                "requested_model": "model-a",
                "actual_model": "",
                "model_invocation_attempted": True,
                "model_invoked": False,
                "any_model_response_received": False,
                "final_model_response_received": False,
                "model_response_count": 0,
                "invocation_error_reason": "http_429",
                "error_category": "quota",
                "quota_scope": "model",
                "status_code": 429,
                "model_fallback_allowed": True,
                "fallback_blocked_reason": "",
                "retry_after_seconds": 17,
                "normalized_error_history": [
                    {
                        "provider_code": "gemini",
                        "category": "quota",
                        "retryable": True,
                        "quota_scope": "model",
                        "status_code": 429,
                        "safe_message": "Model quota is temporarily unavailable.",
                        "model_fallback_allowed": True,
                        "retry_after_seconds": 17,
                    }
                ],
                "invocation_contract_history": ["structured_output"],
                "invocation_outcome_history": [
                    {
                        "contract": "structured_output",
                        "requested_model": "model-a",
                        "actual_model": "",
                        "response_received": False,
                        "error_reason": "http_429",
                        "fallback_used": False,
                        "error_category": "quota",
                        "quota_scope": "model",
                        "status_code": 429,
                        "model_fallback_allowed": True,
                        "fallback_blocked_reason": "",
                        "retry_after_seconds": 17,
                        "normalized_error_history": [
                            {
                                "provider_code": "gemini",
                                "category": "quota",
                                "retryable": True,
                                "quota_scope": "model",
                                "status_code": 429,
                                "safe_message": "Model quota is temporarily unavailable.",
                                "model_fallback_allowed": True,
                                "retry_after_seconds": 17,
                            }
                        ],
                        "fallback_attempts": [],
                    }
                ],
            }
            raise self.error
        self.resource_plan = {
            "requested_model": "model-a",
            "actual_model": "model-a",
            "model_invocation_attempted": True,
            "model_invoked": True,
            "any_model_response_received": True,
            "final_model_response_received": True,
            "model_response_count": 1,
            "invocation_contract_history": ["structured_output"],
            "invocation_outcome_history": [
                {
                    "contract": "structured_output",
                    "requested_model": "model-a",
                    "actual_model": "model-a",
                    "response_received": True,
                    "error_reason": "",
                    "fallback_used": False,
                }
            ],
        }
        return self.response


class TestOrdersModelAccessibilityProbeCli(unittest.TestCase):
    def test_success_records_exact_model_and_accessibility_status(self) -> None:
        client = _ProbeClient(response="ERİŞİLEBİLİR")
        with patch.object(
            probe_cli,
            "_build_exact_client",
            return_value=(client, {}, False),
        ):
            payload = probe_cli.probe_models(
                provider="gemini",
                models=["model-a"],
                timeout=5,
            )

        row = payload["records"][0]
        self.assertTrue(row["accessible"])
        self.assertEqual(row["actual_model"], "model-a")
        self.assertEqual(row["accessibility_status"], "accessible")
        self.assertEqual(payload["summary"]["accessible"], 1)

    def test_quota_failure_preserves_normalized_scope_without_secret_fields(
        self,
    ) -> None:
        client = _ProbeClient(
            error=RuntimeError(
                "429 url=https://provider.invalid?api_key=super-secret"
            )
        )
        with patch.object(
            probe_cli,
            "_build_exact_client",
            return_value=(client, {}, False),
        ):
            payload = probe_cli.probe_models(
                provider="gemini",
                models=["model-a"],
                timeout=5,
            )

        row = payload["records"][0]
        self.assertFalse(row["accessible"])
        self.assertEqual(row["accessibility_status"], "quota_limited")
        self.assertEqual(row["quota_scope"], "model")
        self.assertEqual(row["status_code"], 429)
        self.assertEqual(row["retry_after_seconds"], 17)
        self.assertEqual(row["invocation_outcome_count"], 1)
        self.assertNotIn("super-secret", str(payload))
        self.assertEqual(payload["summary"]["quota_limited"], 1)


if __name__ == "__main__":
    unittest.main()
