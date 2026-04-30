"""
Messages router — DMs between players via Ping webapp.

Threads are keyed by the two player IDs (always stored low_id, high_id).
SL browser has no WebSockets so polling is used for updates.

Endpoints:
  GET   /messages/threads          — list of threads with unread counts
  GET   /messages/thread/{id}      — fetch messages in a thread
  POST  /messages/send             — send a message (creates thread if needed)
  POST  /messages/read/{thread_id} — mark thread as read
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db, is_postgres
from app.services.notifications import push_notification
from app.services.achievements import increment_stat

router = APIRouter(prefix="/messages", tags=["messages"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class SendMessage(BaseModel):
    token: str
    recipient_avatar_uuid: str
    content: str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_player(token: str, db):
    if is_postgres():
        row = await db.fetchrow(
            "SELECT * FROM players WHERE token = $1 AND is_banned = 0", token)
        return dict(row) if row else None
    else:
        async with db.execute(
            "SELECT * FROM players WHERE token = ? AND is_banned = 0", (token,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _get_player_by_uuid(uuid: str, db):
    if is_postgres():
        row = await db.fetchrow(
            "SELECT * FROM players WHERE avatar_uuid = $1 AND is_banned = 0", uuid)
        return dict(row) if row else None
    else:
        async with db.execute(
            "SELECT * FROM players WHERE avatar_uuid = ? AND is_banned = 0", (uuid,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _get_or_create_thread(player_a: int, player_b: int, db) -> int:
    """
    Threads are always stored with the lower ID as player_a.
    Returns thread id.
    """
    low  = min(player_a, player_b)
    high = max(player_a, player_b)

    if is_postgres():
        row = await db.fetchrow(
            "SELECT id FROM message_threads WHERE player_a_id = $1 AND player_b_id = $2",
            low, high)
        if row:
            return row["id"]
        thread_id = await db.fetchval(
            "INSERT INTO message_threads (player_a_id, player_b_id) VALUES ($1, $2) RETURNING id",
            low, high)
    else:
        async with db.execute(
            "SELECT id FROM message_threads WHERE player_a_id = ? AND player_b_id = ?",
            (low, high)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return row["id"]
        async with db.execute(
            "INSERT INTO message_threads (player_a_id, player_b_id) VALUES (?, ?)",
            (low, high)
        ) as cur:
            thread_id = cur.lastrowid
        await db.commit()

    return thread_id


# ── GET /messages/threads ─────────────────────────────────────────────────────

@router.get("/threads")
async def list_threads(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        rows = await db.fetch(
            """SELECT
                 mt.id,
                 mt.last_message_at,
                 CASE WHEN mt.player_a_id = $1
                      THEN mt.unread_count_a
                      ELSE mt.unread_count_b END AS unread_count,
                 CASE WHEN mt.player_a_id = $1
                      THEN pb.display_name
                      ELSE pa.display_name END AS other_name,
                 CASE WHEN mt.player_a_id = $1
                      THEN pb.avatar_uuid
                      ELSE pa.avatar_uuid END AS other_uuid
               FROM message_threads mt
               JOIN players pa ON pa.id = mt.player_a_id
               JOIN players pb ON pb.id = mt.player_b_id
               WHERE mt.player_a_id = $1 OR mt.player_b_id = $1
               ORDER BY mt.last_message_at DESC NULLS LAST""",
            player_id)
    else:
        async with db.execute(
            """SELECT
                 mt.id,
                 mt.last_message_at,
                 CASE WHEN mt.player_a_id = ?
                      THEN mt.unread_count_a
                      ELSE mt.unread_count_b END AS unread_count,
                 CASE WHEN mt.player_a_id = ?
                      THEN pb.display_name
                      ELSE pa.display_name END AS other_name,
                 CASE WHEN mt.player_a_id = ?
                      THEN pb.avatar_uuid
                      ELSE pa.avatar_uuid END AS other_uuid
               FROM message_threads mt
               JOIN players pa ON pa.id = mt.player_a_id
               JOIN players pb ON pb.id = mt.player_b_id
               WHERE mt.player_a_id = ? OR mt.player_b_id = ?
               ORDER BY mt.last_message_at DESC""",
            (player_id, player_id, player_id, player_id, player_id)
        ) as cur:
            rows = await cur.fetchall()

    return {"threads": [dict(r) for r in rows]}


# ── GET /messages/thread/{thread_id} ─────────────────────────────────────────

@router.get("/thread/{thread_id}")
async def get_thread(thread_id: int, token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    # Verify player is part of this thread
    if is_postgres():
        thread = await db.fetchrow(
            "SELECT * FROM message_threads WHERE id = $1", thread_id)
    else:
        async with db.execute(
            "SELECT * FROM message_threads WHERE id = ?", (thread_id,)
        ) as cur:
            thread = await cur.fetchone()

    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found.")

    if thread["player_a_id"] != player_id and thread["player_b_id"] != player_id:
        raise HTTPException(status_code=403, detail="Not your thread.")

    # Fetch messages
    if is_postgres():
        rows = await db.fetch(
            """SELECT m.id, m.sender_id, p.display_name AS sender_name,
                      m.content, m.sent_at, m.is_read
               FROM messages m
               JOIN players p ON p.id = m.sender_id
               WHERE m.thread_id = $1
               ORDER BY m.sent_at ASC LIMIT 100""",
            thread_id)
        # Mark read
        await db.execute(
            """UPDATE messages SET is_read = 1
               WHERE thread_id = $1 AND sender_id != $2""",
            thread_id, player_id)
        # Reset unread counter
        if thread["player_a_id"] == player_id:
            await db.execute(
                "UPDATE message_threads SET unread_count_a = 0 WHERE id = $1", thread_id)
        else:
            await db.execute(
                "UPDATE message_threads SET unread_count_b = 0 WHERE id = $1", thread_id)
    else:
        async with db.execute(
            """SELECT m.id, m.sender_id, p.display_name AS sender_name,
                      m.content, m.sent_at, m.is_read
               FROM messages m
               JOIN players p ON p.id = m.sender_id
               WHERE m.thread_id = ?
               ORDER BY m.sent_at ASC LIMIT 100""",
            (thread_id,)
        ) as cur:
            rows = await cur.fetchall()
        await db.execute(
            "UPDATE messages SET is_read = 1 WHERE thread_id = ? AND sender_id != ?",
            (thread_id, player_id))
        if thread["player_a_id"] == player_id:
            await db.execute(
                "UPDATE message_threads SET unread_count_a = 0 WHERE id = ?", (thread_id,))
        else:
            await db.execute(
                "UPDATE message_threads SET unread_count_b = 0 WHERE id = ?", (thread_id,))
        await db.commit()

    return {"thread_id": thread_id, "messages": [dict(r) for r in rows]}


# ── POST /messages/send ───────────────────────────────────────────────────────

@router.post("/send")
async def send_message(body: SendMessage, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    recipient = await _get_player_by_uuid(body.recipient_avatar_uuid, db)
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found.")

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    if len(content) > 500:
        raise HTTPException(status_code=400, detail="Message too long (500 char max).")

    sender_id    = player["id"]
    recipient_id = recipient["id"]

    if sender_id == recipient_id:
        raise HTTPException(status_code=400, detail="Cannot message yourself.")

    thread_id = await _get_or_create_thread(sender_id, recipient_id, db)
    low  = min(sender_id, recipient_id)

    if is_postgres():
        await db.execute(
            "INSERT INTO messages (thread_id, sender_id, content) VALUES ($1, $2, $3)",
            thread_id, sender_id, content)
        # Increment unread for recipient, update last_message_at
        if low == sender_id:
            # sender is player_a, so recipient is player_b
            await db.execute(
                """UPDATE message_threads
                   SET last_message_at = now()::text,
                       unread_count_b  = unread_count_b + 1
                   WHERE id = $1""",
                thread_id)
        else:
            await db.execute(
                """UPDATE message_threads
                   SET last_message_at = now()::text,
                       unread_count_a  = unread_count_a + 1
                   WHERE id = $1""",
                thread_id)
    else:
        await db.execute(
            "INSERT INTO messages (thread_id, sender_id, content) VALUES (?, ?, ?)",
            (thread_id, sender_id, content))
        if low == sender_id:
            await db.execute(
                """UPDATE message_threads
                   SET last_message_at = datetime('now'),
                       unread_count_b  = unread_count_b + 1
                   WHERE id = ?""",
                (thread_id,))
        else:
            await db.execute(
                """UPDATE message_threads
                   SET last_message_at = datetime('now'),
                       unread_count_a  = unread_count_a + 1
                   WHERE id = ?""",
                (thread_id,))
        await db.commit()

    # Push notification to recipient
    preview = content[:60] + ("…" if len(content) > 60 else "")
    await push_notification(
        player_id=recipient_id,
        app_source="ping",
        title=f"{player['display_name']}: {preview} 💬",
        body="",
        priority="normal",
        db=db,
    )

    try:
        await increment_stat(player_id, "total_messages_sent")
    except Exception:
        pass

    # Sending a message fills Social need a little
    try:
        from app.services.needs import update_need
        await update_need(player_id, "social", 2.0, db, "Sent a Ping message +2 Social")
    except Exception:
        pass

    return {"status": "sent", "thread_id": thread_id}
