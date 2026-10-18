"""Presentation structure for evidence-bound record answers.

This module recognizes output layout only. It does not interpret user requests,
select business operations, or admit new factual values.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any


_LIST_ORDINAL = re.compile(
    r"^(\s*(?:[-*+]\s+)?(?:\*\*|__)?)"
    r"(\d+)(\s*[.)-](?:\*\*|__)?\s+)"
)


def _plain(value: str) -> str:
    return re.sub(r"[*`_]", "", value).strip()


def _heading(value: str) -> str:
    value = unicodedata.normalize("NFKD", _plain(value).casefold().replace("ı", "i"))
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).split())


def _table_parts(line: str) -> list[str]:
    return re.split(r"(?<!\\)\|", line.rstrip("\r\n"))


def _table_ordinals(lines: list[str]) -> dict[int, tuple[int, int]]:
    """Recognize a labelled sequential ordinal column, never arbitrary numbers."""
    result: dict[int, tuple[int, int]] = {}
    labels = {"#", "no", "no.", "sira", "sira no", "sira no.", "sira numarasi", "index", "row", "row number"}
    for header_index in range(len(lines) - 1):
        header = _table_parts(lines[header_index])
        separator = _table_parts(lines[header_index + 1])
        cells = [cell.strip() for cell in separator if cell.strip()]
        if len(header) < 3 or not cells or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        column = next((i for i, cell in enumerate(header) if _heading(cell) in labels), None)
        if column is None:
            continue
        rows: list[tuple[int, int]] = []
        for line_index in range(header_index + 2, len(lines)):
            parts = _table_parts(lines[line_index])
            if len(parts) != len(header):
                break
            value = _plain(parts[column])
            if not value.isdecimal():
                break
            rows.append((line_index, int(value)))
        if rows and [value for _, value in rows] == list(range(1, len(rows) + 1)):
            result.update({index: (column, value) for index, value in rows})
    return result


def presentation_numeric_text(answer: str) -> str:
    """Remove only ordinal occurrences; equal numbers elsewhere remain claims."""
    lines = str(answer).splitlines(keepends=True)
    tables = _table_ordinals(lines)
    output = []
    for index, line in enumerate(lines):
        if index in tables:
            parts = _table_parts(line)
            parts[tables[index][0]] = " "
            output.append("|".join(parts) + ("\n" if line.endswith("\n") else ""))
        else:
            output.append(_LIST_ORDINAL.sub(lambda m: m[1] + m[3], line, count=1))
    return "".join(output)


def response_layout_receipt(answer: str) -> dict[str, Any]:
    lines = str(answer).splitlines()
    return {
        "answer_sha256": hashlib.sha256(str(answer).encode("utf-8")).hexdigest(),
        "table_ordinal_rows": len(_table_ordinals(lines)),
        "list_ordinal_rows": sum(bool(_LIST_ORDINAL.match(line)) for line in lines),
    }


def record_answer_blocks(answer: str, identifiers: list[str]) -> list[dict[str, Any]]:
    """Bind each record to its line/section up to the next record anchor.

    An explicit identifier is authoritative when visible. Otherwise the typed
    display order supplies the ordinal. Returned blocks never merge records.
    """
    lines = str(answer).splitlines()
    table_ordinals = _table_ordinals(lines)
    patterns = [re.compile(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", re.I) if value else None for value in identifiers]
    anchors: list[tuple[int, int, int | None]] = []
    for line_index, line in enumerate(lines):
        match = _LIST_ORDINAL.match(line)
        ordinal = table_ordinals.get(line_index, (0, int(match[2]) if match else None))[1]
        matching = [i for i, pattern in enumerate(patterns) if pattern and pattern.search(line)]
        if not matching and ordinal and 1 <= ordinal <= len(identifiers) and not identifiers[ordinal - 1]:
            matching = [ordinal - 1]
        if len(matching) == 1:
            anchors.append((line_index, matching[0], ordinal))
    blocks: list[dict[str, Any]] = [{} for _ in identifiers]
    for index, (start, record_index, ordinal) in enumerate(anchors):
        end = anchors[index + 1][0] if index + 1 < len(anchors) else len(lines)
        if not blocks[record_index]:
            blocks[record_index] = {"text": "\n".join(lines[start:end]), "ordinal": ordinal}
    return blocks
