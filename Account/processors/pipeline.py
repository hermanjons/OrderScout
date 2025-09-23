from __future__ import annotations

import os
import shutil

from Account.models import ApiAccount
from Core.utils.model_utils import (
    create_records,
    make_normalizer,
    get_engine,
    update_records,
    delete_records,
    get_records,  # ✅ Genel amaçlı veri çekme fonksiyonu
)
from Feedback.processors.pipeline import Result, map_error_to_message
from settings import MEDIA_ROOT

# -------------------------------------------------
# 🔧 Normalizer
# -------------------------------------------------
account_normalizer = make_normalizer(
    coalesce_none={
        "account_id": None,
        "comp_name": None,
        "platform": None,
    },
    strip_strings=True
)


# -------------------------------------------------
# 💾 Create
# -------------------------------------------------
def save_company_to_db(form_values: dict) -> Result:
    """
    Yeni bir şirket kaydı oluşturur.
    """
    try:
        create_records(
            model=ApiAccount,
            mode="plain",
            data_list=[form_values],
            db_name="orders.db",
            conflict_keys=["account_id", "comp_name", "platform"],
            normalizer=account_normalizer
        )
        return Result.ok("Şirket başarıyla kaydedildi.")
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


# -------------------------------------------------
# ✏️ Update
# -------------------------------------------------
def update_company(pk: int, update_data: dict) -> Result:
    """
    Belirli bir şirket kaydını günceller.
    """
    try:
        engine = get_engine("orders.db")
        filters = {"pk": pk}
        update_records(ApiAccount, engine, filters, update_data)
        return Result.ok("Şirket başarıyla güncellendi.")
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


# -------------------------------------------------
# 🗑️ Delete
# -------------------------------------------------
def delete_company_from_db(pk: int) -> Result:
    """
    Bir şirket kaydını siler.
    """
    try:
        engine = get_engine("orders.db")
        delete_records(
            model=ApiAccount,
            db_engine=engine,
            filters={"pk": pk}
        )
        return Result.ok(f"Şirket (id={pk}) başarıyla silindi.")
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


# -------------------------------------------------
# 🖼️ Logo İşlemleri
# -------------------------------------------------
def process_logo(file_path: str) -> Result:
    """
    Logo dosyasını 'company_logos' klasörüne kopyalar.
    """
    try:
        if not file_path:
            return Result.fail("Geçerli bir dosya yolu verilmedi.")

        logos_dir = os.path.join(MEDIA_ROOT, "company_logos")
        os.makedirs(logos_dir, exist_ok=True)

        file_name = os.path.basename(file_path)
        save_path = os.path.join(logos_dir, file_name)
        shutil.copy(file_path, save_path)

        # ✅ Yeni Result.data kullanımı
        return Result.ok("Logo başarıyla kaydedildi.", close_dialog=False, data={"path": save_path})

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# -------------------------------------------------
# 📦 Read (get_records entegrasyonu ile)
# -------------------------------------------------
def get_all_companies() -> Result:
    """
    Tüm şirketleri getirir.
    """
    try:
        engine = get_engine("orders.db")
        records = get_records(model=ApiAccount, db_engine=engine)

        return Result.ok("Şirketler başarıyla getirildi.", close_dialog=False, data={"records": records})

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_company_by_id(pks: list[int]) -> Result:
    """
    Birden fazla şirketi primary key (pk) listesi üzerinden getirir.
    """
    try:

        if not pks:
            return Result.fail("Hiçbir şirket seçilmedi.", close_dialog=False)
        print(pks)
        engine = get_engine("orders.db")
        res = get_records(
            model=ApiAccount,
            db_engine=engine,
            filters={"pk": pks}  # get_records içinde 'pk IN pks' destekleniyorsa
        )

        if not res.success:
            return res

        records = res.data.get("records", [])
        print(records)
        if not records:
            return Result.fail("Seçilen şirketler bulunamadı.", close_dialog=False)

        return Result.ok(
            f"{len(records)} şirket bulundu.",
            close_dialog=False,
            data={
                "records": records,
                "accounts": [[r.pk, r.api_key, r.api_secret, str(r.account_id)] for r in records]
            }
        )


    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)

