"""
Планировщик авто-синка капов в Google Sheets.
Запускается из main.py при старте Flask.

pip install apscheduler pytz
"""
import os
import json
import logging
from datetime import datetime, timedelta

log = logging.getLogger("scheduler")

_scheduler   = None


def _load_tracking(tracking_file):
    """Всегда читает свежую версию файла."""
    try:
        return json.loads(open(tracking_file).read())
    except Exception:
        return {}


def _patch_tracking(tracking_file, offer_id, **fields):
    """
    Атомарно обновляет только указанные поля оффера.
    Перечитывает файл перед записью чтобы не затереть чужие изменения.
    """
    tracking = _load_tracking(tracking_file)
    if offer_id not in tracking:
        return  # оффер удалён — не восстанавливаем
    for k, v in fields.items():
        tracking[offer_id][k] = v
    open(tracking_file, "w").write(json.dumps(tracking, ensure_ascii=False, indent=2))


def _do_tracking_fd():
    """Обновляет FD для всех офферов из трекинга. Запускается каждые 10 минут."""
    import pytz

    tracking_file = os.path.join(os.path.dirname(__file__), "../../data/offer_tracking.json")
    fd_cache_file = os.path.join(os.path.dirname(__file__), "../../data/tracking_fd_cache.json")

    # Читаем снапшот трекинга на момент старта — только для итерации
    tracking_snapshot = _load_tracking(tracking_file)
    if not tracking_snapshot:
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

    # ── Шаг 1: Один батчевый запрос на все офферы ───────────────────────────
    # Группируем офферы по дате старта — каждая уникальная дата = один запрос
    from collections import defaultdict

    # Собираем все уникальные ID (основные + из групп)
    # offer_id → start_date
    all_ids_by_date = defaultdict(set)  # start_date → set of offer_ids
    id_to_offer     = {}  # offer_id → tracking offer_id (для группировки)

    for offer_id, info in tracking_snapshot.items():
        start_date = info.get("start_date", today)
        all_ids_by_date[start_date].add(str(offer_id))
        id_to_offer[str(offer_id)] = offer_id

        group_ids = info.get("group_ids", "")
        if group_ids:
            for gid in group_ids.replace(",", ":").split(":"):
                gid = gid.strip()
                if gid and gid != str(offer_id):
                    all_ids_by_date[start_date].add(gid)
                    id_to_offer[gid] = offer_id  # будет суммироваться к основному

    # fd_by_id = {binom_offer_id: fd_value}
    fd_by_id  = {}
    fd_key    = None

    for start_date, offer_ids in all_ids_by_date.items():
        # Разбиваем на чанки по 50 — не слишком большой запрос
        ids_list = list(offer_ids)
        chunk_size = 50
        for chunk_start in range(0, len(ids_list), chunk_size):
            chunk = ids_list[chunk_start:chunk_start + chunk_size]
            pairs = [
                ("datePreset",  "custom_time"),
                ("dateFrom",    f"{start_date} 00:00:00"),
                ("dateTo",      f"{today} 23:59:59"),
                ("timezone",    "Europe/Moscow"),
                ("groupings[]", "offer"),
                ("sortColumn",  "clicks"),
                ("sortType",    "desc"),
                ("limit",       "5000"),
                ("offset",      "0"),
            ] + [("ids[]", cid) for cid in campaign_ids]               + [("offerIds[]", oid) for oid in chunk]

            r = binom_get_pairs("/public/api/v1/report/campaign", pairs)
            if not r.ok:
                log.error(f"[tracking] batch request failed: {r.status_code}")
                continue

            raw  = _safe_json(r)
            rows = extract_rows(raw)

            # Определяем ключ FD из первого ответа
            if not fd_key:
                for row in rows:
                    for k in row.keys():
                        if "fd" in k.lower():
                            fd_key = k
                            break
                    if fd_key:
                        break

            for row in rows:
                if str(row.get("level") or "") != "1":
                    continue
                eid  = str(row.get("entity_id") or "").strip()
                rname = str(row.get("name") or "").strip()
                fd   = int(row.get(fd_key) or 0) if fd_key else 0

                # Матчим по entity_id или имени
                matched_id = None
                if eid in chunk:
                    matched_id = eid
                else:
                    # Fallback по имени оффера
                    for oid in chunk:
                        info = tracking_snapshot.get(oid, {})
                        if info.get("name") and info["name"] == rname:
                            matched_id = oid
                            break

                if matched_id:
                    fd_by_id[matched_id] = max(fd_by_id.get(matched_id, 0), fd)

            log.info(f"[tracking] batch start={start_date} chunk={len(chunk)} → {len(fd_by_id)} matches")

    # ── Geo breakdown для офферов с geo_cap ─────────────────────────────────
    geo_cap_offers = {oid: info for oid, info in tracking_snapshot.items() if info.get("geo_cap")}

    if geo_cap_offers:
        geo_breakdown = {}  # offer_id → {geo: fd}
        geo_cap_ids   = list(geo_cap_offers.keys())

        for ci in range(0, len(geo_cap_ids), 50):
            chunk = geo_cap_ids[ci:ci+50]
            pairs_geo = [
                ("datePreset",  "custom_time"),
                ("dateFrom",    f"{min(info.get('start_date', today) for info in geo_cap_offers.values())} 00:00:00"),
                ("dateTo",      f"{today} 23:59:59"),
                ("timezone",    "Europe/Moscow"),
                ("groupings[]", "offer"),
                ("groupings[]", "geoCountry"),
                ("limit",       "10000"),
                ("offset",      "0"),
            ] + [("ids[]", cid) for cid in campaign_ids]               + [("offerIds[]", oid) for oid in chunk]

            r_geo = binom_get_pairs("/public/api/v1/report/campaign", pairs_geo)
            if not r_geo.ok:
                continue

            rows_geo = extract_rows(_safe_json(r_geo))
            current_oid = None
            for row in rows_geo:
                lvl = str(row.get("level") or "")
                if lvl == "1":
                    eid = str(row.get("entity_id") or "").strip()
                    if eid in chunk:
                        current_oid = eid
                    else:
                        current_oid = None
                elif lvl == "2" and current_oid:
                    geo_name = str(row.get("name") or "").strip().upper()
                    if not geo_name:
                        continue
                    fd_val = int(float(row.get(fd_key) or 0)) if fd_key else 0
                    if current_oid not in geo_breakdown:
                        geo_breakdown[current_oid] = {}
                    geo_breakdown[current_oid][geo_name] = fd_val

        # Сохраняем geo_breakdown в кеш
        for oid in geo_cap_offers:
            if oid in geo_breakdown:
                cache.setdefault(oid, {})["geo_breakdown"] = geo_breakdown[oid]

    # Применяем результаты к кешу
    now_str = datetime.now(msk).strftime("%Y-%m-%d %H:%M:%S")
    for offer_id, info in tracking_snapshot.items():
        start_date = info.get("start_date", today)
        group_ids  = info.get("group_ids", "")

        fd_total = fd_by_id.get(str(offer_id), 0)

        # Суммируем группу
        if group_ids:
            for gid in group_ids.replace(",", ":").split(":"):
                gid = gid.strip()
                if gid and gid != str(offer_id):
                    fd_total += fd_by_id.get(gid, 0)

        cache[offer_id] = {
            "fd":         fd_total,
            "start_date": start_date,
            "updated_at": now_str,
        }
        log.info(f"[tracking] offer {offer_id} fd={fd_total}")

    # Чистим кеш от удалённых офферов
    fresh = _load_tracking(tracking_file)
    cache = {k: v for k, v in cache.items() if k in fresh}

    # Подгружаем Binom conversion caps — основной + все ID группы
    # Получаем maxCap из Binom для каждого оффера (только настройки, быстро)
    def _fetch_max_cap(oid):
        """Возвращает (maxCap, currentConversionCap) из Binom."""
        try:
            r = binom_get(f"/public/api/v1/offer/cap/conversion/{oid}")
            if r.ok:
                d = _safe_json(r)
                if isinstance(d, dict) and d.get("maxCap"):
                    return str(oid), (d.get("maxCap"), d.get("currentConversionCap") or 0)
        except Exception:
            pass
        return str(oid), None

    all_cap_ids = set()
    for oid, info in fresh.items():
        all_cap_ids.add(str(oid))
        group_ids = info.get("group_ids", "")
        if group_ids:
            for gid in group_ids.replace(",", ":").split(":"):
                gid = gid.strip()
                if gid:
                    all_cap_ids.add(gid)

    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed
    max_caps = {}  # binom_id → (maxCap, currentConversionCap)
    with ThreadPoolExecutor(max_workers=4) as ex:
        cap_futures = {ex.submit(_fetch_max_cap, oid): oid for oid in all_cap_ids}
        for fut in _as_completed(cap_futures):
            bid, mc = fut.result()
            if mc:
                max_caps[bid] = mc  # (maxCap, current)

    # Для основного оффера и группы
    for oid in fresh:
        if oid not in cache:
            continue
        info      = fresh[oid]
        group_ids = info.get("group_ids", "")

        mc = max_caps.get(str(oid))
        if mc:
            cache[oid]["binom_max_cap"]     = mc[0]
            cache[oid]["binom_current_cap"] = mc[1]

        if group_ids:
            group_caps = {}
            for gid in group_ids.replace(",", ":").split(":"):
                gid = gid.strip()
                if gid and gid != str(oid) and gid in max_caps:
                    group_caps[gid] = {
                        "max":     max_caps[gid][0],
                        "current": max_caps[gid][1],
                    }
            if group_caps:
                cache[oid]["group_binom_caps"] = group_caps

    open(fd_cache_file, "w").write(json.dumps(cache, ensure_ascii=False, indent=2))
    log.info(f"[tracking] FD+cap cache updated for {len(fresh)} offers")

    # ── Шаг 2: Обновляем статусы по весам ротаций ────────────────────────────
    from app.services.binom import _safe_json as _sj
    TRACKED_ROTATIONS = ["121", "117", "118", "120", "124", "127", "61", "133", "134", "135", "137"]
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

        # Перечитываем свежий файл перед обновлением статусов
        fresh = _load_tracking(tracking_file)
        for offer_id, info in list(fresh.items()):
            if info.get("status") in ("no_perform",):
                continue
            w = offer_weights.get(str(offer_id), -1)
            if w == -1:
                continue
            new_status = "stopped" if w == 0 else "active"
            if info.get("status") != new_status:
                # Патчим только этот оффер, не перезаписываем весь файл
                _patch_tracking(tracking_file, offer_id, status=new_status)
                log.info(f"[tracking] offer {offer_id} status → {new_status} (weight={w})")

    except Exception as e:
        log.error(f"[tracking] Weight check error: {e}")

    # ── Шаг 3: Авто-стоп + TG алерты ────────────────────────────────────────
    try:
        from app.services.tg import check_cap_alerts, send_message
        from app.services.binom import _safe_json as _sj2
        from app.services.sheets import _names_match

        alerts         = []
        STOP_ROTATIONS = ["121", "118", "61", "117", "120", "124"]

        # Свежий снапшот для алертов и авто-стопа
        fresh = _load_tracking(tracking_file)

        for offer_id, info in fresh.items():
            max_cap       = info.get("max_cap")
            auto_stop_pct = info.get("auto_stop_pct")
            fd            = cache.get(offer_id, {}).get("fd")
            offer_name    = info.get("name", "")
            offer_status  = info.get("status", "active")

            if not max_cap or fd is None:
                continue

            # Алерты только для активных
            if offer_status not in ("stopped", "no_perform"):
                alerts.append({
                    "sheet_name":   offer_name,
                    "filled_cap":   fd,
                    "max_cap":      max_cap,
                    "sheet":        "Трекинг",
                    "network_name": info.get("partner_name", ""),
                })

            # Авто-стоп
            if not auto_stop_pct:
                continue
            if info.get("auto_stopped"):
                continue
            if offer_status in ("stopped", "no_perform"):
                continue
            if fd < int(auto_stop_pct):
                continue

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
                # Патчим атомарно
                _patch_tracking(
                    tracking_file, offer_id,
                    status="stopped",
                    auto_stopped=datetime.now(msk).strftime("%Y-%m-%d %H:%M:%S"),
                )
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

        # Алерты по GEO капам
        for offer_id, info in fresh.items():
            geo_cap = info.get("geo_cap")
            if not geo_cap:
                continue
            if info.get("status") in ("stopped", "no_perform"):
                continue
            geo_bd = cache.get(offer_id, {}).get("geo_breakdown", {})
            if not geo_bd:
                continue

            threshold = int(geo_cap) * 0.85  # 85% порог
            offer_name = info.get("name", f"#{offer_id}")

            prev_alerts = cache.get(offer_id, {}).get("geo_alerted", {})
            new_alerts  = dict(prev_alerts)
            alerted_this_cycle = []

            for geo_code, geo_fd in geo_bd.items():
                if geo_fd >= threshold:
                    pct = round(geo_fd / int(geo_cap) * 100)
                    prev_pct = prev_alerts.get(geo_code, 0)
                    # Шлём только если новый порог (каждые 5%)
                    bucket = (pct // 5) * 5
                    if bucket > prev_pct:
                        new_alerts[geo_code] = bucket
                        alerted_this_cycle.append((geo_code, geo_fd, pct))

            if alerted_this_cycle:
                lines = [f"⚠️ <b>GEO кап заполняется</b>", f"", f"📋 <b>{offer_name}</b>", f"🎯 Кап на GEO: {geo_cap}", f""]
                for geo_code, geo_fd, pct in alerted_this_cycle:
                    lines.append(f"  🌍 {geo_code}: {geo_fd}/{geo_cap} ({pct}%)")
                try:
                    send_message(chr(10).join(lines))
                    cache.setdefault(offer_id, {})["geo_alerted"] = new_alerts
                except Exception:
                    pass

    except Exception as e:
        log.error(f"[tracking] TG/auto-stop error: {e}", exc_info=True)


def _do_hold_reminders():
    """Еженедельно напоминает партнёрам о невыплаченных холдах."""
    try:
        from app.routes.invoices import send_hold_reminders
        send_hold_reminders()
    except Exception as e:
        log.error(f"[scheduler] Hold reminders error: {e}", exc_info=True)


def init_scheduler(app=None):
    """Вызывать из main.py после создания Flask app."""
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        import pytz

        _scheduler = BackgroundScheduler(timezone=pytz.timezone("Europe/Moscow"))
        _scheduler.start()
        log.info("[scheduler] APScheduler started")

        _scheduler.add_job(
            _do_tracking_fd,
            trigger  = "interval",
            minutes  = 10,
            id       = "tracking_fd",
            name     = "Tracking FD update every 10m",
            replace_existing = True,
        )
        log.info("[scheduler] Tracking FD job started (every 10 min, independent)")

        _scheduler.add_job(
            _do_hold_reminders,
            trigger  = "cron",
            day_of_week = "mon",
            hour     = 10,
            minute   = 0,
            id       = "hold_reminders",
            name     = "Weekly hold reminders",
            replace_existing = True,
        )
        log.info("[scheduler] Hold reminders job started (every Monday 10:00)")

        return _scheduler
    except ImportError:
        log.warning("[scheduler] apscheduler not installed — auto-sync disabled. Run: pip install apscheduler pytz")
        return None
    except Exception as e:
        log.error(f"[scheduler] Init error: {e}")
        return None