"""
Calendar router — personal and community calendar events.

Endpoints:
  POST   /calendar/event             — create event
  GET    /calendar/events            — list events for a month
  PUT    /calendar/event/{id}        — edit event
  DELETE /calendar/event/{id}        — delete event
  GET    /calendar/upcoming          — next 7 days (used by Ritual webapp)
  GET    /calendar/community         — public events from all players
  POST   /calendar/rsvp/{event_id}   — RSVP to a public/community event
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db, is_postgres
from app.services.notifications import push_notification

router = APIRouter(prefix="/calendar", tags=["calendar"])

COLOR_KEYS = ["purple", "rose", "amber", "green", "gold", "blue", "pink", "grey"]
EVENT_TYPES = ["personal", "social", "birthday", "work", "health", "community"]


# ── Schemas ───────────────────────────────────────────────────────────────────

class NewEvent(BaseModel):
    token: str
    title: str
    event_type: str = "personal"
    event_date_slt: str         # ISO date string YYYY-MM-DD
    end_date_slt: str | None = None
    is_recurring: bool = False
    recurrence_rule: str | None = None
    is_public: bool = False
    color_key: str = "purple"
    generates_vibe_key: str | None = None
    notes: str | None = None


class UpdateEvent(BaseModel):
    token: str
    title: str | None = None
    event_type: str | None = None
    event_date_slt: str | None = None
    end_date_slt: str | None = None
    is_public: bool | None = None
    color_key: str | None = None
    notes: str | None = None


class RsvpRequest(BaseModel):
    token: str


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


# ── POST /calendar/event ──────────────────────────────────────────────────────

@router.post("/event")
async def create_event(body: NewEvent, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Event title required.")
    if len(title) > 100:
        raise HTTPException(status_code=400, detail="Title too long.")

    event_type = body.event_type if body.event_type in EVENT_TYPES else "personal"
    color_key  = body.color_key  if body.color_key  in COLOR_KEYS  else "purple"
    player_id  = player["id"]

    if is_postgres():
        event_id = await db.fetchval(
            """INSERT INTO calendar_events
               (player_id, title, event_type, event_date_slt, end_date_slt,
                is_recurring, recurrence_rule, is_public, color_key,
                generates_vibe_key, notes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
               RETURNING id""",
            player_id, title, event_type, body.event_date_slt, body.end_date_slt,
            int(body.is_recurring), body.recurrence_rule, int(body.is_public),
            color_key, body.generates_vibe_key, body.notes)
    else:
        async with db.execute(
            """INSERT INTO calendar_events
               (player_id, title, event_type, event_date_slt, end_date_slt,
                is_recurring, recurrence_rule, is_public, color_key,
                generates_vibe_key, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (player_id, title, event_type, body.event_date_slt, body.end_date_slt,
             int(body.is_recurring), body.recurrence_rule, int(body.is_public),
             color_key, body.generates_vibe_key, body.notes)
        ) as cur:
            event_id = cur.lastrowid
        await db.commit()

    return {"status": "created", "event_id": event_id}


# ── GET /calendar/events ──────────────────────────────────────────────────────

@router.get("/events")
async def list_events(token: str, year: int, month: int, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    # Build month window
    month_start = f"{year:04d}-{month:02d}-01"
    # Last day of month
    if month == 12:
        month_end = f"{year+1:04d}-01-01"
    else:
        month_end = f"{year:04d}-{month+1:02d}-01"

    player_id = player["id"]

    if is_postgres():
        rows = await db.fetch(
            """SELECT * FROM calendar_events
               WHERE player_id = $1
                 AND event_date_slt >= $2
                 AND event_date_slt < $3
               ORDER BY event_date_slt ASC""",
            player_id, month_start, month_end)
    else:
        async with db.execute(
            """SELECT * FROM calendar_events
               WHERE player_id = ?
                 AND event_date_slt >= ?
                 AND event_date_slt < ?
               ORDER BY event_date_slt ASC""",
            (player_id, month_start, month_end)
        ) as cur:
            rows = await cur.fetchall()

    return {"events": [dict(r) for r in rows]}


# ── GET /calendar/upcoming ────────────────────────────────────────────────────

@router.get("/upcoming")
async def upcoming_events(token: str, db=Depends(get_db)):
    """Next 7 days of personal events — used by Ritual webapp home view."""
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        rows = await db.fetch(
            """SELECT * FROM calendar_events
               WHERE player_id = $1
                 AND event_date_slt >= now()::date::text
                 AND event_date_slt <= (now() + interval '7 days')::date::text
               ORDER BY event_date_slt ASC""",
            player_id)
    else:
        async with db.execute(
            """SELECT * FROM calendar_events
               WHERE player_id = ?
                 AND event_date_slt >= date('now')
                 AND event_date_slt <= date('now', '+7 days')
               ORDER BY event_date_slt ASC""",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    return {"upcoming": [dict(r) for r in rows]}


# ── GET /calendar/community ───────────────────────────────────────────────────

@router.get("/community")
async def community_events(token: str, db=Depends(get_db)):
    """Public events from all players — next 30 days."""
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    if is_postgres():
        rows = await db.fetch(
            """SELECT ce.*, p.display_name AS creator_name
               FROM calendar_events ce
               JOIN players p ON p.id = ce.player_id
               WHERE ce.is_public = 1
                 AND ce.event_date_slt >= now()::date::text
                 AND ce.event_date_slt <= (now() + interval '30 days')::date::text
               ORDER BY ce.event_date_slt ASC""")
    else:
        async with db.execute(
            """SELECT ce.*, p.display_name AS creator_name
               FROM calendar_events ce
               JOIN players p ON p.id = ce.player_id
               WHERE ce.is_public = 1
                 AND ce.event_date_slt >= date('now')
                 AND ce.event_date_slt <= date('now', '+30 days')
               ORDER BY ce.event_date_slt ASC"""
        ) as cur:
            rows = await cur.fetchall()

    return {"community": [dict(r) for r in rows]}


# ── PUT /calendar/event/{id} ──────────────────────────────────────────────────

@router.put("/event/{event_id}")
async def update_event(event_id: int, body: UpdateEvent, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        existing = await db.fetchrow(
            "SELECT id FROM calendar_events WHERE id = $1 AND player_id = $2",
            event_id, player_id)
    else:
        async with db.execute(
            "SELECT id FROM calendar_events WHERE id = ? AND player_id = ?",
            (event_id, player_id)
        ) as cur:
            existing = await cur.fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="Event not found.")

    # Build update set
    fields = {}
    if body.title is not None:       fields["title"]          = body.title.strip()
    if body.event_type is not None:  fields["event_type"]     = body.event_type
    if body.event_date_slt is not None: fields["event_date_slt"] = body.event_date_slt
    if body.end_date_slt is not None:   fields["end_date_slt"]   = body.end_date_slt
    if body.is_public is not None:   fields["is_public"]      = int(body.is_public)
    if body.color_key is not None:   fields["color_key"]      = body.color_key
    if body.notes is not None:       fields["notes"]          = body.notes

    if not fields:
        return {"status": "no_changes"}

    if is_postgres():
        set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
        await db.execute(
            f"UPDATE calendar_events SET {set_clause} WHERE id = $1",
            event_id, *fields.values())
    else:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        await db.execute(
            f"UPDATE calendar_events SET {set_clause} WHERE id = ?",
            (*fields.values(), event_id))
        await db.commit()

    return {"status": "updated"}


# ── DELETE /calendar/event/{id} ───────────────────────────────────────────────

@router.delete("/event/{event_id}")
async def delete_event(event_id: int, token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        result = await db.execute(
            "DELETE FROM calendar_events WHERE id = $1 AND player_id = $2",
            event_id, player_id)
    else:
        await db.execute(
            "DELETE FROM calendar_events WHERE id = ? AND player_id = ?",
            (event_id, player_id))
        await db.commit()

    return {"status": "deleted"}


# ── POST /calendar/rsvp/{event_id} ───────────────────────────────────────────

@router.post("/rsvp/{event_id}")
async def rsvp_event(event_id: int, body: RsvpRequest, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    # Verify public event exists
    if is_postgres():
        event = await db.fetchrow(
            "SELECT id, player_id, title FROM calendar_events WHERE id = $1 AND is_public = 1",
            event_id)
    else:
        async with db.execute(
            "SELECT id, player_id, title FROM calendar_events WHERE id = ? AND is_public = 1",
            (event_id,)
        ) as cur:
            event = await cur.fetchone()

    if not event:
        raise HTTPException(status_code=404, detail="Public event not found.")

    # Increment RSVP count
    if is_postgres():
        await db.execute(
            "UPDATE calendar_events SET rsvp_count = rsvp_count + 1 WHERE id = $1",
            event_id)
    else:
        await db.execute(
            "UPDATE calendar_events SET rsvp_count = rsvp_count + 1 WHERE id = ?",
            (event_id,))
        await db.commit()

    # Notify event creator
    if event["player_id"] != player["id"]:
        await push_notification(
            player_id=event["player_id"],
            app_source="ritual",
            title=f"{player['display_name']} RSVPd to {event['title']} 📅",
            body="",
            priority="low",
            db=db,
        )

    return {"status": "rsvpd"}
