"""
Ritual service — background jobs for the Ritual calendar + cycle system.

Jobs:
  run_calendar_reminders()   — every 30 minutes
                               fires upcoming event notifications (24hr window)
                               fires period prediction (2-day warning)

  run_holiday_vibe_engine()  — daily midnight SLT
                               checks today's date against holidays config
                               fires notification + vibe for all active players

  run_cycle_prediction_update() — daily midnight SLT
                                  recalculates avg_cycle_length + next predicted start
                                  for all players with 2+ completed cycles

  run_pregnancy_progression() — daily midnight SLT
                                checks all active pregnancy occurrences
                                advances trimester at day 14 and 28
                                resolves at day 42, auto-adds new_parent
"""

from datetime import datetime, date, timedelta, timezone

from app.config import get_config
from app.database import is_postgres
from app.services.notifications import push_notification


# ── Calendar Reminders ────────────────────────────────────────────────────────

async def run_calendar_reminders(db=None):
    """
    Every 30 min: fire notifications for events happening within 24 hours.
    Also checks for period predictions within 2 days.
    """
    if db is None:
        return

    cfg = get_config()
    window_hours = cfg.get("calendar", {}).get("reminder_window_hours", 24)

    today = date.today()
    window_end = today + timedelta(hours=window_hours)
    today_str      = today.isoformat()
    window_end_str = window_end.isoformat()

    # ── Event reminders ──
    if is_postgres():
        rows = await db.fetch(
            """SELECT ce.player_id, ce.title, ce.event_date_slt, ce.event_type
               FROM calendar_events ce
               WHERE ce.event_date_slt >= $1
                 AND ce.event_date_slt <= $2
               ORDER BY ce.event_date_slt ASC""",
            today_str, window_end_str)
    else:
        async with db.execute(
            """SELECT player_id, title, event_date_slt, event_type
               FROM calendar_events
               WHERE event_date_slt >= ?
                 AND event_date_slt <= ?
               ORDER BY event_date_slt ASC""",
            (today_str, window_end_str)
        ) as cur:
            rows = await cur.fetchall()

    for row in rows:
        event_date = row["event_date_slt"]
        title      = row["title"]
        is_today   = event_date == today_str

        title_str = f"{title} is today! 📅" if is_today else f"{title} is tomorrow! 📅"
        await push_notification(
            player_id=row["player_id"],
            app_source="ritual",
            title=title_str,
            body="",
            priority="normal",
            db=db,
        )

    # ── Period prediction warning (2 days out) ──
    warn_date = today + timedelta(days=2)
    warn_str  = warn_date.isoformat()

    if is_postgres():
        cycle_rows = await db.fetch(
            """SELECT player_id, next_predicted_start
               FROM cycle_log
               WHERE next_predicted_start = $1""",
            warn_str)
    else:
        async with db.execute(
            """SELECT player_id, next_predicted_start
               FROM cycle_log
               WHERE next_predicted_start = ?""",
            (warn_str,)
        ) as cur:
            cycle_rows = await cur.fetchall()

    for row in cycle_rows:
        await push_notification(
            player_id=row["player_id"],
            app_source="ritual",
            title="Period predicted in 2 days 🌙",
            body="Based on your cycle history.",
            priority="normal",
            db=db,
        )


# ── Holiday Vibe Engine ───────────────────────────────────────────────────────

async def run_holiday_vibe_engine(db=None):
    """
    Daily midnight: check today's date against holidays config.
    Fire notification to all active players if it's a holiday.
    """
    if db is None:
        return

    cfg      = get_config()
    holidays = cfg.get("holidays", {})
    today    = date.today()
    key      = today.strftime("%m-%d")

    if key not in holidays:
        return

    holiday = holidays[key]
    name    = holiday.get("name", "Holiday")
    emoji   = holiday.get("emoji", "🎉")

    # Get all non-banned players
    if is_postgres():
        players = await db.fetch(
            "SELECT id FROM players WHERE is_banned = 0")
    else:
        async with db.execute(
            "SELECT id FROM players WHERE is_banned = 0"
        ) as cur:
            players = await cur.fetchall()

    for p in players:
        await push_notification(
            player_id=p["id"],
            app_source="ritual",
            title=f"It's {name} today {emoji}",
            body="",
            priority="low",
            db=db,
        )

        # Apply a mild positive vibe for the occasion
        vibe_key = f"holiday_{key.replace('-','_')}"
        if is_postgres():
            await db.execute(
                """INSERT INTO vibes (player_id, vibe_key, is_negative)
                   VALUES ($1, $2, 0)
                   ON CONFLICT (player_id, vibe_key) DO NOTHING""",
                p["id"], vibe_key)
        else:
            await db.execute(
                """INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative)
                   VALUES (?, ?, 0)""",
                (p["id"], vibe_key))

    if not is_postgres():
        await db.commit()


