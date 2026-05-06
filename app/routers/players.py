"""
Players router — handles registration and player profile endpoints.
Compatible with both SQLite and PostgreSQL.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from app.database import get_db, is_postgres
from app.services.auth import generate_token
from app.models.player import RegisterRequest, RegisterResponse, PlayerResponse
from app.config import all_need_keys, all_skill_keys

router = APIRouter(prefix="/players", tags=["players"])


@router.post("/register", response_model=RegisterResponse)
async def register(body: RegisterRequest, db=Depends(get_db)):
    if is_postgres():
        return await _register_pg(body, db)
    else:
        return await _register_sqlite(body, db)


async def _register_pg(body, conn):
    existing = await conn.fetchrow(
        "SELECT * FROM players WHERE avatar_uuid = $1", body.avatar_uuid
    )
    if existing:
        await conn.execute(
            "UPDATE players SET last_seen = now()::text, is_online = 1 WHERE avatar_uuid = $1",
            body.avatar_uuid
        )
        return RegisterResponse(
            success=True,
            player_id=existing["id"],
            token=existing["token"],
            display_name=existing["display_name"],
            is_new=False
        )

    token = generate_token()
    player_id = await conn.fetchval(
        "INSERT INTO players (avatar_uuid, display_name, token, is_online) VALUES ($1, $2, $3, 1) RETURNING id",
        body.avatar_uuid, body.display_name, token
    )

    for need_key in all_need_keys():
        await conn.execute(
            "INSERT INTO needs (player_id, need_key, value) VALUES ($1, $2, 100.0)",
            player_id, need_key
        )
    for skill_key in all_skill_keys():
        await conn.execute(
            "INSERT INTO skills (player_id, skill_key, level, xp) VALUES ($1, $2, 0, 0.0)",
            player_id, skill_key
        )
    await conn.execute(
        "INSERT INTO event_log (player_id, need_key, action_text, delta, value_after) VALUES ($1, NULL, $2, 0, NULL)",
        player_id, f"{body.display_name} registered and attached the HUD."
    )

    print(f"   New player registered: {body.display_name} ({body.avatar_uuid[:8]}...)")
    return RegisterResponse(success=True, player_id=player_id, token=token, display_name=body.display_name, is_new=True)


async def _register_sqlite(body, db):
    import aiosqlite
    async with db.execute("SELECT * FROM players WHERE avatar_uuid = ?", (body.avatar_uuid,)) as cursor:
        existing = await cursor.fetchone()

    if existing:
        await db.execute(
            "UPDATE players SET last_seen = datetime('now'), is_online = 1 WHERE avatar_uuid = ?",
            (body.avatar_uuid,)
        )
        await db.commit()
        p = dict(existing)
        return RegisterResponse(success=True, player_id=p["id"], token=p["token"], display_name=p["display_name"], is_new=False)

    token = generate_token()
    async with db.execute(
        "INSERT INTO players (avatar_uuid, display_name, token, is_online) VALUES (?, ?, ?, 1)",
        (body.avatar_uuid, body.display_name, token)
    ) as cursor:
        player_id = cursor.lastrowid

    for need_key in all_need_keys():
        await db.execute("INSERT INTO needs (player_id, need_key, value) VALUES (?, ?, 100.0)", (player_id, need_key))
    for skill_key in all_skill_keys():
        await db.execute("INSERT INTO skills (player_id, skill_key, level, xp) VALUES (?, ?, 0, 0.0)", (player_id, skill_key))
    await db.execute(
        "INSERT INTO event_log (player_id, need_key, action_text, delta, value_after) VALUES (?, NULL, ?, 0, NULL)",
        (player_id, f"{body.display_name} registered and attached the HUD.")
    )
    await db.commit()

    print(f"   New player registered: {body.display_name} ({body.avatar_uuid[:8]}...)")
    return RegisterResponse(success=True, player_id=player_id, token=token, display_name=body.display_name, is_new=True)


@router.get("/{player_id}", response_model=PlayerResponse)
async def get_player(player_id: int, db=Depends(get_db)):
    if is_postgres():
        player = await db.fetchrow("SELECT * FROM players WHERE id = $1", player_id)
    else:
        async with db.execute("SELECT * FROM players WHERE id = ?", (player_id,)) as cursor:
            player = await cursor.fetchone()

    if not player:
        raise HTTPException(status_code=404, detail="Player not found.")

    p = dict(player)
    return PlayerResponse(
        player_id=p["id"], avatar_uuid=p["avatar_uuid"], display_name=p["display_name"],
        registered_at=p["registered_at"], last_seen=p["last_seen"], is_online=bool(p["is_online"])
    )


@router.get("/avatar-image/{avatar_uuid}")
async def avatar_image(avatar_uuid: str, db=Depends(get_db)):
    """Proxy SL avatar profile image — looks up stored texture UUID first."""
    import httpx

    pic_uuid = None
    if is_postgres():
        row = await db.fetchrow(
            "SELECT profile_pic_uuid FROM player_profiles WHERE player_id = (SELECT id FROM players WHERE avatar_uuid = $1)",
            avatar_uuid)
        if row:
            pic_uuid = row["profile_pic_uuid"]
    else:
        async with db.execute(
            "SELECT profile_pic_uuid FROM player_profiles WHERE player_id = (SELECT id FROM players WHERE avatar_uuid = ?)",
            (avatar_uuid,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                pic_uuid = row["profile_pic_uuid"]

    if not pic_uuid:
        raise HTTPException(status_code=404, detail="No profile picture stored.")

    url = f"https://secondlife.com/app/image/{pic_uuid}/1"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, follow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            if r.status_code == 200:
                content_type = r.headers.get("content-type", "image/jpeg")
                return Response(content=r.content, media_type=content_type)
    except Exception:
        pass
    raise HTTPException(status_code=404, detail="Avatar image not found.")


# ── VALIDATE TOKEN ────────────────────────────────────────────────────────────

@router.get("/me")
async def get_me(authorization: str = None, db=Depends(get_db)):
    """
    Lightweight token validation endpoint.
    Called by the LSL HUD on reattach to confirm a cached token still exists.
    Returns 200 + player id if valid, 401 if not.
    """
    from fastapi import Header
    from typing import Optional

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization format.")

    token = authorization.split(" ", 1)[1].strip()

    if is_postgres():
        row = await db.fetchrow(
            "SELECT id, display_name FROM players WHERE token = $1 AND is_banned = 0", token)
    else:
        async with db.execute(
            "SELECT id, display_name FROM players WHERE token = ? AND is_banned = 0", (token,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Token invalid or player not found.")

    return {"player_id": row["id"], "display_name": row["display_name"]}
