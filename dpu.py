from typing import Any, Dict, List, Optional, Tuple

from binom_client import binom_get_pairs, _safe_json
from cache import cache_get, cache_set, _DPU_CACHE, get_country_map

MIN_UNIQ = 80

PERIODS: List[Tuple[str, str]] = [
    ("7d",        "last_7_days"),
    ("14d",       "last_14_days"),
    ("30d",       "last_30_days"),
    ("this_year", "this_year"),
    ("all_time",  "all_time"),
]


# ---------- helpers ----------

def _to_int(v) -> int:
    try:
        return int(float(str(v).replace(",", ".").strip()))
    except Exception:
        return 0


def _to_float(v) -> float:
    try:
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return 0.0


def extract_rows(raw: Any) -> List[Dict]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("report", "data", "items", "rows", "result"):
            v = raw.get(key)
            if isinstance(v, list):
                return v
    return []


def extract_dpu_from_row(row: Dict[str, Any]) -> Tuple[float, int]:
    """Возвращает (dpu, unique_campaign_clicks) из строки Binom."""
    uniq = 0
    for fld in ("unique_campaign_clicks", "uniqueCampaignClicks",
                "uniqueClicksCampaign", "unique_clicks_campaign"):
        if fld in row:
            uniq = _to_int(row[fld])
            break

    dpu = None
    for k, v in row.items():
        if isinstance(k, str) and k.lower().startswith("dollarsperuniq::"):
            dpu = _to_float(v)
            break
    if dpu is None:
        for fld in ("dollarsperUniq", "dollarsPerUniq", "dollars_per_uniq", "epu"):
            if fld in row:
                dpu = _to_float(row[fld])
                break
    if dpu is None:
        dpu = 0.0

    return dpu, uniq


# ---------- для /api/rotation/<id>/dpu (старый эндпоинт) ----------

def fetch_offer_report(rotation_id: int, offer_id: Any, date_preset: str) -> Dict[str, Any]:
    pairs = [
        ("datePreset",  date_preset),
        ("timezone",    "Europe/Moscow"),
        ("groupings[]", "rotation"),
        ("groupings[]", "rule"),
        ("sortColumn",  "clicks"),
        ("sortType",    "desc"),
        ("limit",       "5000"),
        ("offset",      "0"),
        ("ids[]",       str(offer_id)),
    ]
    try:
        r    = binom_get_pairs("/public/api/v1/report/offer", pairs)
        data = _safe_json(r)
        return {"_ok": r.ok, "_status": r.status_code, "_data": data, "_rotation_id": rotation_id}
    except Exception as e:
        return {"_ok": False, "_status": 0, "_data": {"error": str(e)}, "_rotation_id": rotation_id}


def extract_rule_row(report_pack: Dict[str, Any], rule_name: str) -> Optional[Dict[str, Any]]:
    """Ищет строку rule в иерархии rotation(level=1) → rule(level=2)."""
    if not isinstance(report_pack, dict) or not report_pack.get("_ok"):
        return None
    rotation_id = report_pack.get("_rotation_id")
    rows = extract_rows(report_pack.get("_data"))
    want = (rule_name or "").strip().lower()
    if not want or not rows:
        return None

    current_rotation_id: Optional[int] = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level") or "").strip()
        name  = str(row.get("name") or "").strip().lower()
        if level == "1":
            try:
                current_rotation_id = int(row.get("entity_id") or 0)
            except Exception:
                current_rotation_id = None
        elif level == "2":
            if rotation_id and current_rotation_id != rotation_id:
                continue
            if name == want or name.startswith(want + " ") or name.startswith(want + "_"):
                return row
    return None


def calc_dpu_for_offer(rotation_id: int, offer_id: Any, geo_title: str) -> Dict[str, Any]:
    """DPU для ротационного эндпоинта. Каскад 7d→14d→30d→all_time."""
    rule_name = (geo_title or "").strip()
    for pname, preset in PERIODS:
        cache_key = f"{rotation_id}:{offer_id}:{rule_name}:{preset}"
        pack = cache_get(cache_key)
        if pack is None:
            pack = fetch_offer_report(rotation_id, offer_id, preset)
            cache_set(cache_key, pack)
        if not (isinstance(pack, dict) and pack.get("_ok")):
            continue
        row = extract_rule_row(pack, rule_name)
        if not row:
            continue
        dpu, uniq = extract_dpu_from_row(row)
        if uniq > 0 or dpu > 0:
            pass
        if uniq >= MIN_UNIQ:
            return {"dpu": dpu, "period": pname, "unique_clicks": uniq}
        if pname == "all_time":
            if uniq == 0:
                return {"dpu": None, "period": None, "unique_clicks": 0, "note": "no_data"}
            return {"dpu": None, "period": pname, "unique_clicks": uniq, "note": "insufficient_data"}
    return {"dpu": None, "period": None, "unique_clicks": 0, "note": "no_data"}


# ---------- для панели ----------

def invalidate_offer_cache(offer_id: str, rotation_id: str = "") -> None:
    """Сбрасывает Binom-кеш для оффера — все rotation_id варианты."""
    prefix = f"panel_dpu10:{offer_id}:"
    keys_to_del = [k for k in _DPU_CACHE if k.startswith(prefix)]
    for k in keys_to_del:
        del _DPU_CACHE[k]


