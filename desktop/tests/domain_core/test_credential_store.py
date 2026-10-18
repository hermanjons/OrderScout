from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from Core.processors.credential_store import (
    coalesce_credential_bundle_reference,
    delete_secret,
    resolve_credential_bundle,
    resolve_secret,
    store_credential_bundle,
    store_secret,
)


class TestCredentialReferenceNormalization(unittest.TestCase):
    def test_duplicate_legacy_and_explicit_bundle_reference_is_coalesced(self) -> None:
        reference, inline_value = coalesce_credential_bundle_reference(
            "credential://marketplaces/stage",
            "credential://marketplaces/stage",
            companion_value="",
        )

        self.assertEqual(reference, "credential://marketplaces/stage")
        self.assertEqual(inline_value, "")

    def test_conflicting_bundle_references_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            coalesce_credential_bundle_reference(
                "credential://marketplaces/one",
                "credential://marketplaces/two",
            )

    def test_individual_secret_references_remain_supported(self) -> None:
        reference, inline_value = coalesce_credential_bundle_reference(
            "",
            "credential://api-key/one",
            companion_value="credential://api-secret/two",
        )

        self.assertEqual(reference, "")
        self.assertEqual(inline_value, "credential://api-key/one")


@unittest.skipUnless(os.name == "nt", "Windows DPAPI is required")
class TestCredentialStore(unittest.TestCase):
    def test_dpapi_store_round_trip_never_writes_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "credentials.json"
            secret = "test-provider-secret-that-must-not-be-plain"

            reference = store_secret("ai-provider-test", secret, store_path=path)

            self.assertTrue(reference.startswith("credential://"))
            self.assertEqual(resolve_secret(reference, store_path=path), secret)
            self.assertNotIn(secret, path.read_text(encoding="utf-8"))
            self.assertTrue(delete_secret(reference, store_path=path))
            self.assertFalse(delete_secret(reference, store_path=path))

    def test_dpapi_credential_bundle_round_trip_never_writes_fields_in_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "credentials.json"
            bundle = {
                "seller_id": "2738",
                "api_key": "stage-key-that-must-not-leak",
                "api_secret": "stage-secret-that-must-not-leak",
            }

            reference = store_credential_bundle(
                "marketplace-stage-test",
                bundle,
                reference="credential://marketplace-stage-test/2738",
                store_path=path,
            )

            self.assertEqual(reference, "credential://marketplace-stage-test/2738")
            self.assertEqual(resolve_credential_bundle(reference, store_path=path), bundle)
            raw_store = path.read_text(encoding="utf-8")
            self.assertNotIn(bundle["api_key"], raw_store)
            self.assertNotIn(bundle["api_secret"], raw_store)


if __name__ == "__main__":
    unittest.main()
