import time
from datetime import datetime


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
