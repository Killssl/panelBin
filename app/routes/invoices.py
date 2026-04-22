"""
routes_invoices.py — система счетов партнёров.

Флоу:
  1. Админ создаёт счёт (binom_amount берётся из Binom по network_id + месяц)
  2. Партнёр видит счёт с разбивкой по офферам, заполняет: paid_amount, hold_amount,
     hold_reason, tx_hashes, comment → отправляет на проверку
  3. Админ проверяет, может написать вопрос в чат, подтверждает или отклоняет
"""

from datetime import datetime, timedelta
import json, os, sqlite3
from flask import Blueprint, jsonify, make_response, request
from app.utils.partner_db import DB_PATH, _conn
from app.utils.config import LOCAL_TZ

bp = Blueprint("invoices", __name__)

# Reuse auth from partner routes
def _require(role=None):
    from app.routes.partner import require_auth
    return require_auth(role)


# ─── DB migrations ────────────────────────────────────────────────────────────

def init_invoices_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS invoices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            network_id      TEXT NOT NULL,
            partner_id      INTEGER REFERENCES users(id),
            month           TEXT NOT NULL,          -- "2026-03"
            binom_amount    REAL NOT NULL DEFAULT 0, -- из Binom (трекер)
            offer_breakdown TEXT,                    -- JSON [{offer_name, fd, amount}]
            paid_amount     REAL,                    -- партнёр заплатил
            hold_amount     REAL,                    -- холд (партнёр вводит)
            hold_reason     TEXT,                    -- причина холда
            tx_hashes       TEXT,                    -- JSON [url, ...]
            partner_comment TEXT,
            admin_comment   TEXT,
            wallet_address  TEXT,                    -- адрес кошелька
            wallet_network  TEXT,                    -- TRC20 / ERC20 / BEP20 и т.д.
            status          TEXT NOT NULL DEFAULT 'pending',
            hold_paid        INTEGER NOT NULL DEFAULT 0,  -- 1 = холд выплачен
            -- pending → filled → review → confirmed | rejected | questioned
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS invoice_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id  INTEGER NOT NULL REFERENCES invoices(id),
            author      TEXT NOT NULL,  -- "admin" | "partner"
            text        TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_inv_network ON invoices(network_id);
        CREATE INDEX IF NOT EXISTS idx_inv_month   ON invoices(month);
        CREATE INDEX IF NOT EXISTS idx_inv_status  ON invoices(status);
        CREATE INDEX IF NOT EXISTS idx_msg_inv     ON invoice_messages(invoice_id);

        CREATE TABLE IF NOT EXISTS admin_notifications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            type        TEXT NOT NULL,   -- "hold_paid" | "invoice_review" | etc
            invoice_id  INTEGER REFERENCES invoices(id),
            text        TEXT NOT NULL,
            read        INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_notif_read ON admin_notifications(read);
        """)
        # Migration: add wallet fields if missing
        cols = {r[1] for r in c.execute("PRAGMA table_info(invoices)")}
        if "wallet_address" not in cols:
            c.execute("ALTER TABLE invoices ADD COLUMN wallet_address TEXT")
        if "wallet_network" not in cols:
            c.execute("ALTER TABLE invoices ADD COLUMN wallet_network TEXT")
        # Migration: add hold_paid if missing
        cols = {r[1] for r in c.execute("PRAGMA table_info(invoices)")}
        if "hold_paid" not in cols:
            c.execute("ALTER TABLE invoices ADD COLUMN hold_paid INTEGER NOT NULL DEFAULT 0")
        # Migration: notifications table (created above via IF NOT EXISTS)


# Auto-run migrations on import
try:
    init_invoices_db()
except Exception as _e:
    import logging as _logging
    _logging.getLogger("invoices").warning(f"init_invoices_db failed: {_e}")


def _inv_row(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    for f in ("offer_breakdown", "tx_hashes"):
        if d.get(f):
            try:
                d[f] = json.loads(d[f])
            except Exception:
                pass
    return d


def _now() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def _require_admin():
    from app.routes.partner import require_auth
    return None  # handled by decorator

def _get_user():
    """Returns current_user from request context."""
    return getattr(request, "current_user", None)


# ─── ADMIN endpoints ──────────────────────────────────────────────────────────



@bp.get("/api/admin/invoices")
def admin_list_invoices():
    """Список счетов. ?month=2026-03 &network_id=27 &status=review"""
    from app.routes.partner import require_auth as _ra
    # manual auth check
    from app.routes.partner import _get_token, _admin_static_token
    from app.utils.partner_db import get_user_by_token
    token = _get_token()
    if not token:
        return make_response(jsonify({"ok": False, "error": "auth"}), 401)
    if token == _admin_static_token():
        pass  # admin ok
    else:
        user = get_user_by_token(token)
        if not user or user.get("role") != "admin":
            return make_response(jsonify({"ok": False, "error": "forbidden"}), 403)

    month      = request.args.get("month", "").strip()
    network_id = request.args.get("network_id", "").strip()
    status     = request.args.get("status", "").strip()

    sql = """SELECT i.*, u.username as partner_name
             FROM invoices i
             LEFT JOIN users u ON u.binom_network_id = i.network_id
             WHERE 1=1"""
    params = []
    if month:      sql += " AND i.month=?";      params.append(month)
    if network_id: sql += " AND i.network_id=?"; params.append(network_id)
    if status:     sql += " AND i.status=?";     params.append(status)
    sql += " ORDER BY i.month DESC, i.id DESC"

    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return jsonify({"ok": True, "invoices": [_inv_row(r) for r in rows]})


@bp.post("/api/admin/invoices")
def admin_create_invoice():
    """Создать счёт. Body: {network_id, month, binom_amount, offer_breakdown}"""
    from app.routes.partner import _get_token, _admin_static_token
    from app.utils.partner_db import get_user_by_token
    token = _get_token()
    if token != _admin_static_token():
        user = get_user_by_token(token)
        if not user or user.get("role") != "admin":
            return make_response(jsonify({"ok": False, "error": "forbidden"}), 403)

    body = request.get_json(force=True) or {}
    network_id      = str(body.get("network_id", "")).strip()
    month           = str(body.get("month", "")).strip()  # "2026-03"
    binom_amount    = float(body.get("binom_amount") or 0)
    offer_breakdown = body.get("offer_breakdown") or []
    wallet_address  = str(body.get("wallet_address") or "").strip()
    wallet_network  = str(body.get("wallet_network") or "").strip()

    if not network_id or not month:
        return make_response(jsonify({"ok": False, "error": "network_id and month required"}), 400)

    # Find partner user by network_id
    with _conn() as c:
        partner = c.execute("SELECT id FROM users WHERE binom_network_id=?", (network_id,)).fetchone()
        partner_id = partner["id"] if partner else None

        # Check no duplicate
        existing = c.execute("SELECT id FROM invoices WHERE network_id=? AND month=?",
                              (network_id, month)).fetchone()
        if existing:
            return make_response(jsonify({"ok": False, "error": f"Счёт за {month} уже существует"}), 409)

        now = _now()
        cur = c.execute(
            """INSERT INTO invoices
               (network_id, partner_id, month, binom_amount, offer_breakdown,
                wallet_address, wallet_network, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (network_id, partner_id, month, binom_amount,
             json.dumps(offer_breakdown, ensure_ascii=False),
             wallet_address or None, wallet_network or None,
             "pending", now, now)
        )
        inv_id = cur.lastrowid

    return jsonify({"ok": True, "id": inv_id})


