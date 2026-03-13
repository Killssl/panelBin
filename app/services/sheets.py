"""
Google Sheets sync — обновляет Filled Cap в таблице капов.

Зависимости (установить на сервере):
    pip install google-auth google-auth-httplib2 google-api-python-client

Структура таблицы определяется автоматически при первом вызове /api/sheets/debug
"""
import os
import re
import json
from datetime import datetime
from typing import Optional

SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), "../../data/google_service_account.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ID таблицы из ссылки
SPREADSHEET_ID = "18Dhoi3moEHUKPKoLEZzYSj7d06o-mVP9NRdzUvEN2xY"


def _get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def read_sheet(sheet_name: str = None, range_: str = None):
    """Читает лист целиком или диапазон."""
    svc   = _get_service()
    range_arg = range_ or (f"{sheet_name}!A1:Z500" if sheet_name else "A1:Z500")
    result = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=range_arg,
    ).execute()
    return result.get("values", [])


def list_sheets():
    """Список листов в таблице."""
    svc = _get_service()
    meta = svc.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


def update_cell(sheet_name: str, row: int, col: int, value):
    """Обновляет одну ячейку. row/col — 1-based."""
    svc  = _get_service()
    col_letter = _col_letter(col)
    range_ = f"{sheet_name}!{col_letter}{row}"
    svc.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=range_,
        valueInputOption="USER_ENTERED",
        body={"values": [[value]]},
    ).execute()


