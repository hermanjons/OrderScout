# Orders/processors/db_save_worker.py
from __future__ import annotations

import sys
import json

from Feedback.processors.pipeline import Result
from Orders.processors.trendyol.pipeline import save_orders_to_db, save_return_claims_to_db


def _read_stdin_utf8() -> str:
    """
    QProcess'ten gelen input'u Windows codepage'e takılmadan garanti UTF-8 okur.
    Kritik nokta: sys.stdin.read() DEĞİL, sys.stdin.buffer.read()
    """
    raw_bytes = sys.stdin.buffer.read()
    if not raw_bytes:
        return ""
    # UTF-8 decode (bozulma burada çözülür)
    return raw_bytes.decode("utf-8", errors="strict").strip()


def _write_stdout_json(obj: dict) -> None:
    """
    Worker output'u JSON-lines protokolüyle basar.
    GenericProcessRunner final sonucu `type=result` satırından okur.
    """
    payload = dict(obj or {})
    payload.setdefault("type", "result")
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _merge_db_results(results: list[Result]) -> Result:
    changed = False
    counts: dict[str, int] = {}
    messages: list[str] = []
    sync_diagnostics: dict = {}

    for res in results:
        if not isinstance(res, Result):
            continue
        if not res.success:
            return res

        payload = res.data or {}
        if bool(payload.get("changed")):
            changed = True
        for key, value in (payload.get("counts") or {}).items():
            try:
                counts[str(key)] = int(counts.get(str(key), 0) or 0) + int(value or 0)
            except Exception:
                continue
        if payload.get("sync_diagnostics"):
            sync_diagnostics = dict(payload.get("sync_diagnostics") or {})
        msg = str(res.message or "").strip()
        if msg:
            messages.append(msg)

    return Result.ok(
        " | ".join(messages) if messages else "Veriler veritabanına kaydedildi.",
        close_dialog=False,
        data={"changed": changed, "counts": counts, "sync_diagnostics": sync_diagnostics},
    )


def main():
    try:
        raw = _read_stdin_utf8()
        if not raw:
            _write_stdout_json({
                "success": False,
                "message": "db_save_worker: Boş input alındı.",
                "data": None,
            })
            return

        payload = json.loads(raw)
        results: list[Result] = []
        if (
            (payload.get("order_data_list") or [])
            or (payload.get("order_item_list") or [])
            or payload.get("sync_diagnostics")
        ):
            results.append(
                save_orders_to_db(
                    Result.ok(
                        "Process içi orders payload",
                        close_dialog=False,
                        data={
                            "order_data_list": payload.get("order_data_list", []) or [],
                            "order_item_list": payload.get("order_item_list", []) or [],
                            "sync_diagnostics": payload.get("sync_diagnostics") or {},
                        },
                    )
                )
            )
        if (payload.get("return_claim_list") or []):
            results.append(
                save_return_claims_to_db(
                    Result.ok(
                        "Process içi returns payload",
                        close_dialog=False,
                        data={"return_claim_list": payload.get("return_claim_list", []) or []},
                    )
                )
            )
        if not results:
            results.append(
                Result.ok(
                    "Kaydedilecek veri yok.",
                    close_dialog=False,
                    data={"changed": False, "counts": {}},
                )
            )

        res = _merge_db_results(results)

        _write_stdout_json({
            "success": bool(res.success),
            "message": res.message,
            "data": res.data,
        })

    except UnicodeDecodeError as e:
        # Eğer input UTF-8 değilse burada patlar (ki biz zaten utf-8 gönderiyoruz)
        _write_stdout_json({
            "success": False,
            "message": f"db_save_worker unicode decode error: {e}",
            "data": None,
        })

    except Exception as e:
        _write_stdout_json({
            "success": False,
            "message": f"db_save_worker exception: {e}",
            "data": None,
        })


if __name__ == "__main__":
    main()
