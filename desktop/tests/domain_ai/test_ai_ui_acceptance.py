from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from AI.processors.ai_ui_acceptance_cli import _chat_design_checks, run


class TestAiUiAcceptance(unittest.TestCase):
    def test_authoritative_surfaces_pass_offscreen_visual_and_geometry_contract(self) -> None:
        reference_dir = Path(__file__).resolve().parent / "fixtures" / "conversation_layout"
        reference_names = (
            "ai-model-hub-concept-v3-scaffold-faithful.png",
        )
        with tempfile.TemporaryDirectory(prefix="orderscout-ai-ui-") as temp_dir:
            output_dir = Path(temp_dir)
            for name in reference_names:
                shutil.copy2(reference_dir / name, output_dir / name)

            guard_root = output_dir / "user-chat-guard"
            guard_root.mkdir()
            guard_path = guard_root / "active_chat.json"
            guard_path.write_text("user chat must stay untouched", encoding="utf-8")
            with patch("AI.processors.chat_session_store.ACTIVE_CHAT_FILE", guard_path):
                evidence_path = run(output_dir)
            self.assertEqual(guard_path.read_text(encoding="utf-8"), "user chat must stay untouched")
            self.assertFalse((guard_root / "conversations").exists())
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

            self.assertEqual(evidence.get("render_mode"), "offscreen")
            self.assertEqual(evidence.get("viewport"), {"width": 1800, "height": 1100})
            self.assertAlmostEqual(float(evidence.get("logical_dpi") or 0), 96.0, delta=0.5)
            self.assertTrue(str(evidence.get("font_family") or "").strip())
            self.assertTrue(evidence.get("acceptance", {}).get("passed"), evidence.get("acceptance"))
            acceptance = evidence["acceptance"]
            self.assertEqual([row["surface"] for row in acceptance["visual"]], ["model_hub"])
            self.assertEqual(acceptance["visual"][0]["threshold"], 0.975)
            transition = acceptance["reference_transition"]
            self.assertEqual(transition["chat_contract"], "Approved conversation layout, 2026-10-20")
            self.assertEqual({Path(row["reference"]).name for row in transition["approved_references"]},
                             {"conversation-layout.html", "layout-conversations.png", "layout-model-menu.png"})
            self.assertTrue(all(len(row["sha256"]) == 64 for row in transition["approved_references"]))
            self.assertTrue(transition["model_hub_reference_unchanged"])
            self.assertEqual(set(acceptance["chat_contracts"]), {"chat_cloud", "chat_local"})
            isolation = evidence["fixture_isolation"]
            self.assertTrue(isolation["active_chat_isolated"])
            self.assertTrue(isolation["conversation_library_derived_from_active_path"])
            self.assertTrue(isolation["task_store_isolated"])
            self.assertGreaterEqual(isolation["saved_synthetic_conversations"], 3)
            self.assertEqual(isolation["live_model_calls"], 0)
            self.assertEqual(len(evidence.get("surfaces") or []), 3)

            generated = {str(row.get("image") or "") for row in evidence.get("surfaces") or []}
            self.assertEqual(
                generated,
                {
                    "ui-acceptance-chat-cloud-1800x1100.png",
                    "ui-acceptance-chat-local-1800x1100.png",
                    "ui-acceptance-model-hub-1800x1100.png",
                },
            )
            state_matrix = dict(evidence.get("state_matrix") or {})
            self.assertTrue(state_matrix.get("passed"), [
                {"state": case["state"], "failed_checks": [name for name, passed in case["checks"].items() if not passed]}
                for case in state_matrix.get("cases", []) if not case["passed"]
            ])
            self.assertTrue(state_matrix.get("complete"), state_matrix)
            self.assertGreaterEqual(int(state_matrix.get("rendered_case_count") or 0), 20)
            rendered_states = set(state_matrix.get("rendered_states") or [])
            self.assertIn("chat-cloud-filter-paid", rendered_states)
            self.assertIn("chat-local-unsupported-setting", rendered_states)
            self.assertIn("chat-approval", rendered_states)
            self.assertIn("chat-model-selected-from-popup", rendered_states)
            self.assertIn("chat-busy-navigation-locked", rendered_states)
            self.assertIn("chat-run-details", rendered_states)
            self.assertIn("model-hub-validation-error", rendered_states)
            self.assertIn("model-hub-download-completed", rendered_states)
            self.assertIn("model-hub-download-paused-resumable", rendered_states)
            self.assertIn("model-hub-local-delete", rendered_states)
            self.assertEqual(state_matrix.get("pending_states"), [])
            self.assertNotIn("orderscout-acceptance-secret", evidence_path.read_text(encoding="utf-8"))

            # A displaced composer control must fail the design contract even
            # when its text, visibility and screenshot colors still look valid.
            cloud = next(surface for surface in evidence["surfaces"] if surface["surface"] == "chat_cloud")
            displaced = json.loads(json.dumps(cloud))
            picker = next(row for row in displaced["components"] if row["object_name"] == "AiModelPicker")
            picker["geometry"]["y"] = 0
            self.assertFalse(_chat_design_checks(displaced)["model_picker_in_composer"])
            unnamed = json.loads(json.dumps(cloud))
            picker = next(row for row in unnamed["components"] if row["object_name"] == "AiModelPicker")
            picker["accessible_name"] = ""
            self.assertFalse(_chat_design_checks(unnamed)["named_primary_controls"])


if __name__ == "__main__":
    unittest.main()
