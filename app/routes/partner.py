"""
routes_partner.py — партнёрская система + affiliate networks из Binom.
"""
import os
import json
import secrets
from datetime import datetime
from functools import wraps
from flask import Blueprint, jsonify, make_response, request, Response
from app.utils.partner_db import (
    init_db, authenticate, authenticate_by_uid, get_user_by_token,
    create_user, get_all_users, update_user, delete_user, reset_token,
    regenerate_uid, get_user_by_binom_network,
    create_request, get_requests, update_request_status, get_request,
)
from app.services.binom import binom_get, binom_get_pairs, binom_post, binom_put, _safe_json
from app.utils.config import ADMIN_LOGIN, ADMIN_PASSWORD
import hashlib as _hashlib

# ── Offer tracking ────────────────────────────────────────────────────────────
_TRACKING_FILE = os.path.join(os.path.dirname(__file__), "../../data/offer_tracking.json")

def _load_tracking() -> dict:
    try:
        return json.loads(open(_TRACKING_FILE).read())
    except Exception:
        return {}

def _save_tracking(data: dict):
    open(_TRACKING_FILE, "w").write(json.dumps(data, ensure_ascii=False, indent=2))

def _track_offer(offer_id: str, name: str, rotation_id: str, geo: str,
                 sheet_name: str = "", max_cap: int = None, partner_name: str = "",
                 rate: float = None, currency: str = "USD"):
    """Записывает оффер в трекинг при создании."""
    import pytz as _pytz2
    tracking = _load_tracking()
    now_msk  = datetime.now(_pytz2.timezone("Europe/Moscow"))
    entry = {
        "name":         name,
        "start_date":   now_msk.strftime("%Y-%m-%d"),
        "rotation_id":  str(rotation_id),
        "geo":          geo,
        "sheet_name":   sheet_name,
        "partner_name": partner_name,
        "created_at":   now_msk.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if max_cap:
        entry["max_cap"] = max_cap
    if rate:
        entry["rate"]     = rate
        entry["currency"] = currency
    tracking[str(offer_id)] = entry
    _save_tracking(tracking)


bp = Blueprint("partner", __name__)
init_db()

# ── Кеш весов офферов (offer_name → max_weight) ──────────────────────────────
import time as _time
_offer_weights_cache: dict = {}   # {offer_name_lower: max_weight}
_offer_weights_ts: float   = 0
_OFFER_WEIGHTS_TTL         = 600  # 10 минут

# Только эти ротации проверяем для статуса офферов партнёра
PARTNER_ROTATION_IDS = ["121", "118", "61", "117", "120", "124"]  # iOS
ANDROID_ROTATION_IDS = ["133", "134"]                               # Android
ANDROID_ROT_NAMES    = {"133": "Crash", "134": "Betting"}

ALL_ROTATION_IDS = PARTNER_ROTATION_IDS + ANDROID_ROTATION_IDS


def _get_offer_weights() -> dict:
    """Возвращает {offer_name_lower: max_weight} из ВСЕХ ротаций (iOS + Android). Кешируется на 10 мин."""
    global _offer_weights_cache, _offer_weights_ts
    if _time.time() - _offer_weights_ts < _OFFER_WEIGHTS_TTL:
        return _offer_weights_cache

    weights: dict = {}
    try:
        for rot_id in ALL_ROTATION_IDS:
            r2 = binom_get(f"/public/api/v1/rotation/{rot_id}")
            if not r2.ok:
                continue
            rotation_data = _safe_json(r2)
            if isinstance(rotation_data, dict) and isinstance(rotation_data.get("data"), dict):
                obj = rotation_data["data"]
            else:
                obj = rotation_data
            rules = obj.get("rules") or []
            for rule in (rules if isinstance(rules, list) else []):
                if not isinstance(rule, dict):
                    continue
                for path in (rule.get("paths") or []):
                    if not isinstance(path, dict):
                        continue
                    for offer in (path.get("offers") or []):
                        if not isinstance(offer, dict):
                            continue
                        name   = (offer.get("name") or "").strip().lower()
                        weight = int(offer.get("weight") or 0)
                        if name:
                            weights[name] = max(weights.get(name, 0), weight)
    except Exception as e:
        import logging
        logging.getLogger("partner").error(f"offer_weights error: {e}")

    _offer_weights_cache = weights
    _offer_weights_ts    = _time.time()
    return weights

# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_token():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "): return auth[7:]
    return request.headers.get("X-Token", "") or request.args.get("token", "")

def _admin_static_token() -> str:
    """Статический токен для .env admin — SHA256 от логина+пароля."""
    raw = f"admin:{ADMIN_LOGIN}:{ADMIN_PASSWORD}:panelbin"
    return _hashlib.sha256(raw.encode()).hexdigest()

def require_auth(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            token = _get_token()
            if not token:
                return make_response(jsonify({"ok": False, "error": "Unauthorized"}), 401)
            # Проверяем сначала .env admin токен
            if token == _admin_static_token():
                request.current_user = {"id": 0, "username": ADMIN_LOGIN, "role": "admin", "uid": ""}
                if role and role != "admin":
                    return make_response(jsonify({"ok": False, "error": "Forbidden"}), 403)
                return fn(*args, **kwargs)
            # Затем проверяем токен из БД
            user = get_user_by_token(token)
            if not user:
                return make_response(jsonify({"ok": False, "error": "Invalid token"}), 401)
            if role and user["role"] != role:
                return make_response(jsonify({"ok": False, "error": "Forbidden"}), 403)
            request.current_user = user
            return fn(*args, **kwargs)
        return wrapper
    return decorator

@bp.post("/api/auth/login")
def api_login():
    body = request.get_json(silent=True) or {}
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", "")).strip()
    uid      = str(body.get("uid", "")).strip()

    if uid:
        user = authenticate_by_uid(uid)
        if not user:
            return make_response(jsonify({"ok": False, "error": "Неверный UID"}), 401)
        return jsonify({"ok": True, "token": user["token"], "role": user["role"],
                        "username": user["username"], "uid": user["uid"]})

    if not username or not password:
        return make_response(jsonify({"ok": False, "error": "Укажите логин и пароль"}), 400)

    # Проверяем .env admin credentials
    if username == ADMIN_LOGIN and password == ADMIN_PASSWORD:
        return jsonify({"ok": True, "token": _admin_static_token(),
                        "role": "admin", "username": ADMIN_LOGIN, "uid": ""})

    # Проверяем БД
    user = authenticate(username, password)
    if not user:
        return make_response(jsonify({"ok": False, "error": "Неверный логин или пароль"}), 401)
    return jsonify({"ok": True, "token": user["token"], "role": user["role"],
                    "username": user["username"], "uid": user["uid"]})

@bp.get("/api/auth/session_token")
def api_session_token():
    """Отдаёт API токен если пользователь залогинен через Flask session."""
    from flask import session as flask_session
    if not flask_session.get("logged_in"):
        return make_response(jsonify({"ok": False, "error": "Not logged in"}), 401)
    return jsonify({"ok": True, "token": _admin_static_token(), "role": "admin",
                    "username": flask_session.get("username", ADMIN_LOGIN)})


@bp.get("/api/auth/me")
def api_me():
    token = _get_token()
    if not token:
        return make_response(jsonify({"ok": False}), 401)
    if token == _admin_static_token():
        return jsonify({"ok": True, "role": "admin", "username": ADMIN_LOGIN, "id": 0, "uid": ""})
    user = get_user_by_token(token) if token else None
    if not user:
        return make_response(jsonify({"ok": False}), 401)
    return jsonify({"ok": True, "role": user["role"], "username": user["username"],
                    "id": user["id"], "uid": user["uid"]})

# ── Admin: Affiliate Networks (Binom) ─────────────────────────────────────────

@bp.get("/api/admin/networks")
@require_auth("admin")
def api_admin_networks():
    """Список affiliate networks из Binom, обогащённый данными из нашей БД."""
    r = binom_get("/public/api/v1/affiliate_network/list/all")
    if not r.ok:
        return make_response(jsonify({"ok": False, "error": f"Binom error {r.status_code}: {r.text[:200]}"}), 502)
    data = _safe_json(r)
    if isinstance(data, list):
        networks = data
    elif isinstance(data, dict):
        networks = data.get("data") or data.get("items") or data.get("result") or []
    else:
        networks = []

    # Обогащаем: у каждой сети проверяем есть ли uid в нашей БД
    result = []
    for net in networks:
        nid = str(net.get("id", ""))
        user = get_user_by_binom_network(nid) if nid else None
        result.append({
            **net,
            "has_account": bool(user),
            "partner_uid": user["uid"] if user else None,
            "partner_username": user["username"] if user else None,
        })
    return jsonify({"ok": True, "networks": result})

@bp.get("/api/admin/networks/<network_id>")
@require_auth("admin")
def api_admin_network_detail(network_id):
    """Детали одной affiliate network из Binom."""
    r = binom_get(f"/public/api/v1/affiliate_network/{network_id}")
    if not r.ok:
        return make_response(jsonify({"ok": False, "error": f"Binom {r.status_code}"}), 502)
    data = _safe_json(r)
    # Binom может вернуть: {affiliateNetwork:{...}} или {data:{...}} или плоский объект
    if isinstance(data, dict):
        net = (data.get("affiliateNetwork")
               or data.get("data")
               or data.get("affiliate_network")
               or data)
        # Если всё ещё вложено
        if isinstance(net, dict) and "affiliateNetwork" in net:
            net = net["affiliateNetwork"]
    else:
        net = data

    user = get_user_by_binom_network(str(network_id))
    return jsonify({
        "ok": True,
        "network": net,
        "raw_keys": list(net.keys()) if isinstance(net, dict) else [],
        "account": {
            "exists": bool(user),
            "uid": user["uid"] if user else None,
            "username": user["username"] if user else None,
            "id": user["id"] if user else None,
        }
    })

@bp.get("/api/admin/networks/<network_id>/raw")
@require_auth("admin")
def api_admin_network_raw(network_id):
    """Возвращает сырой JSON из Binom для отладки."""
    r = binom_get(f"/public/api/v1/affiliate_network/{network_id}")
    data = _safe_json(r)
    return jsonify({"ok": r.ok, "status": r.status_code, "raw": data})

@bp.put("/api/admin/networks/<network_id>")
@require_auth("admin")
def api_admin_network_update(network_id):
    """Обновить affiliate network в Binom."""
    body = request.get_json(silent=True) or {}
    # Rename separately if name changed, then full update
    results = {}
    if "name" in body:
        rn = binom_put(f"/public/api/v1/affiliate_network/{network_id}/rename", {"name": body.pop("name")})
        results["rename"] = rn.status_code
    if body:
        ru = binom_put(f"/public/api/v1/affiliate_network/{network_id}", body)
        if not ru.ok:
            return make_response(jsonify({"ok": False, "error": f"Binom {ru.status_code}: {ru.text[:300]}"}), 502)
        results["update"] = _safe_json(ru)
    return jsonify({"ok": True, "results": results})

@bp.post("/api/admin/networks/<network_id>/create_account")
@require_auth("admin")
def api_admin_network_create_account(network_id):
    """
    Создаёт аккаунт партнёра для существующей сети Binom (если аккаунта ещё нет).
    Body: { "username": "...", "password": "..." }
    """
    body     = request.get_json(silent=True) or {}
    username = str(body.get("username", "")).strip()
    password = str(body.get("password") or secrets.token_urlsafe(8)).strip()

    if not username:
        return make_response(jsonify({"ok": False, "error": "username required"}), 400)

    existing = get_user_by_binom_network(str(network_id))
    if existing:
        return make_response(jsonify({"ok": False, "error": "Аккаунт уже существует",
                                       "uid": existing["uid"]}), 409)

    uid = create_user(username, password, role="partner", binom_network_id=str(network_id))
    if uid is None:
        return make_response(jsonify({"ok": False, "error": "Имя уже занято"}), 409)

    user = get_user_by_binom_network(str(network_id))
    return jsonify({"ok": True, "username": username, "password": password,
                    "uid": user["uid"] if user else None})

@bp.delete("/api/admin/networks/<network_id>/account")
@require_auth("admin")
def api_admin_network_delete_account(network_id):
    user = get_user_by_binom_network(str(network_id))
    if not user:
        return make_response(jsonify({"ok": False, "error": "Нет аккаунта"}), 404)
    delete_user(user["id"])
    return jsonify({"ok": True})

@bp.post("/api/admin/networks/<network_id>/regen_uid")
@require_auth("admin")
def api_admin_network_regen_uid(network_id):
    user = get_user_by_binom_network(str(network_id))
    if not user:
        return make_response(jsonify({"ok": False, "error": "Нет аккаунта"}), 404)
    new_uid = regenerate_uid(user["id"])
    return jsonify({"ok": True, "uid": new_uid})

# ── Admin: partners management ────────────────────────────────────────────────

@bp.get("/api/admin/partners")
@require_auth("admin")
def api_admin_partners():
    return jsonify({"ok": True, "partners": get_all_users()})

@bp.post("/api/admin/partners")
@require_auth("admin")
def api_admin_create_partner():
    body = request.get_json(silent=True) or {}
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", "")).strip()
    role     = str(body.get("role", "partner")).strip()
    if role not in ("admin", "partner"): role = "partner"
    if not username or not password:
        return make_response(jsonify({"ok": False, "error": "username and password required"}), 400)
    uid = create_user(username, password, role)
    if uid is None:
        return make_response(jsonify({"ok": False, "error": "Пользователь уже существует"}), 409)
    return jsonify({"ok": True, "id": uid})

@bp.delete("/api/admin/partners/<int:uid>")
@require_auth("admin")
def api_admin_delete_partner(uid):
    delete_user(uid)
    return jsonify({"ok": True})

@bp.post("/api/admin/partners/<int:uid>/reset_token")
@require_auth("admin")
def api_admin_reset_token(uid):
    return jsonify({"ok": True, "token": reset_token(uid)})

@bp.post("/api/admin/partners/<int:uid>/change_password")
@require_auth("admin")
def api_admin_change_password(uid):
    body = request.get_json(silent=True) or {}
    password = str(body.get("password", "")).strip()
    if not password:
        return make_response(jsonify({"ok": False, "error": "password required"}), 400)
    pw_hash = _hashlib.sha256(password.encode()).hexdigest()
    ok = update_user(uid, password_hash=pw_hash)
    if not ok:
        return make_response(jsonify({"ok": False, "error": "User not found"}), 404)
    return jsonify({"ok": True})

@bp.post("/api/admin/partners/<int:uid>/regen_uid")
@require_auth("admin")
def api_admin_regen_uid(uid):
    return jsonify({"ok": True, "uid": regenerate_uid(uid)})

# ── Admin: requests ───────────────────────────────────────────────────────────

@bp.get("/api/admin/requests")
@require_auth("admin")
def api_admin_requests():
    status = request.args.get("status")
    return jsonify({"ok": True, "requests": get_requests(status=status or None)})

@bp.post("/api/admin/requests/<int:req_id>/approve")
@require_auth("admin")
def api_admin_approve(req_id):
    body = request.get_json(silent=True) or {}
    update_request_status(req_id, "approved", str(body.get("comment", "")),
                           str(body.get("rotation_id", "")))
    return jsonify({"ok": True})

@bp.post("/api/admin/requests/<int:req_id>/reject")
@require_auth("admin")
def api_admin_reject(req_id):
    body = request.get_json(silent=True) or {}
    update_request_status(req_id, "rejected", str(body.get("comment", "")))
    return jsonify({"ok": True})

@bp.post("/api/admin/requests/<int:req_id>/pending")
@require_auth("admin")
def api_admin_set_pending(req_id):
    update_request_status(req_id, "pending")
    return jsonify({"ok": True})

# ── Partner ───────────────────────────────────────────────────────────────────

@bp.post("/api/partner/refresh_offers_cache")
@require_auth("partner")
def api_partner_refresh_cache():
    global _offer_weights_ts
    _offer_weights_ts = 0  # сброс кеша
    return jsonify({"ok": True})


@bp.get("/api/partner/my_offers")
@require_auth("partner")
def api_partner_my_offers():
    """Офферы из Binom для сети партнёра."""
    user   = request.current_user
    net_id = user.get("binom_network_id")
    if not net_id:
        return jsonify({"ok": True, "offers": [], "note": "Нет привязанной сети"})

    r = binom_get("/public/api/v1/offer/alternative/all")
    if not r.ok:
        return make_response(jsonify({"ok": False, "error": f"Binom {r.status_code}"}), 502)

    data = _safe_json(r)
    all_offers = data if isinstance(data, list) else (data.get("data") or [])

    offers = []
    for o in all_offers:
        if str(o.get("affiliateNetworkId") or "") != str(net_id):
            continue
        caps = o.get("conversionCaps") or {}
        # conversionCaps может быть dict или list
        if isinstance(caps, list):
            cap_info = caps[0] if caps else {}
        elif isinstance(caps, dict):
            cap_info = caps
        else:
            cap_info = {}
        offers.append({
            "id":       o.get("id"),
            "name":     o.get("name") or "",
            "country":  o.get("countryCode") or "",
            "url":      o.get("url") or "",
            "max_cap":  cap_info.get("maxConversions") if cap_info else None,
            "payout":   (o.get("payout") or {}).get("money", {}).get("amount"),
            "currency": (o.get("payout") or {}).get("money", {}).get("currency", "USD"),
        })

    # Добавляем статус + платформу из весов ротаций
    # Строим отдельные индексы для iOS и Android
    from app.services.binom import binom_get as _bg2, _safe_json as _sj2
    from app.services.sheets import _names_match

    def _build_weights(rot_ids):
        """Возвращает {str(offer_id): max_weight} по всем ротациям."""
        w = {}
        for rid in rot_ids:
            try:
                r2 = _bg2(f"/public/api/v1/rotation/{rid}")
                if not r2.ok: continue
                d2 = _sj2(r2)
                obj = d2.get("data", d2) if isinstance(d2, dict) else d2
                for rule in (obj.get("rules") or []):
                    for path in (rule.get("paths") or []):
                        for off in (path.get("offers") or []):
                            oid = str(off.get("offerId") or off.get("id") or "")
                            if not oid: continue
                            wt = float(off.get("weight") or 0)
                            w[oid] = max(w.get(oid, 0), wt)
            except Exception:
                pass
        return w

    ios_weights     = _build_weights(PARTNER_ROTATION_IDS)
    android_weights = _build_weights(ANDROID_ROTATION_IDS)

    for o in offers:
        oid_str = str(o.get("id") or "")

        def _find(wmap):
            if oid_str and oid_str in wmap:
                return wmap[oid_str]
            return None

        w_ios     = _find(ios_weights)
        w_android = _find(android_weights)

        # Определяем платформу и статус
        if w_ios is not None and w_android is not None:
            # Есть в обеих — берём активную или ios по умолчанию
            o["platform"] = "both"
            w = max(w_ios, w_android)
        elif w_android is not None:
            o["platform"] = "android"
            w = w_android
        elif w_ios is not None:
            o["platform"] = "ios"
            w = w_ios
        else:
            o["platform"] = "ios"  # по умолчанию
            w = None

        # Если в имени оффера уже есть стоп-префикс — показываем как остановленный
        name_has_stop = any(o["name"].startswith(p) for p in ("STOP!", "No Perform!", "FRAUD!", "FCP -", "CAP"))
        if w is None or (name_has_stop and (w or 0) == 0):
            o["status"] = "stopped" if name_has_stop else "unknown"
        elif w == 0:
            o["status"] = "stopped"
        else:
            o["status"] = "active"
            o["weight"] = w

    offers.sort(key=lambda o: (o["status"] != "active", o["name"]))

    # Получаем постбек URL сети партнёра
    network_postback = ""
    try:
        r_net = binom_get(f"/public/api/v1/affiliate_network/{net_id}")
        if r_net.ok:
            net_data = _safe_json(r_net)
            if isinstance(net_data, dict):
                net_obj = (net_data.get("affiliateNetwork")
                           or net_data.get("data")
                           or net_data)
                network_postback = (net_obj.get("postback_url")
                                    or net_obj.get("postbackUrl")
                                    or net_obj.get("postback") or "")
    except Exception:
        pass

    return jsonify({"ok": True, "offers": offers, "network_id": net_id,
                    "network_postback": network_postback})


@bp.get("/api/partner/traffic")
@require_auth("partner")
def api_partner_traffic():
    """Трафик партнёра — переиспользует weekly_uniques без фильтра по сети."""
    from app.routes.reports import api_weekly_uniques
    return api_weekly_uniques()


@bp.get("/api/partner/traffic/debug")
@require_auth("partner")
def api_partner_traffic_debug():
    """Отладка — сырой ответ Binom для трафика."""
    user   = request.current_user
    net_id = user.get("binom_network_id")
    import pytz as _pytz
    from datetime import timedelta
    msk   = _pytz.timezone("Europe/Moscow")
    today = datetime.now(msk)
    date_from = (today - timedelta(days=6)).strftime("%Y-%m-%d")
    date_to   = today.strftime("%Y-%m-%d")

    results = {}
    for ep, pairs in [
        ("/public/api/v1/report/campaign", [
            ("dateFrom", date_from), ("dateTo", date_to),
            ("groupings[]", "offer"), ("groupings[]", "country"),
            ("affiliateNetworkIds[]", str(net_id)),
        ]),
        ("/public/api/v1/report/campaign/stats", [
            ("date[from]", date_from), ("date[to]", date_to),
            ("group1", "offer"), ("group2", "country"),
            ("affiliateNetworkId[]", str(net_id)),
        ]),
    ]:
        r = binom_get_pairs(ep, pairs)
        results[ep] = {"status": r.status_code, "body": r.text[:1000]}
    return jsonify({"ok": True, "net_id": net_id, "results": results})


@bp.get("/api/partner/tracking_fd")
@require_auth("partner")
def api_partner_tracking_fd():
    """FD из кеша для офферов партнёра."""
    try:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data"))
        fd_cache_file = os.path.join(base, "tracking_fd_cache.json")
        tracking_file = os.path.join(base, "offer_tracking.json")
        cache    = json.loads(open(fd_cache_file).read()) if os.path.exists(fd_cache_file) else {}
        tracking = json.loads(open(tracking_file).read()) if os.path.exists(tracking_file) else {}
    except Exception as e:
        return jsonify({"ok": True, "fd": {}, "tracking": {}, "note": str(e)})

    return jsonify({"ok": True, "fd": cache, "tracking": {
        oid: {
            "name":    info.get("name"),
            "max_cap": info.get("max_cap"),
            "geo_cap": info.get("geo_cap"),
        }
        for oid, info in tracking.items()
    }})


@bp.post("/api/partner/offers/<offer_id>/update_cap")
@require_auth("partner")
def api_partner_update_cap(offer_id):
    """Партнёр меняет кап своего оффера → обновляется в Binom и трекинге."""
    body    = request.get_json(silent=True) or {}
    max_cap = body.get("max_cap")
    if not max_cap or int(max_cap) < 1:
        return make_response(jsonify({"ok": False, "error": "max_cap required"}), 400)

    # Обновляем в Binom
    r = binom_post(f"/public/api/v1/offer/cap/conversion/{offer_id}", {
        "maxCap": int(max_cap),
    })
    if not r.ok:
        return make_response(jsonify({"ok": False, "error": f"Binom {r.status_code}"}), 502)

    # Обновляем в трекинге
    import os as _os3
    tracking_file = _os3.path.join(_os3.path.dirname(__file__), "../../data/offer_tracking.json")
    try:
        tracking = json.loads(open(tracking_file).read())
        if str(offer_id) in tracking:
            tracking[str(offer_id)]["max_cap"] = int(max_cap)
            open(tracking_file, "w").write(json.dumps(tracking, ensure_ascii=False, indent=2))
    except Exception:
        pass

    return jsonify({"ok": True, "max_cap": int(max_cap)})


@bp.post("/api/partner/offers/<offer_id>/stop_request")
@require_auth("partner")
def api_partner_stop_request(offer_id):
    """Партнёр запрашивает стоп оффера — пуш админу в TG."""
    body       = request.get_json(silent=True) or {}
    reason     = str(body.get("reason", "")).strip()
    comment    = str(body.get("comment", "")).strip()
    offer_name = str(body.get("offer_name", f"#{offer_id}")).strip()
    user       = request.current_user

    if not reason:
        return make_response(jsonify({"ok": False, "error": "Укажите причину"}), 400)

    try:
        from app.services.tg import send_message, _load_pending, _save_pending
        partner_name = user.get("username", "—")
        msg_lines = [
            "📩 <b>Запрос на стоп оффера</b>",
            "",
            "👤 Партнёр: <b>" + partner_name + "</b>",
            "📋 Оффер: <b>" + offer_name + "</b> (#" + str(offer_id) + ")",
            "🔎 Причина: <b>" + reason + "</b>",
        ]
        if comment:
            msg_lines.append("💬 " + comment)

        cb_stop    = f"stop_partner:stop:{offer_id}:{offer_name[:25]}"
        cb_noperf  = f"stop_partner:noperf:{offer_id}:{offer_name[:25]}"
        reply_markup = {
            "inline_keyboard": [[
                {"text": "⏹ STOP!", "callback_data": cb_stop},
                {"text": "📉 NO PERF!", "callback_data": cb_noperf},
            ]]
        }
        pending = _load_pending()
        for cb_data in (cb_stop, cb_noperf):
            pending[cb_data] = {
                "offer_id":   str(offer_id),
                "offer_name": offer_name,
                "partner":    partner_name,
                "reason":     reason,
                "action":     "stop" if "stop:" in cb_data else "noperf",
            }
        _save_pending(pending)

        mid = send_message(chr(10).join(msg_lines), reply_markup)
        if mid:
            for cb_data in (cb_stop, cb_noperf):
                pending[cb_data]["message_id"] = mid
            _save_pending(pending)
    except Exception as e:
        import logging
        logging.getLogger("partner").error(f"stop_request TG: {e}")

    return jsonify({"ok": True})


@bp.get("/api/partner/requests")
@require_auth("partner")
def api_partner_requests():
    return jsonify({"ok": True, "requests": get_requests(partner_id=request.current_user["id"])})

@bp.post("/api/partner/requests")
@require_auth("partner")
def api_partner_submit():
    body = request.get_json(silent=True) or {}
    name    = str(body.get("offer_name", "")).strip()
    geo     = str(body.get("geo", "")).strip()
    if not name or not geo:
        return make_response(jsonify({"ok": False, "error": "offer_name and geo required"}), 400)
    comment  = str(body.get("comment", ""))
    postback = str(body.get("postback_url", "")).strip()
    if postback:
        comment = ("Postback: " + postback + chr(10) + comment).strip()
    rid = create_request(request.current_user["id"], name,
                          str(body.get("offer_url", "")), geo,
                          str(body.get("rate", "")), comment)
    return jsonify({"ok": True, "id": rid})

# ── Binom: Create offer ────────────────────────────────────────────────────────


@bp.post("/api/binom/offers/add_to_rotation")
@require_auth("admin")
def api_add_offer_to_rotation():
    """Добавляет существующий оффер в ротацию по GEO."""
    body       = request.get_json(silent=True) or {}
    print(f"[add_to_rotation] body={body}", flush=True)
    offer_id   = body.get("offer_id")
    rotation_id = str(body.get("rotation_id", "")).strip()
    geo        = str(body.get("geo", "")).strip()
    weight     = int(float(body.get("weight") or 50))
    offer_name = str(body.get("offer_name", "")).strip()

    if not offer_id or not rotation_id or not geo:
        return make_response(jsonify({"ok": False, "error": "offer_id, rotation_id, geo required"}), 400)

    import re as _re
    geo_lower = geo.lower()
    geo_code_m = _re.search(r'([A-Z]{2})', geo)
    geo_code   = geo_code_m.group(1).lower() if geo_code_m else None

    r_rot = binom_get(f"/public/api/v1/rotation/{rotation_id}")
    if not r_rot.ok:
        return make_response(jsonify({"ok": False, "error": f"Cannot fetch rotation {rotation_id}"}), 502)

    rot_data = _safe_json(r_rot)
    print(f"[add_to_rotation] GET rotation keys: {list(rot_data.keys()) if isinstance(rot_data, dict) else type(rot_data)}", flush=True)
    if isinstance(rot_data, dict) and isinstance(rot_data.get("data"), dict):
        rot_obj = rot_data["data"]
        print(f"[add_to_rotation] rot_obj keys: {list(rot_obj.keys())}", flush=True)
    else:
        rot_obj = rot_data

    rules = rot_obj.get("rules") or []
    target_rule = None
    for rule in (rules if isinstance(rules, list) else []):
        if not isinstance(rule, dict): continue
        rname = str(rule.get("name") or "").strip().lower()
        if (rname == geo_lower
                or (geo_code and geo_code == rname)
                or (geo_code and geo_code in rname)
                or geo_lower in rname or rname in geo_lower):
            target_rule = rule
            break

    if not target_rule:
        available = [str(r.get("name","")) for r in (rules if isinstance(rules, list) else [])[:15]]
        return jsonify({"ok": False, "rotation_error": f"GEO '{geo}' not found in #{rotation_id}. Available: {available}"})

    paths = target_rule.get("paths") or []
    target_path = next((p for p in paths if isinstance(p, dict) and p.get("enabled") is not False), None)
    if not target_path:
        return jsonify({"ok": False, "rotation_error": f"No active path in GEO '{geo}' rotation #{rotation_id}"})

    existing    = target_path.get("offers") or []
    campaign_id = next((int(o.get("campaignId")) for o in existing if o.get("campaignId") is not None), None)
    existing.append({
        "offerId":    int(offer_id) if str(offer_id).isdigit() else offer_id,
        "campaignId": campaign_id,
        "name":       offer_name,
        "weight":     weight,
        "enabled":    True,
        "directUrl":  "",
    })
    # Также фиксируем directUrl у всех существующих офферов в пути
    for o in existing[:-1]:
        if isinstance(o, dict) and o.get("directUrl") is None:
            o["directUrl"] = ""
    target_path["offers"] = existing

    print(f"[add_to_rotation] PUT body keys: {list(rot_obj.keys()) if isinstance(rot_obj, dict) else type(rot_obj)}", flush=True)
    r_put = binom_put(f"/public/api/v1/rotation/{rotation_id}", rot_obj)
    print(f"[add_to_rotation] PUT status={r_put.status_code} body={r_put.text[:500]}", flush=True)
    if not r_put.ok:
        return jsonify({"ok": False, "rotation_error": f"PUT failed #{rotation_id}: {r_put.status_code} — {r_put.text[:200]}"})

    # Записываем в трекинг
    max_cap_val  = body.get("max_cap")
    partner_name = body.get("partner_name", "")
    rate_val     = body.get("rate")
    currency_val = str(body.get("currency", "USD"))
    _track_offer(str(offer_id), offer_name, rotation_id, geo,
                 max_cap=int(max_cap_val) if max_cap_val else None,
                 partner_name=partner_name,
                 rate=float(rate_val) if rate_val else None,
                 currency=currency_val)
    print(f"[add_to_rotation] offer {offer_id} → rotation #{rotation_id} GEO={geo}", flush=True)
    return jsonify({"ok": True, "rotation_id": rotation_id, "geo": geo})


# ── Google Sheets sync ────────────────────────────────────────────────────────

# ── Offer tracking API ────────────────────────────────────────────────────────

@bp.get("/api/tracking/offers")
@require_auth("admin")
def api_tracking_list():
    """Список отслеживаемых офферов."""
    resp = make_response(jsonify({"ok": True, "offers": _load_tracking()}))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.post("/api/tracking/offers/<offer_id>")
@require_auth("admin")
def api_tracking_add(offer_id):
    """Обновить поля оффера в трекинге (частичное обновление)."""
    body     = request.get_json(silent=True) or {}
    tracking = _load_tracking()
    key      = str(offer_id)
    existing = tracking.get(key, {})
    # Обновляем только переданные поля
    for field in ("name", "start_date", "rotation_id", "geo", "sheet_name", "max_cap", "partner_name", "rate", "currency", "auto_stop_pct", "auto_stopped", "group_ids", "geo_cap"):
        if field in body:
            existing[field] = body[field]
    if not existing.get("created_at"):
        existing["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tracking[key] = existing
    _save_tracking(tracking)
    return jsonify({"ok": True})


@bp.post("/api/tracking/manual")
@require_auth("admin")
def api_tracking_manual():
    """Ручное добавление оффера в трекинг."""
    body        = request.get_json(silent=True) or {}
    offer_id    = str(body.get("offer_id", "")).strip()
    name        = str(body.get("name", "")).strip()
    start_date  = str(body.get("start_date", "")).strip()
    rotation_id = str(body.get("rotation_id", "")).strip()
    geo         = str(body.get("geo", "")).strip()
    max_cap      = body.get("max_cap")
    partner_name = str(body.get("partner_name", "")).strip()
    rate_val     = body.get("rate")
    currency_val = str(body.get("currency", "USD")).strip()

    if not offer_id or not name:
        return make_response(jsonify({"ok": False, "error": "offer_id and name required"}), 400)

    import pytz as _pytz2
    if not start_date:
        start_date = datetime.now(_pytz2.timezone("Europe/Moscow")).strftime("%Y-%m-%d")

    tracking = _load_tracking()
    group_ids_val = str(body.get("group_ids", "")).strip()
    geo_cap_val   = body.get("geo_cap")
    platform_val  = str(body.get("platform", "ios")).strip().lower()
    if platform_val not in ("ios", "android"):
        platform_val = "ios"
    tracking[offer_id] = {
        "name":         name,
        "start_date":   start_date,
        "rotation_id":  rotation_id,
        "geo":          geo,
        "partner_name": partner_name,
        "max_cap":      int(max_cap) if max_cap else None,
        "rate":         float(rate_val) if rate_val else None,
        "currency":     currency_val or "USD",
        "group_ids":    group_ids_val or None,
        "geo_cap":      int(geo_cap_val) if geo_cap_val else None,
        "platform":     platform_val,
        "created_at":   datetime.now(_pytz2.timezone("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S"),
        "manual":       True,
    }
    _save_tracking(tracking)
    return jsonify({"ok": True})


@bp.post("/api/tracking/offers/<offer_id>/status")
@require_auth("admin")
def api_tracking_set_status(offer_id):
    """Изменить статус оффера: active / stopped / no_perform."""
    body    = request.get_json(silent=True) or {}
    status  = str(body.get("status", "active"))
    if status not in ("active", "stopped", "no_perform"):
        return make_response(jsonify({"ok": False, "error": "Invalid status"}), 400)
    tracking = _load_tracking()
    if str(offer_id) not in tracking:
        return make_response(jsonify({"ok": False, "error": "Not found"}), 404)
    tracking[str(offer_id)]["status"] = status
    _save_tracking(tracking)
    return jsonify({"ok": True})


@bp.delete("/api/tracking/offers/<offer_id>")
@require_auth("admin")
def api_tracking_delete(offer_id):
    """Удалить оффер из трекинга."""
    tracking = _load_tracking()
    tracking.pop(str(offer_id), None)
    _save_tracking(tracking)
    return jsonify({"ok": True})


_FD_CACHE_FILE = os.path.join(os.path.dirname(__file__), "../../data/tracking_fd_cache.json")

@bp.get("/api/tracking/offers/<offer_id>/binom_cap")
@require_auth("admin")
def api_tracking_binom_cap_get(offer_id):
    """Подтягивает Binom cap для оффера."""
    r = binom_get(f"/public/api/v1/offer/cap/conversion/{offer_id}")
    if not r.ok:
        return make_response(jsonify({"ok": False, "error": f"Binom {r.status_code}"}), 502)
    return jsonify({"ok": True, "cap": _safe_json(r)})


@bp.put("/api/tracking/offers/<offer_id>/binom_cap")
@require_auth("admin")
def api_tracking_binom_cap_update(offer_id):
    """Обновляет Binom cap оффера."""
    body = request.get_json(silent=True) or {}
    max_cap = body.get("maxCap")
    if not max_cap:
        return make_response(jsonify({"ok": False, "error": "maxCap required"}), 400)

    # Получаем текущие настройки капа
    r_get = binom_get(f"/public/api/v1/offer/cap/conversion/{offer_id}")
    if r_get.ok:
        current = _safe_json(r_get)
        # Обновляем только maxCap, остальное сохраняем
        payload = {**current, "maxCap": int(max_cap)}
        r = binom_put(f"/public/api/v1/offer/cap/conversion/{offer_id}", payload)
    else:
        # Капа ещё нет — создаём
        r = binom_post(f"/public/api/v1/offer/cap/conversion/{offer_id}", {
            "maxCap":       int(max_cap),
            "isActive":     True,
            "resetFrequency": 86400,
            "timezone":     "Europe/Moscow",
            "priority":     "in_path",
        })

    if not r.ok:
        return make_response(jsonify({"ok": False, "error": f"Binom {r.status_code}: {r.text[:200]}"}), 502)

    # Обновляем кеш
    fd_cache_file = os.path.join(os.path.dirname(__file__), "../../data/tracking_fd_cache.json")
    try:
        cache = json.loads(open(fd_cache_file).read())
        if str(offer_id) in cache:
            cache[str(offer_id)]["binom_max_cap"] = int(max_cap)
            open(fd_cache_file, "w").write(json.dumps(cache, ensure_ascii=False, indent=2))
    except Exception:
        pass

    return jsonify({"ok": True, "maxCap": int(max_cap)})


@bp.post("/api/tracking/offers/<offer_id>/update_cap")
@require_auth("admin")
def api_tracking_update_cap(offer_id):
    """Обновляет Max Cap оффера в Binom."""
    body    = request.get_json(silent=True) or {}
    max_cap = body.get("max_cap")
    if not max_cap:
        return make_response(jsonify({"ok": False, "error": "max_cap required"}), 400)

    # Обновляем кап в Binom
    r = binom_post(f"/public/api/v1/offer/cap/conversion/{offer_id}", {
        "maxCap": int(max_cap),
    })
    if not r.ok:
        return make_response(jsonify({"ok": False, "error": f"Binom {r.status_code}: {r.text[:200]}"}), 502)

    # Обновляем max_cap в трекинге
    tracking = _load_tracking()
    if str(offer_id) in tracking:
        tracking[str(offer_id)]["max_cap"] = int(max_cap)
        _save_tracking(tracking)

    # Сбрасываем кеш чтобы следующий запрос перечитал
    fd_cache_file = os.path.join(os.path.dirname(__file__), "../../data/tracking_fd_cache.json")
    try:
        cache = json.loads(open(fd_cache_file).read())
        if str(offer_id) in cache:
            cache[str(offer_id)]["binom_max_cap"] = int(max_cap)
            open(fd_cache_file, "w").write(json.dumps(cache, ensure_ascii=False, indent=2))
    except Exception:
        pass

    return jsonify({"ok": True, "max_cap": int(max_cap)})


@bp.get("/api/tracking/fd")
@require_auth("admin")
def api_tracking_fd():
    """Возвращает FD из кеша (обновляется фоном каждые 10 мин)."""
    try:
        cache = json.loads(open(_FD_CACHE_FILE).read())
    except Exception:
        cache = {}
    return jsonify({"ok": True, "fd": cache})


@bp.post("/api/tracking/fd/refresh")
@require_auth("admin")
def api_tracking_fd_refresh():
    """Принудительно запускает обновление FD кеша."""
    try:
        from app.services.scheduler import _do_tracking_fd
        import threading
        threading.Thread(target=_do_tracking_fd, daemon=True).start()
        return jsonify({"ok": True, "note": "Обновление запущено в фоне"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Rates ────────────────────────────────────────────────────────────────────

_RATES_FILE = os.path.join(os.path.dirname(__file__), "../../data/rates.json")

def _load_rates() -> dict:
    try:
        return json.loads(open(_RATES_FILE).read())
    except Exception:
        return {}

def _save_rates(data: dict):
    open(_RATES_FILE, "w").write(json.dumps(data, ensure_ascii=False, indent=2))


@bp.get("/api/rates")
@require_auth("admin")
def api_rates_list():
    resp = make_response(jsonify({"ok": True, "rates": _load_rates()}))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.post("/api/rates")
@require_auth("admin")
def api_rates_save():
    """Сохраняет весь объект ставок."""
    body = request.get_json(silent=True) or {}
    rates = body.get("rates", {})
    _save_rates(rates)
    return jsonify({"ok": True})


@bp.post("/api/admin/stop_offer")
@require_auth("admin")
def api_admin_stop_offer():
    """Останавливает оффер во всех ротациях по Binom ID."""
    body       = request.get_json(silent=True) or {}
    offer_id   = str(body.get("offer_id", "")).strip()
    reason     = str(body.get("reason", "manual")).strip()
    comment    = str(body.get("comment", "")).strip()
    offer_name = str(body.get("offer_name", f"Оффер #{offer_id}")).strip()

    if not offer_id:
        return make_response(jsonify({"ok": False, "error": "offer_id required"}), 400)

    # Подтягиваем имя оффера из Binom по ID
    binom_offer_name = None
    try:
        r_offer = binom_get(f"/public/api/v1/offer/{offer_id}")
        if r_offer.ok:
            od = _safe_json(r_offer)
            if isinstance(od, dict):
                binom_offer_name = (od.get("name")
                                    or (od.get("data") or {}).get("name")
                                    or (od.get("offer") or {}).get("name"))
    except Exception:
        pass
    # Используем имя из Binom если нашли, иначе из тела запроса, иначе ID
    if binom_offer_name:
        offer_name = binom_offer_name
    elif not offer_name:
        offer_name = f"#{offer_id}"

    ROTATIONS = ["121", "117", "118", "120", "124", "127", "61", "133", "134", "135", "137"]
    stopped_rots  = []
    already_zero  = []
    errors        = []

    from app.services.sheets import _names_match

    for rot_id in ROTATIONS:
        try:
            r = binom_get(f"/public/api/v1/rotation/{rot_id}")
            if not r.ok:
                continue
            rot_data = _safe_json(r)
            rot_obj  = rot_data.get("data", rot_data) if isinstance(rot_data, dict) else rot_data

            changed     = False
            was_already = True

            for rule in (rot_obj.get("rules") or []):
                for path in (rule.get("paths") or []):
                    for offer in (path.get("offers") or []):
                        oid   = str(offer.get("offerId") or "")
                        oname = offer.get("name") or ""
                        if oid == offer_id or _names_match(offer_name, oname):
                            if int(offer.get("weight") or 0) > 0:
                                offer["weight"] = 0
                                changed = True
                                was_already = False
                            elif int(offer.get("weight") or 0) == 0:
                                pass  # уже 0

            if changed:
                r_put = binom_put(f"/public/api/v1/rotation/{rot_id}", rot_obj)
                if r_put.ok:
                    stopped_rots.append(rot_id)
                else:
                    errors.append(f"#{rot_id}: {r_put.status_code}")
            elif not was_already:
                already_zero.append(f"#{rot_id}")
        except Exception as e:
            errors.append(f"#{rot_id}: {e}")

    # Переименовываем оффер в Binom — добавляем префикс
    reason_prefix = {
        "no_perform":      "NO PERF!",
        "cap_filled":      "STOP!",
        "partner_request": "STOP!",
        "manual":          "STOP!",
        "fraud":           "FRAUD!",
    }.get(reason, "STOP!")

    if stopped_rots and offer_id and binom_offer_name:
        # Переименовываем только если знаем реальное имя из Binom
        prefixes = ["NO PERF!", "STOP!", "FRAUD!"]
        if not any(binom_offer_name.startswith(p) for p in prefixes):
            new_name = f"{reason_prefix} {binom_offer_name}"
            try:
                r_rename = binom_put(f"/public/api/v1/offer/{offer_id}/rename", {"name": new_name})
                if r_rename.ok:
                    offer_name = new_name
            except Exception:
                pass

    # Обновляем статус в трекинге
    if stopped_rots or already_zero:
        tracking = _load_tracking()
        if offer_id in tracking:
            tracking[offer_id]["status"]       = "stopped" if reason != "no_perform" else "no_perform"
            tracking[offer_id]["stop_reason"]  = reason
            tracking[offer_id]["stop_comment"] = comment
            if stopped_rots:
                tracking[offer_id]["name"] = offer_name  # обновляем имя с префиксом
            _save_tracking(tracking)

    # TG пуш
    reason_labels = {
        "no_perform":      "No Perform",
        "cap_filled":      "Кап заполнен",
        "partner_request": "Запрос партнёра",
        "manual":          "Вручную",
    }
    if stopped_rots:
        try:
            from app.services.tg import send_message
            import pytz
            from datetime import datetime
            msk = pytz.timezone("Europe/Moscow")
            now = datetime.now(msk).strftime("%H:%M МСК")
            rots_line = ', '.join('#'+r for r in stopped_rots)
            comment_line = f"\n💬 {comment}" if comment else ""
            msg = (
                f"⏹ <b>Оффер остановлен через панель</b>\n\n"
                f"📋 <b>{offer_name}</b>\n"
                f"🔢 Binom ID: {offer_id}\n"
                f"📌 Причина: <b>{reason_labels.get(reason, reason)}</b>\n"
                f"🔄 Ротации: {rots_line}"
                f"{comment_line}\n"
                f"⏱ {now}"
            )
            send_message(msg)
        except Exception as e:
            import logging
            logging.getLogger("partner").error(f"TG stop push error: {e}")

    return jsonify({
        "ok":          True,
        "stopped_rots": stopped_rots,
        "already_zero": already_zero,
        "errors":       errors,
    })


@bp.get("/api/binom/affiliate_networks")
@require_auth("admin")
def api_binom_affiliate_networks():
    """Список affiliate networks из Binom."""
    r = binom_get("/public/api/v1/affiliate_network/list/all")
    if not r.ok:
        return make_response(jsonify({"ok": False, "error": f"Binom {r.status_code}"}), 502)
    data = _safe_json(r)
    networks = data if isinstance(data, list) else (data.get("data") or data.get("items") or [])
    return jsonify({"ok": True, "networks": [
        {"id": n.get("id"), "name": n.get("name")} for n in networks if isinstance(n, dict)
    ]})


@bp.get("/api/binom/countries")
@require_auth("admin")
def api_binom_countries():
    """Список стран из Binom."""
    r = binom_get("/public/api/v1/country/list")
    if not r.ok:
        return make_response(jsonify({"ok": False, "error": f"Binom {r.status_code}"}), 502)
    data = _safe_json(r)
    rows = data if isinstance(data, list) else (data.get("data") or data.get("items") or data.get("result") or [])
    countries = []
    for c in rows:
        if not isinstance(c, dict): continue
        code = c.get("code") or c.get("iso") or c.get("iso_code") or c.get("id")
        name = c.get("name") or c.get("title")
        if code and name:
            countries.append({"code": str(code).upper(), "name": name})
    countries.sort(key=lambda c: c["name"])
    return jsonify({"ok": True, "countries": countries})


@bp.get("/api/binom/offer_fields")
@require_auth("admin")
def api_binom_offer_fields():
    """Debug: показывает все поля первого оффера из Binom."""
    r = binom_get("/public/api/v1/offer/alternative/all")
    if not r.ok:
        return make_response(jsonify({"ok": False, "error": f"Binom {r.status_code}"}), 502)
    data = _safe_json(r)
    rows = data if isinstance(data, list) else (data.get("data") or data.get("items") or [])
    if not rows:
        return jsonify({"ok": False, "error": "No offers"})
    # Возвращаем все ключи первых 3 офферов
    sample = [dict(o) for o in rows[:3] if isinstance(o, dict)]
    return jsonify({"ok": True, "sample": sample, "all_keys": list(rows[0].keys()) if rows else []})


@bp.get("/api/binom/offers_list")
@require_auth("admin")
def api_binom_offers_list():
    """Список офферов из Binom для выбора Alternative offer."""
    r = binom_get("/public/api/v1/offer/alternative/all")
    if not r.ok:
        return make_response(jsonify({"ok": False, "error": f"Binom {r.status_code}: {r.text[:200]}"}), 502)
    data = _safe_json(r)
    rows = data if isinstance(data, list) else (data.get("data") or data.get("items") or data.get("result") or [])
    offers = []
    for o in rows:
        if not isinstance(o, dict): continue
        oid  = o.get("id")
        name = o.get("name") or o.get("title")
        if not oid or not name: continue
        country = o.get("country") or o.get("countryCode") or o.get("geo") or ""
        offers.append({"id": oid, "name": name, "country": country})
    offers.sort(key=lambda o: o["name"])
    return jsonify({"ok": True, "offers": offers, "total": len(offers)})


@bp.post("/api/binom/offers")
@require_auth("admin")
def api_binom_create_offer():
    """
    Создаёт оффер в Binom через CLONE существующего + PUT для обновления полей.
    POST /public/api/v1/offer создаёт баг strtoupper(null) в Binom v2.
    """
    import json as _json
    body = request.get_json(silent=True) or {}

    name = str(body.get("name") or "").strip()
    url  = str(body.get("url")  or "").strip()
    if not name or not url:
        return make_response(jsonify({"ok": False, "error": "name and url required"}), 400)

    # ── Шаг 1: клонируем базовый оффер (alternativeOfferId или любой существующий) ──
    source_id = body.get("alternative_offer_id") or body.get("source_offer_id")
    if not source_id:
        # Берём первый доступный оффер из списка
        r_list = binom_get("/public/api/v1/offer/alternative/all")
        if r_list.ok:
            offers = _safe_json(r_list)
            if isinstance(offers, list) and offers:
                source_id = offers[0].get("id")
            elif isinstance(offers, dict):
                items = offers.get("data") or offers.get("items") or []
                if items:
                    source_id = items[0].get("id")

    if not source_id:
        return make_response(jsonify({"ok": False, "error": "Нет базового оффера для клонирования. Укажи source_offer_id."}), 400)

    print(f"[create_offer] Cloning offer id={source_id}", flush=True)
    rc_clone = binom_get(f"/public/api/v1/offer/{source_id}/clone")
    print(f"[create_offer] Clone status={rc_clone.status_code} body={rc_clone.text}", flush=True)

    if not rc_clone.ok:
        return make_response(jsonify({
            "ok": False,
            "error": f"Clone failed: Binom {rc_clone.status_code}: {rc_clone.text[:300]}",
        }), 502)

    clone_data = _safe_json(rc_clone)
    # Clone returns template without id — extract the offer object
    template = None
    if isinstance(clone_data, dict):
        template = clone_data.get("offer") or clone_data
    if not isinstance(template, dict):
        return make_response(jsonify({"ok": False, "error": "Неожиданный формат ответа клона"}), 502)

    # ── Шаг 2: модифицируем шаблон нашими данными ────────────────────────────
    payout_val = body.get("payout")
    currency   = str(body.get("currency") or "USD").strip().upper()
    auto_pay   = body.get("auto_payout", True)

    # Flat payout fields per Binom API schema
    template["name"]        = name
    template["url"]         = url
    template["countryCode"] = str(body.get("country") or "").strip().upper() or "global"
    template["amount"]      = float(payout_val) if payout_val not in (None, "", 0) else 0
    template["currency"]    = currency
    template["isAuto"]      = bool(auto_pay)
    template["isUpsell"]    = False
    # Remove old nested payout if came from clone
    template.pop("payout", None)

    if body.get("affiliate_network_id"):
        template["affiliateNetworkId"] = int(body["affiliate_network_id"])
    if body.get("postback_url"):
        template["postbackUrl"] = str(body["postback_url"]).strip()
    if body.get("alternative_offer_id"):
        template["alternativeOfferId"] = int(body["alternative_offer_id"])
    else:
        template.pop("alternativeOfferId", None)

    # ── Шаг 3: POST с готовым шаблоном → получаем id ─────────────────────────
    # Remove ALL null values — Binom calls strtoupper(null) on any null string field
    def _strip_nulls(obj):
        if isinstance(obj, dict):
            return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
        return obj
    template = _strip_nulls(template)

    print(f"[create_offer] POST /offer: {_json.dumps({'offer': template})}", flush=True)
    rc_post = binom_post("/public/api/v1/offer", {"offer": template})
    print(f"[create_offer] POST status={rc_post.status_code} body={rc_post.text}", flush=True)

    if not rc_post.ok:
        return make_response(jsonify({
            "ok": False,
            "error": f"Binom {rc_post.status_code}: {rc_post.text[:400]}",
        }), 502)

    post_data = _safe_json(rc_post)
    # Response is {"id": 1} per API docs
    new_id = post_data.get("id") if isinstance(post_data, dict) else None
    print(f"[create_offer] Created offer id={new_id} raw={rc_post.text[:200]}", flush=True)

    if not new_id:
        return make_response(jsonify({
            "ok": False,
            "error": f"Оффер создан но id не найден. Ответ: {rc_post.text}",
        }), 502)

    result = {"ok": True, "binom_offer_id": new_id}

    # ── Шаг 3: Conversion cap через отдельный endpoint ────────────────────────
    if body.get("conversion_cap"):
        reset_sec  = body.get("reset_cap_seconds")
        reset_from = body.get("reset_cap_from")
        alt_offer_id = body.get("alternative_offer_id")
        cap_body = {
            "maxCap":           int(body["max_cap"]) if body.get("max_cap") else 10,
            "resetFrequency":   int(reset_sec) if reset_sec else 86400,

            "timezone":         "Europe/Moscow",
            "priority":         "in_path",
            "alternativeOfferId": int(alt_offer_id) if alt_offer_id else 1,
        }
        if reset_from and reset_sec:
            # Binom принимает формат "Y-m-d H:i:s"
            rf = str(reset_from).strip().replace("T", " ")
            if len(rf) == 16:  # "2027-03-18 14:36" → добавляем секунды
                rf += ":00"
            # Убираем таймзону если есть
            rf = rf.split("+")[0].split("Z")[0].strip()
            cap_body["startingFrom"] = rf
        print(f"[create_offer] Cap POST /offer/cap/conversion/{new_id}: {_json.dumps(cap_body)}", flush=True)
        rc_cap = binom_post(f"/public/api/v1/offer/cap/conversion/{new_id}", cap_body)
        print(f"[create_offer] Cap status={rc_cap.status_code} body={rc_cap.text[:300]}", flush=True)
        result["cap_ok"]     = rc_cap.ok
        result["cap_status"] = rc_cap.status_code
        if not rc_cap.ok:
            result["cap_error"] = rc_cap.text[:300]

    # ── Шаг 4: Добавляем в ротацию ────────────────────────────────────────────
    rotation_id = body.get("rotation_id")
    geo         = str(body.get("geo") or "").strip()
    weight      = int(float(body.get("weight") or 50))

    print(f"[create_offer] Rotation step: rotation_id={rotation_id!r} geo={geo!r} new_id={new_id!r}", flush=True)
    if rotation_id and geo and new_id:
        r_rot = binom_get(f"/public/api/v1/rotation/{rotation_id}")
        print(f"[create_offer] Rotation GET status={r_rot.status_code}", flush=True)
        if r_rot.ok:
            rot_data = _safe_json(r_rot)
            # Структура: {data: {rules: [...]}} или просто {rules: [...]}
            if isinstance(rot_data, dict) and isinstance(rot_data.get("data"), dict):
                rot_obj = rot_data["data"]
            elif isinstance(rot_data, dict):
                rot_obj = rot_data
            else:
                rot_obj = rot_data
            rules = rot_obj.get("rules") or []
            print(f"[create_offer] Rotation rules count={len(rules)} geo={geo!r}", flush=True)
            geo_lower = geo.lower()
            # Извлекаем двухбуквенный код из GEO (напр. "Austria AT" → "AT")
            import re as _re
            geo_code = (_re.search(r'\b([A-Z]{2})\b', geo) or _re.search(r'([A-Z]{2})$', geo))
            geo_code = geo_code.group(1).lower() if geo_code else None
            target_rule = None
            for rule in (rules if isinstance(rules, list) else []):
                if not isinstance(rule, dict): continue
                rname = str(rule.get("name") or "").strip()
                rname_lo = rname.lower()
                # Матч по коду страны, полному названию или части
                if (rname_lo == geo_lower
                    or (geo_code and geo_code == rname_lo)
                    or (geo_code and geo_code in rname_lo)
                    or geo_lower in rname_lo
                    or rname_lo in geo_lower):
                    target_rule = rule
                    print(f"[create_offer] Matched GEO rule: {rname!r}", flush=True)
                    break
            if not target_rule:
                print(f"[create_offer] GEO not matched: {geo!r} geo_code={geo_code!r}", flush=True)
                print(f"[create_offer] Available rules: {[r.get('name') for r in rules[:10]]}", flush=True)
            if target_rule:
                paths = target_rule.get("paths") or []
                target_path = next((p for p in paths if isinstance(p, dict) and p.get("enabled") is not False), None)
                if target_path:
                    existing = target_path.get("offers") or []
                    campaign_id = next((
                        int(o.get("campaignId")) for o in existing
                        if o.get("campaignId") is not None
                    ), None)
                    existing.append({
                        "offerId":    int(new_id) if str(new_id).isdigit() else new_id,
                        "campaignId": campaign_id,
                        "name":       name,
                        "weight":     weight,
                        "enabled":    True,
                    })
                    target_path["offers"] = existing
                    r_put_rot = binom_put(f"/public/api/v1/rotation/{rotation_id}", rot_obj)
                    result["rotation_added"]  = r_put_rot.ok
                    result["rotation_status"] = r_put_rot.status_code
                    if r_put_rot.ok:
                        _track_offer(new_id, name, rotation_id, geo)
                        print(f"[create_offer] Tracked offer {new_id} from {rotation_id}/{geo}", flush=True)
                else:
                    result["rotation_added"] = False
                    result["rotation_error"] = "No active path in GEO"
            else:
                result["rotation_added"] = False
                result["rotation_error"] = f"GEO '{geo}' not found in rotation"
        else:
            result["rotation_added"] = False
            result["rotation_error"] = f"Could not fetch rotation {rotation_id}"

    return jsonify(result)



@bp.get("/api/binom/offers/test")
@require_auth("admin")
def api_binom_offer_test():
    """Диагностика: минимальный payload шаг за шагом."""
    import json as _j
    results = []

    def try_create(label, payload, wrap=True):
        body = {"offer": payload} if wrap else payload
        rc = binom_post("/public/api/v1/offer", body)
        ok = rc.ok
        entry = {"step": label, "status": rc.status_code, "ok": ok, "resp": rc.text}  # FULL response
        results.append(entry)
        print(f"[test] {label}: {rc.status_code} {rc.text[:200]}", flush=True)
        # cleanup if created
        if ok:
            try:
                d = _j.loads(rc.text)
                inner = d.get("offer") or d.get("data") or d or {}
                oid = inner.get("id") if isinstance(inner, dict) else None
                if oid:
                    import requests as _r
                    from app.utils.config import BINOM_BASE, BINOM_API_KEY
                    _r.delete(f"{BINOM_BASE}/public/api/v1/offer/{oid}",
                              headers={"X-API-KEY": BINOM_API_KEY}, timeout=5)
            except Exception:
                pass
        return ok

    base = {"name": "ZTEST_DEL", "url": "https://example.com"}
    pay  = {"value": 0, "currency": "EUR", "auto": True}

    # Test wrapped vs flat to find correct format
    try_create("1W. wrapped no payout",          base,                    wrap=True)
    try_create("2W. wrapped +payout",            {**base, "payout": pay}, wrap=True)
    try_create("3F. flat no payout",             base,                    wrap=False)
    try_create("4F. flat +payout",               {**base, "payout": pay}, wrap=False)
    try_create("5F. flat +payout +country",      {**base, "payout": pay, "country": "DE"}, wrap=False)
    try_create("6F. flat +payout +country +aff", {**base, "payout": pay, "country": "DE", "affiliateNetworkId": 11}, wrap=False)

    return jsonify({"results": results})