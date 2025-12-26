# Orders/processors/db_save_worker.py
from __future__ import annotations

import sys
import json

from Feedback.processors.pipeline import Result
from Orders.processors.trendyol_pipeline import save_orders_to_db


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
    Worker output'u tek satır JSON olacak şekilde basar.
    (process_runner son dolu satırı JSON parse ediyor)
    """
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


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
        # payload = {"order_data_list": [...], "order_item_list": [...]}

        fake_result = Result.ok(
            "Process içi payload",
            close_dialog=False,
            data=payload,
        )

        res = save_orders_to_db(fake_result)

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
