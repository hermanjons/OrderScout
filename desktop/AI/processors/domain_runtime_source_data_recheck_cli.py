from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from AI.processors.task_runtime import run_agent_task
from Feedback.processors.pipeline import Result, map_error_to_message
from settings import DB_NAME


DOMAIN_GOALS = {
    "stock": "Stok operasyonunu toparla",
    "finance": "Finans operasyonunu toparla",
    "listing": "Ilan operasyonunu toparla",
    "logistics": "Lojistik operasyonunu toparla",
    "marketplaces": "Pazaryeri operasyonunu toparla",
}


def evaluate_domain_runtime_source_data(*, db_name: str = DB_NAME) -> Result:
    try:
        rows: list[dict[str, Any]] = []
        for domain, goal in DOMAIN_GOALS.items():
            task_result = run_agent_task(
                goal,
                domain=domain,
                db_name=db_name,
                max_steps=8,
            )
            state = dict((task_result.data or {}).get("state") or {})
            completed = [
                dict(row)
                for row in list(state.get("completed_steps") or [])
                if isinstance(row, dict)
            ]
            step_rows = [
                {
                    "step_id": str(row.get("step_id") or ""),
                    "status": str(row.get("status") or ""),
                    "tool_names": list(row.get("tool_names") or []),
                    "exact_tool_binding": list(row.get("tool_names") or [])
                    == [str(row.get("step_id") or "")],
                    "attempt_count": int((row.get("result_data") or {}).get("attempt_count") or 0),
                }
                for row in completed
            ]
            valid = bool(
                task_result.success
                and state.get("status") == "complete"
                and step_rows
                and all(row["status"] == "completed" and row["exact_tool_binding"] for row in step_rows)
            )
            rows.append(
                {
                    "domain": domain,
                    "goal": goal,
                    "valid": valid,
                    "task_status": state.get("status"),
                    "steps": step_rows,
                }
            )
        valid = all(row["valid"] for row in rows)
        data = {
            "schema": "orderscout-domain-runtime-source-data-acceptance-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_entrypoint": "AI.processors.task_runtime.run_agent_task",
            "database": Path(db_name).name,
            "read_only": True,
            "valid": valid,
            "domains": rows,
        }
        if valid:
            return Result.ok("Domain runtime real source-data acceptance gecti.", close_dialog=False, data=data)
        return Result.fail("Domain runtime real source-data acceptance tamamlanmadi.", close_dialog=False, data=data)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run read-only task runtime acceptance against the source DB.")
    parser.add_argument("--db-name", default=DB_NAME)
    parser.add_argument("--output", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = evaluate_domain_runtime_source_data(db_name=str(args.db_name or DB_NAME))
    payload = {"success": result.success, "message": result.message, "data": result.data or {}}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
