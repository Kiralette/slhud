"""
Notifications service.

Every meaningful server-side event calls push_notification().
The HUD polls /notifications/unread-count every 60s for red dot data.
Urgent notifications are also delivered via /notifications/urgent-toast.

Priority levels:
  low    — Canvas history only, no red dot
  normal — red dot on app icon
  urgent — red dot + HUD toast via llOwnerSay
"""

from app.database import is_postgres


async def push_notification(
    player_id: int,
    app_source: str,
    title: str,
    body: str = "",
    priority: str = "normal",   # low | normal | urgent
    action_url: str | None = None,
    db = None,
) -> None:
    """
    Write a notification row for this player.
    Called by decay engine, career service, shop service, etc.
    """
    if db is None:
        return

    if is_postgres():
        await db.execute(
            """INSERT INTO notifications
               (player_id, app_source, title, body, priority, action_url)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            player_id, app_source, title, body, priority, action_url
        )
    else:
        await db.execute(
            """INSERT INTO notifications
               (player_id, app_source, title, body, priority, action_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (player_id, app_source, title, body, priority, action_url)
        )
        await db.commit()


async def get_unread_counts(player_id: int, db) -> dict:
    """
    Returns total unread count and per-app breakdown.
    Used by the HUD heartbeat to know which app dots to show.
    """
    if is_postgres():
        rows = await db.fetch(
            """SELECT app_source, COUNT(*) as cnt
               FROM notifications
               WHERE player_id = $1 AND is_read = 0
               GROUP BY app_source""",
            player_id
        )
    else:
        async with db.execute(
            """SELECT app_source, COUNT(*) as cnt
               FROM notifications
               WHERE player_id = ? AND is_read = 0
               GROUP BY app_source""",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    by_app = {row["app_source"]: row["cnt"] for row in rows}
    total = sum(by_app.values())
    return {"total": total, "by_app": by_app}


async def get_urgent_toasts(player_id: int, db) -> list[dict]:
    """
    Returns urgent untoasted notifications for HUD llOwnerSay delivery.
    Marks them as toasted so they don't repeat.
    """
    if is_postgres():
        rows = await db.fetch(
            """SELECT id, app_source, title, body
               FROM notifications
               WHERE player_id = $1 AND priority = 'urgent' AND is_toasted = 0
               ORDER BY created_at ASC LIMIT 5""",
            player_id
        )
        ids = [row["id"] for row in rows]
        if ids:
            await db.execute(
                f"UPDATE notifications SET is_toasted = 1 WHERE id = ANY($1::int[])",
                ids
            )
    else:
        async with db.execute(
            """SELECT id, app_source, title, body
               FROM notifications
               WHERE player_id = ? AND priority = 'urgent' AND is_toasted = 0
               ORDER BY created_at ASC LIMIT 5""",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            await db.execute(
                f"UPDATE notifications SET is_toasted = 1 WHERE id IN ({placeholders})",
                ids
            )
            await db.commit()

    return [{"app_source": r["app_source"], "title": r["title"], "body": r["body"]} for r in rows]


async def mark_app_read(player_id: int, app_source: str, db) -> None:
    """Mark all notifications from an app as read. Called when player opens that app's webapp."""
    if is_postgres():
        await db.execute(
            "UPDATE notifications SET is_read = 1 WHERE player_id = $1 AND app_source = $2",
            player_id, app_source
        )
    else:
        await db.execute(
            "UPDATE notifications SET is_read = 1 WHERE player_id = ? AND app_source = ?",
            (player_id, app_source)
        )
        await db.commit()


async def mark_all_read(player_id: int, db) -> None:
    """Mark all notifications as read."""
    if is_postgres():
        await db.execute(
            "UPDATE notifications SET is_read = 1 WHERE player_id = $1", player_id)
    else:
        await db.execute(
            "UPDATE notifications SET is_read = 1 WHERE player_id = ?", (player_id,))
        await db.commit()


async def get_recent_notifications(player_id: int, db, limit: int = 50) -> list[dict]:
    """Fetch recent notifications for Canvas history tab."""
    if is_postgres():
        rows = await db.fetch(
            """SELECT app_source, title, body, priority, is_read, created_at
               FROM notifications WHERE player_id = $1
               ORDER BY created_at DESC LIMIT $2""",
            player_id, limit
        )
    else:
        async with db.execute(
            """SELECT app_source, title, body, priority, is_read, created_at
               FROM notifications WHERE player_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (player_id, limit)
        ) as cur:
            rows = await cur.fetchall()

    return [dict(r) for r in rows]
