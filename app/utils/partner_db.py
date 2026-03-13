"""
partner_db.py — SQLite база для партнёрской системы.
"""
import sqlite3
import hashlib
import secrets
import os
from datetime import datetime
from typing import Optional, List, Dict

DB_PATH = os.environ.get("PARTNER_DB_PATH", "partner.db")

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            username         TEXT UNIQUE NOT NULL,
            password_hash    TEXT NOT NULL,
            role             TEXT NOT NULL DEFAULT 'partner',
            token            TEXT UNIQUE,
            uid              TEXT UNIQUE,
            binom_network_id TEXT,
            created_at       TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS offer_requests (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id       INTEGER NOT NULL REFERENCES users(id),
            offer_name       TEXT NOT NULL,
            offer_url        TEXT,
            geo              TEXT NOT NULL,
            rate             TEXT,
            comment          TEXT,
            status           TEXT NOT NULL DEFAULT 'pending',
            admin_comment    TEXT,
            rotation_id      TEXT,
            binom_offer_id   TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_req_partner ON offer_requests(partner_id);
        CREATE INDEX IF NOT EXISTS idx_req_status  ON offer_requests(status);
        """)
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
        if "uid" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN uid TEXT UNIQUE")
        if "binom_network_id" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN binom_network_id TEXT")

def _hash(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

def _gen_uid() -> str:
    return secrets.token_urlsafe(12)

def create_user(username: str, password: str, role: str = "partner",
                binom_network_id: str = None) -> Optional[int]:
    token = secrets.token_urlsafe(32)
    uid   = _gen_uid()
    now   = datetime.utcnow().isoformat()
    try:
        with _conn() as c:
            cur = c.execute(
                "INSERT INTO users (username,password_hash,role,token,uid,binom_network_id,created_at) VALUES (?,?,?,?,?,?,?)",
                (username, _hash(password), role, token, uid, binom_network_id, now)
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None

def authenticate(username: str, password: str) -> Optional[Dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username=? AND password_hash=?",
                        (username, _hash(password))).fetchone()
        return dict(row) if row else None

def authenticate_by_uid(uid: str) -> Optional[Dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE uid=?", (uid,)).fetchone()
        return dict(row) if row else None

def get_user_by_token(token: str) -> Optional[Dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE token=?", (token,)).fetchone()
        return dict(row) if row else None

def get_user_by_binom_network(binom_network_id: str) -> Optional[Dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE binom_network_id=?", (binom_network_id,)).fetchone()
        return dict(row) if row else None

def get_all_users() -> List[Dict]:
    with _conn() as c:
        rows = c.execute("SELECT id,username,role,uid,binom_network_id,created_at FROM users ORDER BY id").fetchall()
        return [dict(r) for r in rows]

def update_user(user_id: int, **kwargs) -> bool:
    allowed = {"username","password_hash","role","binom_network_id"}
    sets = {k: v for k, v in kwargs.items() if k in allowed}
    if not sets: return False
    sql = "UPDATE users SET " + ",".join(f"{k}=?" for k in sets) + " WHERE id=?"
    with _conn() as c:
        c.execute(sql, list(sets.values()) + [user_id])
    return True

def delete_user(user_id: int) -> bool:
    with _conn() as c:
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
    return True

def reset_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with _conn() as c:
        c.execute("UPDATE users SET token=? WHERE id=?", (token, user_id))
    return token

def regenerate_uid(user_id: int) -> str:
    uid = _gen_uid()
    with _conn() as c:
        c.execute("UPDATE users SET uid=? WHERE id=?", (uid, user_id))
    return uid

def create_request(partner_id: int, offer_name: str, offer_url: str,
                   geo: str, rate: str, comment: str) -> int:
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO offer_requests (partner_id,offer_name,offer_url,geo,rate,comment,status,created_at,updated_at) VALUES (?,?,?,?,?,?,'pending',?,?)",
            (partner_id, offer_name, offer_url, geo, rate, comment, now, now)
        )
        return cur.lastrowid

def get_requests(partner_id: int = None, status: str = None) -> List[Dict]:
    sql = "SELECT r.*,u.username as partner_name,u.binom_network_id FROM offer_requests r JOIN users u ON u.id=r.partner_id WHERE 1=1"
    params = []
    if partner_id is not None:
        sql += " AND r.partner_id=?"; params.append(partner_id)
    if status:
        sql += " AND r.status=?"; params.append(status)
    sql += " ORDER BY r.id DESC"
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]

def update_request_status(req_id: int, status: str, admin_comment: str = None,
                           rotation_id: str = None, binom_offer_id: str = None) -> bool:
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute("UPDATE offer_requests SET status=?,admin_comment=?,rotation_id=?,binom_offer_id=?,updated_at=? WHERE id=?",
                  (status, admin_comment, rotation_id, binom_offer_id, now, req_id))
    return True

def get_request(req_id: int) -> Optional[Dict]:
    with _conn() as c:
        row = c.execute("SELECT r.*,u.username as partner_name,u.binom_network_id FROM offer_requests r JOIN users u ON u.id=r.partner_id WHERE r.id=?", (req_id,)).fetchone()
        return dict(row) if row else None