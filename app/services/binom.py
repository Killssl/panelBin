from typing import Any, Dict, List, Optional, Tuple
import requests
from app.utils.config import BINOM_BASE, BINOM_API_KEY


def _headers() -> Dict[str, str]:
    return {
        "Accept":    "application/json",
        "api-key":   BINOM_API_KEY,
        "Api-Key":   BINOM_API_KEY,
        "X-API-Key": BINOM_API_KEY,
    }


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:3000]}


def binom_get(path: str, params: Optional[dict] = None) -> requests.Response:
    url = f"{BINOM_BASE}{path}"
    return requests.get(url, headers=_headers(), params=params or {}, timeout=30)


def binom_get_pairs(path: str, pairs: List[Tuple[str, str]]) -> requests.Response:
    url = f"{BINOM_BASE}{path}"
    return requests.get(url, headers=_headers(), params=pairs, timeout=60)


def binom_put(path: str, data: Any) -> requests.Response:
    url = f"{BINOM_BASE}{path}"
    h = {**_headers(), "Content-Type": "application/json"}
    return requests.put(url, headers=h, json=data, timeout=30)


def binom_post(path: str, data: Any) -> requests.Response:
    url = f"{BINOM_BASE}{path}"
    h = {**_headers(), "Content-Type": "application/json"}
    return requests.post(url, headers=h, json=data, timeout=30)