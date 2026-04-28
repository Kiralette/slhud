"""
Needs router — read-only endpoints for need state and history.
These are what the phone app calls when you tap on a need's app icon.
"""

from fastapi import APIRouter, Depends, HTTPException
from app.database import get_db
from app.services.auth import get_current_player
from app.services.needs import get_all_needs, get_zone
from app.config import get_config
import aiosqlite

router = APIRouter(prefix="/needs", tags=["needs"])


@router.get("/")
async def get_needs(
    player: dict = Depends(get_current_player),
    db: aiosqlite.Connection = Depends(get_db)
):
    """Returns all 7 needs with current value and zone for this player."""
    cfg = get_config()
    needs_cfg = cfg["needs"]
    all_needs = await get_all_needs(player["id"], db)

    return {
        "player_id": player["id"],
        "display_name": player["display_name"],
        "needs": [
            {
                "need_key": n["need_key"],
                "display_name": needs_cfg[n["need_key"]]["display_name"],
                "icon": needs_cfg[n["need_key"]]["icon"],
                "value": round(n["value"], 1),
                "zone": get_zone(n["value"], needs_cfg[n["need_key"]]),
                "last_updated": n["last_updated"]
            }
            for n in all_needs
            if n["need_key"] in needs_cfg
        ]
    }


@router.get("/{need_key}")
async def get_need_detail(
    need_key: str,
    player: dict = Depends(get_current_player),
    db: aiosqlite.Connection = Depends(get_db)
):
    """
    Returns detailed info for one need including the last 20 log entries.
    This is what populates the individual need app screen on the phone.
    """
    cfg = get_config()
    needs_cfg = cfg["needs"]

    if need_key not in needs_cfg:
        raise HTTPException(status_code=404, detail=f"Need '{need_key}' not found.")

    need_cfg = needs_cfg[need_key]
    player_id = player["id"]

    # Get current value
    async with db.execute(
        "SELECT value, last_updated FROM needs WHERE player_id = ? AND need_key = ?",
        (player_id, need_key)
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Need not found for this player.")

    value = round(float(row["value"]), 1)
    zone = get_zone(value, need_cfg)

    # Get last 20 log entries for this need
    async with db.execute(
        """SELECT action_text, delta, timestamp
           FROM event_log
           WHERE player_id = ? AND need_key = ?
           ORDER BY timestamp DESC
           LIMIT 20""",
        (player_id, need_key)
    ) as cursor:
        log_rows = await cursor.fetchall()

    # Zone descriptions shown as the subtitle in the app
    zone_labels = {
        "thriving":  f"Feeling great",
        "okay":      f"Doing fine",
        "struggling": f"Getting low",
        "critical":  f"Critically low — act soon",
        "zero":      f"Depleted — consequences active"
    }

    return {
        "need_key": need_key,
        "display_name": need_cfg["display_name"],
        "icon": need_cfg["icon"],
        "value": value,
        "zone": zone,
        "zone_label": zone_labels.get(zone, ""),
        "last_updated": row["last_updated"],
        "log": [
            {
                "action_text": r["action_text"],
                "delta": r["delta"],
                "timestamp": r["timestamp"]
            }
            for r in log_rows
        ]
    }


@router.get("/moodlets/active")
async def get_active_moodlets(
    player: dict = Depends(get_current_player),
    db: aiosqlite.Connection = Depends(get_db)
):
    """Returns all currently active moodlets for the player."""
    cfg = get_config()
    moodlets_cfg = cfg["moodlets"]
    player_id = player["id"]

    async with db.execute(
        """SELECT moodlet_key, applied_at, expires_at, is_negative
           FROM moodlets
           WHERE player_id = ?
           AND (expires_at IS NULL OR expires_at > datetime('now'))
           ORDER BY applied_at DESC""",
        (player_id,)
    ) as cursor:
        rows = await cursor.fetchall()

    return {
        "player_id": player_id,
        "moodlets": [
            {
                "moodlet_key": r["moodlet_key"],
                "display_name": moodlets_cfg.get(r["moodlet_key"], {}).get("display_name", r["moodlet_key"]),
                "icon": moodlets_cfg.get(r["moodlet_key"], {}).get("icon", ""),
                "description": moodlets_cfg.get(r["moodlet_key"], {}).get("description", ""),
                "is_negative": bool(r["is_negative"]),
                "applied_at": r["applied_at"],
                "expires_at": r["expires_at"]
            }
            for r in rows
        ]
    }
