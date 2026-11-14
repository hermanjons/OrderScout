"""Bound the model's working set without deleting durable conversation or results.

Sizes here are UTF-8 bytes, not claims about a provider's tokenizer. Complete
values remain in AgentSessionState and are addressable by memory tools/bindings.
"""
from copy import deepcopy
import json


def json_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def _sample(value, *, strings, items, fields, depth):
    if isinstance(value, str):
        return value if len(value) <= strings else value[:strings] + " [excerpt; full value stored]"
    if isinstance(value, dict):
        if depth <= 0:
            return {"stored_type": "object", "field_count": len(value), "preview_only": True}
        # Technical evidence digests stay in the durable receipt. In a bounded
        # view they must not displace an actual result, its unit or its source.
        keys = sorted(value, key=lambda key: (
            str(key).endswith(("_hash", "_sha256")),
            isinstance(value[key], (dict, list, tuple))))
        result = {key: _sample(value[key], strings=strings, items=items, fields=fields, depth=depth - 1)
                  for key in keys[:fields]}
        if len(keys) > fields:
            result["_omitted_field_count"] = len(keys) - fields
        return result
    if isinstance(value, (list, tuple)):
        if depth <= 0:
            return {"stored_row_count": len(value), "preview_only": True}
        preview = [_sample(child, strings=strings, items=items, fields=fields, depth=depth - 1)
                   for child in value[:items]]
        return preview if len(value) <= items else {
            "stored_row_count": len(value), "preview_only": True, "first_rows": preview}
    return value


def bounded_preview(value, *, max_bytes=6000):
    if json_bytes(value) <= max_bytes:
        return deepcopy(value)
    for strings, items, fields, depth in ((1200, 3, 30, 6), (600, 2, 20, 5),
                                         (240, 1, 12, 4), (100, 1, 6, 2)):
        preview = {"preview_only": True, "full_value_stored": True,
                   "preview": _sample(value, strings=strings, items=items, fields=fields, depth=depth)}
        if json_bytes(preview) <= max_bytes:
            return preview
    return {"preview_only": True, "full_value_stored": True, "stored_type": type(value).__name__}


def compact_facts(value, *, max_bytes=1400):
    """Retain complete small fields, never infer business facts or sample rows."""
    if not isinstance(value, dict):
        return {}
    def scalar(item):
        return item is None or isinstance(item, (bool, int, float)) or isinstance(item, str) and len(item) <= 160
    candidates = []
    metadata = {"tool", "query", "query_fingerprint", "source_revision", "source_snapshot_hash", "evidence_hash",
                "account_by_order", "account_by_claim", "order_numbers", "returned_order_numbers", "sample_orders"}
    for key, item in value.items():
        if key in metadata or key.endswith(("_sha256", "_hash")):
            continue
        flat_map = isinstance(item, dict) and len(item) <= 32 and all(scalar(v) for v in item.values())
        flat_list = isinstance(item, list) and len(item) <= 12 and all(scalar(v) for v in item)
        if (scalar(item) or flat_map or flat_list) and json_bytes(item) <= 800:
            candidates.append((key, item))
    # Preserve actual measures before technical labels. Never sample a map or
    # turn record/account identity maps into purported business measurements.
    def priority(row):
        item = row[1]
        if isinstance(item, dict) and item and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in item.values()):
            return 0
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            return 1
        return 2 if isinstance(item, bool) else 3
    candidates.sort(key=priority)
    result = {}
    for key, item in candidates:
        if json_bytes({**result, key: item}) <= max_bytes:
            result[key] = deepcopy(item)
    return result


def conversation_window(turns, *, max_bytes=18000, max_turns=12):
    """A contiguous recent suffix; old turns remain retrievable by identity."""
    selected, used = [], 0
    for turn in reversed(turns[-max_turns:]):
        row = {"role": turn.role, "content": turn.content}
        size = json_bytes(row)
        if used + size > max_bytes:
            if not selected:
                excerpt = bounded_preview(turn.content, max_bytes=max_bytes // 2)
                row["content"] = ("Stored conversation excerpt (not the complete turn); use conversation.read "
                                  f"with turn_id={turn.turn_id} for the original: " +
                                  json.dumps(excerpt, ensure_ascii=False))
                selected.append(row)
            break
        selected.append(row)
        used += size
    return list(reversed(selected)), len(turns) - len(selected)


def context_size_record(prompt, definitions):
    messages = prompt.to_messages()
    history_count = len(getattr(prompt, "_conversation", []))
    request_index = 1 + history_count
    return {"measurement": "utf8_bytes_not_tokens", "instructions_bytes": json_bytes(messages[0]),
            "history_bytes": json_bytes(messages[1:request_index]),
            "request_and_context_bytes": json_bytes(messages[request_index]),
            "tool_history_bytes": json_bytes(messages[request_index + 1:]),
            "tool_schema_bytes": json_bytes(definitions), "visible_tools": len(definitions),
            "total_bytes": json_bytes(messages) + json_bytes(definitions)}