# ── Cycle Prediction Update ───────────────────────────────────────────────────

async def run_cycle_prediction_update(db=None):
    """
    Daily midnight: recalculate avg_cycle_length and next_predicted_start
    for all players with 2+ completed cycles.
    """
    if db is None:
        return

    # Get all distinct player IDs with cycle data
    if is_postgres():
        player_ids = await db.fetch(
            "SELECT DISTINCT player_id FROM cycle_log WHERE cycle_length_days IS NOT NULL")
    else:
        async with db.execute(
            "SELECT DISTINCT player_id FROM cycle_log WHERE cycle_length_days IS NOT NULL"
        ) as cur:
            player_ids = await cur.fetchall()

    for row in player_ids:
        pid = row["player_id"]
        await _update_player_prediction(pid, db)


async def _update_player_prediction(player_id: int, db):
    """Recalculate and store prediction for one player."""
    if is_postgres():
        cycles = await db.fetch(
            """SELECT cycle_start_slt, period_duration_days, cycle_length_days
               FROM cycle_log
               WHERE player_id = $1
                 AND cycle_length_days IS NOT NULL
                 AND is_manual_override = 0
               ORDER BY cycle_start_slt DESC""",
            player_id)
    else:
        async with db.execute(
            """SELECT cycle_start_slt, period_duration_days, cycle_length_days
               FROM cycle_log
               WHERE player_id = ?
                 AND cycle_length_days IS NOT NULL
                 AND is_manual_override = 0
               ORDER BY cycle_start_slt DESC""",
            (player_id,)
        ) as cur:
            cycles = await cur.fetchall()

    if len(cycles) < 2:
        return

    lengths    = [c["cycle_length_days"] for c in cycles if c["cycle_length_days"]]
    avg_length = sum(lengths) / len(lengths)

    last_start_str = cycles[0]["cycle_start_slt"]
    try:
        last_start = date.fromisoformat(last_start_str[:10])
    except Exception:
        return

    next_start     = last_start + timedelta(days=round(avg_length))
    next_start_str = next_start.isoformat()

    if is_postgres():
        await db.execute(
            """UPDATE cycle_log
               SET avg_cycle_length = $1, next_predicted_start = $2
               WHERE player_id = $3
                 AND cycle_start_slt = $4""",
            avg_length, next_start_str, player_id, last_start_str)
    else:
        await db.execute(
            """UPDATE cycle_log
               SET avg_cycle_length = ?, next_predicted_start = ?
               WHERE player_id = ?
                 AND cycle_start_slt = ?""",
            (avg_length, next_start_str, player_id, last_start_str))
        await db.commit()


# ── Pregnancy Progression ─────────────────────────────────────────────────────

# ── Pregnancy Progression ─────────────────────────────────────────────────────

def _calc_pregnancy_dates(started_at_str: str, metadata: dict) -> tuple[date, date, date, date]:
    """
    Returns (conception_date, t2_start, t3_start, due_date) based on metadata.
    pregnancy_length is in weeks (stored as string e.g. '40').
    Falls back to started_at + 40 weeks if no date info available.
    """
    import json

    length_weeks = int(metadata.get("pregnancy_length") or 40)
    length_days  = length_weeks * 7

    # Resolve conception/start date
    conception: date | None = None

    lmp_str = metadata.get("lmp_date")
    due_str = metadata.get("due_date")

    if lmp_str:
        try:
            conception = date.fromisoformat(lmp_str[:10])
        except Exception:
            pass

    if conception is None and due_str:
        try:
            due = date.fromisoformat(due_str[:10])
            conception = due - timedelta(days=length_days)
        except Exception:
            pass

    if conception is None:
        try:
            conception = date.fromisoformat(started_at_str[:10])
        except Exception:
            conception = date.today()

    due_date = conception + timedelta(days=length_days)
    t2_start = conception + timedelta(days=round(length_days / 3))
    t3_start = conception + timedelta(days=round(2 * length_days / 3))

    return conception, t2_start, t3_start, due_date


