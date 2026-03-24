"""
Планировщик авто-синка капов в Google Sheets.
Запускается из main.py при старте Flask.

pip install apscheduler pytz
"""
import os
import json
import logging
from datetime import datetime, timedelta

log = logging.getLogger("sheets_scheduler")

_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "../../data/sheets_schedule.json")
_scheduler   = None


def _default_config():
    return {"enabled": False, "interval_minutes": 5, "sheet_name": "Betting"}


def get_schedule() -> dict:
    try:
        return json.loads(open(_CONFIG_FILE).read())
    except Exception:
        return _default_config()


def set_schedule(enabled: bool, interval_minutes: int = 5, sheet_name: str = "Betting", **_):
    cfg = {"enabled": enabled, "interval_minutes": interval_minutes, "sheet_name": sheet_name}
    open(_CONFIG_FILE, "w").write(json.dumps(cfg, indent=2))
    _reschedule(cfg)
    log.info(f"[scheduler] Schedule updated: {cfg}")


def _do_sync():
    """Выполняется каждые N минут — синкает данные за СЕГОДНЯ (текущие сутки)."""
    cfg = get_schedule()
    if not cfg.get("enabled"):
        return

    import pytz
    from app.utils.cache import get_all_campaigns
    from app.utils.dpu import extract_rows
    from app.services.binom import binom_get_pairs, _safe_json, binom_get
    from app.services.sheets import sync_from_cap_report

    msk      = pytz.timezone("Europe/Moscow")
    date_str = datetime.now(msk).strftime("%Y-%m-%d")  # СЕГОДНЯ

    log.info(f"[scheduler] Auto-sync caps for {date_str} → {cfg['sheet_name']}")

    try:
        campaigns    = get_all_campaigns() or []
        campaign_ids = [c["id"] for c in campaigns]

        sheet_name = cfg["sheet_name"]

        # Если "all" — синкаем все листы
        if sheet_name.lower() == "all":
            from app.services.sheets import list_sheets
            sheets = list_sheets()
        else:
            sheets = [sheet_name]

        log.info(f"[scheduler] Sheets to sync: {sheets}")

        for s in sheets:
            try:
                result = sync_from_cap_report(
                binom_get_pairs_fn = binom_get_pairs,
                binom_get_fn       = binom_get,
                safe_json_fn       = _safe_json,
                extract_rows_fn    = extract_rows,
                campaign_ids       = campaign_ids,
                sheet_name         = s,
                date_str           = date_str,
                dry_run            = False,
            )
                log.info(f"[scheduler] {s}: updated={len(result.get('updated', []))} not_found={len(result.get('not_found', []))}")
            except Exception as sheet_err:
                log.error(f"[scheduler] Error syncing sheet '{s}': {sheet_err}", exc_info=True)
    except Exception as e:
        log.error(f"[scheduler] Sync error: {e}", exc_info=True)


def _do_tracking_fd():
    """Обновляет FD для всех офферов из трекинга. Запускается каждые 10 минут."""
    import json, os, pytz
    from datetime import datetime

    tracking_file  = os.path.join(os.path.dirname(__file__), "../../data/offer_tracking.json")
    fd_cache_file  = os.path.join(os.path.dirname(__file__), "../../data/tracking_fd_cache.json")

    try:
        tracking = json.loads(open(tracking_file).read())
    except Exception:
        return

    if not tracking:
        return

    from app.utils.cache import get_all_campaigns
    from app.utils.dpu import extract_rows
    from app.services.binom import binom_get_pairs, _safe_json

    msk   = pytz.timezone("Europe/Moscow")
    today = datetime.now(msk).strftime("%Y-%m-%d")

    try:
        campaign_ids = [c["id"] for c in (get_all_campaigns() or [])]
    except Exception:
        campaign_ids = []

    try:
        cache = json.loads(open(fd_cache_file).read())
    except Exception:
        cache = {}

    for offer_id, info in tracking.items():
        start_date = info.get("start_date", today)
        name       = info.get("name", "")
        try:
            pairs = [
                ("datePreset",  "custom_time"),
                ("dateFrom",    f"{start_date} 00:00:00"),
                ("dateTo",      f"{today} 23:59:59"),
                ("timezone",    "Europe/Moscow"),
                ("groupings[]", "offer"),
                ("sortColumn",  "clicks"),
                ("sortType",    "desc"),
                ("limit",       "10000"),
                ("offset",      "0"),
            ] + [("ids[]", cid) for cid in campaign_ids]

            r = binom_get_pairs("/public/api/v1/report/campaign", pairs)
            if not r.ok:
                continue

            raw  = _safe_json(r)
            rows = extract_rows(raw)

            fd_key = None
            for row in rows:
                for k in row.keys():
                    if "fd" in k.lower():
                        fd_key = k
                        break
                if fd_key:
                    break

            fd_total = 0
            for row in rows:
                if str(row.get("level") or "") != "1":
                    continue
                eid   = str(row.get("entity_id") or "").strip()
                rname = str(row.get("name") or "").strip()
                fd    = int(row.get(fd_key) or 0) if fd_key else 0
                if eid == str(offer_id) or rname == name:
                    fd_total = max(fd_total, fd)

            cache[offer_id] = {
                "fd":         fd_total,
                "start_date": start_date,
                "updated_at": datetime.now(msk).strftime("%Y-%m-%d %H:%M:%S"),
            }
            log.info(f"[tracking] offer {offer_id} fd={fd_total} since {start_date}")

        except Exception as e:
            log.error(f"[tracking] Error for offer {offer_id}: {e}")

    open(fd_cache_file, "w").write(json.dumps(cache, ensure_ascii=False, indent=2))
    log.info(f"[tracking] FD cache updated for {len(tracking)} offers")

    # Проверяем веса офферов в ротациях — если везде 0, помечаем как stopped
    from app.services.binom import _safe_json as _sj
    TRACKED_ROTATIONS = ["121", "118", "61", "117", "120", "124"]
    try:
        # Получаем веса всех офферов из ротаций
        offer_weights = {}  # offer_id → max_weight
        for rot_id in TRACKED_ROTATIONS:
            r = binom_get(f"/public/api/v1/rotation/{rot_id}")
            if not r.ok:
                continue
            rot_data = _sj(r)
            rot_obj  = rot_data.get("data", rot_data) if isinstance(rot_data, dict) else rot_data
            for rule in (rot_obj.get("rules") or []):
                for path in (rule.get("paths") or []):
                    for offer in (path.get("offers") or []):
                        oid = str(offer.get("offerId") or "")
                        w   = int(offer.get("weight") or 0)
                        if oid:
                            offer_weights[oid] = max(offer_weights.get(oid, 0), w)

        # Обновляем статус в tracking
        tracking_changed = False
        for offer_id, info in list(tracking.items()):
            if info.get("status") in ("no_perform",):
                continue  # не трогаем ручные статусы
            w = offer_weights.get(str(offer_id), -1)
            if w == -1:
                continue  # не найден в ротациях — не меняем
            new_status = "stopped" if w == 0 else "active"
            if info.get("status") != new_status:
                tracking[offer_id]["status"] = new_status
                tracking_changed = True
                log.info(f"[tracking] offer {offer_id} status → {new_status} (weight={w})")

        if tracking_changed:
            open(tracking_file, "w").write(json.dumps(tracking, ensure_ascii=False, indent=2))

    except Exception as e:
        log.error(f"[tracking] Weight check error: {e}")

    # Проверяем пороги и шлём TG алерты
    try:
        alerts = []
        for offer_id, info in tracking.items():
            max_cap = info.get("max_cap")
            if not max_cap:
                continue
            fd = cache.get(offer_id, {}).get("fd")
            if fd is None:
                continue
            alerts.append({
                "sheet_name":   info.get("name", ""),
                "filled_cap":   fd,
                "max_cap":      max_cap,
                "sheet":        "Трекинг",
                "network_name": info.get("partner_name", ""),
            })
        if alerts:
            from app.services.tg import check_cap_alerts
            check_cap_alerts(alerts)
    except Exception as e:
        log.error(f"[tracking] TG alerts error: {e}")


