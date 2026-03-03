from datetime import datetime
from typing import Any, Dict, List

from flask import Blueprint, jsonify, make_response, request

from binom_client import binom_get, binom_get_pairs, binom_put, _safe_json
from config import LOCAL_TZ
from dpu import calc_dpu_for_offer, extract_rows, extract_dpu_from_row, MIN_UNIQ

bp = Blueprint("rotations", __name__)


def _now_local_str() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _parse_country_name(geo_title: str) -> str:
    t = (geo_title or "").strip()
    if not t:
        return ""
    parts = t.split()
    if len(parts) >= 2:
        last = parts[-1]
        if len(last) in (2, 3) and last.isalpha() and last.upper() == last:
            return " ".join(parts[:-1]).strip()
    return t


def _get_rotation_src(rotation_id: int):
    r = binom_get(f"/public/api/v1/rotation/{rotation_id}")
    if not r.ok:
        return None, make_response(jsonify({
            "ok": False, "server_time_local": _now_local_str(),
            "binom_status": r.status_code, "error": "Binom request failed",
            "details": r.text[:2000],
        }), 502)
    data = _safe_json(r)
    src  = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    return src, None


@bp.get("/api/rotations")
def api_rotations():
    q        = request.args.get("q", "").strip()
    status   = request.args.get("status", "").strip()
    page     = request.args.get("page", "").strip()
    per_page = request.args.get("per_page", "").strip()

    params: Dict[str, Any] = {}
    if q:        params["search"]   = q
    if status:   params["status"]   = status
    if page:     params["page"]     = page
    if per_page: params["per_page"] = per_page

    r = binom_get("/public/api/v1/rotation/list/filtered", params=params)
    if not r.ok:
        return make_response(jsonify({
            "ok": False, "server_time_local": _now_local_str(),
            "binom_status": r.status_code, "error": "Binom request failed",
            "details": r.text[:2000],
        }), 502)
    return jsonify({"ok": True, "server_time_local": _now_local_str(), "data": _safe_json(r)})


@bp.get("/api/rotation/<int:rotation_id>")
def api_rotation_details(rotation_id: int):
    r = binom_get(f"/public/api/v1/rotation/{rotation_id}")
    if not r.ok:
        return make_response(jsonify({
            "ok": False, "server_time_local": _now_local_str(),
            "binom_status": r.status_code, "error": "Binom request failed",
        }), 502)
    return jsonify({"ok": True, "server_time_local": _now_local_str(), "data": _safe_json(r)})


@bp.get("/api/rotation/<int:rotation_id>/rules")
def api_rotation_rules(rotation_id: int):
    src, err = _get_rotation_src(rotation_id)
    if err:
        return err
    rules = src.get("rules") or [] if isinstance(src, dict) else []
    return jsonify({"ok": True, "server_time_local": _now_local_str(),
                    "rotation_id": rotation_id, "rules": rules})


@bp.get("/api/rotation/<int:rotation_id>/active_offers_grouped")
def api_rotation_active_offers_grouped(rotation_id: int):
    src, err = _get_rotation_src(rotation_id)
    if err:
        return err
    rules = src if isinstance(src, list) else (src.get("rules") or [])

    grouped: Dict[str, Any] = {}
    total_offers = 0

    for rule in (rules if isinstance(rules, list) else []):
        if not isinstance(rule, dict) or rule.get("enabled") is False:
            continue
        geo_title = str(rule.get("name") or "—").strip()
        for path in (rule.get("paths") or []):
            if not isinstance(path, dict) or path.get("enabled") is False:
                continue
            for off in (path.get("offers") or []):
                if not isinstance(off, dict) or off.get("enabled") is False:
                    continue
                try:
                    w = float(off.get("weight") or 0)
                except Exception:
                    w = 0.0
                if w <= 0:
                    continue
                total_offers += 1
                entry = grouped.setdefault(geo_title, {
                    "geoTitle": geo_title, "totalWeight": 0.0, "items": []
                })
                entry["totalWeight"] += w
                entry["items"].append({
                    "offerId":              off.get("offerId") or off.get("id"),
                    "offerName":            off.get("name") or "—",
                    "weight":               w,
                    "affiliateNetworkName": off.get("affiliateNetworkName") or "",
                    "pathName":             path.get("name") or "—",
                })

    groups = sorted(grouped.values(), key=lambda x: x["totalWeight"], reverse=True)
    for g in groups:
        g["items"].sort(key=lambda x: x["weight"], reverse=True)

    return jsonify({"ok": True, "server_time_local": _now_local_str(),
                    "rotation_id": rotation_id, "total_offers": total_offers, "groups": groups})


