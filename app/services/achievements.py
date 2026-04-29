"""
Achievement checker service.
Called after any action that might unlock an achievement.
Checks player_stats against achievement conditions defined in config.yaml.
"""

from datetime import datetime, timezone
from app.config import get_config
from app.database import get_db_conn, is_postgres


async def check_achievements(player_id: int, trigger_stat: str | None = None) -> list[str]:
    """
    Check all unearned achievements for a player.
    Returns list of newly unlocked achievement keys.
    Fires notifications for each unlock.
    """
    cfg = get_config()
    achievement_defs = cfg.get("achievements", {})
    if not achievement_defs:
        return []

    async with get_db_conn() as db:
        # Load already-earned achievements
        if is_postgres():
            earned_rows = await db.fetch(
                "SELECT achievement_key FROM player_achievements WHERE player_id = $1", player_id
            )
            stats_row = await db.fetchrow(
                "SELECT * FROM player_stats WHERE player_id = $1", player_id
            )
        else:
            async with db.execute(
                "SELECT achievement_key FROM player_achievements WHERE player_id = ?", (player_id,)
            ) as cur:
                earned_rows = await cur.fetchall()
            async with db.execute(
                "SELECT * FROM player_stats WHERE player_id = ?", (player_id,)
            ) as cur:
                stats_row = await cur.fetchone()

        earned = {r["achievement_key"] for r in (earned_rows or [])}
        stats = dict(stats_row) if stats_row else {}

        newly_unlocked = []

        for key, ach in achievement_defs.items():
            if key in earned:
                continue

            condition = ach.get("condition", {})
            stat_name = condition.get("stat")
            threshold = condition.get("gte", 0)

            if not stat_name:
                continue

            current_value = stats.get(stat_name, 0) or 0

            if float(current_value) >= float(threshold):
                now = datetime.now(timezone.utc).isoformat()

                if is_postgres():
                    await db.execute(
                        """INSERT INTO player_achievements (player_id, achievement_key, unlocked_at)
                           VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                        player_id, key, now
                    )
                else:
                    await db.execute(
                        """INSERT OR IGNORE INTO player_achievements (player_id, achievement_key, unlocked_at)
                           VALUES (?, ?, ?)""",
                        (player_id, key, now)
                    )
                    await db.commit()

                # XP reward to knowledge skill
                xp_reward = ach.get("xp_reward", 0)
                if xp_reward:
                    if is_postgres():
                        await db.execute(
                            """UPDATE skills SET xp = xp + $1
                               WHERE player_id = $2 AND skill_key = 'knowledge'""",
                            xp_reward, player_id
                        )
                    else:
                        await db.execute(
                            """UPDATE skills SET xp = xp + ?
                               WHERE player_id = ? AND skill_key = 'knowledge'""",
                            (xp_reward, player_id)
                        )
                        await db.commit()

                # Notification
                await _fire_achievement_notification(db, player_id, key, ach, now)

                newly_unlocked.append(key)

        return newly_unlocked


async def _fire_achievement_notification(db, player_id: int, key: str, ach: dict, now: str):
    title = f"Achievement unlocked: {ach['display_name']} {ach.get('icon', '🏆')}"
    body = ach.get("description", "")

    if is_postgres():
        await db.execute(
            """INSERT INTO notifications (player_id, title, body, app_key, priority, created_at)
               VALUES ($1, $2, $3, 'canvas', 'normal', $4)""",
            player_id, title, body, now
        )
    else:
        await db.execute(
            """INSERT INTO notifications (player_id, title, body, app_key, priority, created_at)
               VALUES (?, ?, ?, 'canvas', 'normal', ?)""",
            (player_id, title, body, now)
        )
        await db.commit()


async def increment_stat(player_id: int, stat_key: str, amount: float = 1) -> None:
    """
    Increment a player_stats counter and check achievements.
    Call this from any action that affects a tracked stat.
    """
    async with get_db_conn() as db:
        if is_postgres():
            await db.execute(
                f"""INSERT INTO player_stats (player_id, {stat_key})
                    VALUES ($1, $2)
                    ON CONFLICT (player_id) DO UPDATE
                    SET {stat_key} = COALESCE(player_stats.{stat_key}, 0) + EXCLUDED.{stat_key}""",
                player_id, amount
            )
        else:
            await db.execute(
                f"""INSERT INTO player_stats (player_id, {stat_key}) VALUES (?, ?)
                    ON CONFLICT (player_id) DO UPDATE
                    SET {stat_key} = COALESCE({stat_key}, 0) + ?""",
                (player_id, amount, amount)
            )
            await db.commit()

    await check_achievements(player_id, stat_key)


async def set_stat_if_greater(player_id: int, stat_key: str, value: float) -> None:
    """Set a stat to value only if value > current (for peak/max stats)."""
    async with get_db_conn() as db:
        if is_postgres():
            await db.execute(
                f"""INSERT INTO player_stats (player_id, {stat_key})
                    VALUES ($1, $2)
                    ON CONFLICT (player_id) DO UPDATE
                    SET {stat_key} = GREATEST(COALESCE(player_stats.{stat_key}, 0), EXCLUDED.{stat_key})""",
                player_id, value
            )
        else:
            await db.execute(
                f"""INSERT INTO player_stats (player_id, {stat_key}) VALUES (?, ?)
                    ON CONFLICT (player_id) DO UPDATE
                    SET {stat_key} = MAX(COALESCE({stat_key}, 0), ?)""",
                (player_id, value, value)
            )
            await db.commit()

    await check_achievements(player_id, stat_key)
