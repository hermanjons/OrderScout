import httpx
from Feedback.processors.pipeline import Result, map_error_to_message


async def async_make_request(
    method: str,
    url: str,
    headers=None,
    auth=None,
    params=None,
    data=None,
    json=None,
    timeout=15
) -> Result:
    """
    Genel amaçlı asenkron HTTP istek fonksiyonu.
    - Başarılı olursa Result.ok döner → data = {"json": ..., "status_code": ...}
    - Hata olursa Result.fail döner.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                auth=auth,
                params=params,
                data=data,
                json=json
            )
            response.raise_for_status()

            # ✅ Başarıyla sonuç döner
            return Result.ok(
                f"{method} {url} isteği başarılı.",
                close_dialog=False,
                data={
                    "json": response.json(),
                    "status_code": response.status_code
                }
            )

    except Exception as e:
        # ✅ Hata feedback sistemine uyarlanır
        msg = map_error_to_message(e)
        return Result.fail(
            f"{method} {url} isteği başarısız: {msg}",
            error=e,
            close_dialog=False
        )
