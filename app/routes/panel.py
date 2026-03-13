import json as _json
from datetime import datetime
from typing import Any, Dict, List, Generator
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, jsonify, make_response, request, Response, stream_with_context

from app.utils.config import LOCAL_TZ
from app.utils.store import (
    load_panel, save_panel, new_id,
    load_history, save_history, append_fd_events, fetch_fd_map,
    apply_fd_atomic, update_offer_dpu_atomic
)
from app.utils.dpu import calc_dpu_for_panel_offer, invalidate_offer_cache

bp = Blueprint("panel", __name__)


def _now() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


# ---------- READ ----------

@bp.get("/api/panel")
def api_panel_get():
    return jsonify({"ok": True, "data": load_panel()})


# ---------- ROTATIONS ----------

@bp.post("/api/panel/rotation")
def api_panel_add_rotation():
    body = request.get_json(force=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return make_response(jsonify({"ok": False, "error": "name required"}), 400)
    panel    = load_panel()
    rotation = {"id": new_id(), "name": name,
                "binom_rotation_id": str(body.get("binom_rotation_id", "")).strip(),
                "geos": []}
    panel["rotations"].append(rotation)
    save_panel(panel)
    return jsonify({"ok": True, "rotation": rotation})


@bp.delete("/api/panel/rotation/<rid>")
def api_panel_del_rotation(rid: str):
    panel = load_panel()
    panel["rotations"] = [r for r in panel["rotations"] if r["id"] != rid]
    save_panel(panel)
    return jsonify({"ok": True})


# ---------- GEOS ----------

@bp.post("/api/panel/rotation/<rid>/geo")
def api_panel_add_geo(rid: str):
    body = request.get_json(force=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return make_response(jsonify({"ok": False, "error": "name required"}), 400)
    panel = load_panel()
    for rot in panel["rotations"]:
        if rot["id"] == rid:
            geo = {"id": new_id(), "name": name, "offers": []}
            rot["geos"].append(geo)
            save_panel(panel)
            return jsonify({"ok": True, "geo": geo})
    return make_response(jsonify({"ok": False, "error": "rotation not found"}), 404)


@bp.patch("/api/panel/geo/<gid>")
def api_panel_edit_geo(gid: str):
    body = request.get_json(force=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return make_response(jsonify({"ok": False, "error": "name required"}), 400)
    panel = load_panel()
    for rot in panel["rotations"]:
        for geo in rot["geos"]:
            if geo["id"] == gid:
                geo["name"] = name
                save_panel(panel)
                return jsonify({"ok": True, "geo": geo})
    return make_response(jsonify({"ok": False, "error": "geo not found"}), 404)


@bp.delete("/api/panel/geo/<gid>")
def api_panel_del_geo(gid: str):
    panel = load_panel()
    for rot in panel["rotations"]:
        rot["geos"] = [g for g in rot["geos"] if g["id"] != gid]
    save_panel(panel)
    return jsonify({"ok": True})


# ---------- OFFERS ----------

@bp.post("/api/panel/geo/<gid>/offer")
def api_panel_add_offer(gid: str):
    body = request.get_json(force=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return make_response(jsonify({"ok": False, "error": "name required"}), 400)

    cap_raw = body.get("cap")
    cap = None if cap_raw in (None, "", "unlimited") else int(cap_raw)

    panel = load_panel()
    for rot in panel["rotations"]:
        for geo in rot["geos"]:
            if geo["id"] == gid:
                offer = {
                    "id":                new_id(),
                    "name":              name,
                    "binom_offer_id":    str(body.get("binom_offer_id", "")).strip(),
                    "rotation_id":       str(body.get("rotation_id", "")).strip(),
                    "cap":               cap,
                    "rate":              float(body["rate"]) if body.get("rate") else None,
                    "currency":          str(body.get("currency") or "USD"),
                    "filled_cap":        None,
                    "filled_cap_manual": None,
                    "dpu":               None,
                    "dpu_period":        None,
                }
                geo["offers"].append(offer)
                save_panel(panel)
                return jsonify({"ok": True, "offer": offer})
    return make_response(jsonify({"ok": False, "error": "geo not found"}), 404)


@bp.patch("/api/panel/offer/<oid>")
def api_panel_update_offer(oid: str):
    body  = request.get_json(force=True) or {}
    panel = load_panel()
    for rot in panel["rotations"]:
        for geo in rot["geos"]:
            for off in geo["offers"]:
                if off["id"] != oid:
                    continue
                if "cap" in body:
                    raw = body["cap"]
                    off["cap"] = None if raw in (None, "", "unlimited") else int(raw)
                if "name" in body:
                    off["name"] = str(body["name"]).strip()
                if "binom_offer_id" in body:
                    off["binom_offer_id"] = str(body["binom_offer_id"]).strip()
                if "rotation_id" in body:
                    off["rotation_id"] = str(body["rotation_id"]).strip()
                if "filled_cap_manual" in body:
                    raw = body["filled_cap_manual"]
                    off["filled_cap_manual"] = None if raw in (None, "", "null") else int(raw)
                if "rate" in body:
                    raw = body["rate"]
                    off["rate"] = None if raw in (None, "", "null") else float(raw)
                if "currency" in body:
                    off["currency"] = str(body["currency"]).strip() or "USD"
                if "status" in body:
                    s = str(body["status"]).strip()
                    off["status"] = s if s in ("active", "stop", "no_perform") else "active"
                if "dpu_updated_at" in body:
                    off["dpu_updated_at"] = None
                save_panel(panel)
                return jsonify({"ok": True, "offer": off})
    return make_response(jsonify({"ok": False, "error": "offer not found"}), 404)


@bp.delete("/api/panel/offer/<oid>")
def api_panel_del_offer(oid: str):
    panel = load_panel()
    for rot in panel["rotations"]:
        for geo in rot["geos"]:
            geo["offers"] = [o for o in geo["offers"] if o["id"] != oid]
    save_panel(panel)
    return jsonify({"ok": True})


@bp.post("/api/panel/offer/<oid>/recalc_dpu")
def api_panel_offer_recalc_dpu(oid: str):
    panel = load_panel()
    for rot in panel["rotations"]:
        for geo in rot["geos"]:
            for off in geo["offers"]:
                if off["id"] != oid:
                    continue
                bid = off.get("binom_offer_id", "")
                if not bid:
                    return jsonify({"ok": False, "error": "no binom_offer_id"})
                try:
                    rid = off.get("rotation_id", "") or rot.get("binom_rotation_id", "")
                    invalidate_offer_cache(bid, rid)
                    res = calc_dpu_for_panel_offer(bid, geo["name"], rotation_id=rid)
                    print(f"[recalc] offer={bid} geo={geo['name']} rid={rid!r} → dpu={res.get('dpu')} period={res.get('period')} uniq={res.get('unique_clicks')} note={res.get('note')}", flush=True)
                    now_iso = datetime.now(LOCAL_TZ).isoformat()
                    dpu_data = {"dpu": res.get("dpu"), "period": res.get("period"),
                                "note": res.get("note"), "updated_at": now_iso}
                    update_offer_dpu_atomic(off["id"], dpu_data)
                    return jsonify({"ok": True, "dpu": res.get("dpu"), "period": res.get("period"), "note": res.get("note")})
                except Exception as e:
                    return jsonify({"ok": False, "error": str(e)})
    return jsonify({"ok": False, "error": "offer not found"})

# ---------- REFRESH ----------

def _apply_fd(panel: Dict, fd_map: Dict, events: List, now_str: str) -> None:
    """Обновляет filled_cap для всех офферов и собирает события."""
    for rot in panel["rotations"]:
        for geo in rot["geos"]:
            for off in geo["offers"]:
                bid = off.get("binom_offer_id", "")
                if not bid or off.get("status") in ("stop", "no_perform"):
                    continue
                was_initialized = off.get("filled_cap") is not None
                old_fd   = off.get("filled_cap") or 0
                geo_key  = f"{bid}:{geo.get('name', '').lower()}"
                binom_fd = fd_map.get(geo_key, 0)
                new_fd   = (off.get("filled_cap_manual") or 0) + binom_fd
                delta    = new_fd - old_fd
                off["filled_cap"] = new_fd
                if was_initialized and delta > 0:
                    events.append({
                        "ts": now_str, "offer": off.get("name", ""),
                        "offer_id": bid, "rotation": rot.get("name", ""),
                        "geo": geo.get("name", ""), "delta": delta,
                        "total": new_fd, "cap": off.get("cap"),
                    })


@bp.post("/api/panel/refresh")
def api_panel_refresh():
    """Обновляет только FD — вызывается авто каждые 5 минут."""
    fd_map = fetch_fd_map()
    events, fd_map_size = apply_fd_atomic(fd_map)
    append_fd_events(events)

    # Возвращаем актуальные filled_cap по каждому офферу — фронт обновит только эти ячейки
    panel = load_panel()
    caps = {}
    for rot in panel["rotations"]:
        for geo in rot["geos"]:
            for off in geo["offers"]:
                caps[off["id"]] = {
                    "filled_cap": off.get("filled_cap"),
                    "cap":        off.get("cap"),
                }
    return jsonify({"ok": True, "fd_map_size": fd_map_size, "new_events": len(events), "caps": caps})


@bp.post("/api/panel/refresh_full")
def api_panel_refresh_full():
    """SSE: обновляет FD + $perUniq, стримит каждый результат сразу."""
    fd_map = fetch_fd_map()
    # apply_fd_atomic сохраняет FD на диск сразу — дубликатов в истории не будет
    events, _ = apply_fd_atomic(fd_map)
    append_fd_events(events)  # сохраняем историю сразу

    panel = load_panel()  # читаем уже обновлённые filled_cap

    # Собираем задачи (2-дневный skip)
    dpu_tasks = []
    for rot in panel["rotations"]:
        for geo in rot["geos"]:
            for off in geo["offers"]:
                bid = off.get("binom_offer_id", "")
                if not bid or off.get("status") in ("stop", "no_perform"):
                    continue
                dpu_updated_at = off.get("dpu_updated_at")
                skip_dpu = False
                if dpu_updated_at and (off.get("dpu") is not None or off.get("dpu_note") == "insufficient_data"):
                    try:
                        age = datetime.now(LOCAL_TZ) - datetime.fromisoformat(dpu_updated_at)
                        if age.total_seconds() < 2 * 24 * 3600:
                            skip_dpu = True
                    except Exception:
                        pass
                if not skip_dpu:
                    dpu_tasks.append((off, bid, geo.get("name", ""), rot.get("binom_rotation_id", "")))

    off_map = {
        off["id"]: off
        for rot in panel["rotations"]
        for geo in rot["geos"]
        for off in geo["offers"]
    }

    def _stream() -> Generator[str, None, None]:
        fd_msg = _json.dumps({"type": "fd", "new_events": len(events)})
        yield "data: " + fd_msg + "\n\n"

        total = len(dpu_tasks)
        done  = 0

        def _calc_one(task):
            off, bid, geo_name, rid = task
            try:
                result = calc_dpu_for_panel_offer(bid, geo_name, rotation_id=rid)
                return off["id"], result
            except Exception as ex:
                return off["id"], {"dpu": None, "period": None, "note": "err:" + str(ex)[:30]}

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_calc_one, t): t for t in dpu_tasks}
            for future in as_completed(futures):
                oid, result = future.result()
                done += 1
                now_iso = datetime.now(LOCAL_TZ).isoformat()
                # Атомарно сохраняем только dpu этого оффера
                dpu_data = {"dpu": result.get("dpu"), "period": result.get("period"),
                            "note": result.get("note"), "updated_at": now_iso}
                update_offer_dpu_atomic(oid, dpu_data)
                msg = _json.dumps({"type": "dpu", "offer_id": oid,
                                   "dpu": result.get("dpu"), "period": result.get("period"),
                                   "note": result.get("note"), "done": done, "total": total})
                yield "data: " + msg + "\n\n"

        done_msg = _json.dumps({"type": "done", "total": total})
        yield "data: " + done_msg + "\n\n"

    return Response(
        stream_with_context(_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ---------- HISTORY ----------

@bp.get("/api/panel/history")
def api_panel_history():
    limit   = int(request.args.get("limit", "200"))
    history = load_history()
    return jsonify({"ok": True, "events": list(reversed(history))[:limit]})


@bp.delete("/api/panel/history")
def api_panel_history_clear():
    save_history([])
    return jsonify({"ok": True})

@bp.get("/api/panel/sync_preview")
def api_panel_sync_preview():
    """Возвращает список всех ротаций из Binom для выбора."""
    from app.services.binom import binom_get, _safe_json
    from app.utils.cache import get_all_rotation_ids
    try:
        rotation_ids = get_all_rotation_ids()
    except Exception as e:
        return make_response(jsonify({"ok": False, "error": str(e)}), 500)

    rotations = []
    for rid in rotation_ids:
        try:
            r   = binom_get(f"/public/api/v1/rotation/{rid}")
            raw = _safe_json(r)
            if r.ok and isinstance(raw, dict):
                rotations.append({"id": str(rid), "name": raw.get("name") or f"Rotation #{rid}"})
        except Exception:
            pass

    return jsonify({"ok": True, "rotations": rotations})


@bp.post("/api/panel/sync_from_binom")
def api_panel_sync_from_binom():
    """
    Синхронизация выбранных ротаций.
    Body: { "rotation_ids": ["123", "456"] }
    Структура Binom: rotation → rules → paths → offers
    GEO берётся из rule.name
    """
    from app.services.binom import binom_get, _safe_json
    from app.utils.cache import get_country_map
    body = request.get_json(force=True) or {}
    country_map = get_country_map()  # code → официальное название Binom
    selected_ids = [str(rid) for rid in (body.get("rotation_ids") or [])]
    if not selected_ids:
        return make_response(jsonify({"ok": False, "error": "rotation_ids required"}), 400)

    panel = load_panel()
    added_rotations = 0
    added_offers    = 0
    skipped_offers  = 0

    for rot_id in selected_ids:
        try:
            r   = binom_get(f"/public/api/v1/rotation/{rot_id}")
            raw = _safe_json(r)
        except Exception as e:
            continue
        if not r.ok or not isinstance(raw, dict):
            continue

        rot_name = str(raw.get("name") or f"Rotation #{rot_id}")
        rules    = raw if isinstance(raw, list) else (raw.get("rules") or [])

        # Найти или создать ротацию в панели
        panel_rot = next((pr for pr in panel["rotations"]
                          if pr.get("binom_rotation_id") == rot_id), None)
        if panel_rot is None:
            panel_rot = {
                "id":                new_id(),
                "name":              rot_name,
                "binom_rotation_id": rot_id,
                "geos":              [],
            }
            panel["rotations"].append(panel_rot)
            added_rotations += 1

        def _process_paths(paths, geo_name):
            nonlocal added_offers, skipped_offers
            for path in (paths or []):
                if not isinstance(path, dict) or path.get("enabled") is False:
                    continue
                for off_entry in (path.get("offers") or []):
                    if not isinstance(off_entry, dict) or off_entry.get("enabled") is False:
                        continue
                    try:
                        weight = float(off_entry.get("weight") or 0)
                    except Exception:
                        weight = 0
                    if weight <= 0:
                        continue

                    # Binom возвращает offerId (не id)
                    offer_id   = str(off_entry.get("offerId") or off_entry.get("id") or "")
                    offer_name = str(off_entry.get("name") or f"Offer #{offer_id}")
                    if not offer_id or offer_id == "0":
                        continue

                    # Резолвим правильное название GEO
                    from app.utils.geo import resolve_geo_name
                    from app.utils.cache import get_country_map
                    resolved_geo = resolve_geo_name(geo_name, get_country_map())

                    # Найти или создать GEO
                    panel_geo = next((g for g in panel_rot["geos"]
                                      if g.get("name", "").upper() == resolved_geo.upper()), None)
                    if panel_geo is None:
                        panel_geo = {"id": new_id(), "name": resolved_geo, "offers": []}
                        panel_rot["geos"].append(panel_geo)

                    # Дедупликация по binom_offer_id
                    already = any(o.get("binom_offer_id") == offer_id for o in panel_geo["offers"])
                    if already:
                        skipped_offers += 1
                        continue

                    panel_geo["offers"].append({
                        "id":                new_id(),
                        "name":              offer_name,
                        "binom_offer_id":    offer_id,
                        "rotation_id":       rot_id,
                        "cap":               None,
                        "rate":              None,
                        "currency":          "USD",
                        "filled_cap":        None,
                        "filled_cap_manual": None,
                        "status":            "active",
                    })
                    added_offers += 1

        # defaultPaths — офферы без GEO-правила
        _process_paths(raw.get("defaultPaths") or [], "DEFAULT")

        # rules → paths → offers
        for rule in (rules if isinstance(rules, list) else []):
            if not isinstance(rule, dict) or rule.get("enabled") is False:
                continue
            rule_title = str(rule.get("name") or "ALL").strip()
            # Извлекаем ISO код из названия rule: "Turkey TR" → "TR"
            # Ищем 2-буквенный код в конце или через /
            from app.utils.geo import is_multigeo_rule, resolve_geo_name
            if is_multigeo_rule(rule_title):
                continue

            geo_name = resolve_geo_name(rule_title, country_map)
            _process_paths(rule.get("paths") or [], geo_name)

        # Убираем пустые GEO
        panel_rot["geos"] = [g for g in panel_rot["geos"] if g["offers"]]

    panel["rotations"] = [r for r in panel["rotations"] if r["geos"]]
    save_panel(panel)

    return jsonify({
        "ok": True,
        "added_rotations": added_rotations,
        "added_offers":    added_offers,
        "skipped_offers":  skipped_offers,
    })

@bp.get("/api/debug/rotation_raw/<int:rotation_id>")
def api_debug_rotation_raw(rotation_id: int):
    """Показывает сырой ответ Binom для ротации — для отладки структуры."""
    from app.services.binom import binom_get, _safe_json
    r   = binom_get(f"/public/api/v1/rotation/{rotation_id}")
    raw = _safe_json(r)
    # Возвращаем первые уровни структуры без глубокой вложенности
    if isinstance(raw, dict):
        preview = {
            "keys":         list(raw.keys()),
            "name":         raw.get("name"),
            "rules_count":  len(raw.get("rules") or []),
            "first_rule":   (raw.get("rules") or [None])[0],
        }
        if preview["first_rule"] and isinstance(preview["first_rule"], dict):
            fr = preview["first_rule"]
            preview["first_rule_keys"]   = list(fr.keys())
            preview["first_rule_paths"]  = len(fr.get("paths") or [])
            fp = (fr.get("paths") or [None])[0]
            if fp and isinstance(fp, dict):
                preview["first_path_keys"]   = list(fp.keys())
                preview["first_path_offers"] = len(fp.get("offers") or [])
                fo = (fp.get("offers") or [None])[0]
                if fo:
                    preview["first_offer"] = fo
    else:
        preview = {"raw": raw}
    return jsonify({"ok": r.ok, "status": r.status_code, "preview": preview})

@bp.get("/api/debug/binom_geos")
def api_debug_binom_geos():
    """Исследуем как получить справочник GEO из Binom."""
    from app.services.binom import binom_get, _safe_json
    results = {}

    for endpoint in [
        "/public/api/v1/geo/list",
        "/public/api/v1/country/list",
        "/public/api/v1/geo",
        "/public/api/v1/countries",
    ]:
        try:
            r = binom_get(endpoint)
            raw = _safe_json(r)
            if r.ok:
                if isinstance(raw, list):
                    results[endpoint] = {"ok": True, "count": len(raw), "first3": raw[:3]}
                elif isinstance(raw, dict):
                    results[endpoint] = {"ok": True, "keys": list(raw.keys()), "sample": str(raw)[:300]}
            else:
                results[endpoint] = {"ok": False, "status": r.status_code}
        except Exception as e:
            results[endpoint] = {"error": str(e)}

    return jsonify(results)

@bp.get("/api/debug/binom_geo_names")
def api_debug_binom_geo_names():
    """Получает все уникальные названия GEO из отчёта Binom за последние 30 дней."""
    from app.services.binom import binom_get_pairs, _safe_json
    from app.utils.cache import get_all_campaign_ids
    from app.utils.dpu import extract_rows, _to_int

    campaign_ids = get_all_campaign_ids()
    pairs = [
        ("datePreset",  "last_30_days"),
        ("timezone",    "Europe/Moscow"),
        ("groupings[]", "geoCountry"),
        ("sortColumn",  "clicks"),
        ("sortType",    "desc"),
        ("limit",       "1000"),
    ] + [("ids[]", cid) for cid in campaign_ids]

    r   = binom_get_pairs("/public/api/v1/report/campaign", pairs)
    raw = _safe_json(r)
    rows = extract_rows(raw)

    geos = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name  = str(row.get("name") or "").strip()
        uniq  = _to_int(row.get("unique_campaign_clicks") or 0)
        if name:
            geos.append({"name": name, "uniq": uniq})

    geos.sort(key=lambda x: x["uniq"], reverse=True)
    return jsonify({"ok": True, "count": len(geos), "geos": geos})