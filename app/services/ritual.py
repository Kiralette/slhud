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
        weeks_in = (today - conception).days // 7

        # Fatigue: trimester 1 (weeks 1-13) and trimester 3 (weeks 27+)
        if meta.get("vibe_fatigue", True):
            if new_stage in ("trimester_1", "trimester_3"):
                await _do_upsert_vibe(db, player_id, "pregnancy_fatigue", 1)
            else:
                # Remove fatigue in T2
                if is_postgres():
                    await db.execute(
                        "DELETE FROM vibes WHERE player_id = $1 AND vibe_key = 'pregnancy_fatigue'",
                        player_id)
                else:
                    await db.execute(
                        "DELETE FROM vibes WHERE player_id = ? AND vibe_key = 'pregnancy_fatigue'",
                        (player_id,))

        # Nesting: trimester 3 only
        if meta.get("vibe_nesting", True) and new_stage == "trimester_3":
            await _do_upsert_vibe(db, player_id, "pregnancy_nesting", 0)

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