@bp.get("/api/rotation/<int:rotation_id>/dpu")
def api_rotation_dpu(rotation_id: int):
    src, err = _get_rotation_src(rotation_id)
    if err:
        return err
    rules = src if isinstance(src, list) else (src.get("rules") or [])

    grouped: Dict[str, Any] = {}
    total_offers = 0

    for rule in (rules if isinstance(rules, list) else []):
        if not isinstance(rule, dict) or rule.get("enabled") is False:
            continue
        geo_title = str(rule.get("name") or "—").strip()
        for path in (rule.get("paths") or []):
            if not isinstance(path, dict) or path.get("enabled") is False:
                continue
            for off in (path.get("offers") or []):
                if not isinstance(off, dict) or off.get("enabled") is False:
                    continue
                try:
                    w = float(off.get("weight") or 0)
                except Exception:
                    w = 0.0
                if w <= 0:
                    continue
                total_offers += 1
                entry = grouped.setdefault(geo_title, {
                    "geoTitle": geo_title, "countryName": _parse_country_name(geo_title),
                    "totalWeight": 0.0, "items": []
                })
                entry["totalWeight"] += w
                entry["items"].append({
                    "offerId": off.get("offerId") or off.get("id"),
                    "offerName": off.get("name") or "—",
                    "weight": w,
                    "affiliateNetworkName": off.get("affiliateNetworkName") or "",
                    "pathName": path.get("name") or "—",
                    "dpu": None, "dpu_period": None, "dpu_uniq": None, "dpu_note": None,
                })

    groups = sorted(grouped.values(), key=lambda x: x["totalWeight"], reverse=True)
    for g in groups:
        g["items"].sort(key=lambda x: x["weight"], reverse=True)

    computed = 0
    for g in groups:
        for item in g["items"]:
            offer_id = item.get("offerId")
            if not offer_id:
                continue
            res = calc_dpu_for_offer(rotation_id, offer_id, g["geoTitle"])
            item["dpu"]        = float(res.get("dpu") or 0.0)
            item["dpu_period"] = res.get("period", "—")
            item["dpu_uniq"]   = int(res.get("unique_clicks") or 0)
            item["dpu_note"]   = res.get("note")
            computed += 1

    return jsonify({
        "ok": True, "server_time_local": _now_local_str(),
        "rotation_id": rotation_id, "total_offers": total_offers,
        "computed_offers": computed, "min_uniq_threshold": MIN_UNIQ, "groups": groups,
    })


@bp.get("/api/rotation/<int:rotation_id>/dpu_geo")
def api_rotation_dpu_geo(rotation_id: int):
    geo_title = request.args.get("geo", "").strip()
    if not geo_title:
        return make_response(jsonify({"ok": False, "error": "geo param required"}), 400)

    src, err = _get_rotation_src(rotation_id)
    if err:
        return err
    rules = src if isinstance(src, list) else (src.get("rules") or [])

    items: List[Dict[str, Any]] = []
    for rule in (rules if isinstance(rules, list) else []):
        if not isinstance(rule, dict) or rule.get("enabled") is False:
            continue
        if str(rule.get("name") or "").strip() != geo_title:
            continue
        for path in (rule.get("paths") or []):
            if not isinstance(path, dict) or path.get("enabled") is False:
                continue
            for off in (path.get("offers") or []):
                if not isinstance(off, dict) or off.get("enabled") is False:
                    continue
                try:
                    w = float(off.get("weight") or 0)
                except Exception:
                    w = 0.0
                if w <= 0:
                    continue
                items.append({
                    "offerId": off.get("offerId") or off.get("id"),
                    "offerName": off.get("name") or "—",
                    "weight": w,
                    "affiliateNetworkName": off.get("affiliateNetworkName") or "",
                    "pathName": path.get("name") or "—",
                    "dpu": None, "dpu_period": None, "dpu_uniq": None, "dpu_note": None,
                })

    for item in items:
        offer_id = item.get("offerId")
        if not offer_id:
            continue
        res = calc_dpu_for_offer(rotation_id, offer_id, geo_title)
        item["dpu"]        = float(res.get("dpu") or 0.0)
        item["dpu_period"] = res.get("period", "—")
        item["dpu_uniq"]   = int(res.get("unique_clicks") or 0)
        item["dpu_note"]   = res.get("note")

    return jsonify({
        "ok": True, "server_time_local": _now_local_str(),
        "rotation_id": rotation_id, "geo_title": geo_title,
        "computed_offers": len(items), "min_uniq_threshold": MIN_UNIQ, "items": items,
    })