@bp.get("/api/admin/invoices/holds")
def admin_list_holds():
    """Все активные холды (hold_amount > 0 AND hold_paid = 0)."""
    from app.routes.partner import _get_token, _admin_static_token
    from app.utils.partner_db import get_user_by_token
    token = _get_token()
    if token != _admin_static_token():
        user = get_user_by_token(token)
        if not user or user.get("role") != "admin":
            return make_response(jsonify({"ok": False, "error": "forbidden"}), 403)

    with _conn() as c:
        rows = c.execute("""
            SELECT i.*, u.username as partner_name
            FROM invoices i
            LEFT JOIN users u ON u.binom_network_id = i.network_id
            WHERE i.hold_amount > 0 AND i.hold_paid = 0
            ORDER BY i.month DESC
        """).fetchall()
    return jsonify({"ok": True, "holds": [_inv_row(r) for r in rows]})



@bp.get("/api/admin/invoices/<int:inv_id>")
def admin_get_invoice(inv_id):
    from app.routes.partner import _get_token, _admin_static_token
    from app.utils.partner_db import get_user_by_token
    token = _get_token()
    if token != _admin_static_token():
        user = get_user_by_token(token)
        if not user or user.get("role") != "admin":
            return make_response(jsonify({"ok": False, "error": "forbidden"}), 403)

    with _conn() as c:
        row  = c.execute("SELECT i.*,u.username as partner_name FROM invoices i LEFT JOIN users u ON u.binom_network_id=i.network_id WHERE i.id=?", (inv_id,)).fetchone()
        msgs = c.execute("SELECT * FROM invoice_messages WHERE invoice_id=? ORDER BY id", (inv_id,)).fetchall()
    if not row:
        return make_response(jsonify({"ok": False, "error": "not found"}), 404)
    return jsonify({"ok": True, "invoice": _inv_row(row), "messages": [dict(m) for m in msgs]})


