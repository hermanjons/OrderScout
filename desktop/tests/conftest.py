"""Keep automated tests away from the developer's business data and credentials."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

_sandbox: tempfile.TemporaryDirectory | None = None
_previous: dict[str, str | None] = {}


def pytest_configure(config):
    global _sandbox
    _sandbox = tempfile.TemporaryDirectory(prefix="orderscout-pytest-", ignore_cleanup_errors=True)
    root = Path(_sandbox.name)
    values = {
        "LOCALAPPDATA": str(root / "appdata"),
        "XDG_DATA_HOME": str(root / "appdata"),
        "ORDERSCOUT_CREDENTIAL_STORE_PATH": str(root / "credentials.dpapi.json"),
    }
    for key, value in values.items():
        _previous[key] = os.environ.get(key)
        os.environ[key] = value
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("ORDERSCOUT_LIVE_LLM_EVAL", "0")


def pytest_sessionstart(session):
    # UI tests can load the default application database asynchronously.
    # Materialize its schema in the sandbox before any UI is constructed.
    from Core.db.bootstrap import init_database

    init_database()


def pytest_unconfigure(config):
    if _sandbox is not None:
        from Core.utils.model_utils import clear_engine_cache

        clear_engine_cache()
    for key, value in _previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    # Windows Qt workers may still hold transient handles during interpreter
    # shutdown; preserve the isolated temp directory if immediate cleanup fails.
    if _sandbox is not None:
        try:
            _sandbox.cleanup()
        except PermissionError:
            pass
