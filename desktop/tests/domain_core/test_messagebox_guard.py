from __future__ import annotations

import unittest
from pathlib import Path


class TestMessageBoxGuard(unittest.TestCase):
    def test_no_direct_qmessagebox_calls_outside_messaging(self) -> None:
        root = Path(__file__).resolve().parents[2]
        messaging_path = (root / "Core" / "views" / "messaging.py").resolve()
        guard_path = Path(__file__).resolve()
        offenders: list[str] = []
        ignored_dirs = {
            ".codex-venv",
            ".pytest_cache",
            ".uv-cache-codex",
            ".uv-cache-run",
            ".venv",
            "__pycache__",
            "node_modules",
        }

        for path in root.rglob("*.py"):
            if any(part in ignored_dirs for part in path.parts):
                continue
            if path.resolve() == messaging_path:
                continue
            if path.resolve() == guard_path:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "QMessageBox." in text:
                offenders.append(str(path))

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