@bp.post("/api/admin/invoices/<int:inv_id>/action")
def admin_invoice_action(inv_id):
    """action: confirm | reject | question. Body: {action, comment}"""
    from app.routes.partner import _get_token, _admin_static_token
    from app.utils.partner_db import get_user_by_token
    token = _get_token()
    if token != _admin_static_token():
        user = get_user_by_token(token)
        if not user or user.get("role") != "admin":
            return make_response(jsonify({"ok": False, "error": "forbidden"}), 403)

    body    = request.get_json(force=True) or {}
    action  = str(body.get("action", "")).strip()
    comment = str(body.get("comment", "")).strip()

    status_map = {"confirm": "confirmed", "reject": "rejected", "question": "questioned", "mark_hold_paid": None}
    if action not in status_map:
        return make_response(jsonify({"ok": False, "error": "invalid action"}), 400)

    if action == "mark_hold_paid":
        now = _now()
        with _conn() as c:
            c.execute("UPDATE invoices SET hold_paid=1, updated_at=? WHERE id=?", (now, inv_id))
            if comment:
                c.execute("INSERT INTO invoice_messages (invoice_id,author,text,created_at) VALUES (?,?,?,?)",
                          (inv_id, "admin", comment, now))
        return jsonify({"ok": True})

    now = _now()
    with _conn() as c:
        c.execute("UPDATE invoices SET status=?, admin_comment=?, updated_at=? WHERE id=?",
                  (status_map[action], comment or None, now, inv_id))
        if comment:
            c.execute("INSERT INTO invoice_messages (invoice_id,author,text,created_at) VALUES (?,?,?,?)",
                      (inv_id, "admin", comment, now))

    # TG notify partner
    try:
        with _conn() as c:
            inv = c.execute("SELECT network_id,month FROM invoices WHERE id=?", (inv_id,)).fetchone()
        if inv:
            from app.services.tg import send_message
            emoji = {"confirmed": "✅", "rejected": "❌", "questioned": "❓"}[status_map[action]]
            msg = f"{emoji} <b>Счёт за {inv['month']}</b>\n\n"
            if action == "confirm":
                msg += "Ваш счёт подтверждён."
            elif action == "reject":
                msg += f"Счёт отклонён.\n{comment}"
            else:
                msg += f"Администратор задал вопрос:\n{comment}"
            send_message(msg)
    except Exception:
        pass

    return jsonify({"ok": True})


@bp.post("/api/admin/invoices/<int:inv_id>/message")
def admin_send_message(inv_id):
    from app.routes.partner import _get_token, _admin_static_token
    from app.utils.partner_db import get_user_by_token
    token = _get_token()
    if token != _admin_static_token():
        user = get_user_by_token(token)
        if not user or user.get("role") != "admin":
            return make_response(jsonify({"ok": False, "error": "forbidden"}), 403)

    body = request.get_json(force=True) or {}
    text = str(body.get("text", "")).strip()
    if not text:
        return make_response(jsonify({"ok": False, "error": "text required"}), 400)

    now = _now()
    with _conn() as c:
        c.execute("INSERT INTO invoice_messages (invoice_id,author,text,created_at) VALUES (?,?,?,?)",
                  (inv_id, "admin", text, now))
        c.execute("UPDATE invoices SET status='questioned', updated_at=? WHERE id=? AND status='review'",
                  (now, inv_id))
    return jsonify({"ok": True})


