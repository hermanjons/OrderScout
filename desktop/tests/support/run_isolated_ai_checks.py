from __future__ import annotations

import json
import hashlib
import os
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
group = sys.argv[1]
test_args = sys.argv[2:]
if not test_args:
    raise SystemExit('Supply the test selection explicitly.')
temp_root = tempfile.mkdtemp(prefix='orderscout-repair-' + group + '-')
os.environ['LOCALAPPDATA'] = temp_root
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['ORDERSCOUT_LIVE_LLM_EVAL'] = '0'
sys.dont_write_bytecode = True


original_connect = socket.socket.connect
original_socketpair = socket.socketpair
socketpair_context = threading.local()


def deny_connection(sock, address, *args, **kwargs):
    # Windows asyncio creates its own loopback self-pipe using socketpair.
    # Permit only that synchronous stdlib construction in the current thread.
    if (getattr(socketpair_context, 'building', False)
            and isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}):
        return original_connect(sock, address, *args, **kwargs)
    raise RuntimeError('Network disabled during isolated OrderScout repair regression')


def isolated_socketpair(*args, **kwargs):
    previous = getattr(socketpair_context, 'building', False)
    socketpair_context.building = True
    try:
        return original_socketpair(*args, **kwargs)
    finally:
        socketpair_context.building = previous


socket.socket.connect = deny_connection
socket.socket.connect_ex = lambda *args, **kwargs: (_ for _ in ()).throw(
    RuntimeError('Network disabled during isolated OrderScout repair regression')
)
socket.socketpair = isolated_socketpair
os.chdir(ROOT / 'desktop')
sys.path.insert(0, str(ROOT / 'desktop'))

# Own one Qt application for the entire test process. Some source UI tests
# otherwise create a local QApplication, whose destruction also deletes shared
# QObject signal buses used by later Finance/Marketplaces/Logistics tests.
from PyQt6.QtWidgets import QApplication
isolated_test_application = QApplication.instance() or QApplication([])

from sqlmodel import SQLModel
from Core.db import model_registry
from Core.utils.model_utils import get_engine
from settings import DB_NAME
import pytest

SQLModel.metadata.create_all(get_engine(DB_NAME))


class TestResults:
    stats = {}
    failures = []
    skip_reasons = {}

    def pytest_terminal_summary(self, terminalreporter):
        self.stats = {key: len(reports) for key, reports in terminalreporter.stats.items() if key}
        self.failures = [report.nodeid for report in terminalreporter.stats.get('failed', [])]
        for report in terminalreporter.stats.get('skipped', []):
            reason = report.longrepr[-1] if isinstance(report.longrepr, tuple) else str(report.longrepr)
            self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1


results = TestResults()


def source_snapshot():
    """Record source identity without copying source text or external app data."""
    files = []
    excluded = {'__pycache__', '.venv', 'venv', '.git', 'build', 'dist', 'node_modules'}
    candidates = list((ROOT / 'desktop').glob('requirements*.txt'))
    for directory, subdirectories, names in os.walk(ROOT / 'desktop'):
        subdirectories[:] = [name for name in subdirectories if name not in excluded and not name.startswith('.')]
        candidates.extend(Path(directory) / name for name in names if name.endswith('.py'))
    for path in sorted(candidates):
        relative = path.relative_to(ROOT)
        if excluded.intersection(relative.parts):
            continue
        files.append({'path': relative.as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'files': files, 'fingerprint': hashlib.sha256(json.dumps(files, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest(),
        'scope': 'Desktop Python source and tests plus root dependency files; no external data or source text.'}


sources_before = source_snapshot()
started = time.perf_counter()
result = pytest.main(['-q', '-p', 'no:cacheprovider', *test_args], plugins=[results])
elapsed = time.perf_counter() - started
sources_after = source_snapshot()
report = {
    'group': group,
    'exit_code': int(result),
    'run_at_utc': datetime.now(timezone.utc).isoformat(),
    'python_version': sys.version,
    'test_arguments': test_args,
    'wall_seconds': round(elapsed, 3),
    'isolated_localappdata': temp_root,
    'default_db': DB_NAME,
    'network_disabled': True,
    'local_asyncio_socketpair_allowed': True,
    'live_llm_disabled': True,
    'qt_platform': os.environ['QT_QPA_PLATFORM'],
    'test_stats': results.stats,
    'failures': results.failures,
    'skip_reasons': results.skip_reasons,
    'source_snapshot_before': sources_before,
    'source_snapshot_after': sources_after,
    'source_snapshot_unchanged': sources_before['fingerprint'] == sources_after['fingerprint'],
}
evidence_dir = ROOT / 'output' / ('agentic-' + datetime.now(timezone.utc).date().isoformat())
evidence_dir.mkdir(parents=True, exist_ok=True)
(evidence_dir / (group + '-run.json')).write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
)
raise SystemExit(result)
