"""Full tool-input JSON Schema validation; errors expose paths, never values."""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator


def _path(parts):
    return "arguments" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in parts)


def _nonfinite(value, path="arguments"):
    if isinstance(value, float) and not math.isfinite(value):
        return [path + ":nonfinite_number"]
    if isinstance(value, dict):
        return [error for key, child in value.items() for error in _nonfinite(child, path + "." + str(key))]
    if isinstance(value, (list, tuple)):
        return [error for index, child in enumerate(value) for error in _nonfinite(child, f"{path}[{index}]")]
    return []


def _has_external_reference(value):
    if isinstance(value, dict):
        return any(isinstance(value.get(key), str) and not value[key].startswith("#")
                   for key in ("$ref", "$dynamicRef")) or any(_has_external_reference(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_external_reference(child) for child in value)
    return False


@lru_cache(maxsize=256)
def _validator(serialized_schema):
    schema = json.loads(serialized_schema)
    Draft202012Validator.check_schema(schema)
    if _has_external_reference(schema):
        raise ValueError("External tool-schema references are not runtime sources")
    return Draft202012Validator(schema)


def validate_tool_arguments(tool, arguments: Any) -> list[str]:
    """Resolve bindings before validation, inject trusted runtime objects after it."""
    if not isinstance(arguments, dict):
        return ["arguments:type"]
    problems = _nonfinite(arguments)
    try:
        schema = tool.parameters if isinstance(tool.parameters, dict) else {}
        validator = _validator(json.dumps(schema, sort_keys=True, ensure_ascii=False, allow_nan=False))
        for error in validator.iter_errors(arguments):
            path = _path(error.absolute_path)
            if error.validator == "required":
                problems.extend(path + "." + key + ":required" for key in error.validator_value if key not in error.instance)
            elif error.validator == "additionalProperties" and error.validator_value is False:
                properties = error.schema.get("properties") or {}
                patterns = error.schema.get("patternProperties") or {}
                # jsonschema's diagnostic can contain user values. Derive only
                # the unknown property names, preserving patternProperties.
                problems.extend(path + "." + str(key) + ":unknown" for key in error.instance
                                if key not in properties and not any(re.search(pattern, key) for pattern in patterns))
            else:
                problems.append(path + ":" + str(error.validator))
    except Exception:
        problems.append("arguments:invalid_tool_schema")
    return sorted(set(problems))
