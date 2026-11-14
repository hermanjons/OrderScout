"""Application-owned background refresh, independent of lazily created tabs.

The timer only schedules work and checks file metadata. Domain reads, marketplace
requests, and persistence run on one worker. Local-only accounts never reach an
API adapter. Cursors advance only after successful domain persistence.
"""
from __future__ import annotations

import asyncio
import copy
import time
from datetime import datetime
from pathlib import Path
from threading import Event, Lock
from typing import Callable

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from Feedback.processors.pipeline import Result

DOMAINS = ("orders", "listing", "finance")


class BusinessRefreshSignals(QObject):
    status_changed = pyqtSignal(str, str)
    refreshed = pyqtSignal(str, object)

    def __init__(self):
        super().__init__()
        self.statuses: dict[str, str] = {}

    def publish_status(self, domain: str, message: str) -> None:
        self.statuses[domain] = message
        self.status_changed.emit(domain, message)


business_refresh_signals = BusinessRefreshSignals()


async def _run_domain(callback, accounts, *, db_name: str, cursor: dict, timeout: float):
    before = asyncio.all_tasks()
    try:
        return await asyncio.wait_for(callback(accounts, db_name=db_name, cursor=cursor), timeout=timeout)
    finally:
        # Shared adapters may create parallel child tasks. Timeout/cancellation
        # must drain them before the next domain can start a marketplace pull.
        children = asyncio.all_tasks() - before
        for task in children:
            task.cancel()
        if children:
            await asyncio.gather(*children, return_exceptions=True)


def account_uses_local_data(account) -> bool:
    """An explicit local fixture marker wins over any accidentally added secret."""
    extra = dict(getattr(account, "extra_config", None) or {})
    if (str(extra.get("data_origin") or "").lower() == "synthetic"
            or str(extra.get("environment") or "").lower() == "local"
            or str(extra.get("auto_sync_mode") or "").lower() == "local"):
        return True
    from Marketplaces.api.trendyol.base_api import trendyol_account_client_kwargs

    try:
        trendyol_account_client_kwargs(account)
    except (ValueError, TypeError):
        return True
    return False


async def refresh_business_data(*, db_name: str, cursors: dict | None = None,
                                allow_remote: bool = True, domain_timeout: float = 60.0) -> Result:
    """Headless refresh entrypoint; callers may select an isolated database."""
    from Account.processors.pipeline import get_active_companies

    accounts_result = get_active_companies(db_name=db_name)
    if not accounts_result.success:
        return Result.fail("Hesaplar okunamadı; otomatik güncelleme yeniden denenecek.",
                           close_dialog=False)
    accounts = list((accounts_result.data or {}).get("records") or [])
    remote_accounts = [a for a in accounts
                       if str(getattr(a, "platform", "")).upper() == "TRENDYOL"
                       and not account_uses_local_data(a)]
    state = copy.deepcopy(cursors or {})
    domains: dict[str, dict] = {}
    for domain in DOMAINS:
        payload = {"changed": False, "mode": "local", "remote_accounts": len(remote_accounts),
                   "local_accounts": len(accounts) - len(remote_accounts)}
        if allow_remote and remote_accounts:
            try:
                if domain == "orders":
                    from Orders.processors.background_refresh import refresh_orders
                    callback = refresh_orders
                elif domain == "listing":
                    from Listing.processors.background_refresh import refresh_listings
                    callback = refresh_listings
                else:
                    from Finance.processors.background_refresh import refresh_finance
                    callback = refresh_finance
                outcome = await _run_domain(
                    callback, remote_accounts, db_name=db_name,
                    cursor=copy.deepcopy(state.get(domain) or {}), timeout=domain_timeout,
                )
                payload.update(dict(outcome.data or {}))
                payload["mode"] = "remote"
                payload["success"] = bool(outcome.success)
                # Exception text may contain a URL or credentials; keep background
                # status generic. Detailed errors remain domain-owned diagnostics.
                payload["message"] = ("Pazaryeri kayıtları otomatik güncellendi." if outcome.success
                                      else "Pazaryeri güncellenemedi; yeniden denenecek.")
                if outcome.success:
                    state[domain] = dict(payload.pop("cursor", state.get(domain) or {}))
            except Exception:
                payload.update(success=False, message="Bağlantı tamamlanamadı; yeniden denenecek.")
        else:
            payload.update(success=True, message=(
                "Yerel kayıtlar otomatik yenilendi. Pazaryeri bağlantısı yapılandırılmadı."
                if not remote_accounts else "Yerel kayıtlar otomatik yenilendi."
            ))
            if not accounts:
                payload["message"] = "Otomatik güncelleme hazır. Şirket hesabı ekleyebilirsin."
        domains[domain] = payload
        await asyncio.sleep(0)
    return Result.ok("Otomatik güncelleme kontrolü tamamlandı.", close_dialog=False,
                     data={"domains": domains, "cursors": state,
                           "remote_success": all(p.get("success") for p in domains.values())})


