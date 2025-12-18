# License/api/license_api.py
from __future__ import annotations

from typing import Dict, Any
import requests

import settings
from Feedback.processors.pipeline import Result


class FreemiusLicenseApi:
    """
    Sadece HTTP konuşur.
    DB yok, UI yok, iş kuralı yok.
    """

    def __init__(self):
        self.base = getattr(settings, "FREEMIUS_BASE_URL", "https://api.freemius.com").rstrip("/")

        if not hasattr(settings, "FREEMIUS_PRODUCT_ID"):
            raise RuntimeError("settings.py içinde FREEMIUS_PRODUCT_ID tanımlı değil.")
        if not hasattr(settings, "FREEMIUS_SECRET_KEY"):
            raise RuntimeError("settings.py içinde FREEMIUS_SECRET_KEY tanımlı değil.")

        self.product_id = int(settings.FREEMIUS_PRODUCT_ID)
        self.secret_key = settings.FREEMIUS_SECRET_KEY

    def _auth(self):
        return (self.secret_key, "")

    def activate(self, *, uid: str, license_key: str) -> Result:
        url = f"{self.base}/v1/products/{self.product_id}/licenses/activate.json"
        params = {"uid": uid, "license_key": license_key}
        try:
            r = requests.post(url, params=params, auth=self._auth(), timeout=20)
            if r.ok:
                return Result.ok(message="Aktivasyon başarılı.", data={"json": r.json()})
            return Result.fail(message=f"Aktivasyon başarısız: {r.text}")
        except Exception as e:
            return Result.fail(message="Aktivasyon sırasında ağ hatası oluştu.", error=e)

    def validate(self, *, uid: str, license_key: str, install_id: int) -> Result:
        url = f"{self.base}/v1/products/{self.product_id}/installs/{install_id}/license.json"
        params = {"uid": uid, "license_key": license_key}
        try:
            r = requests.get(url, params=params, auth=self._auth(), timeout=20)
            if r.ok:
                return Result.ok(message="Doğrulama başarılı.", data={"json": r.json()})
            return Result.fail(message=f"Doğrulama başarısız: {r.text}")
        except Exception as e:
            return Result.fail(message="Doğrulama sırasında ağ hatası oluştu.", error=e)

    def deactivate(self, *, uid: str, license_key: str, install_id: int) -> Result:
        url = f"{self.base}/v1/products/{self.product_id}/licenses/deactivate.json"
        params = {"uid": uid, "license_key": license_key, "install_id": install_id}
        try:
            r = requests.post(url, params=params, auth=self._auth(), timeout=20)
            if r.ok:
                return Result.ok(message="Deaktivasyon başarılı.", data={"json": r.json()})
            return Result.fail(message=f"Deaktivasyon başarısız: {r.text}")
        except Exception as e:
            return Result.fail(message="Deaktivasyon sırasında ağ hatası oluştu.", error=e)
