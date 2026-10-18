"""Durable local schedules for fresh runs of pinned user workflow revisions.

Preparation grants no authority. The shared UI/runtime confirms the exact
schedule action; each actual workflow run still obtains its own effect approval.
A scheduler owns leases and receipts, never plans or resumes model work itself.
After a crash that may have started execution, it reconciles a trusted task
checkpoint or asks for attention instead of replaying an uncertain operation.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import stat
from typing import Any, Callable, Mapping
from uuid import uuid4

from AI.constants.paths import AI_DOMAIN_ROOT
from AI.processors import workflow_store
from AI.processors.session_state import AgentSessionState
from Feedback.processors.pipeline import Result


SCHEMA_VERSION = 1
_APPLICATION_ID = 0x4F535743
_ID = re.compile(r"wfs_[0-9a-f]{32}\Z", re.ASCII)
_RUN_ID = re.compile(r"wrun_[0-9a-f]{64}\Z", re.ASCII)
_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_TASK_ID = re.compile(r"[a-z0-9_-]{1,96}\Z", re.ASCII)
_RESERVED_TASK_IDS = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}
_TERMINAL = {"completed", "failed"}
_BLOCKING = {"paused", "awaiting_approval", "recovery_required", "blocked"}
_SPEC_KEYS = {"workflow_id", "revision_id", "spec_hash", "pinned_spec", "parameters", "interval_seconds", "first_due_at", "budget"}
_SAVE_KEYS = {"schema_version", "action_type", "schedule_id", "expected_schedule_hash", "schedule", "requires_current_approval", "action_hash", "action_id"}
_CANCEL_KEYS = _SAVE_KEYS - {"schedule"}


class ScheduleValidationError(ValueError):
    pass


class ScheduleConflictError(ValueError):
    pass


class ScheduleIntegrityError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _utc(value: datetime | str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise ScheduleValidationError("UTC-aware schedule time required.") from None


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _identity(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ScheduleValidationError("Invalid opaque schedule ID.")
    return value


def _expected_hash(value: Any, *, empty: bool = False) -> str:
    if empty and value == "":
        return ""
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ScheduleValidationError("Exact schedule revision hash required.")
    return value


def _task_identity(value: Any) -> str:
    # The scheduler records checkpoint identities, never paths supplied by a
    # model. Keep precisely the task store's portable, case-sensitive grammar.
    if not isinstance(value, str) or not _TASK_ID.fullmatch(value) or value in _RESERVED_TASK_IDS:
        raise ScheduleIntegrityError("Invalid actual task checkpoint identity.")
    return value


def _no_links(path: Path) -> None:
    for candidate in (path, *path.parents):
        if not candidate.exists() and not candidate.is_symlink():
            continue
        information = candidate.lstat()
        if stat.S_ISLNK(information.st_mode) or (getattr(information, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ScheduleValidationError("Linked scheduler storage is not supported.")


def _budget(value: Any) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != {"max_steps", "max_replans"}:
        raise ScheduleValidationError("Bounded execution budget required.")
    if type(value["max_steps"]) is not int or not 1 <= value["max_steps"] <= 24 or type(value["max_replans"]) is not int or not 0 <= value["max_replans"] <= 4:
        raise ScheduleValidationError("Schedule execution budget is outside its limits.")
    return dict(value)


def _configuration(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _SPEC_KEYS:
        raise ScheduleValidationError("Unsupported schedule configuration fields.")
    pinned = workflow_store.WorkflowSpec.from_dict(value["pinned_spec"])
    if pinned.content_hash != value["spec_hash"]:
        raise ScheduleIntegrityError("Pinned workflow spec hash drifted.")
    if not isinstance(value["parameters"], dict):
        raise ScheduleValidationError("Typed schedule parameters required.")
    # This validates a saved request's structure, not fresh execution authority.
    # Every execution renders again against current runtime-provided scopes.
    requested_scopes = {}
    for name, definition in pinned.to_dict()["parameter_schema"]["properties"].items():
        if definition.get("scope") and name in value["parameters"]:
            parameter = value["parameters"][name]
            requested_scopes.setdefault(definition["scope"], []).extend(parameter if isinstance(parameter, list) else [parameter])
    workflow_store.validate_workflow_parameters(pinned, value["parameters"], allowed_scope_bindings=requested_scopes)
    interval = value["interval_seconds"]
    if type(interval) is not int or not 60 <= interval <= 366 * 24 * 3600:
        raise ScheduleValidationError("Interval must be 60 seconds to 366 days.")
    if _iso(_utc(value["first_due_at"])) != value["first_due_at"]:
        raise ScheduleValidationError("Schedule time must be canonical UTC.")
    _budget(value["budget"])
    if len(_canonical(value).encode("utf-8")) > 96 * 1024:
        raise ScheduleValidationError("Schedule configuration exceeds its bound.")
    return json.loads(_canonical(value))


def _prepared(action_type: str, schedule_id: str, expected: str, configuration: dict[str, Any] | None = None) -> dict[str, Any]:
    core = {"schema_version": SCHEMA_VERSION, "action_type": action_type, "schedule_id": _identity(schedule_id),
            "expected_schedule_hash": _expected_hash(expected, empty=action_type == "workflow.schedule.save"),
            "requires_current_approval": True}
    if configuration is not None:
        core["schedule"] = _configuration(configuration)
    digest = _hash(core)
    return {**core, "action_hash": digest, "action_id": "wsa_" + digest}


@dataclass(frozen=True)
class RunLease:
    run_id: str
    schedule_id: str
    schedule_hash: str
    due_at: str
    owner_id: str
    lease_expires_at: str
    lease_token: str = field(repr=False)
    _schedule_json: str = field(repr=False)

    @property
    def schedule(self) -> dict[str, Any]:
        return json.loads(self._schedule_json)

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "schedule_id": self.schedule_id, "schedule_hash": self.schedule_hash,
                "due_at": self.due_at, "owner_id": self.owner_id, "lease_expires_at": self.lease_expires_at}


class WorkflowScheduler:
    def __init__(self, *, root: str | Path | None = None, workflow_root: str | Path | None = None,
                 clock: Callable[[], datetime] | None = None, lease_seconds: int = 300):
        if type(lease_seconds) is not int or not 30 <= lease_seconds <= 3600:
            raise ScheduleValidationError("Lease must be 30 to 3600 seconds.")
        self.root = Path(root) if root is not None else AI_DOMAIN_ROOT / "workflow_schedules"
        self.workflow_root = workflow_root
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lease_seconds = lease_seconds

    @property
    def path(self) -> Path:
        return self.root / "workflow_scheduler.sqlite3"

    def _now(self) -> datetime:
        return _utc(self.clock())

    @contextmanager
    def _connection(self, *, write: bool):
        _no_links(self.path)
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.path.is_file():
            raise FileNotFoundError("Scheduler store does not exist.")
        connection = sqlite3.connect(str(self.path) if write else self.path.absolute().as_uri() + "?mode=rw",
                                     uri=not write, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            if connection.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
                raise ScheduleIntegrityError("Scheduler requires DELETE journal recovery.")
            if write:
                connection.execute("PRAGMA synchronous=EXTRA")
                connection.execute("BEGIN IMMEDIATE")
            self._check_store(connection, initialise=write)
            if not write:
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
            yield connection
            if write:
                connection.execute("COMMIT")
        finally:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            connection.close()

    @staticmethod
    def _check_store(connection: sqlite3.Connection, *, initialise: bool) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        application = connection.execute("PRAGMA application_id").fetchone()[0]
        if version == SCHEMA_VERSION and application == _APPLICATION_ID:
            return
        tables = connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if not initialise or version or application or tables:
            raise ScheduleIntegrityError("Unsupported or unrelated scheduler database.")
        connection.execute("CREATE TABLE schedules (schedule_id TEXT PRIMARY KEY, schedule_hash TEXT NOT NULL, configuration_json TEXT NOT NULL, status TEXT NOT NULL, next_due_at TEXT, active_run_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        connection.execute("CREATE TABLE schedule_actions (action_hash TEXT PRIMARY KEY, action_id TEXT UNIQUE NOT NULL, action_json TEXT NOT NULL, approved_by TEXT NOT NULL, approved_at TEXT NOT NULL, receipt_json TEXT NOT NULL)")
        connection.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL, schedule_hash TEXT NOT NULL, configuration_json TEXT NOT NULL, due_at TEXT NOT NULL, status TEXT NOT NULL, owner_id TEXT NOT NULL, lease_token TEXT NOT NULL, lease_expires_at TEXT NOT NULL, attempts INTEGER NOT NULL, execution_started_at TEXT, session_id TEXT, receipt_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        connection.execute("CREATE TABLE run_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, event_type TEXT NOT NULL, created_at TEXT NOT NULL, metadata_json TEXT NOT NULL)")
        for table in ("schedule_actions", "run_events"):
            connection.execute(f"CREATE TRIGGER immutable_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'Immutable scheduler record'); END")
            connection.execute(f"CREATE TRIGGER immutable_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'Immutable scheduler record'); END")
        connection.execute("CREATE TRIGGER immutable_run_intent BEFORE UPDATE OF run_id, schedule_id, schedule_hash, configuration_json, due_at, created_at ON runs BEGIN SELECT RAISE(ABORT, 'Immutable run intent'); END")
        connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @staticmethod
    def _schedule(row: sqlite3.Row) -> dict[str, Any]:
        configuration = _configuration(json.loads(row["configuration_json"]))
        _identity(row["schedule_id"])
        _expected_hash(row["schedule_hash"])
        if row["status"] not in {"active", "cancelled"}:
            raise ScheduleIntegrityError("Invalid scheduler status.")
        if row["next_due_at"] is not None:
            _utc(row["next_due_at"])
        return {"schedule_id": row["schedule_id"], "schedule_hash": row["schedule_hash"], "schedule": configuration,
                "status": row["status"], "next_due_at": row["next_due_at"], "active_run_id": row["active_run_id"],
                "created_at": row["created_at"], "updated_at": row["updated_at"]}

    @staticmethod
    def _run(row: sqlite3.Row) -> dict[str, Any]:
        _configuration(json.loads(row["configuration_json"]))
        expected = "wrun_" + _hash({"schedule_id": row["schedule_id"], "schedule_hash": row["schedule_hash"], "due_at": row["due_at"]})
        if row["run_id"] != expected or row["status"] not in _TERMINAL | _BLOCKING | {"leased", "running"}:
            raise ScheduleIntegrityError("Stored run identity or status drifted.")
        if row["session_id"] is not None:
            _task_identity(row["session_id"])
        return {key: row[key] for key in ("run_id", "schedule_id", "schedule_hash", "due_at", "status", "owner_id",
                "lease_expires_at", "attempts", "execution_started_at", "session_id", "created_at", "updated_at")} | {"receipt": json.loads(row["receipt_json"])}

    @staticmethod
    def _event(connection: sqlite3.Connection, run_id: str, event_type: str, now: str, metadata: dict[str, Any] | None = None) -> None:
        connection.execute("INSERT INTO run_events (run_id,event_type,created_at,metadata_json) VALUES (?,?,?,?)",
                           (run_id, event_type, now, _canonical(metadata or {})))

    def _checked_configuration(self, connection: sqlite3.Connection, schedule_id: str, schedule_hash: str, configuration_json: str) -> dict[str, Any]:
        _identity(schedule_id)
        seen = set()
        while schedule_hash:
            if schedule_hash in seen or len(seen) >= 128:
                raise ScheduleIntegrityError("Schedule approval chain is invalid.")
            seen.add(schedule_hash)
            row = connection.execute("SELECT action_json FROM schedule_actions WHERE action_hash=?", (schedule_hash,)).fetchone()
            if row is None:
                raise ScheduleIntegrityError("Schedule confirmation record is missing.")
            action = json.loads(row[0])
            cancel = action.get("action_type") == "workflow.schedule.cancel"
            expected = _prepared("workflow.schedule.cancel" if cancel else "workflow.schedule.save",
                                 action["schedule_id"], action["expected_schedule_hash"], None if cancel else action["schedule"])
            if (_canonical(action) != _canonical(expected) or action["action_hash"] != schedule_hash
                    or action["schedule_id"] != schedule_id):
                raise ScheduleIntegrityError("Stored exact schedule confirmation drifted.")
            if not cancel:
                if _canonical(action["schedule"]) != configuration_json:
                    raise ScheduleIntegrityError("Configuration differs from the human-confirmed schedule.")
                return action["schedule"]
            schedule_hash = action["expected_schedule_hash"]
        raise ScheduleIntegrityError("Schedule confirmation chain has no saved configuration.")

    def prepare_schedule_save(self, workflow_id: str, *, revision_id: str, parameters: Mapping[str, Any],
                              interval_seconds: int, first_due_at: datetime | str, schedule_id: str | None = None,
                              expected_schedule_hash: str = "", allowed_scope_bindings: Mapping[str, Any] | None = None,
                              budget: Mapping[str, int] | None = None) -> dict[str, Any]:
        revision = workflow_store.read_workflow(workflow_id, revision_id=revision_id, root=self.workflow_root)
        values = workflow_store.validate_workflow_parameters(revision.spec, parameters, allowed_scope_bindings=allowed_scope_bindings)
        configuration = {"workflow_id": revision.workflow_id, "revision_id": revision.revision_id,
                         "spec_hash": revision.spec.content_hash, "pinned_spec": revision.spec.to_dict(), "parameters": values,
                         "interval_seconds": interval_seconds, "first_due_at": _iso(_utc(first_due_at)),
                         "budget": dict(budget or {"max_steps": 12, "max_replans": 2})}
        return _prepared("workflow.schedule.save", schedule_id or "wfs_" + uuid4().hex, expected_schedule_hash, configuration)

    def prepare_schedule_cancel(self, schedule_id: str, *, expected_schedule_hash: str) -> dict[str, Any]:
        return _prepared("workflow.schedule.cancel", schedule_id, expected_schedule_hash)

    def _validated_action(self, action: Mapping[str, Any], *, cancel: bool = False) -> dict[str, Any]:
        value = dict(action)
        if set(value) != (_CANCEL_KEYS if cancel else _SAVE_KEYS) or type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
            raise ScheduleValidationError("Unsupported schedule proposal fields.")
        kind = "workflow.schedule.cancel" if cancel else "workflow.schedule.save"
        expected = _prepared(kind, value["schedule_id"], value["expected_schedule_hash"], None if cancel else value["schedule"])
        if _canonical(expected) != _canonical(value):
            raise ScheduleIntegrityError("The exact reviewed schedule proposal changed.")
        if not cancel:
            config = expected["schedule"]
            revision = workflow_store.read_workflow(config["workflow_id"], revision_id=config["revision_id"], root=self.workflow_root)
            if revision.spec.to_dict() != config["pinned_spec"] or revision.spec.content_hash != config["spec_hash"]:
                raise ScheduleIntegrityError("Pinned canonical workflow revision drifted.")
        return expected

    def _confirm(self, action: Mapping[str, Any], confirmed_action_hash: str, approved_by: str, *, cancel: bool) -> Result:
        value = self._validated_action(action, cancel=cancel)
        if (not isinstance(approved_by, str) or not approved_by.strip() or len(approved_by) > 160
                or not isinstance(confirmed_action_hash, str) or not hmac.compare_digest(value["action_hash"], confirmed_action_hash)):
            raise ScheduleValidationError("Human confirmation of the exact action hash is required.")
        now = _iso(self._now())
        with self._connection(write=True) as connection:
            receipt = connection.execute("SELECT receipt_json FROM schedule_actions WHERE action_hash=?", (value["action_hash"],)).fetchone()
            if receipt:
                return Result.ok("Zamanlama teklifi daha once kaydedildi.", close_dialog=False, data=json.loads(receipt[0]))
            previous = connection.execute("SELECT * FROM schedules WHERE schedule_id=?", (value["schedule_id"],)).fetchone()
            actual = previous["schedule_hash"] if previous else ""
            if actual != value["expected_schedule_hash"] or (cancel and previous is None):
                raise ScheduleConflictError("Schedule changed since the reviewed proposal.")
            if previous and previous["active_run_id"]:
                active = connection.execute("SELECT * FROM runs WHERE run_id=?", (previous["active_run_id"],)).fetchone()
                if active is None:
                    raise ScheduleIntegrityError("Active schedule run is missing.")
                if active["execution_started_at"] is None:
                    run_receipt = json.loads(active["receipt_json"])
                    run_receipt.update({"status": "failed", "success": False, "reason": "schedule_cancelled" if cancel else "schedule_updated_before_execution"})
                    connection.execute("UPDATE runs SET status='failed',receipt_json=?,updated_at=? WHERE run_id=?",
                                       (_canonical(run_receipt), now, active["run_id"]))
                    connection.execute("UPDATE schedules SET active_run_id=NULL WHERE schedule_id=?", (value["schedule_id"],))
                    self._event(connection, active["run_id"], "unstarted_run_invalidated", now)
            if cancel:
                connection.execute("UPDATE schedules SET status='cancelled',schedule_hash=?,next_due_at=NULL,updated_at=? WHERE schedule_id=?",
                                   (value["action_hash"], now, value["schedule_id"]))
            elif previous:
                connection.execute("UPDATE schedules SET schedule_hash=?,configuration_json=?,status='active',next_due_at=?,updated_at=? WHERE schedule_id=?",
                                   (value["action_hash"], _canonical(value["schedule"]), value["schedule"]["first_due_at"], now, value["schedule_id"]))
            else:
                connection.execute("INSERT INTO schedules VALUES (?,?,?,'active',?,NULL,?,?)",
                                   (value["schedule_id"], value["action_hash"], _canonical(value["schedule"]), value["schedule"]["first_due_at"], now, now))
            current = connection.execute("SELECT * FROM schedules WHERE schedule_id=?", (value["schedule_id"],)).fetchone()
            data = {"schedule": self._schedule(current), "confirmed_action_id": value["action_id"], "effect_approval_granted": False}
            connection.execute("INSERT INTO schedule_actions VALUES (?,?,?,?,?,?)",
                               (value["action_hash"], value["action_id"], _canonical(value), approved_by.strip(), now, _canonical(data)))
        return Result.ok("Planli calisma zamanlamasi kaydedildi.", close_dialog=False, data=data)

    def save_prepared_schedule(self, action: Mapping[str, Any], *, confirmed_action_hash: str, approved_by: str) -> Result:
        return self._confirm(action, confirmed_action_hash, approved_by, cancel=False)

    def cancel_prepared_schedule(self, action: Mapping[str, Any], *, confirmed_action_hash: str, approved_by: str) -> Result:
        return self._confirm(action, confirmed_action_hash, approved_by, cancel=True)

    def list_schedules(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        with self._connection(write=False) as connection:
            rows = connection.execute("SELECT * FROM schedules ORDER BY created_at,schedule_id LIMIT ?", (max(1, min(128, int(limit))),)).fetchall()
            for row in rows:
                self._checked_configuration(connection, row["schedule_id"], row["schedule_hash"], row["configuration_json"])
            return [self._schedule(row) for row in rows]

    def list_runs(self, *, schedule_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if schedule_id is not None:
            _identity(schedule_id)
        if not self.path.is_file():
            return []
        with self._connection(write=False) as connection:
            rows = connection.execute("SELECT * FROM runs WHERE (? IS NULL OR schedule_id=?) ORDER BY created_at DESC,run_id LIMIT ?",
                                      (schedule_id, schedule_id, max(1, min(128, int(limit))))).fetchall()
            for row in rows:
                self._checked_configuration(connection, row["schedule_id"], row["schedule_hash"], row["configuration_json"])
            return [self._run(row) for row in rows]

    @staticmethod
    def _lease(row: sqlite3.Row) -> RunLease:
        return RunLease(row["run_id"], row["schedule_id"], row["schedule_hash"], row["due_at"],
                        row["owner_id"], row["lease_expires_at"], row["lease_token"], row["configuration_json"])

    def _owned(self, connection: sqlite3.Connection, lease: RunLease) -> sqlite3.Row:
        if type(lease) is not RunLease or not _RUN_ID.fullmatch(lease.run_id):
            raise ScheduleValidationError("Runtime lease required.")
        row = connection.execute("SELECT * FROM runs WHERE run_id=?", (lease.run_id,)).fetchone()
        if row is None or row["owner_id"] != lease.owner_id or not hmac.compare_digest(row["lease_token"], lease.lease_token):
            raise ScheduleConflictError("Lease is no longer owned by this worker.")
        if row["schedule_hash"] != lease.schedule_hash or row["configuration_json"] != lease._schedule_json:
            raise ScheduleIntegrityError("Immutable run intent drifted.")
        self._checked_configuration(connection, row["schedule_id"], row["schedule_hash"], row["configuration_json"])
        self._run(row)
        return row

    def claim_due(self, *, owner_id: str, max_runs: int = 1) -> list[RunLease]:
        if not isinstance(owner_id, str) or not owner_id.strip() or len(owner_id) > 160 or type(max_runs) is not int or not 1 <= max_runs <= 8:
            raise ScheduleValidationError("Bounded scheduler worker identity required.")
        if not self.path.is_file():
            return []
        now, leases = self._now(), []
        now_text = _iso(now)
        expiry = _iso(now + timedelta(seconds=self.lease_seconds))
        with self._connection(write=True) as connection:
            schedules = connection.execute("SELECT * FROM schedules WHERE status='active' ORDER BY next_due_at,schedule_id").fetchall()
            for schedule in schedules:
                if len(leases) >= max_runs:
                    break
                config = self._checked_configuration(connection, schedule["schedule_id"], schedule["schedule_hash"], schedule["configuration_json"])
                self._schedule(schedule)
                if schedule["active_run_id"]:
                    active = connection.execute("SELECT * FROM runs WHERE run_id=?", (schedule["active_run_id"],)).fetchone()
                    if active is None:
                        raise ScheduleIntegrityError("Active schedule run is missing.")
                    if active["status"] in _BLOCKING or active["status"] in _TERMINAL:
                        continue
                    if _utc(active["lease_expires_at"]) > now:
                        continue
                    if active["execution_started_at"] is not None:
                        # Execution may have caused an effect. Fence the expired
                        # worker, retain this run, and reconcile its checkpoint;
                        # never acquire a lease to execute the objective again.
                        connection.execute("UPDATE runs SET status='recovery_required',owner_id=?,lease_token=?,lease_expires_at=?,updated_at=? WHERE run_id=?",
                                           (owner_id, secrets.token_hex(32), now_text, now_text, active["run_id"]))
                        self._event(connection, active["run_id"], "expired_execution_requires_recovery", now_text)
                        continue
                    token = secrets.token_hex(32)
                    connection.execute("UPDATE runs SET status='leased',owner_id=?,lease_token=?,lease_expires_at=?,attempts=attempts+1,updated_at=? WHERE run_id=?",
                                       (owner_id, token, expiry, now_text, active["run_id"]))
                    self._event(connection, active["run_id"], "unstarted_lease_reclaimed", now_text)
                    leases.append(self._lease(connection.execute("SELECT * FROM runs WHERE run_id=?", (active["run_id"],)).fetchone()))
                    continue
                if schedule["next_due_at"] is None or _utc(schedule["next_due_at"]) > now:
                    continue
                due = _utc(schedule["next_due_at"])
                run_id = "wrun_" + _hash({"schedule_id": schedule["schedule_id"], "schedule_hash": schedule["schedule_hash"], "due_at": _iso(due)})
                token = secrets.token_hex(32)
                missed = max(0, int((now - due).total_seconds()) // config["interval_seconds"])
                next_due = due + timedelta(seconds=(missed + 1) * config["interval_seconds"])
                connection.execute("INSERT INTO runs VALUES (?,?,?,?,?,'leased',?,?,?,1,NULL,NULL,?,?,?)",
                                   (run_id, schedule["schedule_id"], schedule["schedule_hash"], schedule["configuration_json"], _iso(due),
                                    owner_id, token, expiry, _canonical({"skipped_intervals": missed, "effect_approval_granted": False}), now_text, now_text))
                connection.execute("UPDATE schedules SET active_run_id=?,next_due_at=?,updated_at=? WHERE schedule_id=?",
                                   (run_id, _iso(next_due), now_text, schedule["schedule_id"]))
                self._event(connection, run_id, "lease_claimed", now_text, {"skipped_intervals": missed})
                leases.append(self._lease(connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()))
        return leases

    def heartbeat(self, lease: RunLease) -> bool:
        now = self._now()
        with self._connection(write=True) as connection:
            row = self._owned(connection, lease)
            if row["status"] not in {"leased", "running"} or _utc(row["lease_expires_at"]) <= now:
                return False
            connection.execute("UPDATE runs SET lease_expires_at=?,updated_at=? WHERE run_id=?",
                               (_iso(now + timedelta(seconds=self.lease_seconds)), _iso(now), lease.run_id))
        return True

    @staticmethod
    def _state_from_result(result: Result) -> dict[str, Any]:
        data = result.data if isinstance(result.data, dict) else {}
        candidate = data.get("session_state") or data.get("state") or data.get("agent_state")
        if isinstance(candidate, AgentSessionState):
            return candidate.to_dict()
        return deepcopy(candidate) if isinstance(candidate, dict) else {}

    @staticmethod
    def _outcome(result: Result, state: dict[str, Any]) -> str:
        status = state.get("status")
        if not state.get("session_id"):
            return "recovery_required"
        if status in {"pending_approval", "awaiting_approval"} or state.get("pending_actions") or state.get("active_pending_action_id"):
            return "awaiting_approval"
        if status == "paused":
            return "paused"
        if status in {"running", "interrupted"}:
            return "recovery_required"
        if status == "complete" and result.success:
            return "completed"
        if status == "completed" and result.success:
            return "completed"
        if status in {"failed", "cancelled", "superseded"} or not result.success:
            return "failed"
        return "recovery_required"

    def _settle(self, lease: RunLease, result: Result, *, override_status: str | None = None,
                reason: str = "", blocked_by_session_id: str | None = None) -> dict[str, Any]:
        state = self._state_from_result(result)
        now = _iso(self._now())
        with self._connection(write=True) as connection:
            row = self._owned(connection, lease)
            if row["status"] in _TERMINAL:
                return self._run(row)
            if state.get("session_id") and row["session_id"] and state["session_id"] != row["session_id"]:
                raise ScheduleIntegrityError("Runner returned a different execution session.")
            status = override_status or self._outcome(result, state)
            if status not in _TERMINAL | _BLOCKING:
                raise ScheduleValidationError("Invalid schedule run outcome.")
            receipt = json.loads(row["receipt_json"])
            receipt.update({"success": bool(result.success and status in {"completed", "paused", "awaiting_approval"}), "status": status, "reason": reason,
                            "session_status": state.get("status"), "effect_approval_granted": False})
            if blocked_by_session_id:
                receipt["blocked_by_session_id"] = blocked_by_session_id
            task_session_id = state.get("session_id") or row["session_id"]
            if task_session_id:
                _task_identity(task_session_id)
                receipt["task_session_bound"] = True
            connection.execute("UPDATE runs SET status=?,session_id=?,receipt_json=?,updated_at=? WHERE run_id=?",
                               (status, task_session_id, _canonical(receipt), now, lease.run_id))
            if status in _TERMINAL:
                connection.execute("UPDATE schedules SET active_run_id=NULL,updated_at=? WHERE schedule_id=? AND active_run_id=?",
                                   (now, lease.schedule_id, lease.run_id))
            self._event(connection, lease.run_id, "run_settled", now, {"status": status, "reason": reason})
            return self._run(connection.execute("SELECT * FROM runs WHERE run_id=?", (lease.run_id,)).fetchone())

    def _begin_execution(self, lease: RunLease, session_state: dict[str, Any]) -> None:
        session_id = _task_identity(session_state.get("session_id"))
        now = self._now()
        with self._connection(write=True) as connection:
            row = self._owned(connection, lease)
            schedule = connection.execute("SELECT status,active_run_id FROM schedules WHERE schedule_id=?", (lease.schedule_id,)).fetchone()
            if (row["status"] != "leased" or row["execution_started_at"] is not None or _utc(row["lease_expires_at"]) <= now
                    or schedule is None or schedule["status"] != "active" or schedule["active_run_id"] != lease.run_id):
                raise ScheduleConflictError("Lease cannot start or replay this execution.")
            receipt = json.loads(row["receipt_json"])
            receipt.update({"submission_session_id": session_id, "task_session_bound": False})
            connection.execute("UPDATE runs SET status='running',execution_started_at=?,receipt_json=?,updated_at=? WHERE run_id=?",
                               (_iso(now), _canonical(receipt), _iso(now), lease.run_id))
            self._event(connection, lease.run_id, "execution_started", _iso(now), {"submission_session_id": session_id})

    def attach_task_session(self, lease: RunLease, session_id: str) -> None:
        """Runtime-only hook when the actual task/checkpoint is created.

        Shared conversation runners may allocate a new execution session rather
        than reuse workflow_store's submission context. Binding its real ID
        before tools run permits safe task-store reconciliation after a crash.
        """
        _task_identity(session_id)
        now = _iso(self._now())
        with self._connection(write=True) as connection:
            row = self._owned(connection, lease)
            if row["execution_started_at"] is None or row["status"] not in {"running", "recovery_required"}:
                raise ScheduleConflictError("No started execution owns this task session.")
            if row["session_id"] not in (None, session_id):
                raise ScheduleIntegrityError("Actual task session was already bound.")
            receipt = json.loads(row["receipt_json"])
            receipt["task_session_bound"] = True
            connection.execute("UPDATE runs SET session_id=?,receipt_json=?,updated_at=? WHERE run_id=?",
                               (session_id, _canonical(receipt), now, lease.run_id))
            self._event(connection, lease.run_id, "task_session_bound", now, {"session_id": session_id})

    def execute_lease(self, lease: RunLease, *, runner: Callable[..., Result], planner_client: Any = None,
                      chat_client: Any = None, current_session: AgentSessionState | Mapping[str, Any] | None = None,
                      allowed_scope_bindings: Mapping[str, Any] | None = None,
                      runner_options: Mapping[str, Any] | None = None) -> Result:
        # Validate fencing before invoking any canonical workflow/provider code.
        with self._connection(write=False) as connection:
            row = self._owned(connection, lease)
            if row["status"] != "leased" or row["execution_started_at"] is not None:
                return Result.ok("Onceki calisma yeniden baslatilmadi.", close_dialog=False,
                                 data={"run": self._run(row), "executed": False})
        if not callable(runner) or (planner_client is None and chat_client is None):
            raise ScheduleValidationError("Current shared runner and provider client required.")
        options = dict(runner_options or {})
        if not set(options).issubset({"domain", "db_name", "persist", "task_store_root", "progress_callback", "max_steps", "max_replans", "runtime_context"}):
            raise ScheduleValidationError("Scheduler options cannot convey approval or plans.")
        configuration = _configuration(lease.schedule)
        for name, maximum in configuration["budget"].items():
            requested = options.get(name, maximum)
            if type(requested) is not int or requested < (1 if name == "max_steps" else 0):
                raise ScheduleValidationError("Invalid bounded runner options.")
            options[name] = min(requested, maximum)
        options.setdefault("persist", True)
        if current_session is None:
            current = AgentSessionState(goal="Scheduled fresh workflow", active_domain=options.get("domain") or "general")
        else:
            current = current_session if isinstance(current_session, AgentSessionState) else AgentSessionState.from_dict(dict(current_session))
        if "runtime_context" not in options:
            metadata = current.active_entities.get("runtime_context")
            if isinstance(metadata, dict):
                metadata = {key: deepcopy(metadata[key]) for key in ("source", "provider_id", "model_name") if key in metadata}
                if metadata:
                    options["runtime_context"] = metadata
        if (current.pending_actions or current.active_pending_action_id
                or current.status in {"paused", "pending_approval", "awaiting_approval"}
                or (current.status == "running" and (current.completed_steps or current.remaining_steps))):
            stopped = Result.fail("Mevcut calisma kullanici karari bekliyor; planli is yeniden baslatilmadi.", close_dialog=False)
            receipt = self._settle(lease, stopped, override_status="blocked", reason="current_session_requires_attention",
                                   blocked_by_session_id=current.session_id)
            return Result.fail(stopped.message, close_dialog=False, data={"run": receipt, "executed": False})
        original_progress = options.get("progress_callback")
        def progress(*args, **kwargs):
            self.heartbeat(lease)
            if callable(original_progress):
                original_progress(*args, **kwargs)
        options["progress_callback"] = progress
        started = False
        def shared_runner(goal, **kwargs):
            nonlocal started
            self._begin_execution(lease, kwargs["session_state"])
            started = True
            return runner(goal, **kwargs)
        try:
            result = workflow_store.run_workflow(configuration["workflow_id"], revision_id=configuration["revision_id"],
                parameters=configuration["parameters"], runner=shared_runner, planner_client=planner_client,
                chat_client=chat_client, current_session=current, allowed_scope_bindings=allowed_scope_bindings,
                root=self.workflow_root, runner_options=options)
            if not isinstance(result, Result):
                raise TypeError("Shared workflow runner must return Result.")
            receipt = self._settle(lease, result)
            acknowledged = receipt["status"] in {"completed", "paused", "awaiting_approval"}
            message = result.message if acknowledged else "Planli calismanin sonucu kayitli gorevden kontrol edilmeli."
            return Result(success=bool(result.success and acknowledged), message=message, error=result.error, close_dialog=False,
                          data={"run": receipt, "executed": started, "workflow_result": deepcopy(result.data)})
        except (ScheduleConflictError, ScheduleIntegrityError):
            # A fencing/integrity failure cannot change somebody else's receipt.
            raise
        except Exception as exc:
            result = Result.fail("Planli calisma tamamlanamadi; kayitli durumdan kontrol edilmeli.", close_dialog=False)
            status = "recovery_required" if started else "failed"
            receipt = self._settle(lease, result, override_status=status, reason=type(exc).__name__)
            return Result.fail(result.message, close_dialog=False, data={"run": receipt, "executed": started})

    def reconcile_run(self, run_id: str, *, session_loader: Callable[[str], AgentSessionState | Mapping[str, Any]]) -> dict[str, Any]:
        """Read a trusted task checkpoint; never call a runner or approval action."""
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id) or not callable(session_loader):
            raise ScheduleValidationError("Run and trusted checkpoint loader required.")
        with self._connection(write=False) as connection:
            previous = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if previous is None:
                raise ScheduleValidationError("Unknown scheduled run.")
            if previous["status"] in _TERMINAL:
                return self._run(previous)
            receipt = json.loads(previous["receipt_json"])
            session_id = previous["session_id"] or receipt.get("blocked_by_session_id")
            if not session_id:
                return self._run(previous)
        try:
            checkpoint = session_loader(session_id)
        except (FileNotFoundError, OSError):
            # The active run remains blocked; an absent checkpoint cannot prove
            # that the original execution never happened.
            return self._run(previous)
        state = checkpoint.to_dict() if isinstance(checkpoint, AgentSessionState) else dict(checkpoint or {})
        if state.get("session_id") != session_id:
            raise ScheduleIntegrityError("Checkpoint identity differs from scheduled execution.")
        loaded = Result(success=state.get("status") in {"complete", "completed"}, close_dialog=False, data={"state": state})
        if previous["status"] == "blocked" and state.get("status") not in {"complete", "completed", "failed", "cancelled"}:
            return self._run(previous)
        if previous["status"] == "blocked":
            with self._connection(write=True) as connection:
                current = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if current["status"] == "blocked" and current["execution_started_at"] is None:
                    clean_receipt = json.loads(current["receipt_json"])
                    clean_receipt.pop("blocked_by_session_id", None)
                    connection.execute("UPDATE runs SET status='leased',lease_expires_at=?,receipt_json=?,updated_at=? WHERE run_id=?",
                                       (_iso(self._now()), _canonical(clean_receipt), _iso(self._now()), run_id))
                    self._event(connection, run_id, "admission_block_resolved", _iso(self._now()))
                return self._run(connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone())
        lease = self._lease(previous)
        return self._settle(lease, loaded, reason="trusted_task_checkpoint_reconciled")

    def dispatch_due(self, *, owner_id: str, runner: Callable[..., Result], planner_client: Any = None,
                     chat_client: Any = None, current_session: AgentSessionState | Mapping[str, Any] | None = None,
                     allowed_scope_bindings: Mapping[str, Any] | None = None,
                     scope_resolver: Callable[[dict[str, Any]], Mapping[str, Any]] | None = None,
                     runner_options: Mapping[str, Any] | None = None, max_runs: int = 1) -> Result:
        """Bounded dispatch, suitable for a later Qt timer/background worker."""
        leases = self.claim_due(owner_id=owner_id, max_runs=max_runs)
        results = []
        for lease in leases:
            context = dict(scope_resolver(lease.schedule)) if scope_resolver is not None else {
                "current_session": current_session, "allowed_scope_bindings": allowed_scope_bindings,
            }
            if not set(context).issubset({"current_session", "allowed_scope_bindings"}):
                raise ScheduleValidationError("Scope resolver cannot convey plans or approval.")
            result = self.execute_lease(lease, runner=runner, planner_client=planner_client, chat_client=chat_client,
                                        runner_options=runner_options, **context)
            results.append({"success": result.success, "message": result.message, "data": result.data})
        return Result.ok("Planli calisma kuyruğu kontrol edildi.", close_dialog=False,
                         data={"claimed_count": len(leases), "runs": [row["data"]["run"] for row in results], "results": results})
