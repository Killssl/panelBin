"""
routes_partner.py — партнёрская система + affiliate networks из Binom.
"""
import secrets
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

bp = Blueprint("partner", __name__)
init_db()

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
    rid = create_request(request.current_user["id"], name,
                          str(body.get("offer_url", "")), geo,
                          str(body.get("rate", "")), str(body.get("comment", "")))
    return jsonify({"ok": True, "id": rid})

# ── Binom: Create offer ────────────────────────────────────────────────────────

# ── Google Sheets sync ────────────────────────────────────────────────────────

@bp.get("/api/sheets/debug")
@require_auth("admin")
def api_sheets_debug():
    """Показывает структуру таблицы — листы и заголовки."""
    try:
        from app.services.sheets import list_sheets, read_sheet
        sheets = list_sheets()
        result = {"sheets": sheets, "previews": {}}
        for s in sheets:
            rows = read_sheet(s)
            result["previews"][s] = {
                "headers": rows[0] if rows else [],
                "row_count": len(rows) - 1,
                "sample": rows[1:3] if len(rows) > 1 else [],
            }
        return jsonify({"ok": True, **result})
    except Exception as e:
        return make_response(jsonify({"ok": False, "error": str(e)}), 500)


@bp.post("/api/sheets/sync_caps")
@require_auth("admin")
def api_sheets_sync_caps():
    """
    Синхронизирует Filled Cap из Binom CAP Report → Google Sheets.
    Body: {"sheet_name": "Betting", "date": "2026-03-10", "dry_run": false}
    date по умолчанию = вчера (московское время)
    """
    from datetime import datetime, timedelta
    body       = request.get_json(silent=True) or {}
    sheet_name = body.get("sheet_name", "Betting")
    dry_run    = bool(body.get("dry_run", False))

    # Дата по умолчанию — сегодня по Москве
    date_str = body.get("date") or ""
    if not date_str:
        import pytz
        msk  = pytz.timezone("Europe/Moscow")
        date_str = datetime.now(msk).strftime("%Y-%m-%d")

    try:
        from app.services.sheets import sync_from_cap_report, list_sheets
        from app.utils.cache import get_all_campaigns
        from app.utils.dpu import extract_rows
        from app.services.binom import binom_get_pairs, _safe_json as binom_safe_json, binom_get as _binom_get

        all_campaigns = get_all_campaigns()
        if not all_campaigns:
            return make_response(jsonify({"ok": False, "error": "Не удалось получить список кампаний"}), 500)

        campaign_ids = [c["id"] for c in all_campaigns]

        # Если sheet_name="all" — синкаем все листы
        if sheet_name.lower() == "all":
            sheets = list_sheets()
            results = {}
            for s in sheets:
                results[s] = sync_from_cap_report(
                    binom_get_pairs_fn = binom_get_pairs,
                    binom_get_fn       = _binom_get,
                    safe_json_fn       = binom_safe_json,
                    extract_rows_fn    = extract_rows,
                    campaign_ids       = campaign_ids,
                    sheet_name         = s,
                    date_str           = date_str,
                    dry_run            = dry_run,
                )
            return jsonify({"ok": True, "date": date_str, "sheets": results})

        result = sync_from_cap_report(
            binom_get_pairs_fn = binom_get_pairs,
            binom_get_fn       = _binom_get,
            safe_json_fn       = binom_safe_json,
            extract_rows_fn    = extract_rows,
            campaign_ids       = campaign_ids,
            sheet_name         = sheet_name,
            date_str           = date_str,
            dry_run            = dry_run,
        )
        return jsonify(result)

    except Exception as e:
        import traceback
        return make_response(jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500)


@bp.post("/api/sheets/schedule")
@require_auth("admin")
def api_sheets_schedule():
    """
    Включает/выключает авто-синк капов.
    Body: {"enabled": true, "hour": 3, "minute": 0, "sheet_name": "Betting"}
    """
    body = request.get_json(silent=True) or {}
    from app.services.scheduler import set_schedule, get_schedule
    if body.get("enabled") is not None:
        set_schedule(
            enabled          = bool(body["enabled"]),
            interval_minutes = int(body.get("interval_minutes", 5)),
            sheet_name       = body.get("sheet_name", "Betting"),
        )
    return jsonify({"ok": True, "schedule": get_schedule()})


