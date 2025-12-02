# Orders/processors/db_save_worker.py

import sys
import json

from Feedback.processors.pipeline import Result
from Orders.processors.trendyol_pipeline import save_orders_to_db


def main():
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            out = {
                "success": False,
                "message": "db_save_worker: Boş input alındı.",
                "data": None,
            }
            sys.stdout.write(json.dumps(out))
            return

        payload = json.loads(raw)
        # payload = {"order_data_list": [...], "order_item_list": [...]}

        # save_orders_to_db Result beklediği için gerçek bir Result üretiyoruz
        fake_result = Result.ok(
            "Process içi payload",
            close_dialog=False,
            data=payload
        )

        res = save_orders_to_db(fake_result)

        out = {
            "success": res.success,
            "message": res.message,
            "data": res.data,
        }
        sys.stdout.write(json.dumps(out))

    except Exception as e:
        out = {
            "success": False,
            "message": f"db_save_worker exception: {e}",
            "data": None,
        }
        sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