class _RefreshWorker(QThread):
    result_ready = pyqtSignal(object)

    def __init__(self, callback: Callable, kwargs: dict):
        super().__init__()
        self.callback = callback
        self.kwargs = kwargs
        self._cancelled = Event()
        self._loop_lock = Lock()
        self._loop = None
        self._task = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._loop_lock:
            if self._loop is not None and self._task is not None:
                self._loop.call_soon_threadsafe(self._task.cancel)

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with self._loop_lock:
                self._loop = loop
                self._task = loop.create_task(self.callback(**self.kwargs))
                if self._cancelled.is_set():
                    self._task.cancel()
            result = loop.run_until_complete(self._task)
            if not self._cancelled.is_set():
                self.result_ready.emit(result)
        except asyncio.CancelledError:
            pass
        except Exception:
            if not self._cancelled.is_set():
                self.result_ready.emit(Result.fail("Otomatik güncelleme tamamlanamadı.", close_dialog=False))
        finally:
            # Cancel children created by shared async atoms before closing their
            # HTTP clients and event loop (including timeout/cancel paths).
            for task in asyncio.all_tasks(loop):
                task.cancel()
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            try:
                from Core.utils.request_utils import close_async_request_clients
                loop.run_until_complete(close_async_request_clients())
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            with self._loop_lock:
                self._loop = None
                self._task = None
                loop.close()


class BusinessRefreshService(QObject):
    """One serial worker, a coalesced queue, bounded backoff, and local file watch."""
    stopped = pyqtSignal()

    def __init__(self, *, db_name: str, parent=None, interval_seconds: float = 120,
                 poll_ms: int = 5000, callback: Callable = refresh_business_data,
                 clock: Callable = time.monotonic):
        super().__init__(parent)
        self.db_name = str(db_name)
        self.interval_seconds = max(1.0, float(interval_seconds))
        self._callback = callback
        self._clock = clock
        self._worker: _RefreshWorker | None = None
        self._pending = False
        self._running = False
        self._cursors: dict = {}
        self._failures = 0
        self._next_remote = 0.0
        self._last_fingerprint = None
        self._active_fingerprint = None
        self._active_remote = False
        self._timer = QTimer(self)
        self._timer.setInterval(max(20, int(poll_ms)))
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._timer.start()
        from Account.signals.signals import account_signals
        account_signals.company_changed.connect(self.request_refresh)
        QTimer.singleShot(0, self._tick)

    def _fingerprint(self):
        result = []
        for suffix in ("", "-wal"):
            try:
                stat = Path(self.db_name + suffix).stat()
                result.append((stat.st_mtime_ns, stat.st_size))
            except OSError:
                result.append(None)
        return tuple(result)

    def request_refresh(self) -> None:
        if not self._running:
            return
        # Account changes force a local reload immediately. Remote retries keep
        # their deadline, so a flurry of signals cannot bypass provider backoff.
        self._pending = True
        self._tick()

    def _tick(self) -> None:
        if not self._running:
            return
        if self._worker is not None:
            return
        fingerprint = self._fingerprint()
        remote_due = self._clock() >= self._next_remote
        if not (self._pending or fingerprint != self._last_fingerprint or remote_due):
            return
        self._pending = False
        self._active_fingerprint = fingerprint
        self._active_remote = remote_due
        worker = _RefreshWorker(self._callback, {
            "db_name": self.db_name, "cursors": copy.deepcopy(self._cursors), "allow_remote": remote_due,
        })
        self._worker = worker
        worker.result_ready.connect(self._on_result)
        worker.finished.connect(self._on_finished)
        worker.start()

    def _on_result(self, result: Result) -> None:
        if not self._running:
            return
        data = dict(result.data or {})
        if result.success:
            self._cursors = dict(data.get("cursors") or self._cursors)
        success = bool(result.success and data.get("remote_success", True))
        if self._active_remote:
            self._failures = 0 if success else min(self._failures + 1, 7)
            catching_up = any(p.get("has_more") for p in (data.get("domains") or {}).values())
            delay = (5.0 if catching_up else self.interval_seconds) if success else min(1800, 30 * 2 ** (self._failures - 1))
            self._next_remote = self._clock() + delay
        fingerprint = self._fingerprint()
        local_changed = fingerprint != self._last_fingerprint
        self._last_fingerprint = fingerprint
        checked_at = datetime.now().strftime("%H:%M:%S")
        for domain in DOMAINS:
            payload = dict((data.get("domains") or {}).get(domain) or {})
            message = payload.get("message") or "Otomatik güncelleme tamamlanamadı; yeniden denenecek."
            if local_changed or payload.get("changed"):
                business_refresh_signals.refreshed.emit(domain, payload)
            business_refresh_signals.publish_status(domain, f"{message} Son kontrol: {checked_at}")
        if local_changed or ((data.get("domains") or {}).get("orders") or {}).get("changed"):
            from Orders.signals.signals import order_signals
            order_signals.orders_changed.emit()
        if local_changed or ((data.get("domains") or {}).get("listing") or {}).get("changed"):
            from Listing.signals.signals import listing_signals
            listing_signals.listing_cache_updated.emit({"source": "automatic_refresh"})

    def _on_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        if not self._running:
            self.stopped.emit()
        elif self._pending:
            QTimer.singleShot(0, self._tick)

    def stop(self) -> bool:
        self._running = False
        self._pending = False
        self._timer.stop()
        from Account.signals.signals import account_signals
        try:
            account_signals.company_changed.disconnect(self.request_refresh)
        except (TypeError, RuntimeError):
            pass
        if self._worker is None:
            return True
        self._worker.cancel()
        # Shell close is retried by the stopped signal, keeping the GUI responsive
        # and retaining ownership until no thread can touch the database.
        return not self._worker.isRunning()
