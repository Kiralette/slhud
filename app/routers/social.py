"""
Social router — follow/unfollow, proximity heartbeat, nearby players.

Endpoints:
  POST   /social/follow            — follow another player
  DELETE /social/follow            — unfollow
  GET    /social/following         — list of players this player follows
  POST   /social/proximity         — LSL heartbeat updates who's nearby
  GET    /social/nearby            — players currently within range
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db, is_postgres
from app.services.notifications import push_notification

router = APIRouter(prefix="/social", tags=["social"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class FollowRequest(BaseModel):
    follower_token: str
    following_avatar_uuid: str   # we look up by UUID so LSL can pass it directly


class UnfollowRequest(BaseModel):
    follower_token: str
    following_avatar_uuid: str


class ProximityUpdate(BaseModel):
    token: str                      # player reporting proximity
    nearby_uuids: list[str]         # UUIDs of players within 20m
    zone: str | None = None         # zone key from zone object, if any


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


# ── POST /social/follow ───────────────────────────────────────────────────────

@router.post("/follow")
async def follow_player(body: FollowRequest, db=Depends(get_db)):
    follower = await _get_player(body.follower_token, db)
    if not follower:
        raise HTTPException(status_code=401, detail="Invalid token.")

    target = await _get_player_by_uuid(body.following_avatar_uuid, db)
    if not target:
        raise HTTPException(status_code=404, detail="Target player not found.")

    if follower["id"] == target["id"]:
        raise HTTPException(status_code=400, detail="Cannot follow yourself.")

    if is_postgres():
        existing = await db.fetchrow(
            "SELECT id FROM follows WHERE follower_id = $1 AND following_id = $2",
            follower["id"], target["id"])
        if existing:
            return {"status": "already_following"}
        await db.execute(
            "INSERT INTO follows (follower_id, following_id) VALUES ($1, $2)",
            follower["id"], target["id"])
    else:
        async with db.execute(
            "SELECT id FROM follows WHERE follower_id = ? AND following_id = ?",
            (follower["id"], target["id"])
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            return {"status": "already_following"}
        await db.execute(
            "INSERT INTO follows (follower_id, following_id) VALUES (?, ?)",
            (follower["id"], target["id"]))
        await db.commit()

    # Notify the followed player
    await push_notification(
        player_id=target["id"],
        app_source="flare",
        title=f"{follower['display_name']} followed you on Flare 👀",
        body="",
        priority="low",
        action_url=f"/app/flare?token={{token}}&tab=discover",
        db=db,
    )

    return {"status": "following", "following": target["display_name"]}


# ── DELETE /social/follow ─────────────────────────────────────────────────────

@router.delete("/follow")
async def unfollow_player(body: UnfollowRequest, db=Depends(get_db)):
    follower = await _get_player(body.follower_token, db)
    if not follower:
        raise HTTPException(status_code=401, detail="Invalid token.")

    target = await _get_player_by_uuid(body.following_avatar_uuid, db)
    if not target:
        raise HTTPException(status_code=404, detail="Target player not found.")

    if is_postgres():
        await db.execute(
            "DELETE FROM follows WHERE follower_id = $1 AND following_id = $2",
            follower["id"], target["id"])
    else:
        await db.execute(
            "DELETE FROM follows WHERE follower_id = ? AND following_id = ?",
            (follower["id"], target["id"]))
        await db.commit()

    return {"status": "unfollowed"}


# ── GET /social/following ─────────────────────────────────────────────────────

@router.get("/following")
async def get_following(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    if is_postgres():
        rows = await db.fetch(
            """SELECT p.avatar_uuid, p.display_name, f.followed_at
               FROM follows f
               JOIN players p ON p.id = f.following_id
               WHERE f.follower_id = $1
               ORDER BY f.followed_at DESC""",
            player["id"])
    else:
        async with db.execute(
            """SELECT p.avatar_uuid, p.display_name, f.followed_at
               FROM follows f
               JOIN players p ON p.id = f.following_id
               WHERE f.follower_id = ?
               ORDER BY f.followed_at DESC""",
            (player["id"],)
        ) as cur:
            rows = await cur.fetchall()

    return {"following": [dict(r) for r in rows]}


# ── POST /social/proximity ────────────────────────────────────────────────────

@router.post("/proximity")
async def update_proximity(body: ProximityUpdate, db=Depends(get_db)):
    """
    Called by LSL heartbeat script every 60s.
    Sends list of UUIDs within 20m sensor range.
    Server upserts proximity_log and fires 'nearby' notification
    for first encounter with a player.
    """
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    encountered = []

    for uuid in body.nearby_uuids:
        nearby = await _get_player_by_uuid(uuid, db)
        if not nearby or nearby["id"] == player_id:
            continue

        nearby_id = nearby["id"]

        if is_postgres():
            existing = await db.fetchrow(
                "SELECT id, session_count FROM proximity_log WHERE player_id = $1 AND nearby_player_id = $2",
                player_id, nearby_id)
            if existing:
                await db.execute(
                    """UPDATE proximity_log
                       SET last_seen_at = now()::text, session_count = session_count + 1, last_zone = $3
                       WHERE player_id = $1 AND nearby_player_id = $2""",
                    player_id, nearby_id, body.zone)
            else:
                await db.execute(
                    """INSERT INTO proximity_log (player_id, nearby_player_id, last_zone)
                       VALUES ($1, $2, $3)""",
                    player_id, nearby_id, body.zone)
                # First encounter — notify both sides
                await push_notification(
                    player_id=player_id,
                    app_source="aura",
                    title=f"{nearby['display_name']} is nearby! 👋",
                    body="A fellow HUD wearer just entered range.",
                    priority="low",
                    db=db,
                )
        else:
            async with db.execute(
                "SELECT id, session_count FROM proximity_log WHERE player_id = ? AND nearby_player_id = ?",
                (player_id, nearby_id)
            ) as cur:
                existing = await cur.fetchone()
            if existing:
                await db.execute(
                    """UPDATE proximity_log
                       SET last_seen_at = datetime('now'), session_count = session_count + 1, last_zone = ?
                       WHERE player_id = ? AND nearby_player_id = ?""",
                    (body.zone, player_id, nearby_id))
            else:
                await db.execute(
                    """INSERT INTO proximity_log (player_id, nearby_player_id, last_zone)
                       VALUES (?, ?, ?)""",
                    (player_id, nearby_id, body.zone))
                await push_notification(
                    player_id=player_id,
                    app_source="aura",
                    title=f"{nearby['display_name']} is nearby! 👋",
                    body="A fellow HUD wearer just entered range.",
                    priority="low",
                    db=db,
                )
            await db.commit()

        encountered.append(nearby["display_name"])

    return {"status": "ok", "encountered": encountered}


# ── GET /social/nearby ────────────────────────────────────────────────────────

@router.get("/nearby")
async def get_nearby(token: str, db=Depends(get_db)):
    """
    Returns players seen within the last 90 seconds (2 heartbeat intervals).
    Used by the Aura webapp 'Who's Around' tab.
    """
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    if is_postgres():
        rows = await db.fetch(
            """SELECT p.display_name, p.avatar_uuid, pl.last_seen_at, pl.last_zone
               FROM proximity_log pl
               JOIN players p ON p.id = pl.nearby_player_id
               WHERE pl.player_id = $1
                 AND pl.last_seen_at >= (now() - interval '90 seconds')::text
               ORDER BY pl.last_seen_at DESC""",
            player["id"])
    else:
        async with db.execute(
            """SELECT p.display_name, p.avatar_uuid, pl.last_seen_at, pl.last_zone
               FROM proximity_log pl
               JOIN players p ON p.id = pl.nearby_player_id
               WHERE pl.player_id = ?
                 AND pl.last_seen_at >= datetime('now', '-90 seconds')
               ORDER BY pl.last_seen_at DESC""",
            (player["id"],)
        ) as cur:
            rows = await cur.fetchall()

    return {"nearby": [dict(r) for r in rows]}
