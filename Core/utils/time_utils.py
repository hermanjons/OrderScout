from __future__ import annotations

import time
from datetime import datetime, date


def time_stamp_calculator(hour):
    """
    girilen saat değerini epoch tipine çevirir
    :param hour:herhangi bir saat değeri
    :return: epoch tipine çevrilmiş olan saat değerini döndürür
    """
    minutes = hour * 60

    seconds = minutes * 60

    mili_seconds = int(seconds) * 1000

    return mili_seconds


def epoch_to_datetime(epoch):
    """

    :param epoch:epoch cinsinden süre
    :return: epoch cinsinden verilmiş olan süreyi tarih ve saat biçimine çevirir
    """
    return datetime.fromtimestamp(epoch / 1000)


def time_for_now():
    """
    herhangi ülkesindeki saati anlık olarak GMT kuralına uygun bir biçimde epoch tipinde verir
    :return: herhangi ülkesindeki mevcut saati epoch tipinde verir
    """
    return int(time.time()) * 1000


def time_for_now_tr():
    """
    Turkey ülkesindeki saati anlık olarak GMT+3 kuralına uygun bir biçimde epoch tipinde verir
    :return: Turkey ülkesindeki mevcut saati epoch tipinde verir
    """
    return int(time.time()) * 1000 + time_stamp_calculator(3)




def coerce_to_date(value) -> date | None:
    """
    Farklı formatlardaki tarih değerlerini güvenli bir şekilde `date` nesnesine dönüştürür.

    Desteklenen türler:
    - datetime.datetime
    - datetime.date
    - epoch (saniye veya milisaniye)
    - string ("2025-10-09", "2025/10/09", "09.10.2025" vb.)
    """
    if value is None:
        return None

    # 1️⃣ datetime → date
    if isinstance(value, datetime):
        return value.date()

    # 2️⃣ doğrudan date
    if isinstance(value, date):
        return value

    # 3️⃣ epoch (int veya float)
    if isinstance(value, (int, float)):
        try:
            # 13 haneliyse milisaniyedir → saniyeye çevir
            if value > 1e12:
                value = value / 1000
            return datetime.fromtimestamp(value).date()
        except Exception:
            return None

    # 4️⃣ string tarih (çeşitli formatlarda)
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except Exception:
                pass

    # 💥 tanınmayan format
    return None


