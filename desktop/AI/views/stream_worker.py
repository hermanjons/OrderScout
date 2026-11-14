"""Forward model response fragments from the worker thread to the chat view."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal

from Core.threads.sync_worker import SyncWorker


class ChatStreamWorker(SyncWorker):
    response_event = pyqtSignal(dict)

    def run(self) -> None:
        from AI.runtime.response_stream import response_stream

        with response_stream(self.response_event.emit):
            super().run()
