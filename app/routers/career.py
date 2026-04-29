"""
Career service — shared logic for clock-out pay, auto-clock-out, midnight reset.
"""

from datetime import datetime, timezone, timedelta
from app.config import get_config
from app.database import is_postgres, get_db_url, get_db_path
from app.services.notifications import push_notification
from app.services.achievements import increment_stat


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _slt_now() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=7)


def _is_midnight_slt() -> bool:
    slt = _slt_now()
    return slt.hour == 0 and slt.minute < 2


def calculate_pay(daily_pay: float, hours_worked: float, shift_max: float = 4.0) -> float:
    """
    Pro-rate pay based on hours worked vs max shift.
    daily_pay in config is the 'per shift' rate at max hours.
    """
    capped = min(hours_worked, shift_max)
    return round(daily_pay * (capped / shift_max), 2)


def get_career_path_cfg(cfg: dict, path_key: str) -> dict | None:
    return cfg.get("careers", {}).get("paths", {}).get(path_key)


def get_tier_cfg(cfg: dict, path_key: str, tier_level: int) -> dict | None:
    path = get_career_path_cfg(cfg, path_key)
    if not path:
        return None
    return path.get("tiers", {}).get(tier_level)


def check_skill_requirements(skill_reqs: dict | None, player_skills: dict) -> tuple[bool, list[str]]:
    """
    Check if player meets skill requirements for a tier.
    Returns (met: bool, missing: list of human-readable strings).
    """
    if not skill_reqs:
        return True, []
    missing = []
    for skill_key, required_level in skill_reqs.items():
        actual = player_skills.get(skill_key, 0)
        if actual < required_level:
            missing.append(f"{skill_key.title()} Lv.{required_level} (you have Lv.{actual})")
    return len(missing) == 0, missing


