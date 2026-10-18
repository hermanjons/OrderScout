from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from AI.processors.ai_ui_acceptance_cli import run


class TestAiUiAcceptance(unittest.TestCase):
    def test_authoritative_surfaces_pass_offscreen_visual_and_geometry_contract(self) -> None:
        docs_dir = Path(__file__).resolve().parents[2] / "AI" / "docs"
        reference_names = (
            "ai-chat-cloud-workspace-concept-v3-scaffold-faithful.png",
            "ai-chat-local-workspace-concept-v3-scaffold-faithful.png",
            "ai-model-hub-concept-v3-scaffold-faithful.png",
        )
        with tempfile.TemporaryDirectory(prefix="orderscout-ai-ui-") as temp_dir:
            output_dir = Path(temp_dir)
            for name in reference_names:
                shutil.copy2(docs_dir / name, output_dir / name)

            evidence_path = run(output_dir)
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

            self.assertEqual(evidence.get("render_mode"), "offscreen")
            self.assertEqual(evidence.get("viewport"), {"width": 1800, "height": 1100})
            self.assertAlmostEqual(float(evidence.get("logical_dpi") or 0), 96.0, delta=0.5)
            self.assertTrue(str(evidence.get("font_family") or "").strip())
            self.assertTrue(evidence.get("acceptance", {}).get("passed"), evidence.get("acceptance"))
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
            self.assertTrue(state_matrix.get("passed"), state_matrix)
            self.assertTrue(state_matrix.get("complete"), state_matrix)
            self.assertGreaterEqual(int(state_matrix.get("rendered_case_count") or 0), 20)
            rendered_states = set(state_matrix.get("rendered_states") or [])
            self.assertIn("chat-cloud-filter-paid", rendered_states)
            self.assertIn("chat-local-unsupported-setting", rendered_states)
            self.assertIn("chat-approval", rendered_states)
            self.assertIn("model-hub-validation-error", rendered_states)
            self.assertIn("model-hub-download-completed", rendered_states)
            self.assertIn("model-hub-download-paused-resumable", rendered_states)
            self.assertIn("model-hub-local-delete", rendered_states)
            self.assertEqual(state_matrix.get("pending_states"), [])
            self.assertNotIn("orderscout-acceptance-secret", evidence_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