@bp.get("/api/rotation/<int:rotation_id>/analytics")
def api_rotation_analytics(rotation_id: int):
    """
    Аналитика офферов в ротации: Uniq / Reg / FD / CR% / FTD% / DPU / Weight.
    ?preset=last_7_days|last_14_days|last_30_days|this_year|all_time
    """
    preset = request.args.get("preset", "last_7_days").strip()

    # 1. Получаем активные офферы из ротации
    src, err = _get_rotation_src(rotation_id)
    if err:
        return err
    rules = src if isinstance(src, list) else (src.get("rules") or [])

    # Собираем offers по GEO
    geo_offers: Dict[str, List[Dict]] = {}
    all_offer_ids: List[str] = []
    for rule in (rules if isinstance(rules, list) else []):
        if not isinstance(rule, dict) or rule.get("enabled") is False:
            continue
        geo = str(rule.get("name") or "").strip()
        if not geo:
            continue
        for path in (rule.get("paths") or []):
            if not isinstance(path, dict) or path.get("enabled") is False:
                continue
            for off in (path.get("offers") or []):
                if not isinstance(off, dict) or off.get("enabled") is False:
                    continue
                try:
                    w = float(off.get("weight") or 0)
                except Exception:
                    w = 0.0
                if w <= 0:
                    continue
                oid = str(off.get("offerId") or off.get("id") or "")
                if not oid:
                    continue
                if geo not in geo_offers:
                    geo_offers[geo] = []
                geo_offers[geo].append({
                    "offerId": oid,
                    "offerName": off.get("name") or "—",
                    "weight": w,
                })
                if oid not in all_offer_ids:
                    all_offer_ids.append(oid)

    if not all_offer_ids:
        return jsonify({"ok": True, "groups": [], "rotation_id": rotation_id})

    # 2. Запрос в Binom: rotation → offer → geoCountry
    # Запрос с группировкой rotation → offer → geoCountry
    # Так же как dpu.py — фильтруем по entity_id ротации на уровне 1
    pairs2 = [
        ("datePreset",   preset),
        ("timezone",     "Europe/Moscow"),
        ("groupings[]",  "rotation"),
        ("groupings[]",  "offer"),
        ("groupings[]",  "geoCountry"),
        ("sortColumn",   "clicks"),
        ("sortType",     "desc"),
        ("limit",        "10000"),
    ]
    for oid in all_offer_ids:
        pairs2.append(("ids[]", oid))

    try:
        r2 = binom_get_pairs("/public/api/v1/report/offer", pairs2)
        raw2 = _safe_json(r2)
    except Exception:
        raw2 = {}

    rows2 = extract_rows(raw2)

    def _get_uuid_field_raw(row, prefix: str):
        p = prefix.lower() + "::"
        for k, v in row.items():
            if isinstance(k, str) and k.lower().startswith(p):
                return v
        return None

    # Строим индекс: offer_id -> geo_lower -> stats
    # Уровни: 1=rotation, 2=offer, 3=geoCountry
    # Берём данные только из нашей ротации
    stats_index: Dict[str, Dict[str, Dict]] = {}
    in_our_rotation = False
    cur_offer_id = None
    rid_str = str(rotation_id)

    for row in rows2:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level", "")).strip()
        if level == "1":
            # Rotation уровень — проверяем что это наша ротация
            in_our_rotation = str(row.get("entity_id") or "").strip() == rid_str
            cur_offer_id = None
        elif level == "2" and in_our_rotation:
            cur_offer_id = str(row.get("entity_id") or "").strip()
        elif level == "3" and in_our_rotation and cur_offer_id:
            geo_name = str(row.get("name") or "").strip().lower()
            if cur_offer_id not in stats_index:
                stats_index[cur_offer_id] = {}
            stats_index[cur_offer_id][geo_name] = row

    # 4. Собираем результат
    def _get_uuid_field(row, prefix: str) -> float:
        """Ищет поле вида PREFIX::UUID и возвращает float."""
        p = prefix.lower() + "::"
        for k, v in row.items():
            if isinstance(k, str) and k.lower().startswith(p):
                try:
                    return float(v or 0)
                except Exception:
                    return 0.0
        return 0.0

    def _get_stat(row, *fields):
        for f in fields:
            v = row.get(f)
            if v is not None and v != "":
                try:
                    return float(v)
                except Exception:
                    pass
        return 0.0

    def _find_geo_stats(offer_id: str, geo_title: str):
        geo_lower = geo_title.strip().lower()
        offer_stats = stats_index.get(offer_id, {})
        if geo_lower in offer_stats:
            return offer_stats[geo_lower]
        for k, v in offer_stats.items():
            if k.startswith(geo_lower + " ") or k.startswith(geo_lower + "_") or geo_lower.startswith(k + " "):
                return v
        return None

    groups_out = []
    for geo, offers in geo_offers.items():
        items_out = []
        for off in offers:
            oid = off["offerId"]
            row = _find_geo_stats(oid, geo)
            if row:
                uniq   = int(_get_stat(row, "unique_campaign_clicks") or 0)
                reg    = int(_get_uuid_field(row, "Reg") or _get_stat(row, "leads", "event_1") or 0)
                fd     = int(_get_uuid_field(row, "FD")  or _get_stat(row, "event_2") or 0)
                dpu, _ = extract_dpu_from_row(row)
                # cr из Binom уже посчитан как reg/clicks*100, нам нужен reg/uniq
                cr     = round(reg / uniq * 100, 1) if uniq > 0 else None
                ftd_r  = round(fd  / reg * 100, 1) if reg  > 0 else None
                profit = _get_stat(row, "profit", "revenue")
            else:
                uniq = reg = fd = 0
                dpu = profit = 0.0
                cr = ftd_r = None

            items_out.append({
                "offerId":   oid,
                "offerName": off["offerName"],
                "weight":    off["weight"],
                "uniq":  uniq,
                "reg":   reg,
                "fd":    fd,
                "dpu":   round(dpu, 4) if dpu else 0,
                "profit": round(profit, 2),
                "cr":    cr,
                "ftd_rate": ftd_r,
            })

        # Сортируем по DPU desc
        items_out.sort(key=lambda x: x["dpu"] or 0, reverse=True)

        # Рекомендации — эталон всегда 100 (лидер должен иметь вес 100)
        best_item   = max(items_out, key=lambda x: x["dpu"] or 0) if items_out else None
        max_dpu     = best_item["dpu"] if best_item and best_item.get("dpu") else 0
        for item in items_out:
            ideal = _calc_ideal_weight(item.get("dpu") or 0, max_dpu, 100.0)
            item["ideal_weight"] = max(0, round(ideal))
            item["rec"] = _weight_rec(item, max_dpu, 100.0)

        groups_out.append({"geo": geo, "items": items_out})

    groups_out.sort(key=lambda x: sum(i["uniq"] for i in x["items"]), reverse=True)

    return jsonify({
        "ok": True,
        "rotation_id": rotation_id,
        "preset": preset,
        "groups": groups_out,
        "server_time_local": _now_local_str(),
    })


