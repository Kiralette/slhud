"""
Needs router — read-only endpoints for need state and history.
Compatible with both SQLite and PostgreSQL.
"""

from fastapi import APIRouter, Depends, HTTPException
from app.database import get_db, is_postgres
from app.services.auth import get_current_player
from app.services.needs import get_all_needs, get_zone
from app.config import get_config

router = APIRouter(prefix="/needs", tags=["needs"])


@router.get("/")
async def get_needs(player: dict = Depends(get_current_player), db=Depends(get_db)):
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
            for n in all_needs if n["need_key"] in needs_cfg
        ]
    }


@router.get("/vibes/active")
async def get_active_vibes(player: dict = Depends(get_current_player), db=Depends(get_db)):
    cfg = get_config()
    vibes_cfg = cfg["vibes"]
    player_id = player["id"]

    if is_postgres():
        rows = await db.fetch(
            "SELECT vibe_key, applied_at, expires_at, is_negative FROM vibes WHERE player_id = $1 AND (expires_at IS NULL OR expires_at > now()::text) ORDER BY applied_at DESC",
            player_id
        )
    else:
        async with db.execute(
            "SELECT vibe_key, applied_at, expires_at, is_negative FROM vibes WHERE player_id = ? AND (expires_at IS NULL OR expires_at > datetime('now')) ORDER BY applied_at DESC",
            (player_id,)
        ) as cursor:
            rows = await cursor.fetchall()

    return {
        "player_id": player_id,
        "vibes": [
            {
                "vibe_key": r["vibe_key"],
                "display_name": vibes_cfg.get(r["vibe_key"], {}).get("display_name", r["vibe_key"]),
                "icon": vibes_cfg.get(r["vibe_key"], {}).get("icon", ""),
                "description": vibes_cfg.get(r["vibe_key"], {}).get("description", ""),
                "is_negative": bool(r["is_negative"]),
                "applied_at": r["applied_at"],
                "expires_at": r["expires_at"]
            }
            for r in rows
        ]
    }


@router.get("/{need_key}")
async def get_need_detail(need_key: str, player: dict = Depends(get_current_player), db=Depends(get_db)):
    cfg = get_config()
    needs_cfg = cfg["needs"]

    if need_key not in needs_cfg:
        raise HTTPException(status_code=404, detail=f"Need '{need_key}' not found.")

    need_cfg = needs_cfg[need_key]
    player_id = player["id"]

    if is_postgres():
        row = await db.fetchrow("SELECT value, last_updated FROM needs WHERE player_id = $1 AND need_key = $2", player_id, need_key)
        log_rows = await db.fetch(
            "SELECT action_text, delta, timestamp FROM event_log WHERE player_id = $1 AND need_key = $2 ORDER BY timestamp DESC LIMIT 20",
            player_id, need_key
        )
    else:
        async with db.execute("SELECT value, last_updated FROM needs WHERE player_id = ? AND need_key = ?", (player_id, need_key)) as cursor:
            row = await cursor.fetchone()
        async with db.execute(
            "SELECT action_text, delta, timestamp FROM event_log WHERE player_id = ? AND need_key = ? ORDER BY timestamp DESC LIMIT 20",
            (player_id, need_key)
        ) as cursor:
            log_rows = await cursor.fetchall()

    if not row:
        raise HTTPException(status_code=404, detail="Need not found for this player.")

    value = round(float(row["value"]), 1)
    zone_labels = {
        "thriving": "Feeling great", "okay": "Doing fine", "struggling": "Getting low",
        "critical": "Critically low — act soon", "zero": "Depleted — consequences active"
    }
    zone = get_zone(value, need_cfg)
    return {
        "need_key": need_key, "display_name": need_cfg["display_name"], "icon": need_cfg["icon"],
        "value": value, "zone": zone, "zone_label": zone_labels.get(zone, ""),
        "last_updated": row["last_updated"],
        "log": [{"action_text": r["action_text"], "delta": r["delta"], "timestamp": r["timestamp"]} for r in log_rows]
    }
