"""Reusable user instructions, never saved execution graphs or approvals.

Storage is a separate local SQLite catalog. SQLite handles interrupted journal
recovery; readers never create a catalog or modify workflow records. Product
approval/execute registration remains the responsibility of the shared adapter.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Mapping
import uuid

from AI.constants.paths import AI_DOMAIN_ROOT
from AI.processors.session_state import ActiveScope, AgentSessionState


SCHEMA_VERSION = 1
_APPLICATION_ID = 0x4F535746
_ID = re.compile(r"[a-z0-9_-]{1,96}\Z", re.ASCII)
_NAME = re.compile(r"[a-z][a-z0-9_]{0,47}\Z", re.ASCII)
_REVISION = re.compile(r"wfr_[0-9a-f]{64}\Z", re.ASCII)
_PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_]{0,47})\s*\}\}", re.ASCII)
_PATH = re.compile(r"(?:[a-zA-Z]:[\\/]|\\\\|(?:^|\s)(?:/|\.\.?[\\/])|file://)")
_RELATIVE_FILE = re.compile(r"(?<![\w:/])[\w.-]+[/\\][^\s]+\.(?:csv|json|xlsx?|sqlite3?|db|txt)\b", re.IGNORECASE)
_SECRET = re.compile(r"(?:\b(?:api[_ -]?key|api[_ -]?secret|password|credential|approval[_ -]?token)\s*[:=]\s*\S+|\bBearer\s+\S+|\bsk-[a-zA-Z0-9_-]{12,})", re.IGNORECASE)
_AUTHORITY = re.compile(r"[\"']?\b(?:pending_actions?|approval_tokens?|tool_results?|observations?|completed_steps|step_graph|action_id|credentials)[\"']?\s*[:=]", re.IGNORECASE)
_FORBIDDEN = {"approval", "approval_token", "approved_by", "pending_action", "pending_actions", "action_id",
              "observations", "observation", "tool_result", "tool_results", "completed_steps", "step_graph",
              "credentials", "credential", "api_key", "api_secret", "password", "token", "secret", "source_path",
              "output_path", "path", "db_name", "source_snapshot", "selection_snapshot", "selection_id"}
_SCOPE_TYPES = {"account_id": "integer", "environment": "string", "attachment_id": "string",
                "store_name": "string", "record_id": "integer", "record_number": "string"}
_KNOWN_SCOPES = {"account_id": "account_id", "account_ids": "account_id", "api_account_id": "account_id",
                 "api_account_ids": "account_id", "environment": "environment", "attachment_id": "attachment_id",
                 "attachment_ids": "attachment_id", "store_name": "store_name", "record_id": "record_id",
                 "record_ids": "record_id", "record_number": "record_number", "record_numbers": "record_number"}
_SPEC_KEYS = {"schema_version", "name", "instructions", "objective_template", "parameter_schema", "source_policy", "effect_policy"}
_ACTION_KEYS = {"schema_version", "action_type", "workflow_id", "expected_revision_id", "revision_id", "spec",
                "spec_hash", "requires_current_approval", "action_hash", "action_id"}


class WorkflowValidationError(ValueError):
    pass


class WorkflowConflictError(ValueError):
    pass


class WorkflowIntegrityError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _workflow_id(value: Any) -> str:
    reserved = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}
    if not isinstance(value, str) or _ID.fullmatch(value) is None or value in reserved:
        raise WorkflowValidationError("Workflow ID must be an exact canonical lowercase ASCII identifier.")
    return value


def _revision_id(value: Any, *, empty: bool = False) -> str:
    if empty and value == "":
        return ""
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise WorkflowValidationError("Invalid immutable workflow revision ID.")
    return value


def _safe_text(value: Any, field: str, *, limit: int = 12000, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()) or len(value) > limit or "\x00" in value:
        raise WorkflowValidationError(f"Invalid {field} text.")
    path_text = re.sub(r"https?://\S+", "", value, flags=re.IGNORECASE)
    if _PATH.search(path_text) or _RELATIVE_FILE.search(path_text) or _SECRET.search(value) or _AUTHORITY.search(value):
        raise WorkflowValidationError(f"{field} cannot embed credentials or arbitrary file-path authority.")
    return value  # Exact user text, including intentional whitespace.


def _matches_type(value: Any, kind: str) -> bool:
    if kind == "boolean":
        return type(value) is bool
    if kind == "integer":
        return type(value) is int
    if kind == "number":
        return type(value) is int or (type(value) is float and math.isfinite(value))
    return isinstance(value, str) if kind == "string" else isinstance(value, list) if kind == "array" else False


def _parameter_schema(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"type", "properties", "required", "additionalProperties"}:
        raise WorkflowValidationError("Parameter schema must be a bounded typed object with no additional properties.")
    properties, required = value["properties"], value["required"]
    if value["type"] != "object" or value["additionalProperties"] is not False or not isinstance(properties, dict) or len(properties) > 32:
        raise WorkflowValidationError("Invalid workflow parameter object schema.")
    if not isinstance(required, list) or any(not isinstance(name, str) for name in required) or len(set(required)) != len(required) or not set(required).issubset(properties):
        raise WorkflowValidationError("Required parameter names do not match the schema.")
    allowed = {"type", "description", "enum", "minimum", "maximum", "minLength", "maxLength", "format", "scope", "items", "minItems", "maxItems"}
    for name, definition in properties.items():
        if not isinstance(name, str) or _NAME.fullmatch(name) is None or name in _FORBIDDEN:
            raise WorkflowValidationError("Parameter name embeds unsupported authority.")
        if not isinstance(definition, dict) or not set(definition).issubset(allowed):
            raise WorkflowValidationError(f"Unsupported parameter schema for {name}.")
        kind = definition.get("type")
        if kind not in {"string", "integer", "number", "boolean", "array"}:
            raise WorkflowValidationError(f"Unsupported parameter type for {name}.")
        if "description" in definition:
            _safe_text(definition["description"], f"parameter {name}", limit=1000)
        if kind == "array":
            items = definition.get("items")
            if not isinstance(items, dict) or set(items) != {"type"} or items["type"] not in {"string", "integer", "number", "boolean"}:
                raise WorkflowValidationError("Array parameters support scalar items only.")
        elif "items" in definition or "minItems" in definition or "maxItems" in definition:
            raise WorkflowValidationError("Only array parameters have item constraints.")
        for lower, upper, valid_kind in (("minimum", "maximum", {"integer", "number"}), ("minLength", "maxLength", {"string"}), ("minItems", "maxItems", {"array"})):
            for key in (lower, upper):
                if key in definition and (kind not in valid_kind or not _matches_type(definition[key], "number") or (key not in {"minimum", "maximum"} and (type(definition[key]) is not int or definition[key] < 0))):
                    raise WorkflowValidationError(f"Invalid {key} constraint.")
            if lower in definition and upper in definition and definition[lower] > definition[upper]:
                raise WorkflowValidationError("Parameter bounds are reversed.")
        if "format" in definition and (kind != "string" or definition["format"] != "date"):
            raise WorkflowValidationError("Only ISO date string formatting is supported.")
        if "enum" in definition:
            enum = definition["enum"]
            if kind == "array" or not isinstance(enum, list) or not enum or len(enum) > 32 or any(not _matches_type(item, kind) for item in enum):
                raise WorkflowValidationError("Invalid typed parameter enumeration.")
            for item in enum:
                if isinstance(item, str):
                    _safe_text(item, "parameter enum", limit=1000, allow_empty=True)
        scope = definition.get("scope")
        if scope is not None and (not isinstance(scope, str) or scope not in _SCOPE_TYPES or (definition["items"]["type"] if kind == "array" else kind) != _SCOPE_TYPES[scope]):
            raise WorkflowValidationError("Scope parameter has an invalid scope or type.")
        if name in _KNOWN_SCOPES and scope != _KNOWN_SCOPES[name]:
            raise WorkflowValidationError("Scope-shaped parameters must declare their fresh scope binding.")
    return value


def _validate_spec(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _SPEC_KEYS or type(payload["schema_version"]) is not int or payload["schema_version"] != SCHEMA_VERSION:
        raise WorkflowValidationError("Unsupported workflow spec fields or version.")
    _safe_text(payload["name"], "name", limit=160)
    _safe_text(payload["instructions"], "instructions")
    template = _safe_text(payload["objective_template"], "objective_template", limit=6000)
    schema = _parameter_schema(payload["parameter_schema"])
    residue = _PLACEHOLDER.sub("", template)
    if "{{" in residue or "}}" in residue:
        raise WorkflowValidationError("Templates support only literal {{parameter}} placeholders.")
    if any(name not in schema["properties"] for name in _PLACEHOLDER.findall(template)):
        raise WorkflowValidationError("Template references an undeclared parameter.")
    for field, flag in (("source_policy", "requires_current_sources"), ("effect_policy", "requires_current_approval")):
        policy = payload[field]
        if not isinstance(policy, dict) or set(policy) != {"description", flag} or policy[flag] is not True:
            raise WorkflowValidationError("Workflow policies require fresh sources and current operation approval.")
        _safe_text(policy["description"], field, limit=2000)
    if len(_canonical(payload).encode("utf-8")) > 65536:
        raise WorkflowValidationError("Workflow spec exceeds the storage limit.")
    return payload


@dataclass(frozen=True)
class WorkflowSpec:
    _canonical_json: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "_canonical_json", _canonical(_validate_spec(json.loads(self._canonical_json))))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowSpec":
        return cls(_canonical(dict(value)))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical_json)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self._canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WorkflowRevision:
    workflow_id: str
    revision_id: str
    parent_revision_id: str
    spec: WorkflowSpec
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {"workflow_id": self.workflow_id, "revision_id": self.revision_id, "parent_revision_id": self.parent_revision_id,
                "spec": self.spec.to_dict(), "spec_hash": self.spec.content_hash, "created_at": self.created_at}


def _new_revision_id(workflow_id: str, parent_id: str, spec: WorkflowSpec) -> str:
    return "wfr_" + _hash({"workflow_id": workflow_id, "parent_revision_id": parent_id, "spec_hash": spec.content_hash})


def prepare_workflow_save(spec: WorkflowSpec | Mapping[str, Any], *, workflow_id: str | None = None,
                          expected_revision_id: str = "") -> dict[str, Any]:
    """Produce an exact reviewable proposal; does not create files or authorize it."""
    spec = spec if isinstance(spec, WorkflowSpec) else WorkflowSpec.from_dict(spec)
    workflow_id = _workflow_id(workflow_id if workflow_id is not None else "wf_" + uuid.uuid4().hex)
    expected_revision_id = _revision_id(expected_revision_id, empty=True)
    core = {"schema_version": SCHEMA_VERSION, "action_type": "workflow.save_spec", "workflow_id": workflow_id,
            "expected_revision_id": expected_revision_id, "revision_id": _new_revision_id(workflow_id, expected_revision_id, spec),
            "spec": spec.to_dict(), "spec_hash": spec.content_hash, "requires_current_approval": True}
    digest = _hash(core)
    return {**core, "action_hash": digest, "action_id": "wfa_" + digest}


def _validated_action(action: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(action)
    if set(value) != _ACTION_KEYS:
        raise WorkflowValidationError("Save proposal contains unsupported authority or fields.")
    expected = prepare_workflow_save(value["spec"], workflow_id=value["workflow_id"], expected_revision_id=value["expected_revision_id"])
    if _canonical(value) != _canonical(expected):
        raise WorkflowIntegrityError("The reviewed workflow proposal changed; prepare a new proposal.")
    return expected


def render_workflow_review(spec: WorkflowSpec | Mapping[str, Any]) -> str:
    data = (spec if isinstance(spec, WorkflowSpec) else WorkflowSpec.from_dict(spec)).to_dict()
    # Review the complete typed contract: required fields, bounds and enum values
    # affect what the saved instructions may accept on a later invocation.
    parameter_schema = data["parameter_schema"]
    type_labels = {"string": "metin", "integer": "tam sayı", "number": "sayı", "boolean": "evet/hayır", "array": "liste"}
    scope_labels = {"account_id": "güncel hesap", "environment": "güncel ortam", "attachment_id": "bu sohbetin ek dosyası",
                    "store_name": "güncel mağaza", "record_id": "güncel kayıt kimliği", "record_number": "güncel kayıt numarası"}
    parameter_lines = []
    for name, definition in parameter_schema["properties"].items():
        parts = [type_labels[definition["type"]], "zorunlu" if name in parameter_schema["required"] else "isteğe bağlı"]
        if definition.get("description"):
            parts.append(definition["description"])
        for key, label in (("minimum", "en az"), ("maximum", "en çok"),
                           ("minLength", "en az karakter"), ("maxLength", "en çok karakter"),
                           ("minItems", "en az öğe"), ("maxItems", "en çok öğe")):
            if key in definition:
                parts.append(f"{label}: {definition[key]}")
        if "items" in definition:
            parts.append("liste öğeleri: " + type_labels[definition["items"]["type"]])
        if "enum" in definition:
            parts.append("izin verilen değerler: " + ", ".join(_canonical(value) for value in definition["enum"]))
        if definition.get("format") == "date":
            parts.append("tarih biçimi: YYYY-AA-GG")
        if definition.get("scope"):
            parts.append("yalnız bu çalışmada doğrulanan " + scope_labels[definition["scope"]])
        parameter_lines.append(f"- {name}: " + "; ".join(parts))
    parameter_review = ("\n".join(parameter_lines) or "Parametre yok.") + "\nBaşka parametre kabul edilmez."
    return (f"{data['name']}\n\nTalimatlar:\n{data['instructions']}\n\nAmaç:\n{data['objective_template']}\n\n"
            f"Parametreler:\n{parameter_review}\n\nKaynaklar:\n{data['source_policy']['description']}\n"
            "Her çalıştırmada güncel kaynak gerekir: evet.\n\n"
            f"İşlem onayı:\n{data['effect_policy']['description']}\n"
            "Her işlem için güncel onay gerekir: evet.")


def workflow_store_path(*, root: str | Path | None = None) -> Path:
    return (Path(root) if root is not None else AI_DOMAIN_ROOT / "workflows") / "workflow_store.sqlite3"


def _check_store(connection: sqlite3.Connection, *, initialise: bool) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    application = connection.execute("PRAGMA application_id").fetchone()[0]
    if version == SCHEMA_VERSION and application == _APPLICATION_ID:
        return
    tables = connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    if not initialise or version != 0 or application != 0 or tables:
        raise WorkflowIntegrityError("Unsupported or unrelated workflow catalog format.")
    connection.execute("CREATE TABLE workflow_heads (workflow_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL)")
    connection.execute("CREATE TABLE workflow_revisions (workflow_id TEXT NOT NULL, revision_id TEXT NOT NULL, parent_revision_id TEXT NOT NULL, spec_json TEXT NOT NULL, spec_hash TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(workflow_id, revision_id))")
    connection.execute("CREATE TRIGGER immutable_revision_update BEFORE UPDATE ON workflow_revisions BEGIN SELECT RAISE(ABORT, 'Immutable workflow revision'); END")
    connection.execute("CREATE TRIGGER immutable_revision_delete BEFORE DELETE ON workflow_revisions BEGIN SELECT RAISE(ABORT, 'Immutable workflow revision'); END")
    connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


@contextmanager
def _connection(*, root: str | Path | None, write: bool):
    path = workflow_store_path(root=root)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.is_file():
        raise FileNotFoundError("Workflow catalog does not exist.")
    # rw allows SQLite to recover a hot journal after an actual process loss;
    # query_only is enabled after identity/recovery checks for normal readers.
    connection = sqlite3.connect(str(path) if write else path.absolute().as_uri() + "?mode=rw", uri=not write, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        if write:
            if connection.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
                raise WorkflowIntegrityError("Workflow catalog must use the durable DELETE journal format.")
            connection.execute("PRAGMA synchronous=EXTRA")
            connection.execute("BEGIN IMMEDIATE")
            _check_store(connection, initialise=True)
        else:
            _check_store(connection, initialise=False)
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
        yield connection
        if write:
            connection.execute("COMMIT")
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()


def _decode_revision(row: sqlite3.Row) -> WorkflowRevision:
    try:
        spec = WorkflowSpec(row["spec_json"])
        workflow_id = _workflow_id(row["workflow_id"])
        parent = _revision_id(row["parent_revision_id"], empty=True)
        revision_id = _revision_id(row["revision_id"])
        if spec.content_hash != row["spec_hash"] or revision_id != _new_revision_id(workflow_id, parent, spec):
            raise WorkflowIntegrityError("Workflow revision content hash or identity changed.")
        return WorkflowRevision(workflow_id, revision_id, parent, spec, row["created_at"])
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, WorkflowIntegrityError):
            raise
        raise WorkflowIntegrityError("Invalid workflow revision payload.") from exc


def _insert_revision(connection: sqlite3.Connection, revision: WorkflowRevision) -> None:
    connection.execute("INSERT INTO workflow_revisions VALUES (?, ?, ?, ?, ?, ?)",
                       (revision.workflow_id, revision.revision_id, revision.parent_revision_id,
                        revision.spec._canonical_json, revision.spec.content_hash, revision.created_at))


def _load_revision(connection: sqlite3.Connection, workflow_id: str, revision_id: str) -> WorkflowRevision:
    requested = None
    seen = set()
    while revision_id:
        if revision_id in seen:
            raise WorkflowIntegrityError("Workflow revision chain contains a cycle.")
        seen.add(revision_id)
        row = connection.execute("SELECT * FROM workflow_revisions WHERE workflow_id=? AND revision_id=?", (workflow_id, revision_id)).fetchone()
        if row is None:
            raise WorkflowIntegrityError("Requested workflow revision or its parent is missing.")
        decoded = _decode_revision(row)
        requested = requested or decoded
        revision_id = decoded.parent_revision_id
    if requested is None:
        raise WorkflowIntegrityError("Workflow revision identity is empty.")
    return requested


def save_prepared_workflow(action: Mapping[str, Any], *, root: str | Path | None = None) -> WorkflowRevision:
    """Commit a reviewed proposal. Shared approval adapter must authorize this API.

    The proposal's action ID is its immutable content identity, never an approval
    token. Replaying a committed proposal cannot rewind a later head revision.
    """
    value = _validated_action(action)
    with _connection(root=root, write=True) as connection:
        existing = connection.execute("SELECT * FROM workflow_revisions WHERE workflow_id=? AND revision_id=?",
                                      (value["workflow_id"], value["revision_id"])).fetchone()
        if existing is not None:
            return _load_revision(connection, value["workflow_id"], value["revision_id"])
        head = connection.execute("SELECT revision_id FROM workflow_heads WHERE workflow_id=?", (value["workflow_id"],)).fetchone()
        actual = head["revision_id"] if head else ""
        if actual:
            _load_revision(connection, value["workflow_id"], actual)
        if actual != value["expected_revision_id"]:
            raise WorkflowConflictError("Workflow changed after preparation; review a new revision.")
        revision = WorkflowRevision(value["workflow_id"], value["revision_id"], value["expected_revision_id"],
                                    WorkflowSpec.from_dict(value["spec"]), datetime.now(timezone.utc).isoformat())
        _insert_revision(connection, revision)
        connection.execute("INSERT INTO workflow_heads VALUES (?, ?) ON CONFLICT(workflow_id) DO UPDATE SET revision_id=excluded.revision_id",
                           (revision.workflow_id, revision.revision_id))
        return revision


def read_workflow(workflow_id: str, *, revision_id: str | None = None, root: str | Path | None = None) -> WorkflowRevision:
    workflow_id = _workflow_id(workflow_id)
    if revision_id is not None:
        _revision_id(revision_id)
    with _connection(root=root, write=False) as connection:
        if revision_id is None:
            head = connection.execute("SELECT revision_id FROM workflow_heads WHERE workflow_id=?", (workflow_id,)).fetchone()
            if head is None:
                raise KeyError("Workflow not found.")
            revision_id = head["revision_id"]
        return _load_revision(connection, workflow_id, revision_id)


def list_workflows(*, root: str | Path | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise WorkflowValidationError("Invalid workflow list limit.")
    if not workflow_store_path(root=root).is_file():
        return []
    with _connection(root=root, write=False) as connection:
        rows = connection.execute("SELECT h.workflow_id, h.revision_id FROM workflow_heads h LEFT JOIN workflow_revisions r ON r.workflow_id=h.workflow_id AND r.revision_id=h.revision_id ORDER BY r.created_at DESC, h.workflow_id LIMIT ?", (limit,)).fetchall()
        return [{"workflow_id": revision.workflow_id, "revision_id": revision.revision_id,
                 "name": revision.spec.to_dict()["name"], "spec_hash": revision.spec.content_hash, "created_at": revision.created_at}
                for revision in (_load_revision(connection, row["workflow_id"], row["revision_id"]) for row in rows)]


def list_workflow_revisions(workflow_id: str, *, root: str | Path | None = None) -> list[WorkflowRevision]:
    workflow_id = _workflow_id(workflow_id)
    with _connection(root=root, write=False) as connection:
        ids = connection.execute("SELECT revision_id FROM workflow_revisions WHERE workflow_id=? ORDER BY rowid", (workflow_id,)).fetchall()
        return [_load_revision(connection, workflow_id, row["revision_id"]) for row in ids]


def validate_workflow_parameters(spec: WorkflowSpec, parameters: Mapping[str, Any], *,
                                 allowed_scope_bindings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    schema = spec.to_dict()["parameter_schema"]
    values = dict(parameters)
    if not set(values).issubset(schema["properties"]) or not set(schema["required"]).issubset(values):
        raise WorkflowValidationError("Missing or undeclared workflow parameters.")
    for name, value in values.items():
        definition = schema["properties"][name]
        kind = definition["type"]
        if not _matches_type(value, kind):
            raise WorkflowValidationError(f"Parameter {name} has the wrong type.")
        items = value if kind == "array" else [value]
        if kind == "array" and (len(value) > min(100, definition.get("maxItems", 100)) or len(value) < definition.get("minItems", 0) or any(not _matches_type(item, definition["items"]["type"]) for item in value)):
            raise WorkflowValidationError("Invalid parameter array.")
        for item in items:
            if isinstance(item, str):
                _safe_text(item, f"parameter {name}", limit=4000, allow_empty=not definition.get("scope"))
            if kind in {"integer", "number"} and not definition.get("minimum", -math.inf) <= value <= definition.get("maximum", math.inf):
                raise WorkflowValidationError("Parameter is outside its numeric bounds.")
        if kind == "string":
            if not definition.get("minLength", 0) <= len(value) <= min(4000, definition.get("maxLength", 4000)):
                raise WorkflowValidationError("Parameter is outside its text bounds.")
            if definition.get("format") == "date":
                try:
                    if date.fromisoformat(value).isoformat() != value:
                        raise ValueError()
                except ValueError as exc:
                    raise WorkflowValidationError("Parameter is not an exact ISO date.") from exc
        if "enum" in definition and value not in definition["enum"]:
            raise WorkflowValidationError("Parameter is not an allowed typed enum value.")
        if definition.get("scope"):
            allowed = (allowed_scope_bindings or {}).get(definition["scope"])
            if not isinstance(allowed, (list, tuple, set)) or any(not any(type(item) is type(candidate) and item == candidate for candidate in allowed) for item in items):
                raise WorkflowValidationError("Scope parameters must match fresh current-session bindings.")
    return json.loads(_canonical(values))


def render_workflow(spec: WorkflowSpec, parameters: Mapping[str, Any], *,
                    allowed_scope_bindings: Mapping[str, Any] | None = None) -> str:
    values = validate_workflow_parameters(spec, parameters, allowed_scope_bindings=allowed_scope_bindings)
    data = spec.to_dict()
    def substitute(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise WorkflowValidationError("A template parameter is missing.")
        value = values[name]
        return value if isinstance(value, str) else _canonical(value)
    objective = _PLACEHOLDER.sub(substitute, data["objective_template"])
    return (objective + "\n\nKullanıcının iş talimatları:\n" + data["instructions"] +
            "\n\nÇalıştırma parametreleri:\n" + _canonical(values) +
            "\n\nKaynak politikası:\n" + data["source_policy"]["description"] +
            "\n\nİşlem onayı politikası:\n" + data["effect_policy"]["description"])


def prepare_workflow_invocation(workflow_id: str, *, parameters: Mapping[str, Any],
                                current_session: AgentSessionState | Mapping[str, Any] | None = None,
                                allowed_scope_bindings: Mapping[str, Any] | None = None,
                                revision_id: str | None = None, domain: str = "general",
                                root: str | Path | None = None,
                                runtime_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Read the exact revision and prepare a fresh UI/runtime goal and state.

    This has no execution effect. Validation failures leave the caller's current
    state intact; neither historical receipts nor approval authority are copied.
    """
    if not isinstance(domain, str) or not domain or not domain.isidentifier():
        raise WorkflowValidationError("Invalid workflow invocation domain.")
    runtime = runtime_context
    if runtime is not None and (not isinstance(runtime, dict) or not set(runtime).issubset({"source", "provider_id", "model_name"})):
        raise WorkflowValidationError("Current runtime metadata contains unsupported authority.")
    previous = current_session if isinstance(current_session, AgentSessionState) else AgentSessionState.from_dict(dict(current_session or {"goal": ""}))
    if previous.pending_actions or previous.active_pending_action_id:
        raise WorkflowValidationError("Resolve the current pending action before starting a workflow.")
    revision = read_workflow(workflow_id, revision_id=revision_id, root=root)
    goal = render_workflow(revision.spec, parameters, allowed_scope_bindings=allowed_scope_bindings)
    fresh = AgentSessionState(goal=goal, active_domain=domain)
    values = validate_workflow_parameters(revision.spec, parameters, allowed_scope_bindings=allowed_scope_bindings)
    scope_values = {}
    for name, definition in revision.spec.to_dict()["parameter_schema"]["properties"].items():
        if name in values and definition.get("scope"):
            value = values[name]
            scope_values.setdefault(definition["scope"], []).extend(value if isinstance(value, list) else [value])
    for name, scope in previous.active_scopes.items():
        fresh.active_scopes[name] = ActiveScope.create(
            domain=scope.domain, account_ids=scope_values.get("account_id") or scope.account_ids,
            company_ids=scope.company_ids, marketplaces=scope.marketplaces,
            environments=scope_values.get("environment") or scope.environments,
            filters={}, source="workflow_current_session",
        )
    owner = previous.active_entities.get("file_workspace_session_id")
    if isinstance(owner, str) and owner:
        fresh.active_entities["file_workspace_session_id"] = owner
    attachments = scope_values.get("attachment_id") or []
    if attachments:
        workspace = previous.active_entities.get("file_workspace")
        if (not isinstance(workspace, dict) or not isinstance(workspace.get("session_id"), str)
                or not workspace["session_id"] or not isinstance(workspace.get("attachments"), list)):
            raise WorkflowValidationError("Attachment workflow requires the current picker-granted file workspace.")
        metadata = {row.get("attachment_id"): row for row in workspace["attachments"]
                    if isinstance(row, dict) and isinstance(row.get("attachment_id"), str)}
        if not set(attachments).issubset(metadata):
            raise WorkflowValidationError("Attachment parameters must belong to the current picker-granted workspace.")
        from AI.processors.file_workspace import list_attachments
        listed = list_attachments(session_id=workspace["session_id"])
        live_metadata = {row["attachment_id"]: row for row in (listed.data or {}).get("attachments", [])} if listed.success else {}
        public_fields = {"attachment_id", "name", "format", "size_bytes", "sha256", "session_id", "imported_at", "manifest"}
        if any(identity not in live_metadata
               or not public_fields.issubset(metadata[identity])
               or not set(metadata[identity]).issubset(public_fields | {"content_name"})
               or any(metadata[identity][key] != live_metadata[identity].get(key) for key in public_fields)
               or ("content_name" in metadata[identity]
                   and metadata[identity]["content_name"] != live_metadata[identity].get("content_name"))
               for identity in attachments):
            raise WorkflowValidationError("Current attachment manifests did not pass the immutable workspace check.")
        fresh.active_entities["file_workspace"] = {
            "session_id": workspace["session_id"],
            "attachments": [json.loads(_canonical({key: metadata[identity][key] for key in public_fields}))
                            for identity in dict.fromkeys(attachments)],
        }
    if runtime is not None:
        fresh.active_entities["runtime_context"] = json.loads(_canonical(runtime))
    fresh.active_entities["workflow_invocation"] = {"workflow_id": revision.workflow_id, "revision_id": revision.revision_id,
                                                   "spec_hash": revision.spec.content_hash, "fresh_model_plan_required": True,
                                                   "requires_current_sources": True, "requires_current_approval": True}
    return {"revision": revision, "goal": goal, "session_state": fresh.to_dict()}