def _calc_ideal_weight(dpu: float, max_dpu: float, best_weight: float) -> float:
    """
    Идеальный вес: diff/half_best = ratio, ideal = best_weight * (1 - ratio)
    Если ideal <= 0 — оффер в 2+ раза хуже топа.
    """
    if max_dpu <= 0:
        return 0.0
    ratio = (max_dpu - dpu) / (max_dpu / 2.0)
    return best_weight * (1.0 - ratio)


def _weight_rec(item: Dict, max_dpu: float, best_weight: float = 100.0) -> str:
    """
    Рекомендация на основе DPU + текущего веса.
    ideal_weight вычисляется по формуле, сравнивается с actual (±15% tolerance).
    """
    dpu       = item.get("dpu") or 0
    actual_wt = float(item.get("weight") or 0)

    if dpu <= 0 or max_dpu <= 0:
        return "нет данных"

    ideal = _calc_ideal_weight(dpu, max_dpu, best_weight)

    if ideal <= 0:
        return "стоп"

    if actual_wt <= 0:
        return "нет данных"

    tolerance = ideal * 0.15
    diff_wt   = actual_wt - ideal   # >0 завышен, <0 занижен

    if diff_wt > tolerance:
        return "снизить вес"
    elif diff_wt < -tolerance:
        return "увеличить вес"
    else:
        return "держать"


