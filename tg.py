"""
Telegram уведомления о приближении капы к завершению.
Алерт шлётся когда filled_cap пересекает порог (было выше — стало ниже).
"""
import os
import json
import logging
import requests
from datetime import datetime

log = logging.getLogger("tg_alerts")

BOT_TOKEN  = os.getenv("BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

# Порог — слать когда осталось <= 10% от капы
ALERT_THRESHOLD_PCT = 0.10

# Файл с состоянием предыдущего синка
_STATE_FILE = os.path.join(os.path.dirname(__file__), "../../data/tg_alerts_state.json")


def _load_state() -> dict:
    """Загружает состояние предыдущего синка: {offer_key: {"in_threshold": bool, "max_cap": N}}"""
    try:
        return json.loads(open(_STATE_FILE).read())
    except Exception:
        return {}


def _save_state(state: dict):
    open(_STATE_FILE, "w").write(json.dumps(state, ensure_ascii=False, indent=2))


def send_message(text: str) -> bool:
    if not BOT_TOKEN or not TG_CHAT_ID:
        log.warning("[tg] BOT_TOKEN or TG_CHAT_ID not set")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if not r.ok:
            log.error(f"[tg] sendMessage failed: {r.text[:200]}")
        return r.ok
    except Exception as e:
        log.error(f"[tg] sendMessage error: {e}")
        return False


def check_cap_alerts(updated: list):
    """
    updated — список dict из sync_from_cap_report.
    Шлёт алерт когда:
    1. Оффер впервые входит в зону порога (remain <= 10%)
    2. Кап изменился и оффер снова в зоне порога
    """
    if not updated:
        return

    state = _load_state()
    new_state = dict(state)  # копируем, обновим по ходу

    for item in updated:
        name     = item.get("sheet_name") or ""
        filled   = item.get("filled_cap", 0)
        max_cap  = item.get("max_cap", 0)
        sheet    = item.get("sheet", "")
        network  = item.get("network_name", "")

        if not max_cap or max_cap <= 0:
            print(f"[tg] Skip {name!r}: max_cap={max_cap}", flush=True)
            continue

        remain     = max_cap - filled
        remain_pct = remain / max_cap
        in_threshold = remain_pct <= ALERT_THRESHOLD_PCT

        offer_key = name
        prev = state.get(offer_key, {})
        prev_in_threshold = prev.get("in_threshold", False)
        prev_max_cap      = prev.get("max_cap", 0)

        print(f"[tg] {name!r}: filled={filled} cap={max_cap} remain={remain} ({remain_pct*100:.0f}%) in_threshold={in_threshold} prev={prev_in_threshold} prev_cap={prev_max_cap}", flush=True)

        # Обновляем состояние
        new_state[offer_key] = {"in_threshold": in_threshold, "max_cap": max_cap}

        if not in_threshold:
            continue

        # Шлём если:
        # — только что вошёл в зону (раньше не был)
        # — или кап изменился (значит новый цикл — нужен новый алерт)
        if prev_in_threshold and prev_max_cap == max_cap:
            continue  # уже в зоне с тем же капом — не спамим

        network_line = f"🏢 Партнёрка: <b>{network}</b>\n" if network else ""
        if remain <= 0:
            header = "🚨 <b>Кап превышен!</b>"
            remain_line = f"📉 Превышение: <b>{abs(remain)}</b> FD сверх капы\n"
        else:
            header = "⚠️ <b>Кап близко к завершению!</b>"
            remain_line = f"📉 Осталось: <b>{remain}</b> ({remain_pct*100:.0f}%)\n"

        msg = (
            f"{header}\n\n"
            f"{network_line}"
            f"📋 <b>{name}</b>\n"
            f"📊 Лист: {sheet}\n"
            f"🎯 Кап: {filled} / {max_cap}\n"
            f"{remain_line}"
        )

        if send_message(msg):
            log.info(f"[tg] Alert sent: {offer_key} remain={remain} cap={max_cap}")

    _save_state(new_state)