def _col_letter(n: int) -> str:
    """1→A, 2→B, 26→Z, 27→AA ..."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ── Снапшот базовых значений на начало дня ───────────────────────────────────

import pytz as _pytz

_SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), "../../data/sheets_base_snapshot.json")


def _today_msk() -> str:
    return datetime.now(_pytz.timezone("Europe/Moscow")).strftime("%Y-%m-%d")


def _load_snapshot() -> dict:
    """Загружает снапшот. Структура: {key: {"date": "...", "base": N}}"""
    try:
        return json.loads(open(_SNAPSHOT_FILE).read())
    except Exception:
        return {}


def _save_snapshot(data: dict):
    open(_SNAPSHOT_FILE, "w").write(json.dumps(data, ensure_ascii=False, indent=2))


def get_base_for_offer(snapshot: dict, key: str, current_filled: int, today_fd: int) -> int:
    """
    Возвращает базовое значение для оффера.
    База = значение в таблице на начало сегодняшнего дня.

    Логика:
    - Если today_fd == 0 → это начало дня, база = current_filled (что сейчас в таблице)
    - Если снапшот за сегодня уже есть → берём из него
    - Если снапшота нет → база = current_filled - today_fd (вычисляем обратно)
    """
    today = _today_msk()
    entry = snapshot.get(key)

    if entry and entry.get("date") == today:
        return entry.get("base", 0)

    # Снапшота нет или он вчерашний — вычисляем базу
    if today_fd == 0:
        base = current_filled
    else:
        base = max(0, current_filled - today_fd)

    return base


def update_snapshot_entry(snapshot: dict, key: str, base: int) -> dict:
    """Обновляет/создаёт запись снапшота для оффера."""
    today = _today_msk()
    entry = snapshot.get(key)
    # Обновляем только если нет записи за сегодня
    if not entry or entry.get("date") != today:
        snapshot[key] = {"date": today, "base": base}
    return snapshot


# ── Основная логика: синк капов ──────────────────────────────────────────────

def find_cap_col(headers: list, name: str) -> Optional[int]:
    """Находит индекс колонки по части названия (case-insensitive). 0-based."""
    name_lo = name.lower()
    for i, h in enumerate(headers):
        if name_lo in str(h).lower():
            return i
    return None


def sync_filled_caps(binom_caps: list, sheet_name: str, dry_run: bool = False) -> dict:
    """
    binom_caps: список dict с ключами:
        offer_id, offer_name, geo, filled_cap, max_cap

    Ищет строку по offer_name (нечёткое совпадение) в листе,
    обновляет колонку "Filled Cap".

    Возвращает {"updated": [...], "not_found": [...], "errors": [...]}
    """
    rows = read_sheet(sheet_name)
    if not rows:
        return {"error": f"Лист '{sheet_name}' пуст или не найден"}

    headers = rows[0]
    print(f"[sheets] Headers: {headers}")

    # Находим колонки
    filled_col = find_cap_col(headers, "filled")
    name_col   = find_cap_col(headers, "offer") or find_cap_col(headers, "name") or 0

    if filled_col is None:
        return {"error": f"Колонка 'Filled Cap' не найдена. Заголовки: {headers}"}

    print(f"[sheets] name_col={name_col} filled_col={filled_col}")

    updated   = []
    not_found = []
    errors    = []

    for cap in binom_caps:
        offer_name = str(cap.get("offer_name") or "").strip()
        filled     = cap.get("filled_cap", 0)

        # Ищем строку с этим оффером
        found_row = None
        for ri, row in enumerate(rows[1:], start=2):  # start=2 т.к. строка 1 — заголовок
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


def _names_match(binom_name: str, sheet_name: str) -> bool:
    """
    Строгое совпадение: убираем cap-префикс/суффикс и спецсимволы,
    затем требуем что БОЛЕЕ КОРОТКОЕ имя почти полностью входит в длинное.
    Порог: 80% слов короткого должны быть в длинном, минимум 3 слова.
    """
    def clean(s):
        # Убираем cap-префикс типа "CAP300!", "[CAP50]", "15/day!"
        s = re.sub(r'\[CAP[^\]]*\]', '', s, flags=re.I)
        s = re.sub(r'\bCAP\d+[!]?', '', s, flags=re.I)
        s = re.sub(r'\b\d+/day[!]?', '', s, flags=re.I)
        # Убираем спецсимволы, оставляем слова
        s = re.sub(r'[^\w\s]', ' ', s)
        # Фильтруем короткие токены (1-2 символа кроме GEO)
        words = [w for w in s.lower().split() if len(w) >= 2]
        return words

    bn = clean(binom_name)
    sn = clean(sheet_name)
    if not bn or not sn:
        return False

    bn_set = set(bn)
    sn_set = set(sn)

    # Берём БОЛЕЕ КОРОТКОЕ как эталон — но требуем что оно не слишком короткое
    if len(bn) <= len(sn):
        short, long_set, long = bn, sn_set, sn
    else:
        short, long_set, long = sn, bn_set, bn

    # Короткое имя не должно быть в 2+ раза короче длинного
    # Иначе "1win RS" (2 слова) будет матчить "1win RS NEW Betano land" (4 слова)
    if len(long) > len(short) * 1.5 and len(short) < 4:
        return False

    if len(short) < 2:
        return False

    overlap = sum(1 for w in short if w in long_set)
    ratio   = overlap / len(short)

    # Требуем 85% совпадение слов
    return ratio >= 0.85 and overlap >= 2


# ── Синк через CAP Report (FD из Binom → Sheets) ─────────────────────────────

def sync_from_cap_report(binom_get_pairs_fn, binom_get_fn, safe_json_fn,
                          extract_rows_fn, campaign_ids: list,
                          sheet_name: str, date_str: str,
                          dry_run: bool = False) -> dict:
    """
    Тянет FD за date_str из Binom CAP Report,
    обновляет Filled Cap в листе sheet_name.
    """
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

    # fd_key — первый ключ содержащий fd
    fd_key = None
    for row in rows:
        for k in row.keys():
            if "fd" in k.lower():
                fd_key = k
                break
        if fd_key:
            break

    # Офферы которые не нужно трогать в таблице
    SKIP_OFFERS = {"1win rs", "1win rs new betano land"}

    # Собираем FD по офферу — берём МАКСИМУМ если оффер встречается несколько раз
    # (один и тот же оффер может быть в нескольких кампаниях — не суммируем)
    offer_fd: dict = {}
    for row in rows:
        if str(row.get("level") or "") != "1":
            continue
        name = str(row.get("name") or "").strip()
        fd   = int(row.get(fd_key) or 0) if fd_key else 0
        if name and name.lower() not in SKIP_OFFERS:
            # Берём максимальное значение (оффер-уровень уже агрегирован по всем ротациям)
            if fd > offer_fd.get(name, 0):
                offer_fd[name] = fd

    print(f"[sheets] Offers with FD on {date_str}: {len(offer_fd)}", flush=True)

    # Загружаем сети и мапим offerId → networkName
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
                oid   = str(o.get("id") or "")
                netid = str(o.get("affiliateNetworkId") or "")
                if oid and netid:
                    offer_network[o.get("name", "")] = net_map.get(netid, "")
    except Exception as _ne:
        print(f"[sheets] Could not load networks: {_ne}", flush=True)

    if not offer_fd:
        return {"ok": True, "updated": [], "not_found": [], "note": "No FD data for this date"}

    # Строим маппинг offer_id → network_name из Binom
    _offer_network_map = {}  # id → network_name
    _offer_id_name_map = {}  # name → id
    try:
        r_aff = binom_get_fn("/public/api/v1/affiliate_network/list/all")
        aff_data = safe_json_fn(r_aff)
        aff_list = aff_data if isinstance(aff_data, list) else (aff_data.get("data") or [])
        aff_map = {str(a.get("id")): a.get("name") for a in aff_list if a.get("id")}
    except Exception:
        aff_map = {}

    try:
        r_off = binom_get_fn("/public/api/v1/offer/alternative/all")
        off_data = safe_json_fn(r_off)
        off_list = off_data if isinstance(off_data, list) else (off_data.get("data") or [])
        for o in off_list:
            oid  = str(o.get("id") or "")
            name = o.get("name") or ""
            aff_id = str(o.get("affiliateNetworkId") or "")
            net_name = aff_map.get(aff_id) or aff_id
            if oid:
                _offer_network_map[oid] = net_name
            if name:
                _offer_id_name_map[name] = oid
    except Exception:
        pass

    # Читаем таблицу и находим блоки GEO
    rows_sheet = read_sheet(sheet_name)
    if not rows_sheet:
        return {"error": f"Лист '{sheet_name}' пуст"}

    # Находим заголовки в первой строке GEO-блока
    # Структура: строка "Russia | | | Cap remain: | N"
    #            строка "Offer | Cap | $perUnique | Filled Cap | Cap Remain"
    #            строки офферов...
    filled_col_idx = None
    name_col_idx   = None

    for ri, row in enumerate(rows_sheet):
        cells = [str(c).strip().lower() for c in row]
        if "filled cap" in cells or any("filled" in c for c in cells):
            filled_col_idx = next(
                (i for i, c in enumerate(cells) if "filled" in c), None
            )
            name_col_idx = next(
                (i for i, c in enumerate(cells) if "offer" in c or "name" in c), 1
            )
            binom_id_col_idx = next(
                (i for i, c in enumerate(cells) if "binom" in c or c == "id"), 0
            )
            # Cap column — ищем "cap" без "filled" и без "remain"
            cap_col_idx = next(
                (i for i, c in enumerate(cells) if "cap" in c and "filled" not in c and "remain" not in c and "binom" not in c), None
            )
            break

    if filled_col_idx is None:
        return {"error": "Колонка 'Filled Cap' не найдена в таблице"}

    print(f"[sheets] name_col={name_col_idx} filled_col={filled_col_idx} cap_col={cap_col_idx} binom_id_col={binom_id_col_idx}", flush=True)

    # Загружаем снапшот (хранит базу на начало дня по каждому офферу)
    snapshot = _load_snapshot()

    updated   = []
    not_found = list(offer_fd.keys())

    # Строим словарь offer_id → fd_today для матча по ID
    offer_fd_by_id: dict = {}
    for row in rows:
        if str(row.get("level") or "") != "1":
            continue
        eid = str(row.get("entity_id") or "").strip()
        fd  = int(row.get(fd_key) or 0) if fd_key else 0
        if eid and fd > offer_fd_by_id.get(eid, 0):
            offer_fd_by_id[eid] = fd

    for ri, row in enumerate(rows_sheet):
        if len(row) <= name_col_idx:
            continue
        cell_name  = str(row[name_col_idx]).strip() if len(row) > name_col_idx else ""
        binom_id   = str(row[binom_id_col_idx]).strip() if len(row) > binom_id_col_idx else ""

        if not cell_name or cell_name.lower() in ("offer", "name", "binom id", ""):
            continue

        fd_today  = None
        match_key = None

        # Матч по Binom ID (точный)
        if binom_id and binom_id.isdigit():
            fd_today  = offer_fd_by_id.get(binom_id) or offer_fd.get(
                next((n for n in offer_fd if str(n) == binom_id), ""), None
            )
            match_key = f"ID:{binom_id}"

        # Фоллбэк — матч по названию
        if fd_today is None:
            for binom_name, fd_val in offer_fd.items():
                if _names_match(binom_name, cell_name):
                    fd_today  = fd_val
                    match_key = f"name:{binom_name}"
                    break

        if fd_today is None:
            continue

        sheet_row = ri + 1

        # Текущее значение в таблице (читаем первым — нужно для снапшота)
        try:
            current_val = int(str(row[filled_col_idx]).replace(",","").strip() or 0) if len(row) > filled_col_idx else 0
        except Exception:
            current_val = 0

        # Ключ снапшота: binom_id (стабильный), фоллбэк на имя
        snap_key = f"id:{binom_id}" if (binom_id and binom_id.isdigit()) else cell_name
        base_val = get_base_for_offer(snapshot, snap_key, current_val, fd_today)
        update_snapshot_entry(snapshot, snap_key, base_val)
        total = base_val + fd_today

        # Пропускаем если значение не изменилось
        if total == current_val and not dry_run:
            continue

        # Читаем max_cap из колонки Cap
        max_cap = 0
        if cap_col_idx is not None:
            try:
                raw_cap = str(row[cap_col_idx]).strip().lower() if len(row) > cap_col_idx else ""
                if raw_cap not in ("unlimited", "∞", "uncap", ""):
                    max_cap = int(raw_cap.replace(",", "").replace(" ", "") or 0)
            except Exception:
                max_cap = 0

        print(f"[sheets] Match({match_key}): '{cell_name}' base={base_val} + today={fd_today} = {total} (was {current_val}) cap={max_cap} row={sheet_row}", flush=True)
        if not dry_run:
            update_cell(sheet_name, sheet_row, filled_col_idx + 1, total)
        # Получаем network name из offer_network (name → network)
        network_name = offer_network.get(cell_name, "")
        if not network_name:
            for bnom, net in offer_network.items():
                if _names_match(bnom, cell_name):
                    network_name = net
                    break

        updated.append({
            "sheet_name":   cell_name,
            "match":        match_key,
            "row":          sheet_row,
            "base":         base_val,
            "fd_today":     fd_today,
            "filled_cap":   total,
            "max_cap":      max_cap,
            "sheet":        sheet_name,
            "network_name": network_name,
        })
        # Убираем из not_found
        for n in list(not_found):
            if match_key and n in match_key:
                not_found.remove(n)
                break

    # Сохраняем обновлённый снапшот
    if not dry_run:
        _save_snapshot(snapshot)

    # Проверяем капы по ВСЕМ строкам таблицы (не только обновлённым)
    if not dry_run:
        try:
            from app.services.tg import check_cap_alerts
            all_offers_for_alerts = []
            for ri, row in enumerate(rows_sheet):
                if len(row) <= name_col_idx:
                    continue
                cell_name = str(row[name_col_idx]).strip()
                if not cell_name or cell_name.lower() in ("offer", "name", "binom id", ""):
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
                # Колонка H (индекс 7) — статус оффера
                SKIP_STATUSES = {"stop", "stop partner", "no perform", "no perf?", "no perf", "partner stop"}
                status_val = str(row[7]).strip().lower() if len(row) > 7 else ""
                if status_val in SKIP_STATUSES:
                    continue

                if max_cap_val > 0:
                    binom_id_val = str(row[binom_id_col_idx]).strip() if len(row) > binom_id_col_idx else ""
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

    return {
        "ok":        True,
        "date":      date_str,
        "sheet":     sheet_name,
        "dry_run":   dry_run,
        "updated":   updated,
        "not_found": not_found,
    }