"""
Players router — handles registration and player profile endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from app.database import get_db
from app.services.auth import generate_token
from app.models.player import RegisterRequest, RegisterResponse, PlayerResponse
from app.config import all_need_keys, all_skill_keys
import aiosqlite

router = APIRouter(prefix="/players", tags=["players"])


@router.post("/register", response_model=RegisterResponse)
async def register(
    body: RegisterRequest,
    db: aiosqlite.Connection = Depends(get_db)
):
    """
    Called when a player attaches the HUD for the first time.
    If the avatar_uuid already exists in the database, we just
    return their existing token (so re-attaching is safe).
    If they're brand new, we create their full player record.
    """

    # Check if this avatar has registered before
    async with db.execute(
        "SELECT * FROM players WHERE avatar_uuid = ?",
        (body.avatar_uuid,)
    ) as cursor:
        existing = await cursor.fetchone()

    if existing:
        # Already registered — update their display name and last seen,
        # then return their existing token
        await db.execute(
            """UPDATE players
               SET display_name = ?, last_seen = datetime('now'), is_online = 1
               WHERE avatar_uuid = ?""",
            (body.display_name, body.avatar_uuid)
        )
        await db.commit()
        player = dict(existing)
        return RegisterResponse(
            success=True,
            player_id=player["id"],
            token=player["token"],
            display_name=body.display_name,
            is_new=False
        )

    # Brand new player — create everything from scratch
    token = generate_token()

    # Insert the player row
    async with db.execute(
        """INSERT INTO players (avatar_uuid, display_name, token, is_online)
           VALUES (?, ?, ?, 1)""",
        (body.avatar_uuid, body.display_name, token)
    ) as cursor:
        player_id = cursor.lastrowid

    # Seed all 7 needs at 100 for this new player
    for need_key in all_need_keys():
        await db.execute(
            """INSERT INTO needs (player_id, need_key, value)
               VALUES (?, ?, 100.0)""",
            (player_id, need_key)
        )

    # Seed skill rows at level 0 (locked until first use)
    for skill_key in all_skill_keys():
        await db.execute(
            """INSERT INTO skills (player_id, skill_key, level, xp)
               VALUES (?, ?, 0, 0.0)""",
            (player_id, skill_key)
        )

    # Write a welcome entry to the event log
    await db.execute(
        """INSERT INTO event_log (player_id, need_key, action_text, delta, value_after)
           VALUES (?, NULL, ?, 0, NULL)""",
        (player_id, f"{body.display_name} registered and attached the HUD.")
    )

    await db.commit()

    print(f"   ✨ New player registered: {body.display_name} ({body.avatar_uuid[:8]}...)")

    return RegisterResponse(
        success=True,
        player_id=player_id,
        token=token,
        display_name=body.display_name,
        is_new=True
    )


@router.get("/{player_id}", response_model=PlayerResponse)
async def get_player(
    player_id: int,
    db: aiosqlite.Connection = Depends(get_db)
):
    """Fetch a player's basic profile by their ID."""
    async with db.execute(
        "SELECT * FROM players WHERE id = ?", (player_id,)
    ) as cursor:
        player = await cursor.fetchone()

    if not player:
        raise HTTPException(status_code=404, detail="Player not found.")

    p = dict(player)
    return PlayerResponse(
        player_id=p["id"],
        avatar_uuid=p["avatar_uuid"],
        display_name=p["display_name"],
        registered_at=p["registered_at"],
        last_seen=p["last_seen"],
        is_online=bool(p["is_online"])
    )
