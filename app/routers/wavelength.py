"""
Wavelength router — music streaming session management.

POST /wavelength/start  — tune into a station (creates/updates streaming session)
POST /wavelength/stop   — stop current session, log duration + XP
GET  /wavelength/status — current session info (used by LSL HUD to get stream URL)
"""

import aiohttp

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
import httpx

from app.database import get_db, is_postgres
from app.config import get_config
from app.services.notifications import push_notification

router = APIRouter(tags=["wavelength"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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


async def _is_premium(player_id: int, db) -> bool:
    if is_postgres():
        row = await db.fetchrow(
            "SELECT id FROM subscriptions WHERE player_id = $1 AND subscription_key = 'wavelength_premium' AND is_active = 1",
            player_id)
        return row is not None
    else:
        async with db.execute(
            "SELECT id FROM subscriptions WHERE player_id = ? AND subscription_key = 'wavelength_premium' AND is_active = 1",
            (player_id,)
        ) as cur:
            row = await cur.fetchone()
            return row is not None


async def _close_active_session(player_id: int, db, now: str):
    """Close any open streaming session, compute duration, award XP."""
    cfg = get_config()
    wave_cfg = cfg.get("wavelength", {})

    if is_postgres():
        session = await db.fetchrow(
            "SELECT * FROM streaming_sessions WHERE player_id = $1 AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            player_id)
    else:
        async with db.execute(
            "SELECT * FROM streaming_sessions WHERE player_id = ? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            (player_id,)
        ) as cur:
            session = await cur.fetchone()

    if not session:
        return

    session = dict(session)
    started = datetime.fromisoformat(session["started_at"].replace(" ", "T"))
    ended   = datetime.fromisoformat(now.replace(" ", "T"))
    minutes = max(0.0, (ended - started).total_seconds() / 60.0)

    # Cap XP credit at 4 hours per session
    minutes_for_xp = min(minutes, 240.0)

    # Calculate XP from station config
    station_key = session["station_key"]
    station_cfg = wave_cfg.get("stations", {}).get(station_key, {})
    xp_effects  = station_cfg.get("xp_effect", {})
    premium_mult = 2.0 if session.get("is_premium") else 1.0

    xp_total = 0.0
    for skill_key, rate in xp_effects.items():
        if skill_key.startswith("purpose") or skill_key.startswith("social"):
            continue  # those are need effects, not skill XP
        xp_gain = float(rate) * minutes_for_xp * premium_mult
        xp_total += xp_gain
        # Award XP to skill
        if is_postgres():
            await db.execute(
                "UPDATE skills SET xp = xp + $1, last_updated = $2 WHERE player_id = $3 AND skill_key = $4",
                round(xp_gain, 3), now, player_id, skill_key)
        else:
            await db.execute(
                "UPDATE skills SET xp = xp + ?, last_updated = ? WHERE player_id = ? AND skill_key = ?",
                (round(xp_gain, 3), now, player_id, skill_key))

    # Close the session row
    if is_postgres():
        await db.execute(
            "UPDATE streaming_sessions SET ended_at = $1, duration_minutes = $2, xp_earned = $3 WHERE id = $4",
            now, round(minutes, 2), round(xp_total, 3), session["id"])
    else:
        await db.execute(
            "UPDATE streaming_sessions SET ended_at = ?, duration_minutes = ?, xp_earned = ? WHERE id = ?",
            (now, round(minutes, 2), round(xp_total, 3), session["id"]))
        await db.commit()


# ── GET /wavelength/stream ────────────────────────────────────────────────────

@router.get("/wavelength/stream")
async def proxy_stream(url: str):
    """Proxy an audio stream to avoid CORS issues in the browser."""
    http_url = url.replace("https://", "http://", 1)

    async def generator():
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(http_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Icy-MetaData": "1",
                "Connection": "keep-alive",
            }) as r:
                async for chunk in r.content.iter_chunked(4096):
                    if chunk:
                        yield chunk

    return StreamingResponse(
        generator(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
            "Access-Control-Allow-Origin": "*",
            "X-Accel-Buffering": "no",  # tells Render/nginx not to buffer the stream
        },
    )


# ── Models ────────────────────────────────────────────────────────────────────

class TuneInRequest(BaseModel):
    token: str
    station_key: str


class StopRequest(BaseModel):
    token: str


class StatusRequest(BaseModel):
    token: str


# ── POST /wavelength/start ────────────────────────────────────────────────────

@router.post("/wavelength/start")
async def wavelength_start(body: TuneInRequest, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    cfg = get_config()
    wave_cfg = cfg.get("wavelength", {})
    stations = wave_cfg.get("stations", {})
    free_keys = set(wave_cfg.get("free_tier_stations", []))

    station_cfg = stations.get(body.station_key)
    if not station_cfg:
        raise HTTPException(status_code=404, detail=f"Station '{body.station_key}' not found.")

    is_prem_station = station_cfg.get("is_premium", False)
    player_premium  = await _is_premium(player_id, db)

    # Access check
    if is_prem_station and not player_premium and body.station_key not in free_keys:
        return {"error": "This station requires Wavelength Premium. Subscribe in the Haul app."}

    stream_url = station_cfg.get("stream_url", "")
    now = _now_str()

    # Close any existing session first
    await _close_active_session(player_id, db, now)

    # Open new session
    if is_postgres():
        await db.execute(
            """INSERT INTO streaming_sessions (player_id, station_key, started_at, is_premium)
               VALUES ($1, $2, $3, $4)""",
            player_id, body.station_key, now, 1 if player_premium else 0)
    else:
        await db.execute(
            """INSERT INTO streaming_sessions (player_id, station_key, started_at, is_premium)
               VALUES (?, ?, ?, ?)""",
            (player_id, body.station_key, now, 1 if player_premium else 0))
        await db.commit()

    # Apply tune-in bonus if configured
    tune_in_bonus = station_cfg.get("tune_in_bonus", {})
    bonus_applied = {}
    for need_key, amount in tune_in_bonus.items():
        if is_postgres():
            await db.execute(
                "UPDATE needs SET value = LEAST(100.0, value + $1), last_updated = $2 WHERE player_id = $3 AND need_key = $4",
                float(amount), now, player_id, need_key)
        else:
            await db.execute(
                "UPDATE needs SET value = MIN(100.0, value + ?), last_updated = ? WHERE player_id = ? AND need_key = ?",
                (float(amount), now, player_id, need_key))
        bonus_applied[need_key] = float(amount)

    if not is_postgres():
        await db.commit()

    return {
        "ok": True,
        "station_key": body.station_key,
        "station_name": station_cfg.get("display_name", body.station_key),
        "stream_url": stream_url,
        "is_premium_session": player_premium,
        "tune_in_bonus": bonus_applied,
    }


# ── POST /wavelength/stop ─────────────────────────────────────────────────────

@router.post("/wavelength/stop")
async def wavelength_stop(body: StopRequest, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    now = _now_str()
    await _close_active_session(player["id"], db, now)
    if not is_postgres():
        await db.commit()

    return {"ok": True}


# ── GET /wavelength/status ────────────────────────────────────────────────────

@router.get("/wavelength/status")
async def wavelength_status(token: str, db=Depends(get_db)):
    """
    Called by LSL HUD on attach/resume to get the current stream URL
    so it can resume playback without the player re-tapping.
    """
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    cfg = get_config()
    wave_cfg = cfg.get("wavelength", {})

    if is_postgres():
        session = await db.fetchrow(
            "SELECT * FROM streaming_sessions WHERE player_id = $1 AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            player_id)
    else:
        async with db.execute(
            "SELECT * FROM streaming_sessions WHERE player_id = ? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            (player_id,)
        ) as cur:
            session = await cur.fetchone()

    if not session:
        return {"active": False, "station_key": None, "stream_url": None}

    session = dict(session)
    station_key = session["station_key"]
    station_cfg = wave_cfg.get("stations", {}).get(station_key, {})

    return {
        "active": True,
        "station_key": station_key,
        "station_name": station_cfg.get("display_name", station_key),
        "stream_url": station_cfg.get("stream_url", ""),
        "started_at": session["started_at"],
    }