async def run_pregnancy_progression(db=None):
    """
    Daily midnight: advance pregnancy trimesters based on actual dates from metadata.
    Trimester boundaries are calculated dynamically from pregnancy_length and LMP/due date.
    Resolves at due date and auto-adds new_parent.
    Applies/removes fatigue and nesting vibes per player opt-in.
    """
    if db is None:
        return

    import json
    today = date.today()

    if is_postgres():
        rows = await db.fetch(
            """SELECT id, player_id, started_at, sub_stage, metadata
               FROM player_occurrences
               WHERE occurrence_key = 'pregnancy' AND is_resolved = 0""")
    else:
        async with db.execute(
            """SELECT id, player_id, started_at, sub_stage, metadata
               FROM player_occurrences
               WHERE occurrence_key = 'pregnancy' AND is_resolved = 0"""
        ) as cur:
            rows = await cur.fetchall()

    for row in rows:
        occ_id    = row["id"]
        player_id = row["player_id"]
        current_stage = row["sub_stage"] or "trimester_1"

        try:
            meta = json.loads(row["metadata"] or "{}")
        except Exception:
            meta = {}

        try:
            conception, t2_start, t3_start, due_date = _calc_pregnancy_dates(
                row["started_at"], meta)
        except Exception:
            continue

        # ── Resolve at due date ──────────────────────────────────────────────
        if today >= due_date:
            if is_postgres():
                await db.execute(
                    "UPDATE player_occurrences SET is_resolved = 1, ends_at = $1 WHERE id = $2",
                    today.isoformat(), occ_id)
                await db.execute(
                    """INSERT INTO player_occurrences (player_id, occurrence_key, sub_stage)
                       VALUES ($1, 'new_parent', 'active')
                       ON CONFLICT DO NOTHING""",
                    player_id)
            else:
                await db.execute(
                    "UPDATE player_occurrences SET is_resolved = 1, ends_at = ? WHERE id = ?",
                    (today.isoformat(), occ_id))
                await db.execute(
                    """INSERT OR IGNORE INTO player_occurrences (player_id, occurrence_key, sub_stage)
                       VALUES (?, 'new_parent', 'active')""",
                    (player_id,))

            await push_notification(
                player_id=player_id,
                app_source="canvas",
                title="Pregnancy complete 🌟",
                body="A new chapter is beginning.",
                priority="normal",
                db=db,
            )
            continue

        # ── Advance trimester ────────────────────────────────────────────────
        new_stage = current_stage
        if today >= t3_start:
            new_stage = "trimester_3"
        elif today >= t2_start:
            new_stage = "trimester_2"
        else:
            new_stage = "trimester_1"

        if new_stage != current_stage:
            if is_postgres():
                await db.execute(
                    "UPDATE player_occurrences SET sub_stage = $1 WHERE id = $2",
                    new_stage, occ_id)
            else:
                await db.execute(
                    "UPDATE player_occurrences SET sub_stage = ? WHERE id = ?",
                    (new_stage, occ_id))

            labels = {
                "trimester_2": ("Entering Second Trimester 🤰", "Your pregnancy is progressing."),
                "trimester_3": ("Entering Third Trimester 🤰", "Almost there."),
            }
            if new_stage in labels:
                title, body = labels[new_stage]
                await push_notification(
                    player_id=player_id,
                    app_source="canvas",
                    title=title,
                    body=body,
                    priority="normal",
                    db=db,
                )

        # ── Vibe management ──────────────────────────────────────────────────
        # vibes dict in metadata stores per-vibe opt-in: {"morning_sickness": true, ...}
        vibe_prefs = meta.get("vibes", {})

        # Vibes that auto-apply or randomly fire per trimester
        # Only apply if player opted in (default True if key missing — opt-in by default)
        T1_AUTO = ["so_tired"]       # conditional auto-vibes we can apply directly
        T2_AUTO = []
        T3_AUTO = ["nesting_hard", "almost_there"]

        # Remove vibes from other trimesters when stage changes
        ALL_PREG_VIBES = [
            "morning_sickness", "pregnancy_glowing", "so_tired", "telling_people",
            "nesting", "uncomfortable", "feeling_movements",
            "nesting_hard", "ready_now_please", "almost_there",
        ]

        STAGE_VIBES = {
            "trimester_1": ["morning_sickness", "pregnancy_glowing", "so_tired", "telling_people"],
            "trimester_2": ["nesting", "uncomfortable", "feeling_movements"],
            "trimester_3": ["nesting_hard", "ready_now_please", "almost_there"],
        }

        # Clear vibes from stages we're no longer in
        stale_vibes = [v for v in ALL_PREG_VIBES if v not in STAGE_VIBES.get(new_stage, [])]
        for vk in stale_vibes:
            if is_postgres():
                await db.execute(
                    "DELETE FROM vibes WHERE player_id = $1 AND vibe_key = $2", player_id, vk)
            else:
                await db.execute(
                    "DELETE FROM vibes WHERE player_id = ? AND vibe_key = ?", (player_id, vk))

        # Apply nesting_hard in T3 if opted in
        if new_stage == "trimester_3" and vibe_prefs.get("nesting_hard", True):
            await _do_upsert_vibe(db, player_id, "nesting_hard", 0)

        # almost_there fires in final days of T3
        if new_stage == "trimester_3" and vibe_prefs.get("almost_there", True):
            total_days = (pregData_length := meta.get("pregnancy_length", 40)) and int(pregData_length) * 7
            days_in_t3 = (today - t3_start).days
            if days_in_t3 >= (int(meta.get("pregnancy_length", 40)) * 7 // 3) - 2:
                await _do_upsert_vibe(db, player_id, "almost_there", 0)

    if not is_postgres():
        await db.commit()


# ── Period Vibe Engine ────────────────────────────────────────────────────────

async def run_period_vibe_engine(db=None):
    """
    Daily midnight: for players in active period window, roll random vibes.
    Fire post-cycle vibes on day 1 and day 3 after period ends.
    """
    if db is None:
        return

    import random
    today     = date.today()
    today_str = today.isoformat()

    if is_postgres():
        rows = await db.fetch(
            """SELECT po.player_id, po.started_at, po.ends_at, po.sub_stage
               FROM player_occurrences po
               WHERE po.occurrence_key = 'period' AND po.is_resolved = 0""")
    else:
        async with db.execute(
            """SELECT player_id, started_at, ends_at, sub_stage
               FROM player_occurrences
               WHERE occurrence_key = 'period' AND is_resolved = 0"""
        ) as cur:
            rows = await cur.fetchall()

    for row in rows:
        player_id = row["player_id"]
        ends_at   = row["ends_at"]

        # Active period window vibes
        if ends_at and today_str <= ends_at:
            # 50% chance: Irritable
            if random.random() < 0.5:
                _upsert_vibe(db, player_id, "period_irritable", 1)
            # 30% chance: Craving
            if random.random() < 0.3:
                _upsert_vibe(db, player_id, "period_craving", 0)
        elif ends_at:
            # Post-period window
            try:
                end_date = date.fromisoformat(ends_at[:10])
                days_after = (today - end_date).days

                if days_after == 1:
                    _upsert_vibe(db, player_id, "actually_invincible", 0)
                    await push_notification(
                        player_id=player_id,
                        app_source="canvas",
                        title="Actually Invincible 💪",
                        body="All decay -10% for 24 hrs.",
                        priority="low",
                        db=db,
                    )
                    # Resolve period occurrence
                    if is_postgres():
                        await db.execute(
                            """UPDATE player_occurrences
                               SET is_resolved = 1 WHERE player_id = $1
                               AND occurrence_key = 'period' AND is_resolved = 0""",
                            player_id)
                    else:
                        await db.execute(
                            """UPDATE player_occurrences
                               SET is_resolved = 1 WHERE player_id = ?
                               AND occurrence_key = 'period' AND is_resolved = 0""",
                            (player_id,))

                elif days_after == 3:
                    _upsert_vibe(db, player_id, "post_cycle_glow", 0)
                    await push_notification(
                        player_id=player_id,
                        app_source="canvas",
                        title="Glowing ✨",
                        body="Purpose +10, Social gains +15% for 48 hrs.",
                        priority="low",
                        db=db,
                    )
            except Exception:
                pass

    if not is_postgres():
        await db.commit()


def _upsert_vibe(db, player_id: int, vibe_key: str, is_negative: int):
    """Fire-and-forget vibe upsert — called synchronously inside async context."""
    import asyncio
    asyncio.ensure_future(_do_upsert_vibe(db, player_id, vibe_key, is_negative))


async def _do_upsert_vibe(db, player_id: int, vibe_key: str, is_negative: int):
    if is_postgres():
        await db.execute(
            """INSERT INTO vibes (player_id, vibe_key, is_negative)
               VALUES ($1, $2, $3)
               ON CONFLICT (player_id, vibe_key) DO NOTHING""",
            player_id, vibe_key, is_negative)
    else:
        await db.execute(
            """INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative)
               VALUES (?, ?, ?)""",
            (player_id, vibe_key, is_negative))
        await db.commit()


# ── Bedtime Reminders ─────────────────────────────────────────────────────────

async def run_bedtime_reminders():
    """
    Every 5 min: check if any player's bedtime_slt matches current SLT time.
    Fires a notification if within a 5-minute window of their set bedtime.
    Opens its own DB connection like decay.py.
    """
    from app.database import get_db_url, get_db_path

    slt_now = datetime.now(timezone.utc) - timedelta(hours=7)
    current_h = slt_now.hour
    current_m = slt_now.minute
    current_total = current_h * 60 + current_m

    if is_postgres():
        import asyncpg
        url = get_db_url()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch(
                """SELECT player_id, bedtime_slt FROM player_settings
                   WHERE bedtime_slt IS NOT NULL AND is_muted = 0""")
            for row in rows:
                bedtime = row["bedtime_slt"]
                if not bedtime:
                    continue
                try:
                    bh, bm = int(bedtime[:2]), int(bedtime[3:5])
                except Exception:
                    continue
                bedtime_total = bh * 60 + bm
                diff = abs(current_total - bedtime_total)
                diff = min(diff, 1440 - diff)
                if diff <= 4:
                    await conn.execute(
                        """INSERT INTO notifications (player_id, app_source, title, body, priority)
                           VALUES ($1, 'recharge', 'Bedtime 🌙', 'Your bedtime reminder — time to rest.', 'normal')""",
                        row["player_id"])
        finally:
            await conn.close()
    else:
        import aiosqlite
        db_path = get_db_path()
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT player_id, bedtime_slt FROM player_settings
                   WHERE bedtime_slt IS NOT NULL AND is_muted = 0"""
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                bedtime = row["bedtime_slt"]
                if not bedtime:
                    continue
                try:
                    bh, bm = int(bedtime[:2]), int(bedtime[3:5])
                except Exception:
                    continue
                bedtime_total = bh * 60 + bm
                diff = abs(current_total - bedtime_total)
                diff = min(diff, 1440 - diff)
                if diff <= 4:
                    await db.execute(
                        """INSERT INTO notifications (player_id, app_source, title, body, priority)
                           VALUES (?, 'recharge', 'Bedtime 🌙', 'Your bedtime reminder — time to rest.', 'normal')""",
                        (row["player_id"],))
            await db.commit()


# ── Phase Vibe Engine ─────────────────────────────────────────────────────────

async def run_phase_vibe_engine(db=None):
    """
    Daily midnight: detect current cycle phase for all active cycle-tracking
    players and apply/remove the correct phase vibes.
    Also fires fertile_window vibe if TTC and in ovulatory phase.
    Also fires ttc_stress vibe if TTC > 3 months.
    """
    if db is None:
        return

    today = date.today()

    # Phase vibe mapping
    PHASE_VIBE_MAP = {
        "menstrual":  None,            # period vibes handled by existing period_active
        "follicular": "phase_follicular",
        "ovulatory":  "phase_ovulatory",
        "luteal":     "phase_luteal",
        "pms":        "phase_pms",
    }
    ALL_PHASE_VIBES = set(PHASE_VIBE_MAP.values()) - {None}
    ALL_PHASE_VIBES.update({"fertile_window", "ttc_hopeful", "ttc_stress"})

    if is_postgres():
        players = await db.fetch(
            """SELECT pp.player_id, pp.cycle_tracking_mode, pp.default_cycle_length,
                      pp.avg_period_duration
               FROM player_profiles pp
               WHERE pp.cycle_setup_completed = 1
                 AND pp.cycle_tracking_mode NOT IN ('not_applicable', 'infertile',
                                                    'ttc_surrogate_intended')""")
    else:
        async with db.execute(
            """SELECT pp.player_id, pp.cycle_tracking_mode, pp.default_cycle_length,
                      pp.avg_period_duration
               FROM player_profiles pp
               WHERE pp.cycle_setup_completed = 1
                 AND pp.cycle_tracking_mode NOT IN ('not_applicable', 'infertile',
                                                    'ttc_surrogate_intended')"""
        ) as cur:
            players = await cur.fetchall()

    for p in players:
        pid        = p["player_id"]
        mode       = p["cycle_tracking_mode"] or "period_only"
        cycle_len  = int(p["default_cycle_length"] or 28)
        period_dur = int(p["avg_period_duration"] or 5)

        # Get latest cycle log
        if is_postgres():
            latest = await db.fetchrow(
                """SELECT * FROM cycle_log WHERE player_id=$1
                   ORDER BY cycle_start_slt DESC LIMIT 1""", pid)
        else:
            async with db.execute(
                """SELECT * FROM cycle_log WHERE player_id=?
                   ORDER BY cycle_start_slt DESC LIMIT 1""", (pid,)
            ) as cur:
                latest = await cur.fetchone()

        if not latest:
            continue

        try:
            cycle_start = date.fromisoformat(latest["cycle_start_slt"][:10])
            used_len    = latest["cycle_length_days"] or cycle_len
            used_dur    = latest["period_duration_days"] or period_dur
        except Exception:
            continue

        days_in      = (today - cycle_start).days
        ov_day       = used_len - 14
        fert_start   = ov_day - 4
        fert_end     = ov_day + 1
        pms_start    = used_len - 5

        if days_in < 0:
            continue
        if days_in < used_dur:
            phase = "menstrual"
        elif days_in < fert_start:
            phase = "follicular"
        elif days_in <= fert_end:
            phase = "ovulatory"
        elif days_in >= pms_start:
            phase = "pms"
        else:
            phase = "luteal"

        # Clear all phase vibes first
        for vk in ALL_PHASE_VIBES:
            if is_postgres():
                await db.execute(
                    "DELETE FROM vibes WHERE player_id=$1 AND vibe_key=$2", pid, vk)
            else:
                await db.execute(
                    "DELETE FROM vibes WHERE player_id=? AND vibe_key=?", (pid, vk))

        # Apply current phase vibe
        vibe = PHASE_VIBE_MAP.get(phase)
        if vibe:
            if is_postgres():
                await db.execute(
                    """INSERT INTO vibes (player_id, vibe_key, is_negative)
                       VALUES ($1,$2,0) ON CONFLICT (player_id,vibe_key) DO NOTHING""",
                    pid, vibe)
            else:
                await db.execute(
                    """INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative)
                       VALUES (?,?,0)""", (pid, vibe, 0))

        # TTC-specific vibes
        is_ttc = mode in ("ttc_traditional", "ttc_ivf", "ttc_surrogate_carrier")
        if is_ttc:
            # ttc_hopeful always on while TTC
            if is_postgres():
                await db.execute(
                    """INSERT INTO vibes (player_id, vibe_key, is_negative)
                       VALUES ($1,'ttc_hopeful',0)
                       ON CONFLICT (player_id,vibe_key) DO NOTHING""", pid)
            else:
                await db.execute(
                    """INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative)
                       VALUES (?,'ttc_hopeful',0)""", (pid,))

            # fertile_window vibe in ovulatory phase
            if phase == "ovulatory" and mode == "ttc_traditional":
                if is_postgres():
                    await db.execute(
                        """INSERT INTO vibes (player_id, vibe_key, is_negative)
                           VALUES ($1,'fertile_window',0)
                           ON CONFLICT (player_id,vibe_key) DO NOTHING""", pid)
                else:
                    await db.execute(
                        """INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative)
                           VALUES (?,'fertile_window',0)""", (pid,))

            # ttc_stress if trying > 3 months (opt-in check via TTC occurrence metadata)
            if is_postgres():
                ttc_occ = await db.fetchrow(
                    """SELECT metadata, started_at FROM player_occurrences
                       WHERE player_id=$1 AND occurrence_key LIKE 'ttc_%' AND is_resolved=0
                       ORDER BY started_at DESC LIMIT 1""", pid)
            else:
                async with db.execute(
                    """SELECT metadata, started_at FROM player_occurrences
                       WHERE player_id=? AND occurrence_key LIKE 'ttc_%' AND is_resolved=0
                       ORDER BY started_at DESC LIMIT 1""", (pid,)
                ) as cur:
                    ttc_occ = await cur.fetchone()

            if ttc_occ:
                import json as _j
                try:
                    meta = _j.loads(ttc_occ["metadata"] or "{}")
                    dur_months = int(meta.get("ttc_duration_months") or 0)
                    # Also count months since occurrence started
                    occ_start = date.fromisoformat(ttc_occ["started_at"][:10])
                    months_since = (today - occ_start).days // 30
                    total_months = dur_months + months_since
                    if total_months >= 3:
                        if is_postgres():
                            await db.execute(
                                """INSERT INTO vibes (player_id, vibe_key, is_negative)
                                   VALUES ($1,'ttc_stress',1)
                                   ON CONFLICT (player_id,vibe_key) DO NOTHING""", pid)
                        else:
                            await db.execute(
                                """INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative)
                                   VALUES (?,'ttc_stress',1)""", (pid,))
                except Exception:
                    pass

    if not is_postgres():
        await db.commit()


# ── TTC Daily Conception Check Runner ────────────────────────────────────────

async def run_ttc_conception_checks(db=None):
    """
    Daily: run conception probability check for all TTC traditional players
    whose fertile window just closed. Delegates to the cycle router logic.
    """
    if db is None:
        return

    today = date.today()

    if is_postgres():
        players = await db.fetch(
            """SELECT pp.player_id FROM player_profiles pp
               WHERE pp.cycle_tracking_mode = 'ttc_traditional'
                 AND pp.birth_control_active = 0
                 AND pp.infertility_flag = 0""")
    else:
        async with db.execute(
            """SELECT pp.player_id FROM player_profiles pp
               WHERE pp.cycle_tracking_mode = 'ttc_traditional'
                 AND pp.birth_control_active = 0
                 AND pp.infertility_flag = 0"""
        ) as cur:
            players = await cur.fetchall()

    for p in players:
        pid = p["player_id"]

        if is_postgres():
            latest = await db.fetchrow(
                """SELECT * FROM cycle_log WHERE player_id=$1
                   ORDER BY cycle_start_slt DESC LIMIT 1""", pid)
            profile = await db.fetchrow(
                "SELECT default_cycle_length FROM player_profiles WHERE player_id=$1", pid)
        else:
            async with db.execute(
                """SELECT * FROM cycle_log WHERE player_id=?
                   ORDER BY cycle_start_slt DESC LIMIT 1""", (pid,)
            ) as cur:
                latest = await cur.fetchone()
            async with db.execute(
                "SELECT default_cycle_length FROM player_profiles WHERE player_id=?", (pid,)
            ) as cur:
                profile = await cur.fetchone()

        if not latest or not profile:
            continue

        try:
            import random as _r
            cycle_start  = date.fromisoformat(latest["cycle_start_slt"][:10])
            cycle_len    = latest["cycle_length_days"] or int(profile["default_cycle_length"] or 28)
            ovulation_dt = cycle_start + timedelta(days=cycle_len - 14)
            fert_start   = ovulation_dt - timedelta(days=4)
            fert_end     = ovulation_dt + timedelta(days=1)
        except Exception:
            continue

        # Only run day after window closes
        if today != fert_end + timedelta(days=1):
            continue

        # Check already done
        if is_postgres():
            already = await db.fetchrow(
                "SELECT id FROM ttc_conception_checks WHERE player_id=$1 AND cycle_log_id=$2",
                pid, latest["id"])
        else:
            async with db.execute(
                "SELECT id FROM ttc_conception_checks WHERE player_id=? AND cycle_log_id=?",
                (pid, latest["id"])
            ) as cur:
                already = await cur.fetchone()
        if already:
            continue

        # Count intimacy
        if is_postgres():
            ic = await db.fetchval(
                """SELECT COUNT(*) FROM intimacy_log
                   WHERE player_id=$1 AND logged_date>=$2 AND logged_date<=$3""",
                pid, fert_start.isoformat(), fert_end.isoformat())
            pc = await db.fetchval(
                """SELECT COUNT(*) FROM intimacy_log
                   WHERE player_id=$1 AND logged_date=$2""",
                pid, ovulation_dt.isoformat())
        else:
            async with db.execute(
                """SELECT COUNT(*) as cnt FROM intimacy_log
                   WHERE player_id=? AND logged_date>=? AND logged_date<=?""",
                (pid, fert_start.isoformat(), fert_end.isoformat())
            ) as cur:
                r = await cur.fetchone(); ic = r["cnt"] if r else 0
            async with db.execute(
                """SELECT COUNT(*) as cnt FROM intimacy_log
                   WHERE player_id=? AND logged_date=?""",
                (pid, ovulation_dt.isoformat())
            ) as cur:
                r = await cur.fetchone(); pc = r["cnt"] if r else 0

        peak_hit  = pc > 0
        prob      = min(0.30, (ic * 0.08) + (0.12 if peak_hit else 0))
        conceived = _r.random() < prob
        result    = "conceived" if conceived else "not_conceived"

        if is_postgres():
            await db.execute(
                """INSERT INTO ttc_conception_checks
                   (player_id, cycle_log_id, intimacy_count, peak_day_hit, result)
                   VALUES ($1,$2,$3,$4,$5)""",
                pid, latest["id"], ic, int(peak_hit), result)
        else:
            await db.execute(
                """INSERT INTO ttc_conception_checks
                   (player_id, cycle_log_id, intimacy_count, peak_day_hit, result)
                   VALUES (?,?,?,?,?)""",
                (pid, latest["id"], ic, int(peak_hit), result))

        if conceived:
            await push_notification(
                player_id=pid, app_source="ritual",
                title="Something might be different this cycle… 🌸",
                body="Tap to confirm your pregnancy.",
                priority="normal", db=db)

    if not is_postgres():
        await db.commit()


# ── IVF Stage Auto-Progression ────────────────────────────────────────────────

async def run_ivf_stage_progression(db=None):
    """
    Daily: for all IVF players with auto_progress enabled, recalculate the
    correct stage from their stored dates and update sub_stage if it changed.
    Fires a notification when the stage advances.
    """
    if db is None:
        return

    today = date.today()

    if is_postgres():
        occs = await db.fetch(
            """SELECT id, player_id, sub_stage, metadata FROM player_occurrences
               WHERE occurrence_key = 'ttc_ivf' AND is_resolved = 0""")
    else:
        async with db.execute(
            """SELECT id, player_id, sub_stage, metadata FROM player_occurrences
               WHERE occurrence_key = 'ttc_ivf' AND is_resolved = 0"""
        ) as cur:
            occs = await cur.fetchall()

    for occ in occs:
        import json as _j
        try:
            meta = _j.loads(occ["metadata"] or "{}")
        except Exception:
            continue

        if not meta.get("ivf_auto_progress"):
            continue

        # Calculate correct stage from dates
        def parse(key):
            val = meta.get(key)
            if not val:
                return None
            try:
                return date.fromisoformat(val[:10])
            except Exception:
                return None

        stim      = parse("stimulation_start")
        retrieval = parse("retrieval_date")
        transfer  = parse("transfer_date")
        beta      = parse("beta_date")

        if beta and today >= beta:
            new_stage = "beta_wait" if today == beta else "successful"
        elif transfer:
            if today == transfer:
                new_stage = "transfer"
            elif today > transfer:
                new_stage = "transfer_wait"
            elif retrieval and today == retrieval:
                new_stage = "retrieval"
            elif retrieval and today > retrieval:
                new_stage = "fertilization_wait"
            elif stim and today >= stim:
                new_stage = "stimulation"
            else:
                new_stage = "preparing"
        elif retrieval:
            if today == retrieval:
                new_stage = "retrieval"
            elif today > retrieval:
                new_stage = "fertilization_wait"
            elif stim and today >= stim:
                new_stage = "stimulation"
            else:
                new_stage = "preparing"
        elif stim and today >= stim:
            new_stage = "stimulation"
        else:
            new_stage = "preparing"

        current_stage = occ["sub_stage"] or "preparing"
        if new_stage == current_stage:
            continue

        # Stage has advanced — update it
        if is_postgres():
            await db.execute(
                """UPDATE player_occurrences SET sub_stage = $1 WHERE id = $2""",
                new_stage, occ["id"])
        else:
            await db.execute(
                """UPDATE player_occurrences SET sub_stage = ? WHERE id = ?""",
                (new_stage, occ["id"]))

        # Notify the player
        stage_labels = {
            "stimulation":       "Stimulation phase has started 💉",
            "retrieval":         "It's retrieval day 🌱",
            "fertilization_wait": "Waiting on your fertilization news ⏳",
            "transfer":          "It's transfer day ✨",
            "transfer_wait":     "The two week wait has started 🕯️",
            "beta_wait":         "It's beta day 🩸",
            "successful":        "Your IVF journey has reached the next chapter 🌸",
        }
        title = stage_labels.get(new_stage, f"IVF stage updated: {new_stage}")

        await push_notification(
            player_id=occ["player_id"],
            app_source="ritual",
            title=title,
            body="Open Ritual to see your updated stage card.",
            priority="normal",
            db=db)

    if not is_postgres():
        await db.commit()