@bp.post("/api/sheets/fill_ids")
@require_auth("admin")
def api_sheets_fill_ids():
    """
    Один раз: проходит по таблице, ищет каждый оффер в Binom по названию,
    записывает Binom ID в колонку A.
    Body: {"sheet_name": "Betting", "dry_run": true}
    """
    body       = request.get_json(silent=True) or {}
    sheet_name = body.get("sheet_name", "Betting")
    dry_run    = bool(body.get("dry_run", True))

    try:
        from app.services.sheets import read_sheet, update_cell, _names_match, list_sheets

        # Загружаем все офферы из Binom
        r_offers = binom_get("/public/api/v1/offer/alternative/all")
        if not r_offers.ok:
            return make_response(jsonify({"ok": False, "error": f"Binom {r_offers.status_code}"}), 502)
        offers_raw = _safe_json(r_offers)
        binom_offers = offers_raw if isinstance(offers_raw, list) else (offers_raw.get("data") or [])
        binom_map = {o["name"]: str(o["id"]) for o in binom_offers if o.get("name") and o.get("id")}

        def _do_fill_ids(sname, dryrun, binom_map=binom_map):
            rows = read_sheet(sname)
            if not rows:
                return {"error": "Лист пуст"}
            name_col = 1
            for row in rows:
                cells = [str(c).strip().lower() for c in row]
                if any("offer" in c for c in cells):
                    name_col = next((i for i, c in enumerate(cells) if "offer" in c), 1)
                    break
            filled_list = []; skipped_list = []; nf_list = []
            for ri, row in enumerate(rows):
                if len(row) <= name_col: continue
                cell_name = str(row[name_col]).strip()
                if not cell_name or cell_name.lower() in ("offer","name","binom id",""): continue
                existing = str(row[0]).strip() if row else ""
                if existing and existing.isdigit():
                    skipped_list.append(cell_name); continue
                bid = binom_map.get(cell_name)
                if not bid:
                    for bn, b in binom_map.items():
                        if _names_match(bn, cell_name):
                            bid = b; break
                if bid:
                    if not dryrun:
                        update_cell(sname, ri+1, 1, bid)
                    filled_list.append({"row": ri+1, "name": cell_name, "binom_id": bid})
                else:
                    nf_list.append(cell_name)
            return {"filled": filled_list, "skipped": len(skipped_list), "not_found": nf_list}

        # Если sheet_name="all" — заполняем все листы
        if sheet_name.lower() == "all":
            sheets  = list_sheets()
            all_res = {}
            for s in sheets:
                all_res[s] = _do_fill_ids(s, dry_run)
            return jsonify({"ok": True, "sheets": all_res})

        result = _do_fill_ids(sheet_name, dry_run)
        return jsonify({"ok": True, "dry_run": dry_run, **result})

    except Exception as e:
        import traceback
        return make_response(jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500)


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
        cap_body = {
            "maxCap":            int(body["max_cap"]) if body.get("max_cap") else 10,
            "resetCapFrequency": int(reset_sec) if reset_sec else 86400,
        }
        if reset_from and reset_sec:
            cap_body["resetCapFrom"] = str(reset_from)
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

    if rotation_id and geo and new_id:
        r_rot = binom_get(f"/public/api/v1/rotation/{rotation_id}")
        if r_rot.ok:
            rot_data = _safe_json(r_rot)
            rot_obj  = rot_data.get("data") or rot_data if isinstance(rot_data, dict) else rot_data
            rules    = rot_obj if isinstance(rot_obj, list) else (rot_obj.get("rules") or [])
            geo_lower = geo.lower()
            target_rule = None
            for rule in (rules if isinstance(rules, list) else []):
                if not isinstance(rule, dict): continue
                rname = str(rule.get("name") or "").strip()
                if rname.lower() == geo_lower or geo_lower in rname.lower() or rname.lower() in geo_lower:
                    target_rule = rule
                    break
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
                    result["rotation_added"] = r_put_rot.ok
                    result["rotation_status"] = r_put_rot.status_code
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