# ─── Binom fetch helper ────────────────────────────────────────────────────────

@bp.get("/api/admin/invoices/binom_data")
def admin_binom_data():
    """Подтянуть данные из Binom по network_id + month.
       ?network_id=27&month=2026-03"""
    from app.routes.partner import _get_token, _admin_static_token
    from app.utils.partner_db import get_user_by_token
    token = _get_token()
    if token != _admin_static_token():
        user = get_user_by_token(token)
        if not user or user.get("role") != "admin":
            return make_response(jsonify({"ok": False, "error": "forbidden"}), 403)

    network_id = request.args.get("network_id", "").strip()
    month      = request.args.get("month", "").strip()  # "2026-03"
    if not network_id or not month:
        return make_response(jsonify({"ok": False, "error": "network_id and month required"}), 400)

    try:
        year, mon = month.split("-")
        date_from = f"{year}-{mon}-01 00:00:00"
        import calendar
        last_day = calendar.monthrange(int(year), int(mon))[1]
        date_to  = f"{year}-{mon}-{last_day:02d} 23:59:59"
    except Exception:
        return make_response(jsonify({"ok": False, "error": "invalid month format"}), 400)

    from app.services.binom import binom_get_pairs, _safe_json
    from app.utils.dpu import extract_rows
    from app.utils.cache import get_all_campaign_ids

    campaign_ids = get_all_campaign_ids()
    if not campaign_ids:
        return make_response(jsonify({"ok": False, "error": "no campaigns"}), 500)

    # Получаем офферы этой сети через /report/offer с фильтром по affiliateNetworkId
    # Используем report/offer — он корректно фильтрует по сети
    pairs = [
        ("datePreset",             "custom_time"),
        ("dateFrom",               date_from),
        ("dateTo",                 date_to),
        ("timezone",               "Europe/Moscow"),
        ("groupings[]",            "affiliateNetwork"),
        ("groupings[]",            "offer"),
        ("sortColumn",             "profit"),
        ("sortType",               "desc"),
        ("limit",                  "2000"),
        ("affiliateNetworkIds[]",  str(network_id)),
    ] + [("ids[]", cid) for cid in campaign_ids]

    r   = binom_get_pairs("/public/api/v1/report/campaign", pairs)
    raw = _safe_json(r)
    rows = extract_rows(raw)

    def _float(v):
        try: return float(v or 0)
        except: return 0.0

    # Find FD key
    fd_key = next((k for row in rows for k in (row.keys() if isinstance(row, dict) else []) if isinstance(k, str) and k.startswith("FD::")), None)

    # Фильтруем: берём только офферы нашей сети (уровень 2 если группировка network→offer)
    offers = []
    total  = 0.0
    in_our_network = False
    net_id_str = str(network_id)

    for row in rows:
        if not isinstance(row, dict): continue
        level = str(row.get("level") or "").strip()

        if level == "1":
            # affiliateNetwork уровень
            eid = str(row.get("entity_id") or "").strip()
            in_our_network = (eid == net_id_str)
        elif level == "2" and in_our_network:
            name   = str(row.get("name") or "").strip()
            fd     = int(_float(row.get(fd_key) or 0)) if fd_key else 0
            profit = _float(row.get("profit") or row.get("revenue") or 0)
            if profit <= 0 and fd <= 0: continue
            offers.append({"offer_name": name, "fd": fd, "amount": round(profit, 2)})
            total += profit

    return jsonify({"ok": True, "offers": offers, "total": round(total, 2),
                    "date_from": date_from, "date_to": date_to})


# ─── PARTNER endpoints ────────────────────────────────────────────────────────

