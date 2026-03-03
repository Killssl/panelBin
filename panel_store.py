import os
import json
import uuid
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

_PANEL_LOCK = threading.Lock()

from config import LOCAL_TZ
from binom_client import binom_get_pairs, _safe_json
from cache import get_all_campaign_ids
from dpu import extract_rows, _to_int

OFFERS_PANEL_FILE = os.path.join(os.path.dirname(__file__), "offers_panel.json")
FD_HISTORY_FILE   = os.path.join(os.path.dirname(__file__), "fd_history.json")
FD_HISTORY_MAX    = 500


# ---------- panel ----------

def load_panel() -> Dict:
    with _PANEL_LOCK:
        if os.path.exists(OFFERS_PANEL_FILE):
            try:
                with open(OFFERS_PANEL_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"rotations": []}


def save_panel(data: Dict) -> None:
    with _PANEL_LOCK:
        with open(OFFERS_PANEL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def new_id() -> str:
    return str(uuid.uuid4())[:8]


# ---------- history ----------

def load_history() -> List[Dict]:
    if os.path.exists(FD_HISTORY_FILE):
        try:
            with open(FD_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_history(history: List[Dict]) -> None:
    with open(FD_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-FD_HISTORY_MAX:], f, ensure_ascii=False, indent=2)


def append_fd_events(events: List[Dict]) -> None:
    if not events:
        return
    history = load_history()
    history.extend(events)
    save_history(history)


# ---------- Atomic FD update ----------

def apply_fd_atomic(fd_map: Dict[str, int]) -> tuple:
    """
    Загружает панель, применяет FD и сохраняет — всё под одним lock.
    Возвращает (events, fd_map_size).
    """
    now_str = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    events: List[Dict] = []

    with _PANEL_LOCK:
        if os.path.exists(OFFERS_PANEL_FILE):
            try:
                with open(OFFERS_PANEL_FILE, "r", encoding="utf-8") as f:
                    panel = json.load(f)
            except Exception:
                panel = {"rotations": []}
        else:
            panel = {"rotations": []}

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

        with open(OFFERS_PANEL_FILE, "w", encoding="utf-8") as f:
            json.dump(panel, f, ensure_ascii=False, indent=2)

    return events, len(fd_map)


# ---------- Atomic DPU update ----------

def update_offer_dpu_atomic(offer_id: str, dpu_data: dict) -> bool:
    """Обновляет dpu одного оффера атомарно — под локом."""
    with _PANEL_LOCK:
        if not os.path.exists(OFFERS_PANEL_FILE):
            return False
        try:
            with open(OFFERS_PANEL_FILE, "r", encoding="utf-8") as f:
                panel = json.load(f)
        except Exception:
            return False

        found = False
        for rot in panel["rotations"]:
            for geo in rot["geos"]:
                for off in geo["offers"]:
                    if off["id"] == offer_id:
                        off["dpu"]            = dpu_data.get("dpu")
                        off["dpu_period"]     = dpu_data.get("period")
                        off["dpu_note"]       = dpu_data.get("note")
                        off["dpu_updated_at"] = dpu_data.get("updated_at")
                        found = True
                        break

        if found:
            with open(OFFERS_PANEL_FILE, "w", encoding="utf-8") as f:
                json.dump(panel, f, ensure_ascii=False, indent=2)
        return found


# ---------- FD map ----------

def _find_fd_key(row: Dict) -> Optional[str]:
    for key in row:
        if key.startswith("FD::"):
            return key
    return None


def fetch_fd_map() -> Dict[str, int]:
    """Карта offer_id:geo_lower → FD из Binom за сегодня."""
    today     = datetime.now(LOCAL_TZ).date()
    date_from = today.strftime("%Y-%m-%d")
    campaign_ids = get_all_campaign_ids()
    pairs = [
        ("datePreset",  "custom_time"),
        ("dateFrom",    f"{date_from} 00:00:00"),
        ("dateTo",      f"{date_from} 23:59:59"),
        ("timezone",    "Europe/Moscow"),
        ("groupings[]", "offer"),
        ("groupings[]", "geoCountry"),
        ("sortColumn",  "clicks"),
        ("sortType",    "desc"),
        ("limit",       "10000"),
    ] + [("ids[]", cid) for cid in campaign_ids]

    r   = binom_get_pairs("/public/api/v1/report/campaign", pairs)
    raw = _safe_json(r)
    rows = raw.get("report") or raw.get("data") or [] if isinstance(raw, dict) else []
    fd_key = next((_find_fd_key(row) for row in rows if _find_fd_key(row)), None)
    if not fd_key:
        return {}

    fd_map: Dict[str, int] = {}
    cur_offer_id = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level", "")).strip()
        if level == "1":
            cur_offer_id = str(row.get("entity_id") or "")
        elif level == "2" and cur_offer_id:
            if not row.get("entity_id"):
                geo = str(row.get("name") or "").strip().lower()
                fd  = _to_int(row.get(fd_key) or 0)
                key = f"{cur_offer_id}:{geo}"
                fd_map[key] = fd_map.get(key, 0) + fd
        elif level == "3" and cur_offer_id:
            geo = str(row.get("name") or "").strip().lower()
            fd  = _to_int(row.get(fd_key) or 0)
            key = f"{cur_offer_id}:{geo}"
            fd_map[key] = fd_map.get(key, 0) + fd
    return fd_map