"""
Google Sheets sync — обновляет Filled Cap в таблице капов.

Логика:
  filled_cap = current_table_value - last_today_fd + new_today_fd

  Таблица — источник правды для накопленных данных.
  Мы храним только today_fd последнего синка (today_fd_snapshot.json).
  При новом синке: убираем старый today_fd, добавляем новый.

  Сервер лежал N дней → при следующем синке возьмёт current_table_value
  (который остался правильным) и добавит только сегодняшний FD.
"""
import os
import re
import json
from datetime import datetime
from typing import Optional

SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), "../../data/google_service_account.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "18Dhoi3moEHUKPKoLEZzYSj7d06o-mVP9NRdzUvEN2xY"

import pytz as _pytz

_HISTORY_FILE      = os.path.join(os.path.dirname(__file__), "../../data/sync_history.json")
_TRACKING_FILE     = os.path.join(os.path.dirname(__file__), "../../data/offer_tracking.json")

def _load_tracking() -> dict:
    try:
        return json.loads(open(_TRACKING_FILE).read())
    except Exception:
        return {}
_TODAY_FD_FILE     = os.path.join(os.path.dirname(__file__), "../../data/today_fd_snapshot.json")
_HISTORY_KEEP_DAYS  = 30



def _today_msk() -> str:
    return datetime.now(_pytz.timezone("Europe/Moscow")).strftime("%Y-%m-%d")


# ── Google Sheets API ─────────────────────────────────────────────────────────

def _get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def read_sheet(sheet_name: str = None, range_: str = None):
    svc = _get_service()
    range_arg = range_ or (f"{sheet_name}!A1:Z500" if sheet_name else "A1:Z500")
    result = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=range_arg,
    ).execute()
    return result.get("values", [])


def list_sheets():
    svc = _get_service()
    meta = svc.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


def update_cell(sheet_name: str, row: int, col: int, value):
    svc = _get_service()
    col_letter = _col_letter(col)
    range_ = f"{sheet_name}!{col_letter}{row}"
    svc.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=range_,
        valueInputOption="USER_ENTERED",
        body={"values": [[value]]},
    ).execute()


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ── Today FD snapshot ─────────────────────────────────────────────────────────
# Хранит FD последнего синка за сегодня: {"id:1646": {"date": "2026-03-16", "fd": 42}}
# Нужен чтобы при повторном синке за тот же день не удваивать значение

