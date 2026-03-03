from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, make_response, request

from binom_client import binom_get, binom_get_pairs, _safe_json
from cache import get_all_campaign_ids
from config import LOCAL_TZ
from dpu import extract_rows, _to_int

bp = Blueprint("reports", __name__)

# GEO которые исключаем из Weekly Uniques
EXCLUDED_GEOS = {"RU", "RUSSIA", "RUSSIA RU"}


def _now_local_str() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _find_fd_key(row: Dict) -> Optional[str]:
    for key in row:
        if key.startswith("FD::"):
            return key
    return None




# ---------- Weekly Uniques ----------

@bp.get("/api/report/weekly_uniques")
def api_weekly_uniques():
    date_from = request.args.get("date_from", "").strip()
    date_to   = request.args.get("date_to",   "").strip()
    min_uniq  = int(request.args.get("min_uniq", "100"))

    if not date_from or not date_to:
        return make_response(jsonify({"ok": False, "error": "date_from and date_to required"}), 400)

    campaign_ids = get_all_campaign_ids()
    if not campaign_ids:
        return make_response(jsonify({"ok": False, "error": "Не удалось получить список кампаний"}), 500)

    pairs = [
        ("datePreset",  "custom_time"),
        ("dateFrom",    f"{date_from} 00:00:00"),
        ("dateTo",      f"{date_to} 23:59:59"),
        ("timezone",    "Europe/Moscow"),
        ("groupings[]", "rotation"),
        ("groupings[]", "geoCountry"),
        ("sortColumn",  "clicks"),
        ("sortType",    "desc"),
        ("limit",       "5000"),
        ("offset",      "0"),
    ] + [("ids[]", cid) for cid in campaign_ids]

    try:
        r   = binom_get_pairs("/public/api/v1/report/campaign", pairs)
        raw = _safe_json(r)
    except Exception as e:
        return make_response(jsonify({"ok": False, "error": str(e)}), 500)

    if not r.ok:
        return make_response(jsonify({
            "ok": False, "binom_status": r.status_code,
            "error": raw.get("errors", {}).get("detail", r.text[:300]) if isinstance(raw, dict) else r.text[:300]
        }), 502)

    rows: List[Dict] = extract_rows(raw)
    rotations:   List[Dict]     = []
    current_rot: Optional[Dict] = None

    for row in rows:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level") or "").strip()
        name  = str(row.get("name") or "").strip()
        uniq  = _to_int(row.get("unique_campaign_clicks") or 0)
        eid   = str(row.get("entity_id") or "")

        if level == "1":
            current_rot = {"rotationId": eid, "rotationName": name, "countries": []}
            rotations.append(current_rot)
        elif level == "2" and current_rot is not None:
            if name.upper() in EXCLUDED_GEOS:
                continue
            if uniq >= min_uniq:
                current_rot["countries"].append({"country": name, "uniq": uniq})

    rotations = [r for r in rotations if r["countries"]]
    for rot in rotations:
        rot["countries"].sort(key=lambda x: x["uniq"], reverse=True)

    return jsonify({
        "ok": True, "date_from": date_from, "date_to": date_to,
        "min_uniq": min_uniq, "rotations": rotations,
        "server_time_local": _now_local_str(),
    })


# ---------- CAP Report ----------

