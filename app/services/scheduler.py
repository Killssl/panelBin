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
    date_str = datetime.now(msk).strftime("%Y-%m-%d")

    log.info(f"[scheduler] Auto-sync caps for {date_str} → {cfg['sheet_name']}")

    try:
        campaigns    = get_all_campaigns() or []
        campaign_ids = [c["id"] for c in campaigns]

        sheet_name = cfg["sheet_name"]

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
    from app.services.binom import binom_get_pairs, _safe_json, binom_get

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

    def _fetch_fd_for_id(oid, oname, start, fd_key_hint=None):
        """Возвращает (fd_total, fd_key) для одного offer_id."""
        pairs = [
            ("datePreset",  "custom_time"),
            ("dateFrom",    f"{start} 00:00:00"),
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
            return 0, fd_key_hint

        raw  = _safe_json(r)
        rows = extract_rows(raw)

        fd_key = fd_key_hint
        if not fd_key:
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
            if eid == str(oid) or rname == oname:
                fd_total = max(fd_total, fd)
        return fd_total, fd_key

    for offer_id, info in tracking.items():
        start_date = info.get("start_date", today)
        name       = info.get("name", "")
        group_ids  = info.get("group_ids", "")
        try:
            # Основной оффер
            fd_total, fd_key = _fetch_fd_for_id(offer_id, name, start_date)

            # Группа — суммируем FD связанных офферов
            if group_ids:
                extra_ids = [g.strip() for g in group_ids.replace(",", ":").split(":") if g.strip()]
                for extra_id in extra_ids:
                    if extra_id == str(offer_id):
                        continue
                    extra_fd, fd_key = _fetch_fd_for_id(extra_id, "", start_date, fd_key)
                    fd_total += extra_fd
                    log.info(f"[tracking] group: offer {extra_id} fd={extra_fd} added to {offer_id}")

            cap_entry = {
                "fd":         fd_total,
                "start_date": start_date,
                "updated_at": datetime.now(msk).strftime("%Y-%m-%d %H:%M:%S"),
            }

            # Подгружаем капы из Binom
            try:
                r_cap = binom_get(f"/public/api/v1/offer/{offer_id}")
                if r_cap.ok:
                    od = _safe_json(r_cap)
                    if isinstance(od, dict):
                        caps = (od.get("conversionCaps")
                                or (od.get("data") or {}).get("conversionCaps")
                                or (od.get("offer") or {}).get("conversionCaps"))
                        if isinstance(caps, list) and caps:
                            caps = caps[0]
                        if isinstance(caps, dict):
                            cap_entry["binom_max_cap"]     = caps.get("maxConversions") or caps.get("maxCap")
                            cap_entry["binom_current_cap"] = caps.get("currentConversions") or caps.get("current")
            except Exception as ce:
                log.debug(f"[tracking] cap fetch error for {offer_id}: {ce}")

            cache[offer_id] = cap_entry
            log.info(f"[tracking] offer {offer_id} fd={fd_total} since {start_date}")

        except Exception as e:
            log.error(f"[tracking] Error for offer {offer_id}: {e}")

    open(fd_cache_file, "w").write(json.dumps(cache, ensure_ascii=False, indent=2))
    log.info(f"[tracking] FD cache updated for {len(tracking)} offers")

    # Проверяем веса офферов в ротациях — если везде 0, помечаем как stopped
    from app.services.binom import _safe_json as _sj
    TRACKED_ROTATIONS = ["121", "118", "61", "117", "120", "124"]
    try:
        offer_weights = {}
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

        tracking_changed = False
        for offer_id, info in list(tracking.items()):
            if info.get("status") in ("no_perform",):
                continue
            w = offer_weights.get(str(offer_id), -1)
            if w == -1:
                continue
            new_status = "stopped" if w == 0 else "active"
            if info.get("status") != new_status:
                tracking[offer_id]["status"] = new_status
                tracking_changed = True
                log.info(f"[tracking] offer {offer_id} status → {new_status} (weight={w})")

        if tracking_changed:
            open(tracking_file, "w").write(json.dumps(tracking, ensure_ascii=False, indent=2))

    except Exception as e:
        log.error(f"[tracking] Weight check error: {e}")

    # ── Авто-стоп + TG алерты ─────────────────────────────────────────────
    try:
        from app.services.tg import check_cap_alerts, send_message
        from app.services.binom import _safe_json as _sj2
        from app.services.sheets import _names_match

        alerts         = []
        tracking_dirty = False
        STOP_ROTATIONS = ["121", "118", "61", "117", "120", "124"]

        # Перечитываем tracking — он мог измениться выше
        try:
            tracking = json.loads(open(tracking_file).read())
        except Exception:
            pass

        for offer_id, info in tracking.items():
            max_cap       = info.get("max_cap")
            auto_stop_pct = info.get("auto_stop_pct")
            fd            = cache.get(offer_id, {}).get("fd")
            offer_name    = info.get("name", "")

            if not max_cap or fd is None:
                continue

            # TG алерт (порог 10% остатка)
            # Не шлём алерты для стопнутых/не-перформ офферов
            offer_status = info.get("status", "active")
            if offer_status in ("stopped", "no_perform"):
                continue

            alerts.append({
                "sheet_name":   offer_name,
                "filled_cap":   fd,
                "max_cap":      max_cap,
                "sheet":        "Трекинг",
                "network_name": info.get("partner_name", ""),
            })

            # Авто-стоп — пропускаем если:
            # нет настройки, уже стопнут авто, статус ручной
            if not auto_stop_pct:
                continue
            if info.get("auto_stopped"):
                continue
            if info.get("status") in ("stopped", "no_perform"):
                continue

            # auto_stop_pct хранит абсолютное значение FD для стопа
            if fd < int(auto_stop_pct):
                continue

            # Останавливаем — ставим вес=0 во всех ротациях
            stopped_rots = []
            for rot_id in STOP_ROTATIONS:
                try:
                    r_rot = binom_get(f"/public/api/v1/rotation/{rot_id}")
                    if not r_rot.ok:
                        continue
                    rot_data = _sj2(r_rot)
                    rot_obj  = rot_data.get("data", rot_data) if isinstance(rot_data, dict) else rot_data

                    changed = False
                    for rule in (rot_obj.get("rules") or []):
                        for path in (rule.get("paths") or []):
                            for offer in (path.get("offers") or []):
                                oname = offer.get("name") or ""
                                oid   = str(offer.get("offerId") or "")
                                if oid == str(offer_id) or _names_match(offer_name, oname):
                                    if int(offer.get("weight") or 0) > 0:
                                        offer["weight"] = 0
                                        changed = True

                    if changed:
                        from app.services.binom import binom_put
                        r_put = binom_put(f"/public/api/v1/rotation/{rot_id}", rot_obj)
                        if r_put.ok:
                            stopped_rots.append(rot_id)
                except Exception as re:
                    log.error(f"[tracking] auto-stop rot {rot_id}: {re}")

            if stopped_rots:
                pct_filled = round(fd / max_cap * 100)
                tracking[offer_id]["status"]      = "stopped"
                tracking[offer_id]["auto_stopped"] = datetime.now(msk).strftime("%Y-%m-%d %H:%M:%S")
                tracking_dirty = True
                log.info(f"[tracking] AUTO-STOP {offer_name} fd={fd}/{max_cap} ({pct_filled}%) rots={stopped_rots}")

                send_message(
                    f"🛑 <b>Авто-стоп оффера</b>\n\n"
                    f"📋 <b>{offer_name}</b>\n"
                    f"🎯 Кап: <b>{fd} / {max_cap}</b> ({pct_filled}%)\n"
                    f"⚡ Порог авто-стопа: {auto_stop_pct} FD\n"
                    f"🔄 Остановлено в ротациях: {', '.join('#'+r for r in stopped_rots)}\n"
                    f"⏱ {datetime.now(msk).strftime('%H:%M МСК')}"
                )

        if alerts:
            check_cap_alerts(alerts)

        if tracking_dirty:
            open(tracking_file, "w").write(json.dumps(tracking, ensure_ascii=False, indent=2))

    except Exception as e:
        log.error(f"[tracking] TG/auto-stop error: {e}", exc_info=True)


def _do_snapshot():
    """В 23:55 фиксируем текущие filled_cap как базу для следующего дня."""
    cfg = get_schedule()
    if not cfg.get("enabled"):
        return

    import pytz
    from app.services.sheets import list_sheets, _save_today_fd

    msk   = pytz.timezone("Europe/Moscow")
    today = datetime.now(msk).strftime("%Y-%m-%d")
    log.info(f"[scheduler] 23:55 snapshot for {today}")

    try:
        cfg        = get_schedule()
        sheet_name = cfg["sheet_name"]
        sheets     = list_sheets() if sheet_name.lower() == "all" else [sheet_name]

        tomorrow = (datetime.now(msk) + timedelta(days=1)).strftime("%Y-%m-%d")
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