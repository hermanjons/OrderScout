from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


DESKTOP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPEATS = 5

CAPTURED_BASELINE_SECONDS = {
    "startup.total_until_window": 1.023331,
    "imports.Main_interface.views": 0.5065,
    "imports.Orders.views.views": 0.2327,
    "imports.Orders.views.orders_manager_window": 0.5878,
    "imports.Orders.views.returns_manager_window": 0.5726,
    "imports.Listing.views.views": 0.3935,
    "imports.Listing.views.listing_manager_window": 0.520814,
    "imports.Stock.views.views": 0.783519,
    "imports.Finance.views.finance_cost_items_window": 0.443939,
    "imports.Finance.views.finance_transactions_window": 0.408613,
    "imports.Logistics.views.cargo_providers_window": 0.419062,
    "imports.Logistics.views.cargo_tariffs_window": 0.418544,
    "imports.Marketplaces.views.views": 0.3936,
    "imports.Marketplaces.views.marketplaces_manager_window": 0.406269,
    "imports.Account.views.company_manager_dialog": 0.455278,
    "imports.Labels.views.label_print_manager_window": 0.671672,
    "imports.AI.views.views": 0.460247,
}


def _run_python(code: str, *, timeout: int = 45) -> str:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="orderscout-bench-")
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(DESKTOP_ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-2000:] or completed.stdout[-2000:])
    return completed.stdout.strip().splitlines()[-1]


def _median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def _summary(values: list[float]) -> dict[str, object]:
    return {
        "runs": [round(value, 6) for value in values],
        "median": round(_median(values), 6),
        "mean": round(float(statistics.mean(values)), 6) if values else 0.0,
        "min": round(min(values), 6) if values else 0.0,
        "max": round(max(values), 6) if values else 0.0,
    }


def _improvement(baseline: float, current: float) -> float:
    if baseline <= 0:
        return 0.0
    return (baseline - current) / baseline


def benchmark_startup(repeats: int) -> dict[str, object]:
    code = r'''
import os, tempfile, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="orderscout-start-")
t0 = time.perf_counter()
from PyQt6.QtWidgets import QApplication
app = QApplication([])
t_qapp = time.perf_counter()
import Main_interface.views as main_interface_views
t_import = time.perf_counter()
window = main_interface_views.MainInterface(defer_startup=True)
window.showMaximized()
app.processEvents()
t_window = time.perf_counter()
from Core.db.bootstrap import init_database
init_database()
t_boot = time.perf_counter()
window.start_deferred_work()
app.processEvents()
t_ready = time.perf_counter()
print("|".join(str(round(value, 6)) for value in (
    t_qapp - t0,
    t_import - t_qapp,
    t_window - t_import,
    t_window - t0,
    t_boot - t_window,
    t_ready - t0,
)))
'''
    keys = (
        "qapp",
        "main_import_before_boot",
        "window_shell_create",
        "total_until_shell",
        "bootstrap_after_shell",
        "total_until_db_ready",
    )
    values = {key: [] for key in keys}
    for _ in range(repeats):
        row = [float(part) for part in _run_python(code).split("|")]
        for key, value in zip(keys, row):
            values[key].append(value)
    return {key: _summary(row_values) for key, row_values in values.items()}


def benchmark_imports(repeats: int) -> dict[str, object]:
    modules = (
        "Main_interface.views",
        "Orders.views.views",
        "Orders.views.orders_manager_window",
        "Orders.views.returns_manager_window",
        "Listing.views.views",
        "Listing.views.listing_manager_window",
        "Stock.views.tab",
        "Stock.views.views",
        "Finance.views.views",
        "Finance.views.finance_cost_items_window",
        "Finance.views.finance_transactions_window",
        "Logistics.views.views",
        "Logistics.views.cargo_providers_window",
        "Logistics.views.cargo_tariffs_window",
        "Marketplaces.views.views",
        "Marketplaces.views.marketplaces_manager_window",
        "Account.views.company_manager_dialog",
        "Labels.views.label_print_manager_window",
        "AI.views.views",
    )
    results: dict[str, object] = {}
    for module in modules:
        values: list[float] = []
        code = (
            "import time, importlib; "
            "t=time.perf_counter(); "
            f"importlib.import_module({module!r}); "
            "print(time.perf_counter()-t)"
        )
        for _ in range(repeats):
            values.append(float(_run_python(code)))
        results[module] = _summary(values)
    return results


