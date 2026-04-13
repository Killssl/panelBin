"""
Telegram уведомления о капах + polling для обработки кнопок.
"""
import os
import json
import logging
import threading
import requests
from datetime import datetime

log = logging.getLogger("tg_alerts")

BOT_TOKEN  = os.getenv("BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

ALERT_THRESHOLD_PCT = 0.10  # 10%

_STATE_FILE   = os.path.join(os.path.dirname(__file__), "../../data/tg_alerts_state.json")
_PENDING_FILE = os.path.join(os.path.dirname(__file__), "../../data/tg_pending_stops.json")

# ── State ─────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        return json.loads(open(_STATE_FILE).read())
    except Exception:
        return {}

def _save_state(state: dict):
    open(_STATE_FILE, "w").write(json.dumps(state, ensure_ascii=False, indent=2))

def _load_pending() -> dict:
    try:
        return json.loads(open(_PENDING_FILE).read())
    except Exception:
        return {}

def _save_pending(data: dict):
    open(_PENDING_FILE, "w").write(json.dumps(data, ensure_ascii=False, indent=2))


# ── Telegram API ──────────────────────────────────────────────────────────────

def _tg(method: str, **kwargs) -> dict:
    req_timeout = 35 if method == "getUpdates" else 10
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            json=kwargs, timeout=req_timeout,
        )
        return r.json()
    except Exception as e:
        log.error(f"[tg] {method} error: {e}")
        return {}


def send_message(text: str, reply_markup=None) -> int:
    if not BOT_TOKEN or not TG_CHAT_ID:
        return 0
    params = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    j = _tg("sendMessage", **params)
    return j.get("result", {}).get("message_id", 0)


def edit_message(message_id: int, text: str, reply_markup=None):
    if not BOT_TOKEN or not TG_CHAT_ID:
        return
    params = dict(
        chat_id=TG_CHAT_ID,
        message_id=message_id,
        text=text,
        parse_mode="HTML",
    )
    if reply_markup is not None:
        params["reply_markup"] = reply_markup
    _tg("editMessageText", **params)


def answer_callback(callback_id: str, text: str = ""):
    _tg("answerCallbackQuery", callback_query_id=callback_id, text=text)


# ── Поиск оффера в ротациях ───────────────────────────────────────────────────

def _find_offer_in_rotations(offer_name: str) -> list:
    """
    Возвращает список ротаций где есть оффер:
    [{"rot_id": "123", "rot_name": "...", "weight": 50, "already_stopped": False}, ...]
    """
    from app.services.binom import binom_get, _safe_json
    from app.services.sheets import _names_match

    found = []
    offset, limit = 0, 200
    all_rotations = []

    while True:
        r = binom_get("/public/api/v1/rotation/list/filtered",
                      params={"limit": limit, "offset": offset})
        if not r.ok:
            log.error(f"[tg] list rotations failed: {r.status_code}")
            break
        data  = _safe_json(r)
        items = data if isinstance(data, list) else (data.get("data") or data.get("items") or [])
        if not items:
            break
        all_rotations.extend(items)
        if len(items) < limit:
            break
        offset += limit

    log.info(f"[tg] Scanning {len(all_rotations)} rotations for {offer_name!r}")

    for rot in all_rotations:
        rot_id   = str(rot.get("id") or "")
        rot_name = rot.get("name") or ""
        if not rot_id:
            continue

        r_detail = binom_get(f"/public/api/v1/rotation/{rot_id}")
        if not r_detail.ok:
            continue

        rotation_data = _safe_json(r_detail)
        if isinstance(rotation_data, dict) and isinstance(rotation_data.get("data"), dict):
            rotation_obj = rotation_data["data"]
        else:
            rotation_obj = rotation_data

        rules = rotation_obj.get("rules") or []
        if not isinstance(rules, list):
            rules = [rules]

        for rule in rules:
            if not isinstance(rule, dict):
                continue
            for path in (rule.get("paths") or []):
                if not isinstance(path, dict):
                    continue
                for offer in (path.get("offers") or []):
                    if not isinstance(offer, dict):
                        continue
                    oname = offer.get("name") or ""
                    if _names_match(offer_name, oname) or offer_name == oname:
                        weight = offer.get("weight", 0)
                        found.append({
                            "rot_id":          rot_id,
                            "rot_name":        rot_name,
                            "weight":          weight,
                            "already_stopped": weight == 0,
                            "rotation_obj":    rotation_obj,  # нужен для PUT
                        })

    return found