@bp.get("/api/rotation/<int:rotation_id>/analytics_geo")
def api_rotation_analytics_geo(rotation_id: int):
    """
    Аналитика офферов для одного GEO.
    ?geo=Brazil BR&preset=today|last_7_days|...
    """
    geo_title = request.args.get("geo", "").strip()
    preset    = request.args.get("preset", "today").strip()
    if not geo_title:
        return make_response(jsonify({"ok": False, "error": "geo required"}), 400)

    # Получаем офферы этого GEO из ротации
    src, err = _get_rotation_src(rotation_id)
    if err:
        return err
    rules = src if isinstance(src, list) else (src.get("rules") or [])

    offer_ids = []
    offer_map = {}
    for rule in (rules if isinstance(rules, list) else []):
        if not isinstance(rule, dict) or rule.get("enabled") is False:
            continue
        if str(rule.get("name") or "").strip() != geo_title:
            continue
        for path in (rule.get("paths") or []):
            if not isinstance(path, dict) or path.get("enabled") is False:
                continue
            for off in (path.get("offers") or []):
                if not isinstance(off, dict) or off.get("enabled") is False:
                    continue
                try:
                    w = float(off.get("weight") or 0)
                except Exception:
                    w = 0.0
                if w <= 0:
                    continue
                oid = str(off.get("offerId") or off.get("id") or "")
                if oid and oid not in offer_map:
                    offer_ids.append(oid)
                    offer_map[oid] = {"offerId": oid, "offerName": off.get("name") or "—", "weight": w}

    if not offer_ids:
        return jsonify({"ok": True, "items": [], "geo": geo_title, "preset": preset})

    # Маппинг пресетов — today через dateFrom/dateTo
    from datetime import date
    import pytz
    tz     = pytz.timezone("Europe/Moscow")
    today  = datetime.now(tz).date()

    PRESET_MAP = {
        "today":         {"datePreset": "today"},
        "yesterday":     {"datePreset": "yesterday"},
        "last_7_days":   {"datePreset": "last_7_days"},
        "last_14_days":  {"datePreset": "last_14_days"},
        "last_30_days":  {"datePreset": "last_30_days"},
    }

    preset_params = PRESET_MAP.get(preset, {"datePreset": "last_7_days"})

    pairs = [
        ("timezone",     "Europe/Moscow"),
        ("groupings[]",  "rotation"),
        ("groupings[]",  "offer"),
        ("groupings[]",  "geoCountry"),
        ("sortColumn",   "clicks"),
        ("sortType",     "desc"),
        ("limit",        "10000"),
    ]
    for k, v in preset_params.items():
        pairs.append((k, v))
    for oid in offer_ids:
        pairs.append(("ids[]", oid))

    try:
        r = binom_get_pairs("/public/api/v1/report/offer", pairs)
        raw = _safe_json(r)
    except Exception:
        raw = {}

    rows = extract_rows(raw)

    # Индекс: offer_id -> geo -> row (только наша ротация)
    stats_index: Dict[str, Dict[str, Dict]] = {}
    in_our_rotation = False
    cur_offer_id = None
    rid_str = str(rotation_id)

    for row in rows:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level", "")).strip()
        if level == "1":
            in_our_rotation = str(row.get("entity_id") or "").strip() == rid_str
            cur_offer_id = None
        elif level == "2" and in_our_rotation:
            cur_offer_id = str(row.get("entity_id") or "").strip()
        elif level == "3" and in_our_rotation and cur_offer_id:
            geo_name = str(row.get("name") or "").strip().lower()
            if cur_offer_id not in stats_index:
                stats_index[cur_offer_id] = {}
            stats_index[cur_offer_id][geo_name] = row

    def _get_uuid_field(row, prefix: str) -> float:
        p = prefix.lower() + "::"
        for k, v in row.items():
            if isinstance(k, str) and k.lower().startswith(p):
                try: return float(v or 0)
                except: return 0.0
        return 0.0

    def _get_stat(row, *fields):
        for f in fields:
            v = row.get(f)
            if v is not None and v != "":
                try: return float(v)
                except: pass
        return 0.0

    def _find_geo(offer_id, geo):
        geo_lower = geo.strip().lower()
        stats = stats_index.get(offer_id, {})
        if geo_lower in stats:
            return stats[geo_lower]
        for k, v in stats.items():
            if k.startswith(geo_lower + " ") or geo_lower.startswith(k + " "):
                return v
        return None

    items_out = []
    for oid in offer_ids:
        off = offer_map[oid]
        row = _find_geo(oid, geo_title)
        if row:
            uniq  = int(_get_stat(row, "unique_campaign_clicks") or 0)
            reg   = int(_get_uuid_field(row, "Reg") or _get_stat(row, "leads", "event_1") or 0)
            fd    = int(_get_uuid_field(row, "FD")  or _get_stat(row, "event_2") or 0)
            dpu, _ = extract_dpu_from_row(row)
            profit = _get_stat(row, "profit", "revenue")
            cr     = round(reg / uniq * 100, 1) if uniq > 0 else None
            ftd_r  = round(fd  / reg * 100, 1) if reg  > 0 else None
        else:
            uniq = reg = fd = 0
            dpu = profit = 0.0
            cr = ftd_r = None

        items_out.append({
            "offerId":   oid,
            "offerName": off["offerName"],
            "weight":    off["weight"],
            "uniq": uniq, "reg": reg, "fd": fd,
            "dpu":  round(dpu, 4) if dpu else 0,
            "profit": round(profit, 2),
            "cr": cr, "ftd_rate": ftd_r,
        })

    items_out.sort(key=lambda x: x["dpu"] or 0, reverse=True)
    best_item   = items_out[0] if items_out else None
    max_dpu     = best_item["dpu"] if best_item and best_item.get("dpu") else 0
    for item in items_out:
        ideal = _calc_ideal_weight(item.get("dpu") or 0, max_dpu, 100.0)
        item["ideal_weight"] = max(0, round(ideal))
        item["rec"] = _weight_rec(item, max_dpu, 100.0)

    return jsonify({
        "ok": True, "geo": geo_title, "preset": preset,
        "items": items_out, "server_time_local": _now_local_str(),
    })


