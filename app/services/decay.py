"""
Decay engine — runs in the background on a timer, draining needs.
Works with both SQLite (local) and PostgreSQL (Render).
"""

import aiosqlite
from app.config import get_config
from app.database import is_postgres, get_db_url, get_db_path


async def run_decay_tick():
    """Called every N seconds by APScheduler."""
    if is_postgres():
        await _run_decay_postgres()
    else:
        await _run_decay_sqlite()


async def _run_decay_postgres():
    import asyncpg
    cfg = get_config()
    needs_cfg = cfg["needs"]
    interval_minutes = cfg["server"]["decay_interval_seconds"] / 60

    url = get_db_url()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    conn = await asyncpg.connect(url)
    try:
        players = await conn.fetch(
            "SELECT id, is_online FROM players WHERE is_banned = 0"
        )

        for player in players:
            player_id = player["id"]
            is_online = bool(player["is_online"])

            needs = await conn.fetch(
                "SELECT need_key, value FROM needs WHERE player_id = $1",
                player_id
            )
            needs_dict = {n["need_key"]: float(n["value"]) for n in needs}

            for need_key, need_cfg in needs_cfg.items():
                if need_key not in needs_dict:
                    continue
                if need_cfg.get("is_composite"):
                    continue

                rate = need_cfg["decay_online"] if is_online else need_cfg["decay_offline"]
                delta = -(rate * interval_minutes)
                new_value = max(0.0, needs_dict[need_key] + delta)
                needs_dict[need_key] = round(new_value, 2)

                await conn.execute(
                    "UPDATE needs SET value = $1, last_updated = now()::text WHERE player_id = $2 AND need_key = $3",
                    round(new_value, 2), player_id, need_key
                )

            await _process_purpose_pg(conn, player_id, needs_dict, needs_cfg, interval_minutes, is_online)
            await _check_automatic_vibes_pg(conn, player_id, needs_dict, needs_cfg)

    finally:
        await conn.close()


async def _process_purpose_pg(conn, player_id, needs_dict, needs_cfg, interval_minutes, is_online):
    purpose_cfg = needs_cfg.get("purpose", {})
    if not purpose_cfg:
        return

    current_purpose = needs_dict.get("purpose", 100.0)
    other_needs = [v for k, v in needs_dict.items() if k != "purpose"]
    if not other_needs:
        return

    wellbeing_score = sum(other_needs) / len(other_needs)
    passive_gain_threshold = purpose_cfg.get("passive_gain_threshold", 60)
    passive_drain_threshold = purpose_cfg.get("passive_drain_threshold", 40)
    passive_gain_rate = purpose_cfg.get("passive_gain_rate", 0.2)

    rate = purpose_cfg["decay_online"] if is_online else purpose_cfg["decay_offline"]
    delta = -(rate * interval_minutes)

    if wellbeing_score >= passive_gain_threshold:
        delta += passive_gain_rate * interval_minutes
    elif wellbeing_score < passive_drain_threshold:
        delta *= 1.5

    new_purpose = max(0.0, min(100.0, current_purpose + delta))
    await conn.execute(
        "UPDATE needs SET value = $1, last_updated = now()::text WHERE player_id = $2 AND need_key = 'purpose'",
        round(new_purpose, 2), player_id
    )


async def _check_automatic_vibes_pg(conn, player_id, needs_dict, needs_cfg):
    cfg = get_config()
    vibes_cfg = cfg["vibes"]

    hygiene = needs_dict.get("hygiene", 100.0)
    stinky_threshold = vibes_cfg.get("stinky", {}).get("trigger_threshold", 20)

    if hygiene < stinky_threshold:
        await conn.execute(
            """INSERT INTO vibes (player_id, vibe_key, is_negative, expires_at)
               VALUES ($1, 'stinky', 1, NULL)
               ON CONFLICT (player_id, vibe_key) DO NOTHING""",
            player_id
        )
    else:
        await conn.execute(
            "DELETE FROM vibes WHERE player_id = $1 AND vibe_key = 'stinky'",
            player_id
        )

    critical_count = sum(
        1 for need_key, value in needs_dict.items()
        if value < needs_cfg.get(need_key, {}).get("crit_threshold", 20)
    )
    drained_threshold = vibes_cfg.get("drained", {}).get("trigger_critical_count", 2)

    if critical_count >= drained_threshold:
        await conn.execute(
            """INSERT INTO vibes (player_id, vibe_key, is_negative, expires_at)
               VALUES ($1, 'drained', 1, NULL)
               ON CONFLICT (player_id, vibe_key) DO NOTHING""",
            player_id
        )
    else:
        await conn.execute(
            "DELETE FROM vibes WHERE player_id = $1 AND vibe_key = 'drained'",
            player_id
        )