@bp.get("/api/report/cap")
def api_report_cap():
    date_from = request.args.get("date_from", "").strip()
    date_to   = request.args.get("date_to",   "").strip()

    if not date_from or not date_to:
        return make_response(jsonify({"ok": False, "error": "date_from and date_to required"}), 400)

    campaign_ids = get_all_campaign_ids()
    if not campaign_ids:
        return make_response(jsonify({"ok": False, "error": "Не удалось получить список кампаний"}), 500)

    pairs = [
        ("datePreset",  "custom_time"),
        ("dateFrom",    f"{date_from} 00:00:00"),
        ("dateTo",      f"{date_to} 23:59:59"),
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
        err = raw.get("errors", {}) if isinstance(raw, dict) else {}
        return make_response(jsonify({
            "ok": False, "binom_status": r.status_code,
            "error": err.get("detail") or err.get("message") or r.text[:300],
        }), 502)

    rows: List[Dict] = extract_rows(raw)
    fd_key = next((_find_fd_key(r) for r in rows if _find_fd_key(r)), None)

    offers: List[Dict] = []
    cur_offer:    Optional[Dict] = None
    cur_rotation: Optional[Dict] = None

    for row in rows:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level") or "").strip()
        name  = str(row.get("name") or "").strip()
        eid   = str(row.get("entity_id") or "")
        fd    = _to_int(row.get(fd_key) or 0) if fd_key else 0

        if level == "1":
            cur_offer = {"offerId": eid, "offerName": name,
                         "network": str(row.get("affiliateNetworkName") or ""),
                         "fd": fd, "rotations": []}
            offers.append(cur_offer)
            cur_rotation = None
        elif level == "2" and cur_offer is not None:
            cur_rotation = {"rotationId": eid, "rotationName": name, "fd": fd, "countries": []}
            cur_offer["rotations"].append(cur_rotation)
        elif level == "3" and cur_rotation is not None:
            cur_rotation["countries"].append({"country": name, "fd": fd})

    offers = [o for o in offers if o["fd"] > 0]
    totals   = raw.get("totals", {}) if isinstance(raw, dict) else {}
    total_fd = _to_int(totals.get(fd_key) or 0) if fd_key else 0

    return jsonify({
        "ok": True, "date_from": date_from, "date_to": date_to,
        "fd_key": fd_key, "total_fd": total_fd, "offers": offers,
        "server_time_local": _now_local_str(),
    })


# ---------- Debug ----------

@bp.get("/api/debug/report")
def api_debug_report():
    offer_id = request.args.get("offer_id", "").strip()
    preset   = request.args.get("preset", "last_7_days").strip()

    pairs = [
        ("datePreset",  preset),
        ("timezone",    "Europe/Moscow"),
        ("groupings[]", "rotation"),
        ("groupings[]", "rule"),
        ("sortColumn",  "clicks"),
        ("sortType",    "desc"),
        ("limit",       "100"),
        ("offset",      "0"),
    ]
    if offer_id:
        pairs.append(("ids[]", offer_id))

    r   = binom_get_pairs("/public/api/v1/report/offer", pairs)
    raw = _safe_json(r)
    rows = extract_rows(raw)

    return jsonify({
        "ok": r.ok, "status": r.status_code,
        "first_row_keys": list(rows[0].keys()) if rows else [],
        "first_3_rows":   rows[:3],
    })


@bp.get("/api/debug/cap")
def api_debug_cap():
    date_from = request.args.get("date_from", "2026-02-18")
    date_to   = request.args.get("date_to",   "2026-02-24")

    all_ids  = get_all_campaign_ids()
    id_pairs = [("ids[]", cid) for cid in all_ids]
    pairs = [
        ("datePreset",  "custom_time"),
        ("dateFrom",    f"{date_from} 00:00:00"),
        ("dateTo",      f"{date_to} 23:59:59"),
        ("timezone",    "Europe/Moscow"),
        ("groupings[]", "offer"),
        ("groupings[]", "rotation"),
        ("groupings[]", "geoCountry"),
        ("sortColumn",  "clicks"),
        ("sortType",    "desc"),
        ("limit",       "20"),
    ] + id_pairs

    r   = binom_get_pairs("/public/api/v1/report/campaign", pairs)
    raw = _safe_json(r)
    rows = extract_rows(raw)

    return jsonify({
        "ok": r.ok, "status": r.status_code,
        "first_5_rows": rows[:5],
        "totals": raw.get("totals") if isinstance(raw, dict) else {},
    })


@bp.get("/api/debug_dpu_offer")
def api_debug_dpu_offer():
    offer_id = request.args.get("offer_id", "")
    geo      = request.args.get("geo", "")
    all_ids  = get_all_campaign_ids()
    id_pairs = [("ids[]", cid) for cid in all_ids]

    pairs1 = [
        ("datePreset",          "last_30_days"),
        ("timezone",            "Europe/Moscow"),
        ("groupings[]",         "geoCountry"),
        ("filters[offer_id][]", str(offer_id)),
        ("sortColumn",          "clicks"),
        ("sortType",            "desc"),
        ("limit",               "100"),
    ] + id_pairs
    r1    = binom_get_pairs("/public/api/v1/report/campaign", pairs1)
    raw1  = _safe_json(r1)
    rows1 = extract_rows(raw1)
    target1 = next((r for r in rows1 if str(r.get("name", "")).lower() == geo.lower()), None)

    pairs2 = [
        ("datePreset",  "last_30_days"),
        ("timezone",    "Europe/Moscow"),
        ("groupings[]", "rotation"),
        ("groupings[]", "geoCountry"),
        ("sortColumn",  "clicks"),
        ("sortType",    "desc"),
        ("limit",       "1000"),
        ("ids[]",       str(offer_id)),
    ]
    r2    = binom_get_pairs("/public/api/v1/report/offer", pairs2)
    raw2  = _safe_json(r2)
    rows2 = extract_rows(raw2)
    cur_rot = None
    target2 = None
    for row in rows2:
        lvl = str(row.get("level", ""))
        if lvl == "1":
            cur_rot = str(row.get("entity_id", ""))
        elif lvl == "2" and cur_rot:
            if str(row.get("name", "")).lower() == geo.lower():
                target2 = row
                break

    return jsonify({
        "method1": {"ok": r1.ok, "total_rows": len(rows1), "target": target1, "first": rows1[0] if rows1 else None},
        "method2": {"ok": r2.ok, "total_rows": len(rows2), "target": target2},
    })