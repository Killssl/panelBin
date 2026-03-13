from datetime import datetime
from typing import Any, Dict, List

from flask import Blueprint, jsonify, make_response, request

from app.services.binom import binom_get, binom_get_pairs, binom_put, _safe_json
from app.utils.config import LOCAL_TZ
from app.utils.dpu import calc_dpu_for_offer, extract_rows, extract_dpu_from_row, MIN_UNIQ

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
    ?network=BlackFlag+Partners  (фильтр по партнёрке, опционально)
    """
    preset         = request.args.get("preset",  "last_7_days").strip()
    network_filter = request.args.get("network", "").strip().lower()

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
                net = str(off.get("affiliateNetworkName") or "")
                # Фильтруем по партнёрке если задан параметр
                if network_filter and network_filter not in net.lower():
                    continue
                if geo not in geo_offers:
                    geo_offers[geo] = []
                geo_offers[geo].append({
                    "offerId":              oid,
                    "offerName":            off.get("name") or "—",
                    "weight":               w,
                    "affiliateNetworkName": net,
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
                "offerId":              oid,
                "offerName":            off["offerName"],
                "weight":               off["weight"],
                "affiliateNetworkName": off.get("affiliateNetworkName", ""),
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

    # Собираем все уникальные партнёрки для дропдауна (из всей ротации без фильтра)
    all_networks: List[str] = []
    for rule in (rules if isinstance(rules, list) else []):
        if not isinstance(rule, dict) or rule.get("enabled") is False:
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
                net = str(off.get("affiliateNetworkName") or "").strip()
                if net and net not in all_networks:
                    all_networks.append(net)
    all_networks.sort()

    return jsonify({
        "ok": True,
        "rotation_id": rotation_id,
        "preset": preset,
        "network_filter": network_filter,
        "networks": all_networks,
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


@bp.route("/api/rotation/<int:rotation_id>/add_offer", methods=["POST"])
def api_rotation_add_offer(rotation_id: int):
    """
    Добавляет оффер в первый активный Path нужного GEO правила.
    Body: { "offer_id": "123", "offer_name": "...", "geo": "Canada CA", "weight": 50 }
    """
    body      = request.get_json(force=True) or {}
    offer_id  = str(body.get("offer_id", "")).strip()
    offer_name = str(body.get("offer_name", "")).strip()
    geo_title  = str(body.get("geo", "")).strip()
    try:
        weight = int(float(body.get("weight", 50)))
        if weight < 0:
            raise ValueError
    except (TypeError, ValueError):
        weight = 50

    if not offer_id or not geo_title:
        return make_response(jsonify({"ok": False, "error": "offer_id and geo required"}), 400)

    # Получаем текущее состояние ротации
    r_raw = binom_get(f"/public/api/v1/rotation/{rotation_id}")
    if not r_raw.ok:
        return make_response(jsonify({"ok": False, "error": "Failed to fetch rotation"}), 502)

    rotation_data = _safe_json(r_raw)
    if isinstance(rotation_data, dict) and isinstance(rotation_data.get("data"), dict):
        rotation_obj = rotation_data["data"]
    else:
        rotation_obj = rotation_data

    rules = rotation_obj if isinstance(rotation_obj, list) else (rotation_obj.get("rules") or [])

    # Ищем правило с нужным GEO
    target_rule = None
    for rule in (rules if isinstance(rules, list) else []):
        if not isinstance(rule, dict):
            continue
        if str(rule.get("name") or "").strip() == geo_title:
            target_rule = rule
            break

    if target_rule is None:
        # Пробуем частичное совпадение (например "Canada CA" vs "Canada")
        geo_lower = geo_title.lower()
        for rule in (rules if isinstance(rules, list) else []):
            if not isinstance(rule, dict):
                continue
            rname = str(rule.get("name") or "").strip().lower()
            if rname in geo_lower or geo_lower in rname:
                target_rule = rule
                break

    if target_rule is None:
        return make_response(jsonify({
            "ok": False,
            "error": f"GEO '{geo_title}' не найден в ротации {rotation_id}",
            "available_geos": [str(r.get("name","")) for r in (rules if isinstance(rules, list) else []) if isinstance(r, dict)]
        }), 404)

    # Берём первый активный Path
    paths = target_rule.get("paths") or []
    target_path = None
    for path in paths:
        if isinstance(path, dict) and path.get("enabled") is not False:
            target_path = path
            break

    if target_path is None:
        return make_response(jsonify({"ok": False, "error": f"Нет активных путей в GEO '{geo_title}'"}), 404)

    # Проверяем что оффер ещё не стоит
    existing_offers = target_path.get("offers") or []
    for off in existing_offers:
        if str(off.get("offerId") or off.get("id") or "") == offer_id:
            return make_response(jsonify({
                "ok": False,
                "error": f"Оффер {offer_id} уже стоит в этой ротации/GEO"
            }), 409)

    # Берём campaignId из существующих офферов в этом Path (Binom требует его)
    campaign_id = None
    for off in existing_offers:
        print(f"[add_offer] existing offer keys: {list(off.keys())} values: { {k:v for k,v in off.items() if 'campaign' in k.lower() or 'id' in k.lower()} }", flush=True)
        cid = off.get("campaignId") or off.get("campaign_id") or off.get("CampaignId")
        if cid is not None:
            campaign_id = int(cid)
            break

    print(f"[add_offer] resolved campaign_id={campaign_id}", flush=True)

    # Добавляем оффер
    new_offer = {
        "offerId":    int(offer_id) if offer_id.isdigit() else offer_id,
        "campaignId": campaign_id,
        "name":       offer_name,
        "weight":     weight,
        "enabled":    True,
    }
    existing_offers.append(new_offer)
    target_path["offers"] = existing_offers

    print(f"[add_offer] rotation={rotation_id} geo='{geo_title}' path='{target_path.get('name')}' offer_id={offer_id} weight={weight}", flush=True)

    r_put = binom_put(f"/public/api/v1/rotation/{rotation_id}", rotation_obj)
    print(f"[add_offer] PUT status={r_put.status_code} body={r_put.text[:300]}", flush=True)

    if not r_put.ok:
        return make_response(jsonify({
            "ok": False,
            "error": f"Binom PUT failed: {r_put.status_code}",
            "details": r_put.text[:500]
        }), 502)

    return jsonify({
        "ok":          True,
        "offer_id":    offer_id,
        "offer_name":  offer_name,
        "geo":         geo_title,
        "weight":      weight,
        "path_name":   target_path.get("name", "—"),
        "rotation_id": rotation_id,
        "server_time_local": _now_local_str(),
    })


@bp.get("/api/offers/binom")
def api_all_offers_binom():
    """
    Все ротации → офферы weight > 0, сгруппированные по GEO.
    Используется панелью Офферы.
    """
    rot_list = []
    offset, limit = 0, 200
    while True:
        r = binom_get("/public/api/v1/rotation/list/filtered",
                      params={"limit": limit, "offset": offset})
        if not r.ok:
            break
        data  = _safe_json(r)
        items = data if isinstance(data, list) \
            else (data.get("data") or data.get("items") or data.get("result") or []) \
            if isinstance(data, dict) else []
        if not items:
            break
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                rot_list.append({"id":   str(item["id"]),
                                  "name": str(item.get("name") or f"#{item['id']}")})
        if len(items) < limit:
            break
        offset += limit

    if not rot_list:
        return make_response(jsonify({"ok": False, "error": "Не удалось получить список ротаций"}), 500)

    rotations_out = []
    total_offers  = 0

    for rot in rot_list:
        src, err = _get_rotation_src(int(rot["id"]))
        if err or src is None:
            continue
        rules = src if isinstance(src, list) else (src.get("rules") or [])

        geos_dict: Dict[str, list] = {}
        for rule in (rules if isinstance(rules, list) else []):
            if not isinstance(rule, dict) or rule.get("enabled") is False:
                continue
            geo = str(rule.get("name") or "").strip()
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
                    if geo not in geos_dict:
                        geos_dict[geo] = []
                    if not any(o["offer_id"] == oid for o in geos_dict[geo]):
                        geos_dict[geo].append({
                            "offer_id":   oid,
                            "offer_name": str(off.get("name") or "").strip(),
                            "weight":     int(w),
                        })

        if not geos_dict:
            continue

        geos_out = [{"name": g, "offers": offs}
                    for g, offs in sorted(geos_dict.items())]
        total_offers += sum(len(g["offers"]) for g in geos_out)
        rotations_out.append({"id": rot["id"], "name": rot["name"], "geos": geos_out})

    return jsonify({
        "ok":              True,
        "rotations":       rotations_out,
        "total_rotations": len(rotations_out),
        "total_offers":    total_offers,
        "server_time":     _now_local_str(),
    })


# ─── Offers sync cache (JSON file) ───────────────────────────────────────────

import os, json, threading
_OFFERS_SYNC_FILE = os.path.join(os.path.dirname(__file__), "data/offers_sync.json")
_OFFERS_SYNC_LOCK = threading.Lock()


@bp.get("/api/offers/cached")
def api_offers_cached():
    """Возвращает последние сохранённые офферы (без обращения к Binom)."""
    with _OFFERS_SYNC_LOCK:
        if os.path.exists(_OFFERS_SYNC_FILE):
            try:
                with open(_OFFERS_SYNC_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return jsonify({"ok": True, "cached": True, **data})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)})
    return jsonify({"ok": True, "cached": False, "rotations": [], "total_rotations": 0, "total_offers": 0})


@bp.post("/api/offers/sync_save")
def api_offers_sync_save():
    """Сохраняет данные офферов (присланные фронтом после синхронизации)."""
    body = request.get_json(force=True) or {}
    rotations = body.get("rotations", [])
    if not isinstance(rotations, list):
        return make_response(jsonify({"ok": False, "error": "rotations must be array"}), 400)

    total_offers = sum(
        len(o) for r in rotations
        for g in r.get("geos", [])
        for o in [g.get("offers", [])]
    )
    payload = {
        "rotations":       rotations,
        "total_rotations": len(rotations),
        "total_offers":    total_offers,
        "synced_at":       _now_local_str(),
    }
    with _OFFERS_SYNC_LOCK:
        with open(_OFFERS_SYNC_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    return jsonify({"ok": True, "total_rotations": len(rotations), "total_offers": total_offers})


@bp.get("/api/offers/fd")
def api_offers_fd():
    """
    FD по офферам за указанный день.
    ?date=2025-03-08
    Возвращает: { offer_id: { geo_lower: fd_count } }
    """
    from app.utils.dpu import extract_rows
    from app.services.binom import binom_get_pairs
    from app.utils.cache import get_all_campaign_ids

    date_str = request.args.get("date", "").strip()
    if not date_str:
        return make_response(jsonify({"ok": False, "error": "date required (YYYY-MM-DD)"}), 400)

    campaign_ids = get_all_campaign_ids()
    if not campaign_ids:
        return make_response(jsonify({"ok": False, "error": "Не удалось получить кампании"}), 500)

    pairs = [
        ("datePreset",  "custom_time"),
        ("dateFrom",    f"{date_str} 00:00:00"),
        ("dateTo",      f"{date_str} 23:59:59"),
        ("timezone",    "Europe/Moscow"),
        ("groupings[]", "offer"),
        ("groupings[]", "rotation"),
        ("groupings[]", "geoCountry"),
        ("sortColumn",  "clicks"),
        ("sortType",    "desc"),
        ("limit",       "10000"),
        ("offset",      "0"),
    ] + [("ids[]", cid) for cid in campaign_ids]

    try:
        r   = binom_get_pairs("/public/api/v1/report/campaign", pairs)
        raw = _safe_json(r)
    except Exception as e:
        return make_response(jsonify({"ok": False, "error": str(e)}), 500)

    if not r.ok:
        return make_response(jsonify({"ok": False, "error": r.text[:300]}), 502)

    rows = extract_rows(raw)

    # Ищем ключ FD::uuid
    fd_key = None
    for row in rows:
        for k in (row.keys() if isinstance(row, dict) else []):
            if isinstance(k, str) and k.startswith("FD::"):
                fd_key = k
                break
        if fd_key:
            break

    def _to_int(v):
        try: return int(float(v or 0))
        except: return 0

    # Строим индекс: offer_id → geo_lower → fd
    result: Dict[str, Dict[str, int]] = {}
    cur_offer_id = None

    for row in rows:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level") or "").strip()
        eid   = str(row.get("entity_id") or "")
        name  = str(row.get("name") or "").strip()
        fd    = _to_int(row.get(fd_key) or 0) if fd_key else 0

        if level == "1":
            cur_offer_id = eid
            if fd > 0:
                result.setdefault(eid, {})
        elif level == "2":
            pass  # rotation — пропускаем
        elif level == "3" and cur_offer_id and fd > 0:
            result.setdefault(cur_offer_id, {})
            geo_lower = name.lower()
            result[cur_offer_id][geo_lower] = result[cur_offer_id].get(geo_lower, 0) + fd

    total_fd = sum(sum(g.values()) for g in result.values())

    return jsonify({
        "ok":       True,
        "date":     date_str,
        "fd_key":   fd_key,
        "total_fd": total_fd,
        "fd_map":   result,
        "server_time": _now_local_str(),
    })


@bp.post("/api/offers/dpu")
def api_offers_dpu():
    """
    DPU для офферов с фильтром по ротации и GEO.
    Логика: 7d→14d→30d→this_year→all_time, порог uniq>=80.
    Body: { offers: [{offer_id, rot_id, geo}] }
    Returns: { "rot_id::offer_id::geo": { dpu, uniq, period } }
    """
    body = request.get_json(silent=True) or {}
    offers_req = body.get("offers") or []
    if not offers_req:
        return make_response(jsonify({"ok": False, "error": "offers required"}), 400)

    MIN_UNIQ_THRESHOLD = 80
    PERIODS = [
        ("7d",        {"datePreset": "last_7_days"}),
        ("14d",       {"datePreset": "last_14_days"}),
        ("30d",       {"datePreset": "last_30_days"}),
        ("this_year", {"datePreset": "this_year"}),
        ("all_time",  {"datePreset": "all_time"}),
    ]

    def _get_stat(row, *fields):
        for f in fields:
            v = row.get(f)
            if v not in (None, "", "0", 0):
                try: return float(v)
                except: pass
        return 0.0

    # Уникальные offer_id для запроса
    offer_ids = list({str(o["offer_id"]) for o in offers_req})
    # Уникальные rot_id
    rot_ids = list({str(o["rot_id"]) for o in offers_req})

    def _fetch_stats(preset_params):
        """Запрос: groupings rotation→offer→geo, фильтр по offer_ids."""
        pairs = [
            ("timezone",    "Europe/Moscow"),
            ("groupings[]", "rotation"),
            ("groupings[]", "offer"),
            ("groupings[]", "geoCountry"),
            ("sortColumn",  "clicks"),
            ("sortType",    "desc"),
            ("limit",       "10000"),
        ]
        for k, v in preset_params.items():
            pairs.append((k, v))
        for oid in offer_ids:
            pairs.append(("ids[]", oid))
        try:
            r = binom_get_pairs("/public/api/v1/report/offer", pairs)
            raw = _safe_json(r)
        except Exception:
            return {}
        if not r.ok:
            return {}

        rows = extract_rows(raw)
        # Индекс: rot_id → offer_id → geo_lower → row
        idx: Dict[str, Dict[str, Dict[str, Dict]]] = {}
        cur_rot = None
        cur_oid = None
        for row in rows:
            if not isinstance(row, dict): continue
            level = str(row.get("level", "")).strip()
            if level == "1":
                cur_rot = str(row.get("entity_id") or "").strip()
                cur_oid = None
            elif level == "2" and cur_rot:
                cur_oid = str(row.get("entity_id") or "").strip()
                idx.setdefault(cur_rot, {}).setdefault(cur_oid, {})
            elif level == "3" and cur_rot and cur_oid:
                geo = str(row.get("name") or "").strip().lower()
                idx.setdefault(cur_rot, {}).setdefault(cur_oid, {})[geo] = row
        return idx

    # Ключ результата: "rot_id::offer_id::geo"
    result: Dict[str, Dict] = {}
    # Остаток: список (rot_id, offer_id, geo) которым ещё нужен период
    remaining = [
        (str(o["rot_id"]), str(o["offer_id"]), str(o.get("geo", "")).lower())
        for o in offers_req
    ]

    for period_name, preset_params in PERIODS:
        if not remaining:
            break
        idx = _fetch_stats(preset_params)
        still_remaining = []

        for (rid, oid, geo) in remaining:
            rot_data = idx.get(rid, {})
            offer_data = rot_data.get(oid, {})

            # Матчим GEO нечётко
            matched_row = None
            for geoKey, row in offer_data.items():
                if geoKey.startswith(geo) or geo.startswith(geoKey.split(" ")[0]):
                    matched_row = row
                    break

            key = f"{rid}::{oid}::{geo}"
            if matched_row:
                uniq = int(_get_stat(matched_row, "unique_campaign_clicks") or 0)
                if uniq >= MIN_UNIQ_THRESHOLD:
                    dpu_val, _ = extract_dpu_from_row(matched_row)
                    result[key] = {
                        "dpu":    round(dpu_val, 4) if dpu_val else 0,
                        "uniq":   uniq,
                        "period": period_name,
                    }
                    continue  # разрешён
                elif period_name == "all_time":
                    # all_time — тоже мало данных
                    result[key] = {"dpu": 0, "uniq": uniq, "period": "all_time"}
                    continue
            elif period_name == "all_time":
                # Нет данных вообще
                result[key] = {"dpu": 0, "uniq": 0, "period": "all_time"}
                continue

            still_remaining.append((rid, oid, geo))

        remaining = still_remaining

    return jsonify({"ok": True, "dpu_map": result})