def _do_snapshot():
    """В 23:55 фиксируем текущие filled_cap как базу для следующего дня."""
    cfg = get_schedule()
    if not cfg.get("enabled"):
        return

    import pytz
    from app.services.sheets import list_sheets, read_sheet, _today_msk, _save_today_fd

    msk  = pytz.timezone("Europe/Moscow")
    today = datetime.now(msk).strftime("%Y-%m-%d")
    log.info(f"[scheduler] 23:55 snapshot for {today}")

    try:
        sheet_name = cfg["sheet_name"]
        sheets = list_sheets() if sheet_name.lower() == "all" else [sheet_name]

        # Загружаем текущий today_fd снапшот и сбрасываем его для нового дня
        # При следующем синке (уже завтра) last_today_fd будет 0 для всех офферов
        tomorrow = (datetime.now(msk) + timedelta(days=1)).strftime("%Y-%m-%d")

        # Просто очищаем снапшот — при первом синке завтра last_today_fd = 0
        # и формула: current_val - 0 + new_fd = current_val + new_fd (правильно)
        _save_today_fd({})
        log.info(f"[scheduler] Snapshot cleared for new day {tomorrow}")

    except Exception as e:
        log.error(f"[scheduler] Snapshot error: {e}", exc_info=True)


def _reschedule(cfg: dict):
    global _scheduler
    if _scheduler is None:
        return
    for job_id in ("sheets_sync", "sheets_snapshot"):
        try:
            _scheduler.remove_job(job_id)
        except Exception:
            pass

    if cfg.get("enabled"):
        interval_min = int(cfg.get("interval_minutes", 5))
        _scheduler.add_job(
            _do_sync,
            trigger  = "interval",
            minutes  = interval_min,
            id       = "sheets_sync",
            name     = f"Google Sheets cap sync every {interval_min}m",
            replace_existing = True,
        )
        log.info(f"[scheduler] Job scheduled every {interval_min} minutes")

        # Снапшот в 23:55 МСК — сбрасываем today_fd для нового дня
        _scheduler.add_job(
            _do_snapshot,
            trigger  = "cron",
            hour     = 23,
            minute   = 55,
            timezone = "Europe/Moscow",
            id       = "sheets_snapshot",
            name     = "Daily 23:55 snapshot reset",
            replace_existing = True,
        )
        log.info("[scheduler] Snapshot job scheduled at 23:55 MSK")




def init_scheduler(app=None):
    """Вызывать из main.py после создания Flask app."""
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        import pytz

        _scheduler = BackgroundScheduler(timezone=pytz.timezone("Europe/Moscow"))
        _scheduler.start()
        log.info("[scheduler] APScheduler started")

        cfg = get_schedule()
        _reschedule(cfg)

        # Трекинг FD — независимый job, всегда работает
        _scheduler.add_job(
            _do_tracking_fd,
            trigger  = "interval",
            minutes  = 10,
            id       = "tracking_fd",
            name     = "Tracking FD update every 10m",
            replace_existing = True,
        )
        log.info("[scheduler] Tracking FD job started (every 10 min, independent)")

        return _scheduler
    except ImportError:
        log.warning("[scheduler] apscheduler not installed — auto-sync disabled. Run: pip install apscheduler pytz")
        return None
    except Exception as e:
        log.error(f"[scheduler] Init error: {e}")
        return None