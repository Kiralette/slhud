"""
Profile & Settings router.

Endpoints:
  GET   /profile              — full profile data for Canvas
  POST  /profile/update       — update bio, pronouns, display name
  GET   /settings             — current settings
  POST  /settings/update      — update theme color, notification prefs, privacy, MH opt-in
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import json

from app.database import get_db, is_postgres

router = APIRouter(prefix="/profile", tags=["profile"])
settings_router = APIRouter(prefix="/settings", tags=["settings"])

VALID_COLORS = [
    "#7f77dd", "#d47a9a", "#9a7c4e", "#4a7c5f",
    "#3a6a8c", "#b8732a", "#9c5050", "#555555",
]


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    token: str
    display_name: str | None = None
    bio: str | None = None
    pronouns: str | None = None


class SettingsUpdate(BaseModel):
    token: str
    theme_case_color: str | None = None
    is_muted: bool | None = None
    is_mental_health_opted_in: bool | None = None
    notification_prefs: dict | None = None
    privacy_prefs: dict | None = None
    bedtime_slt: str | None = None
    timezone_offset_hours: int | None = None


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


# ── GET /profile ──────────────────────────────────────────────────────────────

@router.get("")
async def get_profile(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        profile = await db.fetchrow(
            "SELECT * FROM player_profiles WHERE player_id = $1", player_id)
        stats = await db.fetchrow(
            "SELECT * FROM player_stats WHERE player_id = $1", player_id)
        trait_rows = await db.fetch(
            "SELECT trait_key FROM player_traits WHERE player_id = $1", player_id)
        vibe_rows = await db.fetch(
            "SELECT * FROM vibes WHERE player_id = $1 ORDER BY applied_at DESC", player_id)
        wallet = await db.fetchrow(
            "SELECT balance FROM wallets WHERE player_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT * FROM player_profiles WHERE player_id = ?", (player_id,)) as cur:
            profile = await cur.fetchone()
        async with db.execute(
            "SELECT * FROM player_stats WHERE player_id = ?", (player_id,)) as cur:
            stats = await cur.fetchone()
        async with db.execute(
            "SELECT trait_key FROM player_traits WHERE player_id = ?", (player_id,)) as cur:
            trait_rows = await cur.fetchall()
        async with db.execute(
            "SELECT * FROM vibes WHERE player_id = ? ORDER BY applied_at DESC", (player_id,)) as cur:
            vibe_rows = await cur.fetchall()
        async with db.execute(
            "SELECT balance FROM wallets WHERE player_id = ?", (player_id,)) as cur:
            wallet = await cur.fetchone()

    return {
        "player":   player,
        "profile":  dict(profile) if profile else {},
        "stats":    dict(stats)   if stats   else {},
        "traits":   [r["trait_key"] for r in trait_rows],
        "vibes":    [dict(r) for r in vibe_rows],
        "balance":  float(wallet["balance"]) if wallet else 0.0,
    }


# ── POST /profile/update ──────────────────────────────────────────────────────

@router.post("/update")
async def update_profile(body: ProfileUpdate, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if body.display_name is not None:
        name = body.display_name.strip()[:40]
        if name:
            if is_postgres():
                await db.execute(
                    "UPDATE players SET display_name = $1 WHERE id = $2", name, player_id)
            else:
                await db.execute(
                    "UPDATE players SET display_name = ? WHERE id = ?", (name, player_id))

    profile_fields = {}
    if body.bio is not None:
        profile_fields["bio"] = body.bio.strip()[:300]
    if body.pronouns is not None:
        profile_fields["pronouns"] = body.pronouns.strip()[:30]

    if profile_fields:
        if is_postgres():
            await db.execute(
                "INSERT INTO player_profiles (player_id) VALUES ($1) ON CONFLICT (player_id) DO NOTHING",
                player_id)
            sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(profile_fields))
            await db.execute(
                f"UPDATE player_profiles SET {sets} WHERE player_id = $1",
                player_id, *profile_fields.values())
        else:
            await db.execute(
                "INSERT OR IGNORE INTO player_profiles (player_id) VALUES (?)", (player_id,))
            sets = ", ".join(f"{k} = ?" for k in profile_fields)
            await db.execute(
                f"UPDATE player_profiles SET {sets} WHERE player_id = ?",
                (*profile_fields.values(), player_id))
            await db.commit()

    return {"status": "updated"}


# ── GET /settings ─────────────────────────────────────────────────────────────

@settings_router.get("")
async def get_settings(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        row = await db.fetchrow(
            "SELECT * FROM player_settings WHERE player_id = $1", player_id)
        mh_row = await db.fetchrow(
            "SELECT is_mental_health_opted_in FROM player_profiles WHERE player_id = $1",
            player_id)
    else:
        async with db.execute(
            "SELECT * FROM player_settings WHERE player_id = ?", (player_id,)) as cur:
            row = await cur.fetchone()
        async with db.execute(
            "SELECT is_mental_health_opted_in FROM player_profiles WHERE player_id = ?",
            (player_id,)) as cur:
            mh_row = await cur.fetchone()

    settings = dict(row) if row else {
        "theme_case_color": "#7f77dd",
        "is_muted": 0,
        "notification_prefs": "{}",
        "privacy_prefs": "{}",
    }
    settings["is_mental_health_opted_in"] = bool(mh_row["is_mental_health_opted_in"]) if mh_row else False

    return settings


# ── POST /settings/update ─────────────────────────────────────────────────────

@settings_router.post("/update")
async def update_settings(body: SettingsUpdate, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    # Ensure settings row exists
    if is_postgres():
        await db.execute(
            "INSERT INTO player_settings (player_id) VALUES ($1) ON CONFLICT (player_id) DO NOTHING",
            player_id)
    else:
        await db.execute(
            "INSERT OR IGNORE INTO player_settings (player_id) VALUES (?)", (player_id,))

    fields = {}
    if body.theme_case_color is not None:
        color = body.theme_case_color.strip()
        if color in VALID_COLORS or (color.startswith("#") and len(color) in (4, 7)):
            fields["theme_case_color"] = color
    if body.is_muted is not None:
        fields["is_muted"] = int(body.is_muted)
    if body.notification_prefs is not None:
        fields["notification_prefs"] = json.dumps(body.notification_prefs)
    if body.privacy_prefs is not None:
        fields["privacy_prefs"] = json.dumps(body.privacy_prefs)

    if fields:
        if is_postgres():
            sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
            await db.execute(
                f"UPDATE player_settings SET {sets} WHERE player_id = $1",
                player_id, *fields.values())
        else:
            sets = ", ".join(f"{k} = ?" for k in fields)
            await db.execute(
                f"UPDATE player_settings SET {sets} WHERE player_id = ?",
                (*fields.values(), player_id))

    # MH opt-in lives in player_profiles
    if body.is_mental_health_opted_in is not None:
        val = int(body.is_mental_health_opted_in)
        if is_postgres():
            await db.execute(
                "INSERT INTO player_profiles (player_id) VALUES ($1) ON CONFLICT (player_id) DO NOTHING",
                player_id)
            await db.execute(
                "UPDATE player_profiles SET is_mental_health_opted_in = $1 WHERE player_id = $2",
                val, player_id)
        else:
            await db.execute(
                "INSERT OR IGNORE INTO player_profiles (player_id) VALUES (?)", (player_id,))
            await db.execute(
                "UPDATE player_profiles SET is_mental_health_opted_in = ? WHERE player_id = ?",
                (val, player_id))

    if not is_postgres():
        await db.commit()

    return {"status": "updated"}