def benchmark_db_batch(repeats: int) -> dict[str, object]:
    code = r'''
import tempfile, time
from pathlib import Path
from sqlmodel import SQLModel
from Core.utils import model_utils
from Core.utils.model_utils import create_records, get_engine
from tests.domain_core.test_model_utils import WideInsertRow

def rows(prefix, n=5000):
    return [
        {
            "code": f"{prefix}-{idx}",
            "c01": "v1", "c02": "v2", "c03": "v3", "c04": "v4",
            "c05": "v5", "c06": "v6", "c07": "v7", "c08": "v8",
            "c09": "v9", "c10": "v10", "c11": "v11", "c12": "v12",
        }
        for idx in range(n)
    ]

def setup_db():
    db = Path(tempfile.mkdtemp(prefix="orderscout-db-")) / "bench.sqlite3"
    model_utils.clear_engine_cache()
    engine = get_engine(str(db))
    SQLModel.metadata.create_all(engine)
    return str(db)

db = setup_db()
t0 = time.perf_counter()
first = create_records(WideInsertRow, rows("ignore"), db_name=db, conflict_keys=["code"], mode="ignore", chunk_size=500)
if not first.success:
    raise RuntimeError(first.message)
t_insert = time.perf_counter()
updated = rows("ignore")
for row in updated:
    row["c12"] = "changed"
second = create_records(WideInsertRow, updated, db_name=db, conflict_keys=["code"], mode="update", chunk_size=500)
if not second.success:
    raise RuntimeError(second.message)
t_update = time.perf_counter()
model_utils.clear_engine_cache()
print(f"{t_insert - t0}|{t_update - t_insert}")
'''
    insert_values: list[float] = []
    update_values: list[float] = []
    for _ in range(repeats):
        insert_time, update_time = [float(part) for part in _run_python(code, timeout=60).split("|")]
        insert_values.append(insert_time)
        update_values.append(update_time)
    return {
        "create_records_ignore_5000x13": _summary(insert_values),
        "create_records_update_5000x13": _summary(update_values),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark key OrderScout desktop performance paths.")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    args = parser.parse_args()
    repeats = max(1, int(args.repeats or DEFAULT_REPEATS))

    startup = benchmark_startup(repeats)
    imports = benchmark_imports(repeats)
    db_batch = benchmark_db_batch(repeats)

    comparisons = {
        "startup.total_until_shell": {
            "baseline": CAPTURED_BASELINE_SECONDS["startup.total_until_window"],
            "current": startup["total_until_shell"]["median"],
        }
    }
    for module in (
        "Main_interface.views",
        "Orders.views.views",
        "Orders.views.orders_manager_window",
        "Orders.views.returns_manager_window",
        "Listing.views.views",
        "Listing.views.listing_manager_window",
        "Stock.views.views",
        "Finance.views.finance_cost_items_window",
        "Finance.views.finance_transactions_window",
        "Logistics.views.cargo_providers_window",
        "Logistics.views.cargo_tariffs_window",
        "Marketplaces.views.views",
        "Marketplaces.views.marketplaces_manager_window",
        "Account.views.company_manager_dialog",
        "Labels.views.label_print_manager_window",
        "AI.views.views",
    ):
        key = f"imports.{module}"
        comparisons[key] = {
            "baseline": CAPTURED_BASELINE_SECONDS[key],
            "current": imports[module]["median"],
        }
    for payload in comparisons.values():
        payload["improvement_pct"] = round(_improvement(float(payload["baseline"]), float(payload["current"])) * 100, 2)

    print(json.dumps(
        {
            "repeats": repeats,
            "startup": startup,
            "imports": imports,
            "db_batch": db_batch,
            "comparisons": comparisons,
        },
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