def _parse_start_date(raw: str) -> str:
    """Парсит дату старта оффера в формат YYYY-MM-DD.
    Поддерживает: DD.MM.YYYY, DD/MM/YYYY, YYYY-MM-DD.
    Если не удалось — возвращает начало текущего месяца.
    """
    raw = raw.strip()
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(raw, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    # Фоллбэк — начало текущего месяца
    return datetime.now(_pytz.timezone("Europe/Moscow")).strftime("%Y-%m-01")


def _fetch_fd_range(date_from: str, date_to: str,
                    binom_get_pairs_fn, safe_json_fn,
                    extract_rows_fn, campaign_ids: list) -> int:
    """Суммирует FD за диапазон дат для конкретного оффера.
    Делает один запрос к Binom с dateFrom/dateTo.
    Возвращает словарь {offer_name: total_fd}.
    """
    pairs = [
        ("datePreset",  "custom_time"),
        ("dateFrom",    f"{date_from} 00:00:00"),
        ("dateTo",      f"{date_to} 23:59:59"),
        ("timezone",    "Europe/Moscow"),
        ("groupings[]", "offer"),
        ("sortColumn",  "clicks"),
        ("sortType",    "desc"),
        ("limit",       "10000"),
        ("offset",      "0"),
    ] + [("ids[]", cid) for cid in campaign_ids]

    r   = binom_get_pairs_fn("/public/api/v1/report/campaign", pairs)
    raw = safe_json_fn(r)
    if not r.ok:
        print(f"[sheets] Binom error range {date_from}→{date_to}: {r.status_code}", flush=True)
        return {}

    rows = extract_rows_fn(raw)

    fd_key = None
    for row in rows:
        for k in row.keys():
            if "fd" in k.lower():
                fd_key = k
                break
        if fd_key:
            break

    SKIP_OFFERS = {"1win rs", "1win rs new betano land"}
    result: dict = {}
    result_by_id: dict = {}

    for row in rows:
        if str(row.get("level") or "") != "1":
            continue
        name = str(row.get("name") or "").strip()
        eid  = str(row.get("entity_id") or "").strip()
        fd   = int(row.get(fd_key) or 0) if fd_key else 0
        if name and name.lower() not in SKIP_OFFERS:
            if fd > result.get(name, 0):
                result[name] = fd
        if eid and fd > result_by_id.get(eid, 0):
            result_by_id[eid] = fd

    return result, result_by_id


def _load_today_fd() -> dict:
    try:
        return json.loads(open(_TODAY_FD_FILE).read())
    except Exception:
        return {}


def _save_today_fd(data: dict):
    open(_TODAY_FD_FILE, "w").write(json.dumps(data, ensure_ascii=False, indent=2))


def get_last_today_fd(snapshot: dict, key: str, date_str: str) -> int:
    """Возвращает FD который мы записали в таблицу в прошлый раз за date_str."""
    entry = snapshot.get(key)
    if entry and entry.get("date") == date_str:
        return entry.get("fd", 0)
    return 0

def get_last_written_value(snapshot: dict, key: str, date_str: str) -> int:
    """Возвращает значение которое мы реально записали в таблицу в прошлый синк."""
    entry = snapshot.get(key)
    if entry and entry.get("date") == date_str:
        return entry.get("written", None)  # None = нет данных
    return None


# ── History ───────────────────────────────────────────────────────────────────

def _load_history() -> list:
    try:
        return json.loads(open(_HISTORY_FILE).read())
    except Exception:
        return []


def _save_history(entries: list):
    from datetime import timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_HISTORY_KEEP_DAYS)).strftime("%Y-%m-%d")
    entries = [e for e in entries if e.get("date", "") >= cutoff]
    open(_HISTORY_FILE, "w").write(json.dumps(entries, ensure_ascii=False, indent=2))


