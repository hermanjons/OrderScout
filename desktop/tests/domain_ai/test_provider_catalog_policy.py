from __future__ import annotations

import unittest

from AI.processors.provider_catalog_policy import (
    gemini_model_is_verified_free_chat,
    gemini_safe_fallback_models,
    provider_free_model_quality_prior,
    provider_model_access,
)


class ProviderCatalogPolicyTests(unittest.TestCase):
    def test_gemini_unknown_is_fail_closed(self) -> None:
        access = provider_model_access("gemini", "gemini-future-unknown")

        self.assertFalse(access.is_free)
        self.assertEqual(access.free_tier_status, "unknown")
        self.assertTrue(access.chat_eligible)

    def test_gemini_paid_and_specialized_models_are_not_free_chat(self) -> None:
        pro = provider_model_access("gemini", "gemini-3.1-pro-preview")
        image = provider_model_access("gemini", "gemini-3.1-flash-image")

        self.assertFalse(pro.is_free)
        self.assertEqual(pro.free_tier_status, "verified_not_free")
        self.assertFalse(image.is_free)
        self.assertFalse(image.chat_eligible)

    def test_gemini_reviewed_free_models_and_gemma_family_are_allowed(self) -> None:
        self.assertTrue(gemini_model_is_verified_free_chat("gemini-3.5-flash"))
        self.assertTrue(gemini_model_is_verified_free_chat("gemini-2.5-pro"))
        self.assertTrue(gemini_model_is_verified_free_chat("gemma-4-31b-it"))
        self.assertNotIn("gemini-3.1-pro-preview", gemini_safe_fallback_models())

    def test_openrouter_requires_free_variant_even_when_media_pricing_is_zero(self) -> None:
        free = provider_model_access("openrouter", "openai/gpt-oss-20b:free")
        media = provider_model_access(
            "openrouter",
            "google/lyria-zero-priced",
            pricing={"prompt": "0", "completion": "0", "request": "0"},
        )

        self.assertTrue(free.is_free)
        self.assertFalse(media.is_free)

    def test_user_selected_free_model_quality_policy_is_central_and_fail_open_for_unknowns(
        self,
    ) -> None:
        gemini_best = provider_free_model_quality_prior(
            "gemini",
            "gemini-3.5-flash",
        )
        gemini_next = provider_free_model_quality_prior(
            "gemini",
            "gemini-3-flash-preview",
        )
        openrouter_best = provider_free_model_quality_prior(
            "openrouter",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
        )
        unknown = provider_free_model_quality_prior(
            "openrouter",
            "vendor/future-free:free",
        )

        self.assertGreater(
            gemini_best["quality_tier"],
            gemini_next["quality_tier"],
        )
        self.assertEqual(gemini_best["quality_score"], 0.0)
        self.assertEqual(openrouter_best["quality_tier"], 100)
        self.assertEqual(unknown["quality_tier"], 0)
        self.assertEqual(unknown["quality_source"], "unmeasured")


if __name__ == "__main__":
    unittest.main()
