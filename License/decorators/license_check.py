# License/decorators/license_check.py
from __future__ import annotations

from functools import wraps
from typing import Callable, Any, Awaitable

from Feedback.processors.pipeline import Result
from License.processors.pipeline import ensure_license_valid


def require_valid_license_async(*, force: bool = False):
    """
    async fonksiyonlar için lisans kontrol decorator'ı.
    API çağrılarından önce lisansı kontrol eder.
    """

    def decorator(fn: Callable[..., Awaitable[Result]]):
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Result:
            lic_res = ensure_license_valid(force=force)
            if not lic_res.success:
                return lic_res
            return await fn(*args, **kwargs)

        return wrapper

    return decorator
