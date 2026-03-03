import time
from typing import Any, Dict, List, Optional, Tuple

from config import DPU_CACHE_TTL_SEC
from binom_client import binom_get, _safe_json

_DPU_CACHE: Dict[str, Tuple[float, Any]] = {}

_CAMPAIGN_IDS_CACHE: Optional[List[str]] = None
_CAMPAIGN_IDS_CACHE_TS: float = 0
_CAMPAIGN_IDS_TTL = 300  # 5 минут


def cache_get(key: str) -> Optional[Any]:
    item = _DPU_CACHE.get(key)
    if not item:
        return None
    ts, payload = item
    if (time.time() - ts) > DPU_CACHE_TTL_SEC:
        return None
    return payload


def cache_set(key: str, payload: Any) -> None:
    _DPU_CACHE[key] = (time.time(), payload)


def get_all_campaign_ids() -> List[str]:
    """Получаем все ID кампаний постранично. Кешируется на 5 минут."""
    global _CAMPAIGN_IDS_CACHE, _CAMPAIGN_IDS_CACHE_TS
    if _CAMPAIGN_IDS_CACHE is not None and (time.time() - _CAMPAIGN_IDS_CACHE_TS) < _CAMPAIGN_IDS_TTL:
        return _CAMPAIGN_IDS_CACHE

    ids: List[str] = []
    offset = 0
    limit  = 500
    while True:
        r = binom_get("/public/api/v1/campaign/list/filtered",
                      params={"limit": limit, "offset": offset})
        if not r.ok:
            break
        data = _safe_json(r)
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("data") or data.get("items") or data.get("result") or []
        else:
            break
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if isinstance(item, dict):
                cid = item.get("id")
                if cid is not None:
                    ids.append(str(cid))
        if len(items) < limit:
            break
        offset += limit

    if ids:
        _CAMPAIGN_IDS_CACHE    = ids
        _CAMPAIGN_IDS_CACHE_TS = time.time()
    return ids


_ROTATION_IDS_CACHE: Optional[List[str]] = None
_ROTATION_IDS_CACHE_TS: float = 0
_ROTATION_IDS_TTL = 300


def get_all_rotation_ids() -> List[str]:
    """Получаем все ID ротаций. Кешируется на 5 минут."""
    global _ROTATION_IDS_CACHE, _ROTATION_IDS_CACHE_TS
    if _ROTATION_IDS_CACHE is not None and (time.time() - _ROTATION_IDS_CACHE_TS) < _ROTATION_IDS_TTL:
        return _ROTATION_IDS_CACHE

    ids: List[str] = []
    offset = 0
    limit  = 500
    while True:
        r = binom_get("/public/api/v1/rotation/list/filtered",
                      params={"limit": limit, "offset": offset})
        if not r.ok:
            break
        data = _safe_json(r)
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("data") or data.get("items") or data.get("result") or []
        else:
            break
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if isinstance(item, dict):
                rid = item.get("id")
                if rid is not None:
                    ids.append(str(rid))
        if len(items) < limit:
            break
        offset += limit

    if ids:
        _ROTATION_IDS_CACHE    = ids
        _ROTATION_IDS_CACHE_TS = time.time()
    return ids


_COUNTRY_MAP_CACHE: dict = {}
_COUNTRY_MAP_TS: float = 0
_COUNTRY_MAP_TTL = 3600  # 1 час


def get_country_map() -> dict:
    """code.upper() → официальное название из Binom. Например: "TR" → "Türkiye"."""
    global _COUNTRY_MAP_CACHE, _COUNTRY_MAP_TS
    if _COUNTRY_MAP_CACHE and (time.time() - _COUNTRY_MAP_TS) < _COUNTRY_MAP_TTL:
        return _COUNTRY_MAP_CACHE

    try:
        r    = binom_get("/public/api/v1/country/list")
        data = _safe_json(r)
        if r.ok and isinstance(data, list):
            m = {item["code"].upper(): item["name"]
                 for item in data if isinstance(item, dict) and item.get("code")}
            if m:
                _COUNTRY_MAP_CACHE = m
                _COUNTRY_MAP_TS    = time.time()
                return m
    except Exception:
        pass

    # Фоллбэк: статический маппинг из geo_map.py (включает Türkiye, Philippines и т.д.)
    if not _COUNTRY_MAP_CACHE:
        try:
            from geo_map import ISO_TO_BINOM
            _COUNTRY_MAP_CACHE = ISO_TO_BINOM
            _COUNTRY_MAP_TS    = time.time()
        except ImportError:
            pass

    return _COUNTRY_MAP_CACHE