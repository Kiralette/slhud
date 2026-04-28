"""
Actions router — handles player actions and state sync.
Compatible with both SQLite and PostgreSQL.
"""

from fastapi import APIRouter, Depends
from app.database import get_db, is_postgres
from app.services.auth import get_current_player
from app.services.needs import process_action, get_all_needs, get_zone
from app.models.action import ActionRequest, ActionResponse, NeedState, LogEntry
from app.config import get_config

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("/action", response_model=ActionResponse)
async def perform_action(body: ActionRequest, player: dict = Depends(get_current_player), db=Depends(get_db)):
    cfg = get_config()
    player_id = player["id"]

    result = await process_action(
        player_id=player_id, object_key=body.object_key,
        duration_seconds=body.duration_seconds, quality_tier=body.quality_tier, db=db
    )

    if is_postgres():
        await db.execute("UPDATE players SET last_seen = now()::text WHERE id = $1", player_id)
    else:
        await db.execute("UPDATE players SET last_seen = datetime('now') WHERE id = ?", (player_id,))
        await db.commit()

    all_needs = await get_all_needs(player_id, db)
    needs_cfg = cfg["needs"]

    return ActionResponse(
        success=True,
        needs=[NeedState(need_key=n["need_key"], value=round(n["value"], 1), zone=get_zone(n["value"], needs_cfg[n["need_key"]])) for n in all_needs if n["need_key"] in needs_cfg],
        log_entries=[LogEntry(action_text=e["action_text"], delta=e["delta"], need_key=e.get("need_key"), timestamp=e["timestamp"]) for e in result["log_entries"]],
        moodlets_applied=result.get("moodlets_applied", []),
        message=result["message"]
    )


@router.get("/sync", response_model=ActionResponse)
async def sync(player: dict = Depends(get_current_player), db=Depends(get_db)):
    cfg = get_config()
    player_id = player["id"]

    if is_postgres():
        await db.execute("UPDATE players SET is_online = 1, last_seen = now()::text WHERE id = $1", player_id)
        rows = await db.fetch("SELECT * FROM event_log WHERE player_id = $1 ORDER BY timestamp DESC LIMIT 10", player_id)
    else:
        await db.execute("UPDATE players SET is_online = 1, last_seen = datetime('now') WHERE id = ?", (player_id,))
        await db.commit()
        async with db.execute("SELECT * FROM event_log WHERE player_id = ? ORDER BY timestamp DESC LIMIT 10", (player_id,)) as cursor:
            rows = await cursor.fetchall()

    all_needs = await get_all_needs(player_id, db)
    needs_cfg = cfg["needs"]

    return ActionResponse(
        success=True,
        needs=[NeedState(need_key=n["need_key"], value=round(n["value"], 1), zone=get_zone(n["value"], needs_cfg[n["need_key"]])) for n in all_needs if n["need_key"] in needs_cfg],
        log_entries=[LogEntry(action_text=r["action_text"], delta=r["delta"], need_key=r["need_key"], timestamp=r["timestamp"]) for r in rows],
        moodlets_applied=[],
        message=f"Synced {player['display_name']}"
    )
