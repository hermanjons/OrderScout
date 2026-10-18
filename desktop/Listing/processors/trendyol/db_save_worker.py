# Listing/processors/trendyol/db_save_worker.py
from __future__ import annotations

import sys
import json
from pathlib import Path

from Listing.processors.pipeline import save_listings_to_db


def _read_stdin_utf8() -> str:
    raw_bytes = sys.stdin.buffer.read()
    if not raw_bytes:
        return ""
    return raw_bytes.decode("utf-8", errors="strict").strip()


def _write_stdout_json(obj: dict) -> None:
    payload = dict(obj or {})
    payload.setdefault("type", "result")
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    try:
        raw = _read_stdin_utf8()
        if not raw:
            _write_stdout_json({
                "success": False,
                "message": "listing db_save_worker: empty input",
                "data": None,
            })
            return

        payload = json.loads(raw)
        if isinstance(payload, dict) and str(payload.get("payload_path") or "").strip():
            payload_path = Path(str(payload.get("payload_path") or "").strip())
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        items = payload.get("items", []) if isinstance(payload, dict) else []
        sync_api_account_ids = payload.get("sync_api_account_ids", []) if isinstance(payload, dict) else []
        prune_missing = bool(payload.get("prune_missing")) if isinstance(payload, dict) else False

        res = save_listings_to_db(
            items,
            sync_api_account_ids=sync_api_account_ids,
            prune_missing=prune_missing,
        )

        _write_stdout_json({
            "success": bool(res.success),
            "message": res.message,
            "data": res.data,
        })

    except UnicodeDecodeError as e:
        _write_stdout_json({
            "success": False,
            "message": f"listing db_save_worker unicode decode error: {e}",
            "data": None,
        })

    except Exception as e:
        _write_stdout_json({
            "success": False,
            "message": f"listing db_save_worker exception: {e}",
            "data": None,
        })


if __name__ == "__main__":
    main()
