# License/api/license_api.py
from __future__ import annotations

from typing import Dict, Any
import requests

import settings
from Feedback.processors.pipeline import Result


class FreemiusLicenseApi:
    """
    EXE -> Worker -> Freemius
    Secret key EXE'de yok.
    """

    def __init__(self):
        self.base = getattr(settings, "LICENSE_BACKEND_BASE_URL", "").rstrip("/")
        if not self.base:
            raise RuntimeError("settings.py içinde LICENSE_BACKEND_BASE_URL tanımlı değil.")

        # health check optional
        # requests.get(f"{self.base}/health", timeout=5)

    def activate(self, *, uid: str, license_key: str) -> Result:
        url = f"{self.base}/v1/license/activate"
        payload = {"uid": uid, "license_key": license_key}
        try:
            r = requests.post(url, json=payload, timeout=25)
            if r.ok:
                j = r.json() if r.text else {}
                if j.get("ok") is True:
                    return Result.ok(message="Aktivasyon başarılı.", data={"json": j.get("json", {})})
                return Result.fail(message=j.get("message") or "Aktivasyon başarısız.")
            return Result.fail(message=f"Aktivasyon başarısız: {r.text}")
        except Exception as e:
            return Result.fail(message="Aktivasyon sırasında ağ hatası oluştu.", error=e)

    def validate(self, *, uid: str, license_key: str, install_id: int) -> Result:
        url = f"{self.base}/v1/license/validate"
        payload = {"uid": uid, "license_key": license_key, "install_id": int(install_id)}
        try:
            r = requests.post(url, json=payload, timeout=25)
            if r.ok:
                j = r.json() if r.text else {}
                if j.get("ok") is True:
                    return Result.ok(message="Doğrulama başarılı.", data={"json": j.get("json", {})})
                return Result.fail(message=j.get("message") or "Doğrulama başarısız.")
            return Result.fail(message=f"Doğrulama başarısız: {r.text}")
        except Exception as e:
            return Result.fail(message="Doğrulama sırasında ağ hatası oluştu.", error=e)

    def deactivate(self, *, uid: str, license_key: str, install_id: int) -> Result:
        url = f"{self.base}/v1/license/deactivate"
        payload = {"uid": uid, "license_key": license_key, "install_id": int(install_id)}
        try:
            r = requests.post(url, json=payload, timeout=25)
            if r.ok:
                j = r.json() if r.text else {}
                if j.get("ok") is True:
                    return Result.ok(message="Deaktivasyon başarılı.", data={"json": j.get("json", {})})
                return Result.fail(message=j.get("message") or "Deaktivasyon başarısız.")
            return Result.fail(message=f"Deaktivasyon başarısız: {r.text}")
        except Exception as e:
            return Result.fail(message="Deaktivasyon sırasında ağ hatası oluştu.", error=e)
