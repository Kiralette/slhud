"""
Achievement checker service.
Called after any action that might unlock an achievement.
Checks player_stats against achievement conditions defined in config.yaml.
"""

import aiosqlite
from datetime import datetime, timezone
from app.config import get_config
from app.database import is_postgres, get_db_path, get_db_url


async def check_achievements(player_id: int, trigger_stat: str | None = None) -> list[str]:
    cfg = get_config()
    achievement_defs = cfg.get("achievements", {})
    if not achievement_defs:
        return []
    if is_postgres():
        return await _check_achievements_pg(player_id, achievement_defs)
    else:
        return await _check_achievements_sqlite(player_id, achievement_defs)


async def _check_achievements_sqlite(player_id: int, achievement_defs: dict) -> list[str]:
    newly_unlocked = []
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT achievement_key FROM player_achievements WHERE player_id = ?", (player_id,)
        ) as cur:
            earned = {r["achievement_key"] for r in await cur.fetchall()}
        async with db.execute(
            "SELECT * FROM player_stats WHERE player_id = ?", (player_id,)
        ) as cur:
            stats_row = await cur.fetchone()
        stats = dict(stats_row) if stats_row else {}
        now = datetime.now(timezone.utc).isoformat()

        for key, ach in achievement_defs.items():
            if key in earned:
                continue
            condition = ach.get("condition", {})
            stat_name = condition.get("stat")
            threshold = condition.get("gte", 0)
            if not stat_name:
                continue
            current_value = float(stats.get(stat_name, 0) or 0)
            if current_value >= float(threshold):
                await db.execute(
                    "INSERT OR IGNORE INTO player_achievements (player_id, achievement_key, unlocked_at) VALUES (?, ?, ?)",
                    (player_id, key, now)
                )
                xp_reward = ach.get("xp_reward", 0)
                if xp_reward:
                    await db.execute(
                        "UPDATE skills SET xp = xp + ? WHERE player_id = ? AND skill_key = 'knowledge'",
                        (xp_reward, player_id)
                    )
                await db.execute(
                    "INSERT INTO notifications (player_id, app_source, title, body, priority, created_at) VALUES (?, 'canvas', ?, ?, 'normal', ?)",
                    (player_id, f"Achievement unlocked: {ach['display_name']} {ach.get('icon','🏆')}", ach.get("description",""), now)
                )
                await db.commit()
                newly_unlocked.append(key)
    return newly_unlocked


async def _check_achievements_pg(player_id: int, achievement_defs: dict) -> list[str]:
    import asyncpg
    newly_unlocked = []
    conn = await asyncpg.connect(get_db_url())
    try:
        earned_rows = await conn.fetch("SELECT achievement_key FROM player_achievements WHERE player_id = $1", player_id)
        earned = {r["achievement_key"] for r in earned_rows}
        stats_row = await conn.fetchrow("SELECT * FROM player_stats WHERE player_id = $1", player_id)
        stats = dict(stats_row) if stats_row else {}
        now = datetime.now(timezone.utc).isoformat()
        for key, ach in achievement_defs.items():
            if key in earned:
                continue
            condition = ach.get("condition", {})
            stat_name = condition.get("stat")
            threshold = condition.get("gte", 0)
            if not stat_name:
                continue
            current_value = float(stats.get(stat_name, 0) or 0)
            if current_value >= float(threshold):
                await conn.execute(
                    "INSERT INTO player_achievements (player_id, achievement_key, unlocked_at) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                    player_id, key, now
                )
                xp_reward = ach.get("xp_reward", 0)
                if xp_reward:
                    await conn.execute("UPDATE skills SET xp = xp + $1 WHERE player_id = $2 AND skill_key = 'knowledge'", xp_reward, player_id)
                await conn.execute(
                    "INSERT INTO notifications (player_id, app_source, title, body, priority, created_at) VALUES ($1, 'canvas', $2, $3, 'normal', $4)",
                    player_id, f"Achievement unlocked: {ach['display_name']} {ach.get('icon','🏆')}", ach.get("description",""), now
                )
                newly_unlocked.append(key)
    finally:
        await conn.close()
    return newly_unlocked


async def increment_stat(player_id: int, stat_key: str, amount: float = 1) -> None:
    """Increment a player_stats counter then check achievements."""
    if is_postgres():
        import asyncpg
        conn = await asyncpg.connect(get_db_url())
        try:
            await conn.execute(
                f"INSERT INTO player_stats (player_id, {stat_key}) VALUES ($1, $2) ON CONFLICT (player_id) DO UPDATE SET {stat_key} = COALESCE(player_stats.{stat_key}, 0) + EXCLUDED.{stat_key}",
                player_id, amount
            )
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(get_db_path()) as db:
            await db.execute(
                f"INSERT INTO player_stats (player_id, {stat_key}) VALUES (?, ?) ON CONFLICT (player_id) DO UPDATE SET {stat_key} = COALESCE({stat_key}, 0) + ?",
                (player_id, amount, amount)
            )
            await db.commit()
    await check_achievements(player_id, stat_key)


async def set_stat_if_greater(player_id: int, stat_key: str, value: float) -> None:
    """Set a stat to value only if value > current (for peak/max tracking)."""
    if is_postgres():
        import asyncpg
        conn = await asyncpg.connect(get_db_url())
        try:
            await conn.execute(
                f"INSERT INTO player_stats (player_id, {stat_key}) VALUES ($1, $2) ON CONFLICT (player_id) DO UPDATE SET {stat_key} = GREATEST(COALESCE(player_stats.{stat_key}, 0), EXCLUDED.{stat_key})",
                player_id, value
            )
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(get_db_path()) as db:
            await db.execute(
                f"INSERT INTO player_stats (player_id, {stat_key}) VALUES (?, ?) ON CONFLICT (player_id) DO UPDATE SET {stat_key} = MAX(COALESCE({stat_key}, 0), ?)",
                (player_id, value, value)
            )
            await db.commit()
    await check_achievements(player_id, stat_key)
