"""
Atlas service — region-entry notification job.

Runs every 5 minutes via scheduler. Checks player heartbeats for recent region
activity. If a player is in a region with Atlas listings and hasn't been notified
about that region in the last 2 hours, sends a low-priority nudge.
"""

from datetime import datetime, timezone, timedelta

from app.database import is_postgres
from app.services.notifications import push_notification


async def run_atlas_region_notifier(db=None):
    """
    Check recent heartbeats and notify players of nearby Atlas spots.
    Called by scheduler every 5 minutes with db=None — opens its own connection.
    """
    if is_postgres():
        import asyncpg
        from app.database import get_db_url
        url = get_db_url()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        conn = await asyncpg.connect(url)
        try:
            await _run_pg(conn)
        finally:
            await conn.close()
    else:
        import aiosqlite
        from app.database import get_db_path
        db_path = get_db_path()
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            await _run_sq(db)


async def _run_pg(conn):
    now           = datetime.now(timezone.utc)
    two_hours_ago = (now - timedelta(hours=2)).isoformat()
    five_mins_ago = (now - timedelta(minutes=5)).isoformat()

    try:
        players = await conn.fetch(
            """SELECT DISTINCT p.id AS player_id, ph.region_name
               FROM player_heartbeats ph
               JOIN players p ON p.id = ph.player_id
               WHERE ph.recorded_at >= $1 AND p.is_banned = 0
               AND ph.region_name IS NOT NULL AND ph.region_name != ''""",
            five_mins_ago)
    except Exception:
        return  # heartbeats table may not exist

    for player in players:
        player_id   = player["player_id"]
        region_name = player["region_name"]

        # Skip if already notified for this region in last 2h
        recent = await conn.fetchrow(
            """SELECT id FROM notifications
               WHERE player_id = $1 AND app_source = 'atlas'
               AND title ILIKE $2 AND created_at >= $3""",
            player_id, f"%{region_name}%", two_hours_ago)
        if recent:
            continue

        count_row = await conn.fetchrow(
            """SELECT COUNT(*) as cnt FROM atlas_locations
               WHERE region_name ILIKE $1 AND visibility = 'public'""",
            f"%{region_name}%")
        count = count_row["cnt"] if count_row else 0
        if count == 0:
            continue

        spots = f"{count} Atlas spot{'s' if count != 1 else ''}"
        try:
            await conn.execute(
                """INSERT INTO notifications
                   (player_id, app_source, title, body, priority, is_read, created_at)
                   VALUES ($1, 'atlas', $2, $3, 'low', 0, $4)""",
                player_id,
                f"You're in {region_name} 🗺️",
                f"{spots} here. Tap to explore.",
                now.isoformat())
        except Exception:
            pass


async def _run_sq(db):
    now           = datetime.now(timezone.utc)
    two_hours_ago = (now - timedelta(hours=2)).isoformat()
    five_mins_ago = (now - timedelta(minutes=5)).isoformat()

    try:
        async with db.execute(
            """SELECT DISTINCT p.id AS player_id, ph.region_name
               FROM player_heartbeats ph
               JOIN players p ON p.id = ph.player_id
               WHERE ph.recorded_at >= ? AND p.is_banned = 0
               AND ph.region_name IS NOT NULL AND ph.region_name != ''""",
            (five_mins_ago,)
        ) as cur:
            players = await cur.fetchall()
    except Exception:
        return

    for player in players:
        player_id   = player["player_id"]
        region_name = player["region_name"]

        async with db.execute(
            """SELECT id FROM notifications
               WHERE player_id = ? AND app_source = 'atlas'
               AND title LIKE ? AND created_at >= ?""",
            (player_id, f"%{region_name}%", two_hours_ago)
        ) as cur:
            recent = await cur.fetchone()
        if recent:
            continue

        async with db.execute(
            """SELECT COUNT(*) as cnt FROM atlas_locations
               WHERE region_name LIKE ? AND visibility = 'public'""",
            (f"%{region_name}%",)
        ) as cur:
            count_row = await cur.fetchone()
        count = count_row["cnt"] if count_row else 0
        if count == 0:
            continue

        spots = f"{count} Atlas spot{'s' if count != 1 else ''}"
        try:
            await db.execute(
                """INSERT INTO notifications
                   (player_id, app_source, title, body, priority, is_read, created_at)
                   VALUES (?, 'atlas', ?, ?, 'low', 0, ?)""",
                (player_id,
                 f"You're in {region_name} 🗺️",
                 f"{spots} here. Tap to explore.",
                 now.isoformat()))
            await db.commit()
        except Exception:
            pass
