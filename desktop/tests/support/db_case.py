from __future__ import annotations

import gc
import time
import tempfile
import unittest
from pathlib import Path

from sqlmodel import SQLModel

from Core.db import model_registry  # noqa: F401
from Core.utils import model_utils


class IsolatedDbTestCase(unittest.TestCase):
    """Creates a temporary sqlite database and materializes all SQLModel tables."""

    def setUp(self) -> None:
        super().setUp()
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp_dir.name) / "test.sqlite3")

        model_utils.clear_engine_cache()
        engine = model_utils.get_engine(self.db_path)
        SQLModel.metadata.create_all(engine)

    def tearDown(self) -> None:
        model_utils.clear_engine_cache()
        gc.collect()
        last_error: Exception | None = None
        for _ in range(5):
            try:
                self._tmp_dir.cleanup()
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                time.sleep(0.05)
                gc.collect()
        if last_error is not None:
            raise last_error
        super().tearDown()
