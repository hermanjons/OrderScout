"""Keep source freshness authority separate from permission to prepare output.

The boundary is native task state, never a plan argument. Existing-only tasks
can transform granted observations and propose a new export; they cannot fetch
replacement data, delegate fresh research, or execute an effect.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps


ALLOW_FRESH = "allow_fresh_sources"
EXISTING_ONLY = "existing_verified_sources_only"
SOURCE_POLICIES = (ALLOW_FRESH, EXISTING_ONLY)
_CURRENT = ContextVar("orderscout_source_policy", default=ALLOW_FRESH)
_TRANSFORMS = frozenset({
    "approvals.cancel",
    "operations.discover", "artifacts.read", "analysis.calculate", "analysis.table",
    "reports.build_snapshot", "reports.xlsx.prepare", "web.research_report",
    "web.research_report_xlsx.prepare",
})


def source_policy(payload):
    value = (payload or {}).get("source_policy", ALLOW_FRESH)
    if value not in SOURCE_POLICIES:
        raise ValueError("invalid_source_policy")
    return value


def state_source_policy(state):
    saved = state.active_entities.get("source_access_policy")
    if saved is not None:
        if not isinstance(saved, dict) or saved.get("version") != 1:
            raise ValueError("invalid_saved_source_policy")
        return source_policy(saved)
    return source_policy(state.active_entities.get("turn_interpretation") or {})


@contextmanager
def source_access_context(policy):
    if policy not in SOURCE_POLICIES:
        raise ValueError("invalid_source_policy")
    # Nested model work cannot widen the enclosing task's source authority.
    effective = EXISTING_ONLY if EXISTING_ONLY in (policy, _CURRENT.get()) else ALLOW_FRESH
    token = _CURRENT.set(effective)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def source_operation_problems(operation_id, authorization=None, *, state=None):
    policy = state_source_policy(state) if state is not None else source_policy(authorization)
    if EXISTING_ONLY in (policy, _CURRENT.get()) and operation_id not in _TRANSFORMS:
        return ["source_policy:fresh_source_or_effect_not_authorized"]
    return []


def restrict_source_tools(registry):
    return {name: tool for name, tool in registry.items()
            if not source_operation_problems(name)}


def task_source_boundary(function):
    @wraps(function)
    def run(*args, **kwargs):
        policy = source_policy(kwargs.get("turn_interpretation") or {})
        with source_access_context(policy):
            return function(*args, **kwargs)
    return run


def continuation_source_boundary(function):
    @wraps(function)
    def run(state, *args, **kwargs):
        with source_access_context(state_source_policy(state)):
            return function(state, *args, **kwargs)
    return run
