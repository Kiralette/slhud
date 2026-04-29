"""
Cycle router — menstrual cycle tracking (Flo-style).

Only accessible to players with biology_agab = 'female' or 'intersex'
in their profile (or if they've opted in manually).

Endpoints:
  POST  /cycle/log-start      — log period start + duration
  POST  /cycle/log-end        — log period end
  GET   /cycle/history        — all logged cycles
  GET   /cycle/prediction     — predicted next window + calendar data
  POST  /cycle/skip           — skip / mark no period this month
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, date, timedelta

from app.database import get_db, is_postgres
from app.services.notifications import push_notification

router = APIRouter(prefix="/cycle", tags=["cycle"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class LogStart(BaseModel):
    token: str
    cycle_start_slt: str         # YYYY-MM-DD
    period_duration_days: int    # 3–8


class LogEnd(BaseModel):
    token: str
    cycle_end_slt: str           # YYYY-MM-DD


class SkipCycle(BaseModel):
    token: str
    note: str | None = None


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


async def _check_cycle_eligible(player_id: int, db) -> bool:
    """Returns True if player has female/intersex biology or mental health opted in."""
    if is_postgres():
        row = await db.fetchrow(
            "SELECT biology_agab FROM player_profiles WHERE player_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT biology_agab FROM player_profiles WHERE player_id = ?", (player_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return False
    agab = (row["biology_agab"] or "").lower()
    return agab in ("female", "intersex", "")  # empty = not filled out = allow access


async def _recalculate_prediction(player_id: int, db):
    """
    Recalculates avg_cycle_length and next_predicted_start from all completed cycles.
    Requires 2+ cycles to make a prediction.
    """
    if is_postgres():
        rows = await db.fetch(
            """SELECT cycle_start_slt, cycle_end_slt, cycle_length_days
               FROM cycle_log
               WHERE player_id = $1
                 AND cycle_length_days IS NOT NULL
                 AND is_manual_override = 0
               ORDER BY cycle_start_slt DESC""",
            player_id)
    else:
        async with db.execute(
            """SELECT cycle_start_slt, cycle_end_slt, cycle_length_days
               FROM cycle_log
               WHERE player_id = ?
                 AND cycle_length_days IS NOT NULL
                 AND is_manual_override = 0
               ORDER BY cycle_start_slt DESC""",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    if len(rows) < 2:
        return None  # Not enough data

    lengths = [r["cycle_length_days"] for r in rows if r["cycle_length_days"]]
    if not lengths:
        return None

    avg_len = sum(lengths) / len(lengths)

    # Next predicted start = most recent cycle start + avg length
    last_start_str = rows[0]["cycle_start_slt"]
    try:
        last_start = date.fromisoformat(last_start_str[:10])
    except Exception:
        return None

    next_start = last_start + timedelta(days=round(avg_len))
    next_start_str = next_start.isoformat()

    if is_postgres():
        await db.execute(
            """UPDATE cycle_log
               SET avg_cycle_length = $1, next_predicted_start = $2
               WHERE player_id = $3
                 AND cycle_start_slt = $4""",
            avg_len, next_start_str, player_id, last_start_str)
    else:
        await db.execute(
            """UPDATE cycle_log
               SET avg_cycle_length = ?, next_predicted_start = ?
               WHERE player_id = ?
                 AND cycle_start_slt = ?""",
            (avg_len, next_start_str, player_id, last_start_str))
        await db.commit()

    return {"avg_cycle_length": avg_len, "next_predicted_start": next_start_str}


# ── POST /cycle/log-start ─────────────────────────────────────────────────────

@router.post("/log-start")
async def log_cycle_start(body: LogStart, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    duration = max(3, min(8, body.period_duration_days))

    # Validate date
    try:
        start_date = date.fromisoformat(body.cycle_start_slt[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    if is_postgres():
        await db.execute(
            """INSERT INTO cycle_log
               (player_id, cycle_start_slt, period_duration_days)
               VALUES ($1, $2, $3)
               ON CONFLICT DO NOTHING""",
            player_id, body.cycle_start_slt[:10], duration)
    else:
        await db.execute(
            """INSERT OR IGNORE INTO cycle_log
               (player_id, cycle_start_slt, period_duration_days)
               VALUES (?, ?, ?)""",
            (player_id, body.cycle_start_slt[:10], duration))
        await db.commit()

    # Fire period_active occurrence
    if is_postgres():
        end_date = start_date + timedelta(days=duration)
        await db.execute(
            """INSERT INTO player_occurrences
               (player_id, occurrence_key, started_at, ends_at, sub_stage)
               VALUES ($1, 'period', $2, $3, 'active')
               ON CONFLICT DO NOTHING""",
            player_id, body.cycle_start_slt[:10], end_date.isoformat())
    else:
        end_date = start_date + timedelta(days=duration)
        await db.execute(
            """INSERT OR IGNORE INTO player_occurrences
               (player_id, occurrence_key, started_at, ends_at, sub_stage)
               VALUES (?, 'period', ?, ?, 'active')""",
            (player_id, body.cycle_start_slt[:10], end_date.isoformat()))
        await db.commit()

    await push_notification(
        player_id=player_id,
        app_source="ritual",
        title="Period logged 🌙",
        body="Take care of yourself.",
        priority="low",
        db=db,
    )

    prediction = await _recalculate_prediction(player_id, db)

    return {
        "status": "logged",
        "cycle_start": body.cycle_start_slt[:10],
        "period_duration_days": duration,
        "prediction": prediction,
    }


# ── POST /cycle/log-end ───────────────────────────────────────────────────────

@router.post("/log-end")
async def log_cycle_end(body: LogEnd, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    try:
        end_date = date.fromisoformat(body.cycle_end_slt[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format.")

    # Get most recent open cycle
    if is_postgres():
        cycle = await db.fetchrow(
            """SELECT id, cycle_start_slt FROM cycle_log
               WHERE player_id = $1 AND cycle_end_slt IS NULL
               ORDER BY cycle_start_slt DESC LIMIT 1""",
            player_id)
    else:
        async with db.execute(
            """SELECT id, cycle_start_slt FROM cycle_log
               WHERE player_id = ? AND cycle_end_slt IS NULL
               ORDER BY cycle_start_slt DESC LIMIT 1""",
            (player_id,)
        ) as cur:
            cycle = await cur.fetchone()

    if not cycle:
        raise HTTPException(status_code=404, detail="No open cycle to end.")

    start_date   = date.fromisoformat(cycle["cycle_start_slt"][:10])
    cycle_length = (end_date - start_date).days

    if is_postgres():
        await db.execute(
            """UPDATE cycle_log
               SET cycle_end_slt = $1, cycle_length_days = $2
               WHERE id = $3""",
            body.cycle_end_slt[:10], cycle_length, cycle["id"])
    else:
        await db.execute(
            """UPDATE cycle_log
               SET cycle_end_slt = ?, cycle_length_days = ?
               WHERE id = ?""",
            (body.cycle_end_slt[:10], cycle_length, cycle["id"]))
        await db.commit()

    prediction = await _recalculate_prediction(player_id, db)

    return {
        "status": "logged",
        "cycle_end": body.cycle_end_slt[:10],
        "cycle_length_days": cycle_length,
        "prediction": prediction,
    }


# ── GET /cycle/history ────────────────────────────────────────────────────────

@router.get("/history")
async def cycle_history(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        rows = await db.fetch(
            """SELECT * FROM cycle_log
               WHERE player_id = $1
               ORDER BY cycle_start_slt DESC LIMIT 24""",
            player_id)
    else:
        async with db.execute(
            """SELECT * FROM cycle_log
               WHERE player_id = ?
               ORDER BY cycle_start_slt DESC LIMIT 24""",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    return {"history": [dict(r) for r in rows]}


# ── GET /cycle/prediction ─────────────────────────────────────────────────────

@router.get("/prediction")
async def cycle_prediction(token: str, db=Depends(get_db)):
    """
    Returns:
    - next predicted start date
    - predicted window (start ±3 days)
    - avg cycle length
    - calendar_days: dict of YYYY-MM-DD → shade type
      (confirmed_period | predicted_start | predicted_window | post_glow)
    """
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        latest = await db.fetchrow(
            """SELECT cycle_start_slt, cycle_end_slt, period_duration_days,
                      avg_cycle_length, next_predicted_start
               FROM cycle_log
               WHERE player_id = $1
               ORDER BY cycle_start_slt DESC LIMIT 1""",
            player_id)
        all_cycles = await db.fetch(
            """SELECT cycle_start_slt, cycle_end_slt, period_duration_days
               FROM cycle_log WHERE player_id = $1
               ORDER BY cycle_start_slt DESC LIMIT 12""",
            player_id)
    else:
        async with db.execute(
            """SELECT cycle_start_slt, cycle_end_slt, period_duration_days,
                      avg_cycle_length, next_predicted_start
               FROM cycle_log
               WHERE player_id = ?
               ORDER BY cycle_start_slt DESC LIMIT 1""",
            (player_id,)
        ) as cur:
            latest = await cur.fetchone()
        async with db.execute(
            """SELECT cycle_start_slt, cycle_end_slt, period_duration_days
               FROM cycle_log WHERE player_id = ?
               ORDER BY cycle_start_slt DESC LIMIT 12""",
            (player_id,)
        ) as cur:
            all_cycles = await cur.fetchall()

    if not latest:
        return {"has_data": False, "calendar_days": {}}

    calendar_days = {}

    # Mark confirmed period days
    for cycle in all_cycles:
        if not cycle["cycle_start_slt"]:
            continue
        try:
            start = date.fromisoformat(cycle["cycle_start_slt"][:10])
            dur   = cycle["period_duration_days"] or 5
            for i in range(dur):
                d = start + timedelta(days=i)
                calendar_days[d.isoformat()] = "confirmed_period"
            # Post-glow days
            if cycle["cycle_end_slt"]:
                end = date.fromisoformat(cycle["cycle_end_slt"][:10])
            else:
                end = start + timedelta(days=dur)
            for i in range(1, 4):
                d = end + timedelta(days=i)
                if d.isoformat() not in calendar_days:
                    calendar_days[d.isoformat()] = "post_glow"
        except Exception:
            pass

    # Mark predicted window
    next_start_str = latest["next_predicted_start"]
    if next_start_str:
        try:
            next_start = date.fromisoformat(next_start_str[:10])
            dur = latest["period_duration_days"] or 5
            # ±3 day variance window
            for i in range(-3, dur + 3):
                d = next_start + timedelta(days=i)
                key = d.isoformat()
                if key not in calendar_days:
                    if 0 <= i < dur:
                        calendar_days[key] = "predicted_start"
                    else:
                        calendar_days[key] = "predicted_window"
        except Exception:
            pass

    return {
        "has_data":           True,
        "avg_cycle_length":   latest["avg_cycle_length"],
        "next_predicted_start": next_start_str,
        "calendar_days":      calendar_days,
    }


# ── POST /cycle/skip ──────────────────────────────────────────────────────────

@router.post("/skip")
async def skip_cycle(body: SkipCycle, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        await db.execute(
            """INSERT INTO cycle_log
               (player_id, cycle_start_slt, is_manual_override)
               VALUES ($1, now()::date::text, 1)""",
            player_id)
    else:
        await db.execute(
            """INSERT INTO cycle_log
               (player_id, cycle_start_slt, is_manual_override)
               VALUES (?, date('now'), 1)""",
            (player_id,))
        await db.commit()

    return {"status": "skipped"}