def _auth_partner():
    from app.routes.partner import _get_token
    from app.utils.partner_db import get_user_by_token
    token = _get_token()
    if not token: return None
    return get_user_by_token(token)


@bp.get("/api/partner/invoices")
def partner_list_invoices():
    user = _auth_partner()
    if not user:
        return make_response(jsonify({"ok": False, "error": "auth"}), 401)

    net_id = user.get("binom_network_id")
    if not net_id:
        return jsonify({"ok": True, "invoices": []})

    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM invoices WHERE network_id=? ORDER BY month DESC",
            (net_id,)
        ).fetchall()
    return jsonify({"ok": True, "invoices": [_inv_row(r) for r in rows]})


@bp.get("/api/partner/invoices/<int:inv_id>")
def partner_get_invoice(inv_id):
    user = _auth_partner()
    if not user: return make_response(jsonify({"ok": False, "error": "auth"}), 401)

    net_id = user.get("binom_network_id")
    with _conn() as c:
        row  = c.execute("SELECT * FROM invoices WHERE id=? AND network_id=?", (inv_id, net_id)).fetchone()
        msgs = c.execute("SELECT * FROM invoice_messages WHERE invoice_id=? ORDER BY id", (inv_id,)).fetchall()
    if not row:
        return make_response(jsonify({"ok": False, "error": "not found"}), 404)
    return jsonify({"ok": True, "invoice": _inv_row(row), "messages": [dict(m) for m in msgs]})


@bp.post("/api/partner/invoices/<int:inv_id>/fill")
def partner_fill_invoice(inv_id):
    """Партнёр заполняет счёт. Body: {paid_amount, hold_amount, hold_reason, tx_hashes, comment, submit}"""
    user = _auth_partner()
    if not user: return make_response(jsonify({"ok": False, "error": "auth"}), 401)

    net_id = user.get("binom_network_id")
    body   = request.get_json(force=True) or {}

    paid_amount  = float(body.get("paid_amount") or 0)
    hold_amount  = float(body.get("hold_amount") or 0)
    hold_reason  = str(body.get("hold_reason") or "").strip()
    tx_hashes    = body.get("tx_hashes") or []
    comment      = str(body.get("comment") or "").strip()
    submit       = bool(body.get("submit"))   # True = отправить на проверку

    pending_hold_payments = body.get("pending_hold_payments") or []

    if submit:
        if not comment:
            return make_response(jsonify({"ok": False, "error": "Комментарий обязателен"}), 400)
        if not tx_hashes:
            return make_response(jsonify({"ok": False, "error": "Хэши транзакций обязательны"}), 400)
        if hold_amount > 0 and not hold_reason:
            return make_response(jsonify({"ok": False, "error": "Укажите причину холда"}), 400)
        for ph in pending_hold_payments:
            if not ph.get("tx_hash") or not ph.get("amount"):
                return make_response(jsonify({"ok": False, "error": "Укажите сумму и хэш для погашения холда"}), 400)

    new_status = "review" if submit else "filled"
    now = _now()

    with _conn() as c:
        row = c.execute("SELECT * FROM invoices WHERE id=? AND network_id=?", (inv_id, net_id)).fetchone()
        if not row:
            return make_response(jsonify({"ok": False, "error": "not found"}), 404)
        if row["status"] not in ("pending", "filled", "questioned"):
            return make_response(jsonify({"ok": False, "error": f"Нельзя редактировать счёт в статусе {row['status']}"}), 409)

        c.execute("""UPDATE invoices SET
            paid_amount=?, hold_amount=?, hold_reason=?,
            tx_hashes=?, partner_comment=?, status=?, updated_at=?
            WHERE id=?""",
            (paid_amount, hold_amount, hold_reason,
             json.dumps(tx_hashes, ensure_ascii=False),
             comment, new_status, now, inv_id))

        if submit and comment:
            c.execute("INSERT INTO invoice_messages (invoice_id,author,text,created_at) VALUES (?,?,?,?)",
                      (inv_id, "partner", comment, now))

        # Уведомление админу при отправке на проверку
        if submit:
            c.execute("""INSERT INTO admin_notifications (type, invoice_id, text, created_at)
                VALUES (?,?,?,?)""",
                ("invoice_review", inv_id,
                 f"Счёт на проверке: {user.get('username')} — {dict(row).get('month','')}",
                 now))

        # Погашение холдов прошлых месяцев
        for ph in pending_hold_payments:
            ph_id  = int(ph.get("invoice_id") or 0)
            ph_amt = float(ph.get("amount") or 0)
            ph_tx  = str(ph.get("tx_hash") or "").strip()
            if not ph_id or ph_amt <= 0: continue
            # Verify it belongs to same partner
            ph_row = c.execute("SELECT * FROM invoices WHERE id=? AND network_id=?", (ph_id, net_id)).fetchone()
            if not ph_row: continue
            # Mark hold as paid - append tx, reset hold_amount
            existing_tx = []
            try: existing_tx = json.loads(ph_row["tx_hashes"] or "[]")
            except: pass
            if ph_tx and ph_tx not in existing_tx:
                existing_tx.append(ph_tx)
            c.execute("""UPDATE invoices SET
                hold_paid=1,
                tx_hashes=?, updated_at=?
                WHERE id=?""",
                (json.dumps(existing_tx, ensure_ascii=False), now, ph_id))
            c.execute("INSERT INTO invoice_messages (invoice_id,author,text,created_at) VALUES (?,?,?,?)",
                      (ph_id, "partner", f"Холд погашен: ${ph_amt:,.2f} · {ph_tx}", now))
            # Admin notification
            ph_month = dict(ph_row).get("month","")
            c.execute("""INSERT INTO admin_notifications (type, invoice_id, text, created_at)
                VALUES (?,?,?,?)""",
                ("hold_paid", ph_id,
                 f"Холд выплачен: {user.get('username')} — {ph_month} · ${ph_amt:,.2f} · {ph_tx}",
                 now))

    # Notify admin via TG if submitted
    if submit:
        try:
            from app.services.tg import send_message
            month = dict(row).get("month", "")
            msg   = (f"📋 <b>Счёт на проверке</b>\n\n"
                     f"Партнёр: {user.get('username')}\n"
                     f"Месяц: {month}\n"
                     f"Оплачено: ${paid_amount:,.2f}\n"
                     f"Холд: ${hold_amount:,.2f}" + (f" — {hold_reason}" if hold_reason else ""))
            send_message(msg)
        except Exception:
            pass

    return jsonify({"ok": True})


