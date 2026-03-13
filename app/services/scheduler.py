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

        for s in sheets:
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
    except Exception as e:
        log.error(f"[scheduler] Sync error: {e}", exc_info=True)


def _reschedule(cfg: dict):
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job("sheets_sync")
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
        return _scheduler
    except ImportError:
        log.warning("[scheduler] apscheduler not installed — auto-sync disabled. Run: pip install apscheduler pytz")
        return None
    except Exception as e:
        log.error(f"[scheduler] Init error: {e}")
        return None