# ── Cap alerts ────────────────────────────────────────────────────────────────

def check_cap_alerts(updated: list):
    if not updated:
        return

    state     = _load_state()
    new_state = dict(state)
    pending   = _load_pending()

    for item in updated:
        name    = item.get("sheet_name") or ""
        filled  = item.get("filled_cap", 0)
        max_cap = item.get("max_cap", 0)
        sheet   = item.get("sheet", "")
        network = item.get("network_name", "")

        if not max_cap or max_cap <= 0:
            continue

        remain       = max_cap - filled
        remain_pct   = remain / max_cap
        in_threshold = remain_pct <= ALERT_THRESHOLD_PCT
        is_over      = remain <= 0

        offer_key = name
        prev = state.get(offer_key, {})
        prev_in_threshold = prev.get("in_threshold", False)
        prev_max_cap = prev.get("max_cap", 0)
        prev_filled = prev.get("filled", -1)

        new_state[offer_key] = {"in_threshold": in_threshold, "max_cap": max_cap, "filled": filled}

        if not in_threshold:
            continue

        # Не дублируем только если то же самое значение filled
        if prev_in_threshold and prev_max_cap == max_cap and prev_filled == filled:
            continue

        network_line = f"🏢 Партнёрка: <b>{network}</b>\n" if network else ""

        if is_over:
            header      = "🚨 <b>Кап переполнен!</b>"
            remain_line = f"📉 Превышение: <b>{abs(remain)}</b> FD сверх капы\n"
        else:
            header      = "⚠️ <b>Кап близко к завершению!</b>"
            remain_line = f"📉 Осталось: <b>{remain}</b> ({remain_pct*100:.0f}%)\n"

        msg = (
            f"{header}\n\n"
            f"{network_line}"
            f"📋 <b>{name}</b>\n"
            f"📊 Лист: {sheet}\n"
            f"🎯 Кап: {filled} / {max_cap}\n"
            f"{remain_line}"
        )

        cb_data = f"stop:{offer_key[:40]}"
        reply_markup = {
            "inline_keyboard": [[
                {"text": "⏹ Остановить оффер", "callback_data": cb_data}
            ]]
        }
        pending[cb_data] = {
            "offer_name": name,
            "sheet":      sheet,
            "network":    network,
        }
        _save_pending(pending)

        mid = send_message(msg, reply_markup)
        if mid:
            pending[cb_data]["message_id"] = mid
            _save_pending(pending)
            log.info(f"[tg] Alert sent: {name} remain={remain} cap={max_cap}")

    _save_state(new_state)


# ── Обработка кнопки "Остановить" ─────────────────────────────────────────────