def append_sync_log(sheet: str, date_str: str, updated: list, not_found: list, duplicate: bool = False):
    history = _load_history()
    now_msk = datetime.now(_pytz.timezone("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S")
    history.append({
        "ts":        now_msk,
        "date":      date_str,
        "sheet":     sheet,
        "updated":   updated,
        "not_found": not_found,
        "duplicate": duplicate,  # флаг если эта дата уже синкалась
    })
    _save_history(history)


def get_last_sync_for_date(sheet: str, date_str: str) -> dict:
    """Возвращает последний синк за эту дату для этого листа, или None."""
    history = _load_history()
    for entry in reversed(history):
        if entry.get("sheet") == sheet and entry.get("date") == date_str:
            return entry
    return None


def get_history(days: int = 30) -> list:
    from datetime import timezone, timedelta
    cutoff = (datetime.now(_pytz.timezone("Europe/Moscow")) - timedelta(days=days)).strftime("%Y-%m-%d")
    return [e for e in _load_history() if e.get("date", "") >= cutoff]


# ── Name matching ─────────────────────────────────────────────────────────────

def find_cap_col(headers: list, name: str) -> Optional[int]:
    name_lo = name.lower()
    for i, h in enumerate(headers):
        if name_lo in str(h).lower():
            return i
    return None


def _names_match(binom_name: str, sheet_name: str) -> bool:
    def clean(s):
        s = re.sub(r'\[CAP[^\]]*\]', '', s, flags=re.I)
        s = re.sub(r'\bCAP\d+[!]?', '', s, flags=re.I)
        s = re.sub(r'\b\d+/day[!]?', '', s, flags=re.I)
        s = re.sub(r'[^\w\s]', ' ', s)
        words = [w for w in s.lower().split() if len(w) >= 2]
        return words

    bn = clean(binom_name)
    sn = clean(sheet_name)
    if not bn or not sn:
        return False

    bn_set = set(bn)
    sn_set = set(sn)

    if len(bn) <= len(sn):
        short, long_set, long = bn, sn_set, sn
    else:
        short, long_set, long = sn, bn_set, bn

    if len(long) > len(short) * 1.5 and len(short) < 4:
        return False
    if len(short) < 2:
        return False

    overlap = sum(1 for w in short if w in long_set)
    ratio   = overlap / len(short)
    return ratio >= 0.85 and overlap >= 2


# ── Fill Binom IDs ────────────────────────────────────────────────────────────

def sync_filled_caps(binom_caps: list, sheet_name: str, dry_run: bool = False) -> dict:
    rows = read_sheet(sheet_name)
    if not rows:
        return {"error": f"Лист '{sheet_name}' пуст или не найден"}

    headers = rows[0]
    filled_col = find_cap_col(headers, "filled")
    name_col   = find_cap_col(headers, "offer") or find_cap_col(headers, "name") or 0

    if filled_col is None:
        return {"error": f"Колонка 'Filled Cap' не найдена. Заголовки: {headers}"}

    updated   = []
    not_found = []
    errors    = []

    for cap in binom_caps:
        offer_name = str(cap.get("offer_name") or "").strip()
        filled     = cap.get("filled_cap", 0)
        found_row  = None

        for ri, row in enumerate(rows[1:], start=2):
            cell = str(row[name_col]).strip() if len(row) > name_col else ""
            if _names_match(offer_name, cell):
                found_row = ri
                break

        if found_row is None:
            not_found.append(offer_name)
            continue

        try:
            if not dry_run:
                update_cell(sheet_name, found_row, filled_col + 1, filled)
            updated.append({"offer": offer_name, "row": found_row, "filled": filled})
        except Exception as e:
            errors.append({"offer": offer_name, "error": str(e)})

    return {"updated": updated, "not_found": not_found, "errors": errors}


# ── Основной синк ─────────────────────────────────────────────────────────────

def sync_from_cap_report(binom_get_pairs_fn, binom_get_fn, safe_json_fn,
                          extract_rows_fn, campaign_ids: list,
                          sheet_name: str, date_str: str,
                          dry_run: bool = False) -> dict:
    """
    Логика:
      filled_cap = current_table_value - last_today_fd + new_today_fd

    Таблица хранит правильно накопленное значение.
    Мы только обновляем сегодняшний прирост FD.
    При перезапуске сервера или пропуске дней — всё корректно,
    т.к. берём актуальное значение из таблицы как базу.
    """
    # Запрашиваем FD из Binom за date_str
    pairs = [
        ("datePreset",  "custom_time"),
        ("dateFrom",    f"{date_str} 00:00:00"),
        ("dateTo",      f"{date_str} 23:59:59"),
        ("timezone",    "Europe/Moscow"),
        ("groupings[]", "offer"),
        ("sortColumn",  "clicks"),
        ("sortType",    "desc"),
        ("limit",       "10000"),
        ("offset",      "0"),
    ] + [("ids[]", cid) for cid in campaign_ids]

    r   = binom_get_pairs_fn("/public/api/v1/report/campaign", pairs)
    raw = safe_json_fn(r)
    if not r.ok:
        return {"error": f"Binom {r.status_code}: {r.text[:300]}"}

    rows = extract_rows_fn(raw)

    # Находим fd_key
    fd_key = None
    for row in rows:
        for k in row.keys():
            if "fd" in k.lower():
                fd_key = k
                break
        if fd_key:
            break

    SKIP_OFFERS = {"1win rs", "1win rs new betano land"}

    # offer_fd: offer_name → today_fd (берём MAX по всем кампаниям)
    offer_fd: dict = {}
    # offer_fd_by_id: entity_id → today_fd
    offer_fd_by_id: dict = {}

    for row in rows:
        if str(row.get("level") or "") != "1":
            continue
        name = str(row.get("name") or "").strip()
        eid  = str(row.get("entity_id") or "").strip()
        fd   = int(row.get(fd_key) or 0) if fd_key else 0
        if name and name.lower() not in SKIP_OFFERS:
            if fd > offer_fd.get(name, 0):
                offer_fd[name] = fd
        if eid and fd > offer_fd_by_id.get(eid, 0):
            offer_fd_by_id[eid] = fd

    print(f"[sheets] {sheet_name} | {date_str} | offers with FD: {len(offer_fd)}", flush=True)

    # Загружаем сети
    offer_network: dict = {}
    try:
        r_nets = binom_get_fn("/public/api/v1/affiliate_network/list/all")
        if r_nets.ok:
            nets_raw = safe_json_fn(r_nets)
            nets = nets_raw if isinstance(nets_raw, list) else (nets_raw.get("data") or [])
            net_map = {str(n.get("id")): n.get("name", "") for n in nets if n.get("id")}
        r_off = binom_get_fn("/public/api/v1/offer/alternative/all")
        if r_off.ok:
            offs_raw = safe_json_fn(r_off)
            offs = offs_raw if isinstance(offs_raw, list) else (offs_raw.get("data") or [])
            for o in offs:
                aff_id = str(o.get("affiliateNetworkId") or "")
                offer_network[o.get("name", "")] = net_map.get(aff_id, "")
    except Exception as _ne:
        print(f"[sheets] Could not load networks: {_ne}", flush=True)

    if not offer_fd:
        return {"ok": True, "updated": [], "not_found": [], "note": "No FD data for this date"}

    # Читаем таблицу
    rows_sheet = read_sheet(sheet_name)
    if not rows_sheet:
        return {"error": f"Лист '{sheet_name}' пуст"}

    # Находим колонки
    filled_col_idx     = None
    name_col_idx       = 1
    binom_id_col_idx   = 0
    cap_col_idx        = None
    start_date_col_idx = None

    for ri, row in enumerate(rows_sheet):
        cells = [str(c).strip().lower() for c in row]
        if any("filled" in c for c in cells):
            filled_col_idx    = next((i for i, c in enumerate(cells) if "filled" in c), None)
            name_col_idx      = next((i for i, c in enumerate(cells) if "offer" in c or "name" in c), 1)
            binom_id_col_idx  = next((i for i, c in enumerate(cells) if "binom" in c or c == "id"), 0)
            # Колонка C (индекс 2) — Cap, но также ищем по заголовку как фоллбэк
            cap_col_idx = 2  # колонка C зафиксирована
            # Проверяем заголовок — если там не "cap", ищем по названию
            if "cap" not in cells[2] if len(cells) > 2 else True:
                cap_col_idx = next((i for i, c in enumerate(cells)
                                    if "cap" in c and "filled" not in c
                                    and "remain" not in c and "binom" not in c), 2)
            start_date_col_idx = next((i for i, c in enumerate(cells)
                                       if "start" in c or "дата" in c or "date" in c), None)
            break

    if filled_col_idx is None:
        return {"error": "Колонка 'Filled Cap' не найдена в таблице"}

    print(f"[sheets] name_col={name_col_idx} filled_col={filled_col_idx} cap_col={cap_col_idx}", flush=True)

    # Проверяем был ли уже синк за эту дату
    last_sync = get_last_sync_for_date(sheet_name, date_str)
    is_duplicate = last_sync is not None
    if is_duplicate:
        print(f"[sheets] ⚠️ Duplicate sync for {date_str} on {sheet_name} (last at {last_sync.get('ts')})", flush=True)

    # Загружаем today_fd снапшот и трекинг офферов
    today_fd_snap = _load_today_fd()
    new_today_fd_snap = dict(today_fd_snap)
    offer_tracking = _load_tracking()  # {offer_id: {start_date, name, ...}}



    updated   = []
    not_found = list(offer_fd.keys())

    for ri, row in enumerate(rows_sheet):
        if len(row) <= name_col_idx:
            continue
        cell_name  = str(row[name_col_idx]).strip() if len(row) > name_col_idx else ""
        binom_id   = str(row[binom_id_col_idx]).strip() if len(row) > binom_id_col_idx else ""
        start_date = str(row[start_date_col_idx]).strip() if (start_date_col_idx is not None and len(row) > start_date_col_idx) else ""

        if not cell_name or cell_name.lower() in ("offer", "name", "binom id", ""):
            continue

        # Проверяем кап — пропускаем если не чистое число (unlimited, 100/day, etc.)
        if cap_col_idx is not None:
            raw_cap = str(row[cap_col_idx]).strip() if len(row) > cap_col_idx else ""
            if raw_cap and not raw_cap.replace(",", "").replace(" ", "").isdigit():
                continue  # unlimited, 100/day, ∞ и т.д. — пропускаем

        new_today_fd = None
        match_key    = None

        # Матч по Binom ID (точный) — только если entity_id есть в данных Binom
        if binom_id and binom_id.isdigit():
            fd_val = offer_fd_by_id.get(binom_id)
            if fd_val is not None:
                new_today_fd = fd_val
                match_key    = f"ID:{binom_id}"

        # Фоллбэк — матч по названию
        if new_today_fd is None:
            for binom_name, fd_val in offer_fd.items():
                if _names_match(binom_name, cell_name):
                    new_today_fd = fd_val
                    match_key    = f"name:{binom_name}"
                    break

        if new_today_fd is None or new_today_fd == 0:
            continue  # нет FD за этот день — не трогаем ячейку

        # Ключ снапшота — включает имя листа чтобы не пересекаться между листами
        snap_key = f"{sheet_name}:id:{binom_id}" if (binom_id and binom_id.isdigit()) else f"{sheet_name}:name:{cell_name}"

        # Проверяем трекинг по binom_id — приоритет над колонкой в таблице
        if binom_id and binom_id.isdigit() and binom_id in offer_tracking:
            tracked = offer_tracking[binom_id]
            start_date = tracked.get("start_date", start_date)
            print(f"[sheets] {cell_name!r}: tracked start_date={start_date}", flush=True)

        # Если есть дата старта — считаем весь диапазон от start_date до date_str
        if start_date and start_date >= "2020-01-01":
            parsed_start = _parse_start_date(start_date)
            if parsed_start < date_str:
                # Запрашиваем FD за весь период одним запросом
                range_fd, range_fd_by_id = _fetch_fd_range(
                    parsed_start, date_str,
                    binom_get_pairs_fn, safe_json_fn, extract_rows_fn, campaign_ids
                )
                # Матч по ID или имени в range данных
                if binom_id and binom_id.isdigit():
                    total = range_fd_by_id.get(binom_id, 0)
                    if not total:
                        for bnom, fd_val in range_fd.items():
                            if _names_match(bnom, cell_name):
                                total = fd_val; break
                else:
                    for bnom, fd_val in range_fd.items():
                        if _names_match(bnom, cell_name):
                            total = fd_val; break
                    else:
                        total = 0
                total = max(0, total)
                print(f"[sheets] {cell_name!r}: range {parsed_start}→{date_str} total={total} | row={ri+1}", flush=True)
                # Снапшот не нужен для range-режима — обновляем только today_fd для совместимости
                new_today_fd_snap[snap_key] = {"date": date_str, "fd": new_today_fd}
            else:
                # start_date = сегодня — только today_fd
                total = new_today_fd
                new_today_fd_snap[snap_key] = {"date": date_str, "fd": new_today_fd}
        else:
            # Нет start_date — логика: current - last_fd + new_fd
            try:
                current_val = int(str(row[filled_col_idx]).replace(",","").strip() or 0) if len(row) > filled_col_idx else 0
            except Exception:
                current_val = 0
            last_today_fd   = get_last_today_fd(today_fd_snap, snap_key, date_str)
            last_written    = get_last_written_value(today_fd_snap, snap_key, date_str)

            if last_written is not None and last_written != current_val:
                # Таблица и снапшот разошлись — значит предыдущая запись не прошла
                # Используем last_written как базу (что должно быть в таблице)
                print(f"[sheets] {cell_name!r}: MISMATCH table={current_val} written={last_written} — using written as base", flush=True)
                base = last_written
            else:
                base = current_val

            total = base - last_today_fd + new_today_fd
            total = max(0, total)
            print(f"[sheets] {cell_name!r}: base={base} - last_fd={last_today_fd} + new_fd={new_today_fd} = {total} | row={ri+1}", flush=True)

            new_today_fd_snap[snap_key] = {"date": date_str, "fd": new_today_fd, "written": total}

        # Текущее значение в таблице (для сравнения)
        try:
            current_val = int(str(row[filled_col_idx]).replace(",","").strip() or 0) if len(row) > filled_col_idx else 0
        except Exception:
            current_val = 0

        # Пропускаем если не изменилось
        if total == current_val and not dry_run:
            continue

        # Max cap
        max_cap = 0
        if cap_col_idx is not None:
            try:
                raw_cap = str(row[cap_col_idx]).strip().lower() if len(row) > cap_col_idx else ""
                if raw_cap not in ("unlimited", "∞", "uncap", ""):
                    max_cap = int(raw_cap.replace(",", "").replace(" ", "") or 0)
            except Exception:
                max_cap = 0

        if not dry_run:
            update_cell(sheet_name, ri + 1, filled_col_idx + 1, total)

        # Network name
        network_name = offer_network.get(cell_name, "")
        if not network_name:
            for bnom, net in offer_network.items():
                if _names_match(bnom, cell_name):
                    network_name = net
                    break

        updated.append({
            "sheet_name":   cell_name,
            "match":        match_key,
            "row":          ri + 1,
            "before":       current_val,       # значение ДО записи
            "last_fd":      last_today_fd,
            "fd_today":     new_today_fd,
            "filled_cap":   total,             # значение ПОСЛЕ записи
            "max_cap":      max_cap,
            "sheet":        sheet_name,
            "network_name": network_name,
        })
        for n in list(not_found):
            if match_key and n in match_key:
                not_found.remove(n)
                break

    # Сохраняем обновлённый today_fd снапшот
    if not dry_run:
        _save_today_fd(new_today_fd_snap)

    # TG alerts
    if not dry_run:
        try:
            from app.services.tg import check_cap_alerts
            all_offers_for_alerts = []
            SKIP_STATUSES = {"stop", "stop partner", "no perform", "no perf?", "no perf", "partner stop"}
            for ri, row in enumerate(rows_sheet):
                if len(row) <= name_col_idx:
                    continue
                cell_name = str(row[name_col_idx]).strip()
                if not cell_name or cell_name.lower() in ("offer", "name", "binom id", ""):
                    continue
                status_val = str(row[7]).strip().lower() if len(row) > 7 else ""
                if status_val in SKIP_STATUSES:
                    continue
                try:
                    filled_val = int(str(row[filled_col_idx]).replace(",","").strip() or 0) if len(row) > filled_col_idx else 0
                except Exception:
                    filled_val = 0
                max_cap_val = 0
                if cap_col_idx is not None:
                    try:
                        raw = str(row[cap_col_idx]).strip().lower() if len(row) > cap_col_idx else ""
                        if raw not in ("unlimited", "∞", "uncap", ""):
                            max_cap_val = int(raw.replace(",","").replace(" ","") or 0)
                    except Exception:
                        max_cap_val = 0
                if max_cap_val > 0:
                    net = offer_network.get(cell_name, "")
                    if not net:
                        for bn, n in offer_network.items():
                            if _names_match(bn, cell_name):
                                net = n; break
                    all_offers_for_alerts.append({
                        "sheet_name":   cell_name,
                        "filled_cap":   filled_val,
                        "max_cap":      max_cap_val,
                        "sheet":        sheet_name,
                        "network_name": net,
                    })
            check_cap_alerts(all_offers_for_alerts)
        except Exception as e:
            import traceback
            print(f"[sheets] TG alerts error: {e}", flush=True)
            print(traceback.format_exc(), flush=True)

    # Лог
    if not dry_run:
        append_sync_log(sheet_name, date_str, [
            {"offer": u["sheet_name"], "row": u["row"],
             "before": u["before"], "last_fd": u["last_fd"],
             "fd_today": u["fd_today"], "filled_cap": u["filled_cap"],
             "max_cap": u["max_cap"]}
            for u in updated
        ], not_found, duplicate=is_duplicate)

    return {
        "ok":        True,
        "date":      date_str,
        "sheet":     sheet_name,
        "dry_run":   dry_run,
        "duplicate": is_duplicate,
        "last_sync": last_sync.get("ts") if last_sync else None,
        "updated":   updated,
        "not_found": not_found,
    }