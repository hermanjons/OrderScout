"""Small typed user files for real source-UI attachment acceptance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def seed_attachment_fixtures(isolation_root: str | Path) -> dict[str, dict[str, Any]]:
    root = Path(isolation_root).resolve()
    directory = root / "selected-fixtures"
    directory.mkdir(parents=True, exist_ok=True)
    rows = [
        {"sku": "PILOT-KUPA", "quantity": 4, "unit": "adet", "revenue": 1200.5, "currency": "TRY", "discount": None},
        {"sku": "PILOT-FILTRE", "quantity": 3, "unit": "adet", "revenue": 90.25, "currency": "USD", "discount": None},
        {"sku": "PILOT-BOS", "quantity": 0, "unit": "adet", "revenue": 0, "currency": "TRY", "discount": None},
    ]
    columns = list(rows[0])
    json_path = directory / "pilot-sales.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from openpyxl import Workbook
    workbook = Workbook()
    workbook.active.title = "Kaynak Satışlar"
    workbook.active.append(columns)
    for row in rows:
        workbook.active.append([row[key] for key in columns])
    xlsx_path = directory / "pilot-sales.xlsx"
    workbook.save(xlsx_path)
    workbook.close()
    return {kind: {"path": str(path), "name": path.name, "format": kind,
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "size_bytes": path.stat().st_size, "rows": rows, "columns": columns,
                   "sheet": "Kaynak Satışlar" if kind == "xlsx" else "",
                   "scope": "Synthetic source rows; revenue is a file value, not observed bank settlement."}
            for kind, path in (("json", json_path), ("xlsx", xlsx_path))}