@bp.post("/api/partner/invoices/<int:inv_id>/pay_hold")
def partner_pay_hold(inv_id):
    """Партнёр оплачивает холд отдельно."""
    user = _auth_partner()
    if not user: return make_response(jsonify({"ok": False, "error": "auth"}), 401)

    net_id = user.get("binom_network_id")
    body   = request.get_json(force=True) or {}
    amount = float(body.get("amount") or 0)
    tx     = str(body.get("tx_hash") or "").strip()

    if not tx:   return make_response(jsonify({"ok": False, "error": "Хэш транзакции обязателен"}), 400)
    if not amount: return make_response(jsonify({"ok": False, "error": "Укажите сумму"}), 400)

    now = _now()
    with _conn() as c:
        row = c.execute("SELECT * FROM invoices WHERE id=? AND network_id=?", (inv_id, net_id)).fetchone()
        if not row: return make_response(jsonify({"ok": False, "error": "not found"}), 404)
        if row["hold_paid"]: return make_response(jsonify({"ok": False, "error": "Холд уже выплачен"}), 409)

        existing_tx = []
        try: existing_tx = json.loads(row["tx_hashes"] or "[]")
        except: pass
        if tx not in existing_tx: existing_tx.append(tx)

        c.execute("UPDATE invoices SET hold_paid=1, tx_hashes=?, updated_at=? WHERE id=?",
                  (json.dumps(existing_tx, ensure_ascii=False), now, inv_id))
        c.execute("INSERT INTO invoice_messages (invoice_id,author,text,created_at) VALUES (?,?,?,?)",
                  (inv_id, "partner", f"Холд выплачен отдельно: ${amount:,.2f} · {tx}", now))
        c.execute("""INSERT INTO admin_notifications (type, invoice_id, text, created_at)
            VALUES (?,?,?,?)""",
            ("hold_paid", inv_id,
             f"Холд выплачен: {user.get('username')} — {row['month']} · ${amount:,.2f} · {tx}",
             now))

    # TG notify
    try:
        from app.services.tg import send_message
        send_message(f"💰 <b>Холд выплачен</b>\n\nПартнёр: {user.get('username')}\nМесяц: {row['month']}\nСумма: ${amount:,.2f}\nХэш: {tx}")
    except Exception: pass

    return jsonify({"ok": True})