async def _run_decay_sqlite():
    """SQLite version for local development."""
    cfg = get_config()
    needs_cfg = cfg["needs"]
    interval_minutes = cfg["server"]["decay_interval_seconds"] / 60
    db_path = get_db_path()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")

        async with db.execute(
            "SELECT id, is_online FROM players WHERE is_banned = 0"
        ) as cursor:
            players = await cursor.fetchall()

        for player in players:
            player_id = player["id"]
            is_online = bool(player["is_online"])

            async with db.execute(
                "SELECT need_key, value FROM needs WHERE player_id = ?",
                (player_id,)
            ) as cursor:
                needs = await cursor.fetchall()

            needs_dict = {n["need_key"]: float(n["value"]) for n in needs}

            for need_key, need_cfg in needs_cfg.items():
                if need_key not in needs_dict:
                    continue
                if need_cfg.get("is_composite"):
                    continue

                rate = need_cfg["decay_online"] if is_online else need_cfg["decay_offline"]
                delta = -(rate * interval_minutes)
                new_value = max(0.0, needs_dict[need_key] + delta)
                needs_dict[need_key] = round(new_value, 2)

                await db.execute(
                    "UPDATE needs SET value = ?, last_updated = datetime('now') WHERE player_id = ? AND need_key = ?",
                    (round(new_value, 2), player_id, need_key)
                )

            await _process_purpose_sqlite(db, player_id, needs_dict, needs_cfg, interval_minutes, is_online)
            await _check_automatic_vibes_sqlite(db, player_id, needs_dict, needs_cfg)

        await db.commit()


async def _process_purpose_sqlite(db, player_id, needs_dict, needs_cfg, interval_minutes, is_online):
    purpose_cfg = needs_cfg.get("purpose", {})
    if not purpose_cfg:
        return

    current_purpose = needs_dict.get("purpose", 100.0)
    other_needs = [v for k, v in needs_dict.items() if k != "purpose"]
    if not other_needs:
        return

    wellbeing_score = sum(other_needs) / len(other_needs)
    passive_gain_threshold = purpose_cfg.get("passive_gain_threshold", 60)
    passive_drain_threshold = purpose_cfg.get("passive_drain_threshold", 40)
    passive_gain_rate = purpose_cfg.get("passive_gain_rate", 0.2)

    rate = purpose_cfg["decay_online"] if is_online else purpose_cfg["decay_offline"]
    delta = -(rate * interval_minutes)

    if wellbeing_score >= passive_gain_threshold:
        delta += passive_gain_rate * interval_minutes
    elif wellbeing_score < passive_drain_threshold:
        delta *= 1.5

    new_purpose = max(0.0, min(100.0, current_purpose + delta))
    await db.execute(
        "UPDATE needs SET value = ?, last_updated = datetime('now') WHERE player_id = ? AND need_key = 'purpose'",
        (round(new_purpose, 2), player_id)
    )


async def _check_automatic_vibes_sqlite(db, player_id, needs_dict, needs_cfg):
    cfg = get_config()
    vibes_cfg = cfg["vibes"]

    hygiene = needs_dict.get("hygiene", 100.0)
    stinky_threshold = vibes_cfg.get("stinky", {}).get("trigger_threshold", 20)

    if hygiene < stinky_threshold:
        await db.execute(
            """INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative, expires_at)
               VALUES (?, 'stinky', 1, NULL)""",
            (player_id,)
        )
    else:
        await db.execute(
            "DELETE FROM vibes WHERE player_id = ? AND vibe_key = 'stinky'",
            (player_id,)
        )

    critical_count = sum(
        1 for need_key, value in needs_dict.items()
        if value < needs_cfg.get(need_key, {}).get("crit_threshold", 20)
    )
    drained_threshold = vibes_cfg.get("drained", {}).get("trigger_critical_count", 2)

    if critical_count >= drained_threshold:
        await db.execute(
            """INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative, expires_at)
               VALUES (?, 'drained', 1, NULL)""",
            (player_id,)
        )
    else:
        await db.execute(
            "DELETE FROM vibes WHERE player_id = ? AND vibe_key = 'drained'",
            (player_id,)
        )
