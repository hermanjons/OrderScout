import httpx
import logging

logger = logging.getLogger("HttpUtils")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('[%(levelname)s] %(asctime)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


async def async_make_request(method: str, url: str, headers=None, auth=None, params=None, data=None, json=None, timeout=15):
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
            return response.json(), response.status_code
    except httpx.RequestError as e:
        logger.error(f"[ASYNC REQUEST ERROR] {method} {url} - {str(e)}", exc_info=True)
        return {}, 500
