"""
Actions router — handles player actions and state sync.
"""

from fastapi import APIRouter, Depends, HTTPException
from app.database import get_db
from app.services.auth import get_current_player
from app.services.needs import process_action, get_all_needs, get_zone
from app.models.action import ActionRequest, ActionResponse, NeedState, LogEntry
from app.config import get_config
import aiosqlite

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("/action", response_model=ActionResponse)
async def perform_action(
    body: ActionRequest,
    player: dict = Depends(get_current_player),
    db: aiosqlite.Connection = Depends(get_db)
):
    """
    Called when a player uses an object in-world.
    Calculates gains, updates the database, returns the new state.
    """
    cfg = get_config()
    player_id = player["id"]

    result = await process_action(
        player_id=player_id,
        object_key=body.object_key,
        duration_seconds=body.duration_seconds,
        quality_tier=body.quality_tier,
        db=db
    )

    await db.commit()

    # Update last_seen
    await db.execute(
        "UPDATE players SET last_seen = datetime('now') WHERE id = ?",
        (player_id,)
    )
    await db.commit()

    # Build the full needs response
    all_needs = await get_all_needs(player_id, db)
    needs_cfg = cfg["needs"]

    need_states = [
        NeedState(
            need_key=n["need_key"],
            value=round(n["value"], 1),
            zone=get_zone(n["value"], needs_cfg[n["need_key"]])
        )
        for n in all_needs
        if n["need_key"] in needs_cfg
    ]

    log_entries = [
        LogEntry(
            action_text=e["action_text"],
            delta=e["delta"],
            need_key=e.get("need_key"),
            timestamp=e["timestamp"]
        )
        for e in result["log_entries"]
    ]

    return ActionResponse(
        success=True,
        needs=need_states,
        log_entries=log_entries,
        moodlets_applied=result.get("moodlets_applied", []),
        message=result["message"]
    )


@router.get("/sync", response_model=ActionResponse)
async def sync(
    player: dict = Depends(get_current_player),
    db: aiosqlite.Connection = Depends(get_db)
):
    """
    Called when the HUD is first attached or after being offline.
    Returns the player's full current state so the HUD can refresh
    all 7 need bars at once — including any decay that happened offline.
    """
    cfg = get_config()
    player_id = player["id"]

    # Mark player as online
    await db.execute(
        "UPDATE players SET is_online = 1, last_seen = datetime('now') WHERE id = ?",
        (player_id,)
    )
    await db.commit()

    all_needs = await get_all_needs(player_id, db)
    needs_cfg = cfg["needs"]

    need_states = [
        NeedState(
            need_key=n["need_key"],
            value=round(n["value"], 1),
            zone=get_zone(n["value"], needs_cfg[n["need_key"]])
        )
        for n in all_needs
        if n["need_key"] in needs_cfg
    ]

    # Fetch the last 10 log entries to populate app history
    async with db.execute(
        """SELECT * FROM event_log
           WHERE player_id = ?
           ORDER BY timestamp DESC LIMIT 10""",
        (player_id,)
    ) as cursor:
        rows = await cursor.fetchall()

    log_entries = [
        LogEntry(
            action_text=r["action_text"],
            delta=r["delta"],
            need_key=r["need_key"],
            timestamp=r["timestamp"]
        )
        for r in rows
    ]

    return ActionResponse(
        success=True,
        needs=need_states,
        log_entries=log_entries,
        moodlets_applied=[],
        message=f"Synced {player['display_name']}"
    )