def _handle_stop_callback(callback_query: dict):
    cb_id   = callback_query.get("id", "")
    cb_data = callback_query.get("data", "")
    user    = callback_query.get("from", {}).get("username") or "unknown"
    msg_id  = callback_query.get("message", {}).get("message_id")

    pending = _load_pending()
    info    = pending.get(cb_data)

    if not info:
        answer_callback(cb_id, "Уже обработано")
        return

    offer_name = info.get("offer_name", "")
    answer_callback(cb_id, "⏳ Проверяю ротации...")

    # Сначала находим все ротации с оффером
    found = _find_offer_in_rotations(offer_name)

    if not found:
        text = (
            f"❓ <b>Оффер не найден в ротациях</b>\n\n"
            f"📋 {offer_name}\n"
            f"Возможно уже удалён из всех ротаций."
        )
        if msg_id:
            edit_message(msg_id, text, reply_markup={"inline_keyboard": []})
        else:
            send_message(text)
        del pending[cb_data]
        _save_pending(pending)
        return

    # Проверяем — все ли уже остановлены
    active   = [r for r in found if not r["already_stopped"]]
    stopped  = [r for r in found if r["already_stopped"]]

    if not active:
        # Оффер уже остановлен везде
        rot_lines = "\n".join(
            f"  ⏹ {r['rot_name']} (#{r['rot_id']}) — вес: {r['weight']}"
            for r in found
        )
        text = (
            f"ℹ️ <b>Оффер уже остановлен</b>\n\n"
            f"📋 <b>{offer_name}</b>\n\n"
            f"🔄 Ротации ({len(found)}):\n{rot_lines}\n\n"
            f"👤 Проверил: @{user}"
        )
        if msg_id:
            edit_message(msg_id, text, reply_markup={"inline_keyboard": []})
        else:
            send_message(text)
        del pending[cb_data]
        _save_pending(pending)
        return

    # Есть активные — останавливаем
    log.info(f"[tg] Stopping {offer_name!r}: {len(active)} active, {len(stopped)} already stopped")

    from app.services.binom import binom_put, _safe_json

    stopped_now = []
    errors      = []

    # Группируем по rot_id (один оффер может встречаться в нескольких путях одной ротации)
    seen_rot_ids = set()
    for r in active:
        rot_id = r["rot_id"]
        if rot_id in seen_rot_ids:
            continue
        seen_rot_ids.add(rot_id)

        rotation_obj = r["rotation_obj"]
        # Ставим weight=0 для всех вхождений оффера в этой ротации
        rules = rotation_obj.get("rules") or []
        from app.services.sheets import _names_match
        for rule in (rules if isinstance(rules, list) else []):
            if not isinstance(rule, dict): continue
            for path in (rule.get("paths") or []):
                if not isinstance(path, dict): continue
                for offer in (path.get("offers") or []):
                    if not isinstance(offer, dict): continue
                    oname = offer.get("name") or ""
                    if _names_match(offer_name, oname) or offer_name == oname:
                        offer["weight"] = 0

        r_upd = binom_put(f"/public/api/v1/rotation/{rot_id}", rotation_obj)
        if r_upd.ok:
            stopped_now.append(f"{r['rot_name']}(#{rot_id})")
        else:
            errors.append(f"{r['rot_name']}(#{rot_id}): {r_upd.status_code}")
            log.error(f"[tg] PUT failed #{rot_id}: {r_upd.text[:200]}")

    # Формируем итоговое сообщение
    lines = []
    if stopped_now:
        lines.append(f"✅ Остановлено сейчас ({len(stopped_now)}):")
        for s in stopped_now:
            lines.append(f"  • {s}")
    if stopped:
        lines.append(f"\nℹ️ Уже было остановлено ({len(stopped)}):")
        for r in stopped:
            lines.append(f"  ⏹ {r['rot_name']}(#{r['rot_id']})")
    if errors:
        lines.append(f"\n❌ Ошибки ({len(errors)}):")
        for e in errors:
            lines.append(f"  • {e}")

    text = (
        f"{'✅' if stopped_now else '⚠️'} <b>Результат остановки</b>\n\n"
        f"📋 <b>{offer_name}</b>\n\n"
        f"{chr(10).join(lines)}\n\n"
        f"👤 @{user}"
    )

    if msg_id:
        edit_message(msg_id, text, reply_markup={"inline_keyboard": []})
    else:
        send_message(text)

    del pending[cb_data]
    _save_pending(pending)


# ── Polling ───────────────────────────────────────────────────────────────────

_polling_thread  = None
_last_update_id  = 0


def _polling_loop():
    global _last_update_id
    log.info("[tg] Polling started")

    while True:
        try:
            j = _tg("getUpdates", offset=_last_update_id + 1, timeout=25)
            updates = j.get("result") or []

            for upd in updates:
                _last_update_id = upd.get("update_id", _last_update_id)
                cb = upd.get("callback_query")
                if cb:
                    cb_data = cb.get("data", "")
                    if cb_data.startswith("stop:"):
                        _handle_stop_callback(cb)

        except Exception as e:
            log.error(f"[tg] Polling error: {e}")
            import time; time.sleep(5)


def start_polling():
    global _polling_thread
    if not BOT_TOKEN:
        log.warning("[tg] BOT_TOKEN not set — polling disabled")
        return
    if _polling_thread and _polling_thread.is_alive():
        return

    _polling_thread = threading.Thread(target=_polling_loop, daemon=True, name="tg-polling")
    _polling_thread.start()
    log.info("[tg] Polling thread started")