def run_workflow(workflow_id: str, *, parameters: Mapping[str, Any], runner: Callable[..., Any],
                 planner_client: Any = None, chat_client: Any = None,
                 current_session: AgentSessionState | Mapping[str, Any] | None = None,
                 allowed_scope_bindings: Mapping[str, Any] | None = None, revision_id: str | None = None,
                 root: str | Path | None = None, runner_options: Mapping[str, Any] | None = None) -> Any:
    """Submit fresh user instructions to an injected shared model runtime.

    The runner authors a new plan and retains exact current effect approval.
    """
    if not callable(runner) or (planner_client is None and chat_client is None):
        raise WorkflowValidationError("A current shared model runner/client is required.")
    options = dict(runner_options or {})
    if not set(options).issubset({"domain", "db_name", "persist", "task_store_root", "progress_callback", "max_steps", "max_replans", "runtime_context"}):
        raise WorkflowValidationError("Runner options cannot inject plans, source results, or approval authority.")
    invocation = prepare_workflow_invocation(
        workflow_id, parameters=parameters, current_session=current_session,
        allowed_scope_bindings=allowed_scope_bindings, revision_id=revision_id,
        domain=options.get("domain") or "general", root=root,
        runtime_context=options.get("runtime_context"),
    )
    return runner(invocation["goal"], session_state=invocation["session_state"],
                  planner_client=planner_client, chat_client=chat_client, **options)
