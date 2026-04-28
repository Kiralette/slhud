"""
Players router — handles registration and player profile endpoints.
Compatible with both SQLite and PostgreSQL.
"""

from fastapi import APIRouter, Depends, HTTPException
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
            "UPDATE players SET display_name = $1, last_seen = now()::text, is_online = 1 WHERE avatar_uuid = $2",
            body.display_name, body.avatar_uuid
        )
        return RegisterResponse(
            success=True,
            player_id=existing["id"],
            token=existing["token"],
            display_name=body.display_name,
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
            "UPDATE players SET display_name = ?, last_seen = datetime('now'), is_online = 1 WHERE avatar_uuid = ?",
            (body.display_name, body.avatar_uuid)
        )
        await db.commit()
        p = dict(existing)
        return RegisterResponse(success=True, player_id=p["id"], token=p["token"], display_name=body.display_name, is_new=False)

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
