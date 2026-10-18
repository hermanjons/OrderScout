from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from AI.processors.architecture_boundary import audit_core_dry_architecture


def default_output_path() -> Path:
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return (
        local_app_data
        / "OrderScout"
        / "stage-acceptance"
        / "architecture"
        / "core-dry-full-audit-r1.json"
    )


def build_artifact(project_root: str | Path) -> dict:
    audit = audit_core_dry_architecture(project_root)
    return {
        **audit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_contract": {
            "customer_data_included": False,
            "credentials_included": False,
            "local_paths_included": False,
            "source_tree_mutated_by_audit": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the binding OrderScout Core/DRY architecture audit."
    )
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[2]),
    )
    parser.add_argument("--output", default=str(default_output_path()))
    args = parser.parse_args(argv)

    artifact = build_artifact(args.project_root)
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "success": bool(artifact.get("valid")),
                "output": str(output_path),
                "product_python_file_count": artifact.get("product_python_file_count"),
                "violation_count": artifact.get("violation_count"),
                "check_count": len(artifact.get("checks") or {}),
            },
            ensure_ascii=False,
        )
    )
    return 0 if artifact.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