@bp.patch("/api/rotation/<int:rotation_id>/offer_weight")
def api_update_offer_weight(rotation_id: int):
    """
    Обновляет вес оффера в ротации.
    Body: { "offer_id": "123", "weight": 50 }
    """
    body = request.get_json(force=True) or {}
    offer_id   = str(body.get("offer_id", "")).strip()
    new_weight = body.get("weight")

    if not offer_id:
        return make_response(jsonify({"ok": False, "error": "offer_id required"}), 400)
    try:
        new_weight = int(float(new_weight))
        if new_weight < 0:
            raise ValueError
    except (TypeError, ValueError):
        return make_response(jsonify({"ok": False, "error": "invalid weight"}), 400)

    # GET текущее состояние ротации
    src, err = _get_rotation_src(rotation_id)
    if err:
        return err

    # Binom возвращает data внутри обёртки — нам нужен исходный dict для PUT
    r_raw = binom_get(f"/public/api/v1/rotation/{rotation_id}")
    if not r_raw.ok:
        return make_response(jsonify({"ok": False, "error": "Failed to fetch rotation"}), 502)
    rotation_data = _safe_json(r_raw)
    # Извлекаем нужный уровень
    if isinstance(rotation_data, dict) and isinstance(rotation_data.get("data"), dict):
        rotation_obj = rotation_data["data"]
    else:
        rotation_obj = rotation_data

    rules = rotation_obj if isinstance(rotation_obj, list) else (rotation_obj.get("rules") or [])

    # Находим и обновляем вес оффера во всех путях где он встречается
    updated = 0
    for rule in (rules if isinstance(rules, list) else []):
        if not isinstance(rule, dict):
            continue
        for path in (rule.get("paths") or []):
            if not isinstance(path, dict):
                continue
            for off in (path.get("offers") or []):
                if not isinstance(off, dict):
                    continue
                oid = str(off.get("offerId") or off.get("id") or "")
                if oid == offer_id:
                    off["weight"] = int(new_weight)
                    updated += 1

    if updated == 0:
        return make_response(jsonify({"ok": False, "error": f"Offer {offer_id} not found in rotation"}), 404)

    # Логируем что отправляем
    put_payload = rotation_obj if isinstance(rotation_obj, list) else rotation_obj
    print(f"[weight] PUT /rotation/{rotation_id} payload keys: {list(put_payload.keys()) if isinstance(put_payload, dict) else type(put_payload)}", flush=True)
    print(f"[weight] updated={updated} offer_id={offer_id} new_weight={new_weight}", flush=True)

    r_put = binom_put(f"/public/api/v1/rotation/{rotation_id}", put_payload)
    print(f"[weight] response status={r_put.status_code} body={r_put.text[:500]}", flush=True)

    if not r_put.ok:
        return make_response(jsonify({
            "ok": False, "error": f"Binom PUT failed: {r_put.status_code}",
            "details": r_put.text[:500]
        }), 502)

    return jsonify({
        "ok": True,
        "offer_id": offer_id,
        "weight": new_weight,
        "updated_paths": updated,
        "server_time_local": _now_local_str(),
    })