@bp.post("/api/partner/invoices/<int:inv_id>/message")
def partner_send_message(inv_id):
    user = _auth_partner()
    if not user: return make_response(jsonify({"ok": False, "error": "auth"}), 401)

    net_id = user.get("binom_network_id")
    body   = request.get_json(force=True) or {}
    text   = str(body.get("text", "")).strip()
    if not text:
        return make_response(jsonify({"ok": False, "error": "text required"}), 400)

    now = _now()
    with _conn() as c:
        row = c.execute("SELECT id FROM invoices WHERE id=? AND network_id=?", (inv_id, net_id)).fetchone()
        if not row:
            return make_response(jsonify({"ok": False, "error": "not found"}), 404)
        c.execute("INSERT INTO invoice_messages (invoice_id,author,text,created_at) VALUES (?,?,?,?)",
                  (inv_id, "partner", text, now))
    return jsonify({"ok": True})


# ─── Admin notifications ─────────────────────────────────────────────────────────

@bp.get("/api/admin/notifications")
def admin_get_notifications():
    from app.routes.partner import _get_token, _admin_static_token
    from app.utils.partner_db import get_user_by_token
    token = _get_token()
    if token != _admin_static_token():
        user = get_user_by_token(token)
        if not user or user.get("role") != "admin":
            return make_response(jsonify({"ok": False, "error": "forbidden"}), 403)
    with _conn() as c:
        rows = c.execute("SELECT * FROM admin_notifications ORDER BY id DESC LIMIT 50").fetchall()
        unread = c.execute("SELECT COUNT(*) FROM admin_notifications WHERE read=0").fetchone()[0]
    return jsonify({"ok": True, "notifications": [dict(r) for r in rows], "unread": unread})


@bp.post("/api/admin/notifications/read")
def admin_mark_read():
    from app.routes.partner import _get_token, _admin_static_token
    from app.utils.partner_db import get_user_by_token
    token = _get_token()
    if token != _admin_static_token():
        user = get_user_by_token(token)
        if not user or user.get("role") != "admin":
            return make_response(jsonify({"ok": False, "error": "forbidden"}), 403)
    body = request.get_json(force=True) or {}
    nid  = body.get("id")
    with _conn() as c:
        if nid: c.execute("UPDATE admin_notifications SET read=1 WHERE id=?", (nid,))
        else:   c.execute("UPDATE admin_notifications SET read=1")
    return jsonify({"ok": True})


# ─── TG hold reminders (called from scheduler) ────────────────────────────────

def send_hold_reminders():
    """Раз в неделю напоминать партнёрам у кого есть невыплаченный счёт (hold > 0)."""
    try:
        from app.services.tg import send_message
        with _conn() as c:
            rows = c.execute("""
                SELECT i.*, u.username
                FROM invoices i
                LEFT JOIN users u ON u.binom_network_id = i.network_id
                WHERE i.hold_amount > 0
                  AND i.hold_paid = 0
            """).fetchall()

        for row in rows:
            d = _inv_row(row)
            try:
                msg = (f"💰 <b>Напоминание об оплате</b>\n\n"
                       f"Счёт за <b>{d['month']}</b> — холд ещё не выплачен.\n\n"
                       f"Сумма холда: <b>${d['hold_amount']:,.2f}</b>\n"
                       f"Причина: {d.get('hold_reason') or '—'}\n\n"
                       f"Зайдите в кабинет и обновите счёт.")
                send_message(msg)
            except Exception:
                pass
    except Exception as e:
        import logging
        logging.getLogger("invoices").error(f"hold reminders error: {e}")