def _find_geo_row(pack: Dict, rotation_id: str, geo_name: str) -> Optional[Dict]:
    """
    Ищет строку страны в иерархии rotation(level=1) → geoCountry(level=2).
    Если в ответе только одна ротация — не фильтруем по rotation_id.
    """
    if not pack or not pack.get("_ok"):
        return None
    rows = extract_rows(pack.get("_data", {}))

    # Резолвим geo_name в официальное название Binom ("Turkey" → "Türkiye")
    try:
        from geo_map import resolve_geo_name
        from cache import get_country_map
        geo_name = resolve_geo_name(geo_name, get_country_map())
    except ImportError:
        pass

    geo_want = geo_name.strip().lower()
    rid_want = str(rotation_id).strip() if rotation_id else ""

    def _extract_iso(s: str) -> set:
        """Извлекает 2-буквенные ISO коды из строки."""
        codes = set()
        for part in s.replace("/", " ").split():
            if len(part) == 2 and part.isalpha():
                codes.add(part.lower())
        return codes

    geo_codes = _extract_iso(geo_want)

    # Карта code→name для поиска официального имени из report row
    cmap = get_country_map()  # "TR" → "Türkiye"
    # Обратная карта: official_name.lower() → code
    name_to_code = {v.lower(): k for k, v in cmap.items()}
    # Код для нашего geo_want (панель хранит официальные имена после синхронизации)
    geo_want_code = name_to_code.get(geo_want, "")

    def _geo_match(name: str) -> bool:
        n = name.strip().lower()
        # Точное совпадение
        if n == geo_want:
            return True
        # ISO код из названия в отчёте совпадает с кодом нашего GEO
        if geo_want_code:
            n_codes = _extract_iso(n)
            if geo_want_code.lower() in n_codes:
                return True
        # ISO коды из обеих строк пересекаются
        if geo_codes:
            n_codes = _extract_iso(n)
            if geo_codes & n_codes:
                return True
        # Официальное имя row совпадает с нашим geo_want
        row_code = name_to_code.get(n, "")
        if row_code and row_code.lower() in geo_codes:
            return True
        # Фоллбэк: вхождение
        if geo_want and (n in geo_want or geo_want in n):
            return True
        return False

    # Считаем сколько уникальных ротаций в ответе
    rot_ids = set()
    for row in rows:
        if isinstance(row, dict) and str(row.get("level", "")).strip() == "1":
            rot_ids.add(str(row.get("entity_id") or "").strip())
    single_rotation = len(rot_ids) <= 1  # если одна (или ноль) — фильтр не нужен

    cur_rot_id = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level", "")).strip()
        if level == "1":
            cur_rot_id = str(row.get("entity_id") or "").strip()
        elif level == "2":
            name = str(row.get("name", "")).strip().lower()
            if _geo_match(name):
                if not single_rotation and rid_want and cur_rot_id != rid_want:
                    print(f"[geo_row] SKIP geo={name} rot={cur_rot_id!r} want_rot={rid_want!r}", flush=True)
                    continue
                print(f"[geo_row] MATCH geo={name} rot={cur_rot_id!r} uniq={row.get('unique_campaign_clicks')}", flush=True)
                return row

    print(f"[geo_row] NOT FOUND geo={geo_want!r} rid={rid_want!r} total_rows={len(rows)} rot_ids={rot_ids}", flush=True)
    return None


def _fetch_period_pack(offer_id: str, rotation_id: str, pname: str, preset: str) -> Tuple[str, Any]:
    """Один запрос одного периода. report/offer + rotation+geoCountry. Кешируется."""
    cache_key = f"panel_dpu10:{offer_id}:{rotation_id}:{preset}"
    pack = cache_get(cache_key)
    if pack is None:
        pairs = [
            ("datePreset",  preset),
            ("timezone",    "Europe/Moscow"),
            ("groupings[]", "rotation"),
            ("groupings[]", "geoCountry"),
            ("sortColumn",  "clicks"),
            ("sortType",    "desc"),
            ("limit",       "5000"),
            ("ids[]",       str(offer_id)),
        ]
        try:
            r    = binom_get_pairs("/public/api/v1/report/offer", pairs)
            pack = {"_ok": r.ok, "_data": _safe_json(r), "_rotation_id": int(rotation_id) if rotation_id else None}
        except Exception:
            pack = {"_ok": False, "_data": {}, "_rotation_id": None}
        cache_set(cache_key, pack)
    return pname, pack


def calc_dpu_for_panel_offer(offer_id: str, geo_name: str, rotation_id: str = "") -> Dict[str, Any]:
    """
    DPU для оффера панели — периоды последовательно 7d→14d→30d→this_year→all_time.
    Останавливается на первом периоде с uniq >= MIN_UNIQ.
    """
    best: Optional[Dict[str, Any]] = None

    for pname, preset in PERIODS:
        _, pack = _fetch_period_pack(offer_id, rotation_id, pname, preset)
        row = _find_geo_row(pack, rotation_id, geo_name)
        if not row:
            print(f"[dpu] offer={offer_id} geo={geo_name} rid={rotation_id} period={pname} → no row", flush=True)
            continue
        dpu, uniq = extract_dpu_from_row(row)
        print(f"[dpu] offer={offer_id} geo={geo_name} rid={rotation_id} period={pname} → uniq={uniq} dpu={dpu:.4f}", flush=True)
        if uniq >= MIN_UNIQ:
            return {"dpu": dpu, "period": pname, "unique_clicks": uniq}
        if uniq > 0 and best is None:
            best = {"dpu": None, "period": pname, "unique_clicks": uniq, "note": "insufficient_data"}

    if best:
        return best
    return {"dpu": None, "period": None, "unique_clicks": 0, "note": "no_data"}