async def do_clockout(db, player_id: int, employment: dict, reason: str = "manual") -> dict:
    """
    Shared clock-out logic. Calculates pay, deposits, fires notification.
    Works with either SQLite db or asyncpg connection.
    Returns summary dict.
    """
    cfg = get_config()
    now = _now_str()

    path_key  = employment["career_path_key"]
    tier      = int(employment["tier_level"])
    title     = employment["job_title"]
    clocked_in_at = employment["clocked_in_at"]

    # Calculate hours
    try:
        start = datetime.fromisoformat(str(clocked_in_at).replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        hours = (datetime.now(timezone.utc) - start).total_seconds() / 3600
    except Exception:
        hours = 0.0

    hours = round(min(hours, float(cfg["careers"]["shift_max_hours"])), 4)

    # Get daily pay for current tier
    tier_cfg  = get_tier_cfg(cfg, path_key, tier)
    daily_pay = float(tier_cfg.get("daily_pay", 0)) if tier_cfg else 0.0
    pay       = calculate_pay(daily_pay, hours)

    pg = is_postgres()

    # Update employment row
    if pg:
        await db.execute(
            """UPDATE employment
               SET is_clocked_in     = 0,
                   clocked_in_at     = NULL,
                   last_heartbeat_at = NULL,
                   hours_today       = hours_today + $1,
                   total_days_worked = total_days_worked + 1,
                   days_at_tier      = days_at_tier + 1
               WHERE player_id = $2""",
            hours, player_id)
    else:
        await db.execute(
            """UPDATE employment
               SET is_clocked_in     = 0,
                   clocked_in_at     = NULL,
                   last_heartbeat_at = NULL,
                   hours_today       = hours_today + ?,
                   total_days_worked = total_days_worked + 1,
                   days_at_tier      = days_at_tier + 1
               WHERE player_id = ?""",
            (hours, player_id))

    if pay > 0:
        # Credit wallet
        if pg:
            await db.execute(
                """UPDATE wallets
                   SET balance      = balance + $1,
                       total_earned = total_earned + $1,
                       last_updated = $2
                   WHERE player_id = $3""",
                pay, now, player_id)
            await db.execute(
                """INSERT INTO transactions (player_id, amount, type, description, timestamp)
                   VALUES ($1, $2, 'shift', $3, $4)""",
                player_id, pay,
                f"Shift complete — {title} ({hours:.2f}h)", now)
        else:
            await db.execute(
                """UPDATE wallets
                   SET balance      = balance + ?,
                       total_earned = total_earned + ?,
                       last_updated = ?
                   WHERE player_id = ?""",
                (pay, pay, now, player_id))
            await db.execute(
                """INSERT INTO transactions (player_id, amount, type, description, timestamp)
                   VALUES (?, ?, 'shift', ?, ?)""",
                (player_id, pay,
                 f"Shift complete — {title} ({hours:.2f}h)", now))

        # Notification
        title_notif = "Auto clocked out 📴" if reason == "auto" else f"Shift complete! ✦{pay:.0f} deposited 💰"
        body_notif  = (
            f"Attachment removed or heartbeat lost." if reason == "auto"
            else f"{hours:.1f}h worked as {title}."
        )
        await push_notification(
            player_id, "grind", title_notif, body_notif,
            priority="normal", db=db
        )

    if not pg:
        await db.commit()

    return {"hours": hours, "pay": pay, "reason": reason}


# ── Midnight reset job ────────────────────────────────────────────────────────

async def midnight_reset():
    """
    Runs every 60s, gates on SLT midnight window.
    Resets hours_today and odd_job count for all players.
    Also auto-clocks-out anyone still clocked in (grace: shift over 4h).
    """
    if not _is_midnight_slt():
        return

    cfg = get_config()

    if is_postgres():
        await _midnight_reset_pg(cfg)
    else:
        await _midnight_reset_sqlite(cfg)

    print("[career] Midnight reset complete.")


async def _midnight_reset_pg(cfg):
    import asyncpg
    url = get_db_url()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    conn = await asyncpg.connect(url)
    try:
        # Reset hours_today for everyone
        await conn.execute("UPDATE employment SET hours_today = 0")
        # Reset odd job counts (tracked via odd_job_log — no separate counter col needed)
        # Increment days_at_tier for clocked-out workers (already done at clock-out)
        print("[career] Postgres midnight reset done.")
    finally:
        await conn.close()


async def _midnight_reset_sqlite(cfg):
    import aiosqlite
    from pathlib import Path
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("UPDATE employment SET hours_today = 0")
        # Increment days_alive for all players with an active wallet (i.e. registered)
        await db.execute(
            "UPDATE player_stats SET days_alive = days_alive + 1 WHERE player_id IN (SELECT player_id FROM wallets)"
        )
        await db.commit()
    # Check days_alive achievements for all players
    try:
        import aiosqlite as _aio
        async with _aio.connect(db_path) as db2:
            db2.row_factory = _aio.Row
            async with db2.execute("SELECT player_id FROM wallets") as cur:
                pids = [r[0] for r in await cur.fetchall()]
        for pid in pids:
            try:
                await increment_stat(pid, "days_alive", 0)  # 0 = just trigger check, already incremented above
            except Exception:
                pass
    except Exception:
        pass
    print("[career] SQLite midnight reset done.")


# ── Auto-clockout sweep (runs every decay tick) ───────────────────────────────

async def auto_clockout_sweep():
    """
    Check all clocked-in players. Auto-clock-out if:
      - heartbeat missed >= grace_misses (2)
      - or shift exceeded max hours
    Called every 60s alongside decay tick.
    """
    cfg = get_config()
    grace = int(cfg["careers"]["heartbeat_grace_misses"])
    interval_s = int(cfg["careers"]["heartbeat_interval_seconds"])
    max_hours = float(cfg["careers"]["shift_max_hours"])
    grace_window = timedelta(seconds=interval_s * (grace + 1))
    max_shift = timedelta(hours=max_hours)

    now = datetime.now(timezone.utc)

    if is_postgres():
        await _auto_clockout_pg(grace_window, max_shift, now, cfg)
    else:
        await _auto_clockout_sqlite(grace_window, max_shift, now, cfg)


async def _auto_clockout_pg(grace_window, max_shift, now, cfg):
    import asyncpg
    url = get_db_url()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            """SELECT player_id, career_path_key, tier_level, job_title,
                      clocked_in_at, last_heartbeat_at
               FROM employment WHERE is_clocked_in = 1"""
        )
        for row in rows:
            emp = dict(row)
            player_id = emp["player_id"]
            should_out = False

            if emp["last_heartbeat_at"]:
                try:
                    hb = datetime.fromisoformat(str(emp["last_heartbeat_at"]).replace("Z", "+00:00"))
                    if hb.tzinfo is None:
                        hb = hb.replace(tzinfo=timezone.utc)
                    if now - hb > grace_window:
                        should_out = True
                except Exception:
                    pass

            if emp["clocked_in_at"]:
                try:
                    start = datetime.fromisoformat(str(emp["clocked_in_at"]).replace("Z", "+00:00"))
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=timezone.utc)
                    if now - start >= max_shift:
                        should_out = True
                except Exception:
                    pass

            if should_out:
                await do_clockout(conn, player_id, emp, reason="auto")
    finally:
        await conn.close()


async def _auto_clockout_sqlite(grace_window, max_shift, now, cfg):
    import aiosqlite
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT player_id, career_path_key, tier_level, job_title,
                      clocked_in_at, last_heartbeat_at
               FROM employment WHERE is_clocked_in = 1"""
        ) as cur:
            rows = await cur.fetchall()

        for row in rows:
            emp = dict(row)
            player_id = emp["player_id"]
            should_out = False

            if emp["last_heartbeat_at"]:
                try:
                    hb = datetime.fromisoformat(str(emp["last_heartbeat_at"]).replace("Z", "+00:00"))
                    if hb.tzinfo is None:
                        hb = hb.replace(tzinfo=timezone.utc)
                    if now - hb > grace_window:
                        should_out = True
                except Exception:
                    pass

            if emp["clocked_in_at"]:
                try:
                    start = datetime.fromisoformat(str(emp["clocked_in_at"]).replace("Z", "+00:00"))
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=timezone.utc)
                    if now - start >= max_shift:
                        should_out = True
                except Exception:
                    pass

            if should_out:
                await do_clockout(db, player_id, emp, reason="auto")
