"""
Cycle router — unified reproductive health tracking (Flo-style).

Tracking modes (stored in player_profiles.cycle_tracking_mode):
  period_only              — period + phase tracking, no TTC
  ttc_traditional          — period + ovulation + intimacy + conception probability
  ttc_ivf                  — IVF stage tracking
  ttc_surrogate_intended   — intended parent, no physical tracking
  ttc_surrogate_carrier    — carrier, full pregnancy physical tracking
  not_applicable           — opted out
  infertile                — infertility flag set, no pregnancy mechanics
  pregnant                 — currently pregnant, cycle paused
  postpartum               — post-birth, awaiting cycle return

Endpoints:
  POST  /cycle/setup             — unified onboarding questionnaire
  POST  /cycle/log-start         — log period start (override-aware)
  POST  /cycle/log-end           — log period end (override-aware)
  POST  /cycle/override          — override predicted period start/end/skip
  POST  /cycle/intimacy          — log intimacy (private, optional partner UUID)
  POST  /cycle/skip              — skip / mark no period this cycle
  GET   /cycle/history           — logged cycles
  GET   /cycle/prediction        — next period + ovulation window + calendar days
  GET   /cycle/phase             — current phase, advice, shop suggestions
  GET   /cycle/fertile-window    — fertile window dates + today status + intimacy count
  POST  /cycle/conception-check  — run probability check (called by scheduler)
  POST  /cycle/mode              — change tracking mode (settings)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, date, timedelta
import random

from app.database import get_db, is_postgres
from app.services.notifications import push_notification

router = APIRouter(prefix="/cycle", tags=["cycle"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class CycleSetup(BaseModel):
    token: str
    tracking_mode: str
    last_period_start: str | None = None
    last_period_end: str | None   = None
    period_ongoing: bool          = False
    cycle_length: int             = 28
    period_duration: int          = 5
    ttc_method: str | None        = None
    ttc_duration_months: int      = 0
    track_intimacy: bool          = True
    ivf_stage: str | None         = None
    linked_player_uuid: str | None = None
    infertility_reason: str | None = None


class LogStart(BaseModel):
    token: str
    cycle_start_slt: str
    period_duration_days: int = 5
    is_override: bool = False
    override_note: str | None = None


class LogEnd(BaseModel):
    token: str
    cycle_end_slt: str
    is_override: bool = False


class OverrideCycle(BaseModel):
    token: str
    action: str        # early_end | late_start | skip | spotting
    date_slt: str
    note: str | None = None


class LogIntimacy(BaseModel):
    token: str
    logged_date: str | None = None
    partner_uuid: str | None = None


class SkipCycle(BaseModel):
    token: str
    note: str | None = None


class ChangeMode(BaseModel):
    token: str
    tracking_mode: str
    ivf_stage: str | None = None


# ── Phase advice data ─────────────────────────────────────────────────────────

PHASE_ADVICE = {
    "menstrual": {
        "headline": "Rest and restore 🌙",
        "body":     "Your body is working hard. Iron-rich foods help replenish energy. Slow down, journal, or take a warm bath.",
        "eats":     ["Dark chocolate", "Leafy greens", "Lentil soup", "Warming herbal tea"],
        "haul":     ["Heating pad", "Cozy blanket", "Face mask", "Comfy socks"],
    },
    "follicular": {
        "headline": "Energy is rising ✨",
        "body":     "Estrogen is climbing and so is your energy. You may feel more creative, social, and optimistic. A great time to start new things.",
        "eats":     ["Fresh salads", "Smoothie bowls", "Light proteins", "Citrus fruits"],
        "haul":     ["New outfit", "Going-out accessories", "Skincare refresh"],
    },
    "ovulatory": {
        "headline": "Peak power 🌟",
        "body":     "You're at your most energetic and communicative. Social activities feel easy. If you're trying to conceive, this is your window.",
        "eats":     ["Grilled proteins", "Raw veggies", "Coconut water", "Berries"],
        "haul":     ["Date night outfit", "Confidence accessories", "Perfume"],
    },
    "luteal": {
        "headline": "Turning inward 🍂",
        "body":     "Progesterone is rising. Energy is more steady but lower. You may crave comfort and alone time. Magnesium-rich foods can really help.",
        "eats":     ["Dark chocolate", "Pumpkin seeds", "Complex carbs", "Warm soups"],
        "haul":     ["Self-care items", "Journal", "Comfort candle", "Cozy home items"],
    },
    "pms": {
        "headline": "Be gentle with yourself 💙",
        "body":     "Hormones are shifting fast. Cravings, irritability, and bloating are all normal. Prioritise sleep and foods that stabilise blood sugar.",
        "eats":     ["Magnesium-rich foods", "Chamomile tea", "Complex carbs", "Less caffeine"],
        "haul":     ["Heating pad", "Comfort snacks", "Bath salts", "Cozy things"],
    },
}


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


async def _get_profile(player_id: int, db) -> dict:
    if is_postgres():
        row = await db.fetchrow(
            "SELECT * FROM player_profiles WHERE player_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT * FROM player_profiles WHERE player_id = ?", (player_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else {}


async def _upsert_profile(player_id: int, fields: dict, db):
    if is_postgres():
        await db.execute(
            "INSERT INTO player_profiles (player_id) VALUES ($1) ON CONFLICT DO NOTHING",
            player_id)
        if fields:
            sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
            await db.execute(
                f"UPDATE player_profiles SET {sets} WHERE player_id = $1",
                player_id, *fields.values())
    else:
        await db.execute(
            "INSERT OR IGNORE INTO player_profiles (player_id) VALUES (?)", (player_id,))
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            await db.execute(
                f"UPDATE player_profiles SET {sets} WHERE player_id = ?",
                (*fields.values(), player_id))
        await db.commit()


def _calc_cycle_phase(cycle_start: date, today: date,
                      period_duration: int, cycle_length: int) -> dict:
    days_in      = (today - cycle_start).days
    ovulation_day = cycle_length - 14
    fertile_start = ovulation_day - 4
    fertile_end   = ovulation_day + 1
    pms_start     = cycle_length - 5

    if days_in < 0:
        return {"phase": "unknown", "cycle_day": 0, "days_remaining": 0}

    if days_in < period_duration:
        phase = "menstrual"
    elif days_in < fertile_start:
        phase = "follicular"
    elif days_in <= fertile_end:
        phase = "ovulatory"
    elif days_in >= pms_start:
        phase = "pms"
    else:
        phase = "luteal"

    return {
        "phase":           phase,
        "cycle_day":       days_in + 1,
        "cycle_length":    cycle_length,
        "period_duration": period_duration,
        "ovulation_day":   ovulation_day,
        "fertile_start":   fertile_start,
        "fertile_end":     fertile_end,
        "pms_start":       pms_start,
        "days_remaining":  max(0, cycle_length - days_in),
    }


async def _recalculate_prediction(player_id: int, db):
    if is_postgres():
        rows = await db.fetch(
            """SELECT cycle_start_slt, cycle_length_days FROM cycle_log
               WHERE player_id = $1 AND cycle_length_days IS NOT NULL
               AND is_manual_override = 0 ORDER BY cycle_start_slt DESC LIMIT 12""",
            player_id)
    else:
        async with db.execute(
            """SELECT cycle_start_slt, cycle_length_days FROM cycle_log
               WHERE player_id = ? AND cycle_length_days IS NOT NULL
               AND is_manual_override = 0 ORDER BY cycle_start_slt DESC LIMIT 12""",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    if len(rows) < 2:
        return None

    lengths = [r["cycle_length_days"] for r in rows if r["cycle_length_days"]]
    if not lengths:
        return None

    avg_len    = sum(lengths) / len(lengths)
    last_start = date.fromisoformat(rows[0]["cycle_start_slt"][:10])
    next_start = last_start + timedelta(days=round(avg_len))

    if is_postgres():
        await db.execute(
            """UPDATE cycle_log SET avg_cycle_length = $1, next_predicted_start = $2
               WHERE player_id = $3 AND cycle_start_slt = $4""",
            avg_len, next_start.isoformat(), player_id, rows[0]["cycle_start_slt"])
    else:
        await db.execute(
            """UPDATE cycle_log SET avg_cycle_length = ?, next_predicted_start = ?
               WHERE player_id = ? AND cycle_start_slt = ?""",
            (avg_len, next_start.isoformat(), player_id, rows[0]["cycle_start_slt"]))
        await db.commit()

    return {"avg_cycle_length": avg_len, "next_predicted_start": next_start.isoformat()}


# ── POST /cycle/setup ─────────────────────────────────────────────────────────

@router.post("/setup")
async def cycle_setup(body: CycleSetup, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    mode      = body.tracking_mode.lower().strip()

    VALID_MODES = {
        "period_only", "ttc_traditional", "ttc_ivf",
        "ttc_surrogate_intended", "ttc_surrogate_carrier",
        "not_applicable", "infertile", "pregnant", "postpartum"
    }
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid tracking mode: {mode}")

    cycle_length = max(21, min(45, body.cycle_length))
    period_dur   = max(2, min(10, body.period_duration))

    await _upsert_profile(player_id, {
        "cycle_tracking_mode":   mode,
        "cycle_setup_completed": 1,
        "default_cycle_length":  cycle_length,
        "avg_period_duration":   period_dur,
        "infertility_flag":      1 if mode == "infertile" else 0,
    }, db)

    # Log last period if provided
    if body.last_period_start and mode not in ("not_applicable", "infertile",
                                                "ttc_surrogate_intended"):
        start_str = body.last_period_start[:10]
        try:
            start_date = date.fromisoformat(start_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid last_period_start.")

        if is_postgres():
            await db.execute(
                """INSERT INTO cycle_log (player_id, cycle_start_slt, period_duration_days)
                   VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                player_id, start_str, period_dur)
        else:
            await db.execute(
                """INSERT OR IGNORE INTO cycle_log
                   (player_id, cycle_start_slt, period_duration_days) VALUES (?, ?, ?)""",
                (player_id, start_str, period_dur))
            await db.commit()

        if body.last_period_end and not body.period_ongoing:
            end_str = body.last_period_end[:10]
            try:
                cycle_len = (date.fromisoformat(end_str) - start_date).days
            except Exception:
                cycle_len = cycle_length
            if is_postgres():
                await db.execute(
                    """UPDATE cycle_log SET cycle_end_slt = $1, cycle_length_days = $2
                       WHERE player_id = $3 AND cycle_start_slt = $4""",
                    end_str, cycle_len, player_id, start_str)
            else:
                await db.execute(
                    """UPDATE cycle_log SET cycle_end_slt = ?, cycle_length_days = ?
                       WHERE player_id = ? AND cycle_start_slt = ?""",
                    (end_str, cycle_len, player_id, start_str))
                await db.commit()

    # Create TTC occurrence
    if mode in ("ttc_traditional", "ttc_ivf", "ttc_surrogate_intended", "ttc_surrogate_carrier"):
        import json
        occ_map = {
            "ttc_traditional":        "ttc_traditional",
            "ttc_ivf":                "ttc_ivf",
            "ttc_surrogate_intended": "ttc_surrogate_intended",
            "ttc_surrogate_carrier":  "ttc_surrogate_carrier",
        }
        occ_key  = occ_map[mode]
        meta     = json.dumps({"ttc_duration_months": body.ttc_duration_months,
                               "track_intimacy": body.track_intimacy,
                               "ivf_stage": body.ivf_stage})
        sub_stage = body.ivf_stage or "active"

        if is_postgres():
            await db.execute(
                """INSERT INTO player_occurrences
                   (player_id, occurrence_key, sub_stage, metadata, linked_player_uuid)
                   VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING""",
                player_id, occ_key, sub_stage, meta, body.linked_player_uuid)
        else:
            await db.execute(
                """INSERT OR IGNORE INTO player_occurrences
                   (player_id, occurrence_key, sub_stage, metadata, linked_player_uuid)
                   VALUES (?,?,?,?,?)""",
                (player_id, occ_key, sub_stage, meta, body.linked_player_uuid))
            await db.commit()

    return {"status": "setup_complete", "tracking_mode": mode,
            "cycle_length": cycle_length, "period_duration": period_dur}


# ── POST /cycle/log-start ─────────────────────────────────────────────────────

@router.post("/log-start")
async def log_cycle_start(body: LogStart, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    duration  = max(2, min(10, body.period_duration_days))

    try:
        start_date = date.fromisoformat(body.cycle_start_slt[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format.")

    is_ov = 1 if body.is_override else 0

    if is_postgres():
        await db.execute(
            """INSERT INTO cycle_log
               (player_id, cycle_start_slt, period_duration_days, is_override, override_note)
               VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING""",
            player_id, body.cycle_start_slt[:10], duration, is_ov, body.override_note)
    else:
        await db.execute(
            """INSERT OR IGNORE INTO cycle_log
               (player_id, cycle_start_slt, period_duration_days, is_override, override_note)
               VALUES (?,?,?,?,?)""",
            (player_id, body.cycle_start_slt[:10], duration, is_ov, body.override_note))
        await db.commit()

    end_date = start_date + timedelta(days=duration)
    if is_postgres():
        await db.execute(
            """INSERT INTO player_occurrences
               (player_id, occurrence_key, started_at, ends_at, sub_stage)
               VALUES ($1,'period',$2,$3,'active') ON CONFLICT DO NOTHING""",
            player_id, body.cycle_start_slt[:10], end_date.isoformat())
    else:
        await db.execute(
            """INSERT OR IGNORE INTO player_occurrences
               (player_id, occurrence_key, started_at, ends_at, sub_stage)
               VALUES (?,'period',?,?,'active')""",
            (player_id, body.cycle_start_slt[:10], end_date.isoformat()))
        await db.commit()

    await push_notification(player_id=player_id, app_source="ritual",
        title="Period logged 🌙", body="Take care of yourself.",
        priority="low", db=db)

    prediction = await _recalculate_prediction(player_id, db)
    return {"status": "logged", "cycle_start": body.cycle_start_slt[:10],
            "period_duration_days": duration, "prediction": prediction}


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

    if is_postgres():
        cycle = await db.fetchrow(
            """SELECT id, cycle_start_slt FROM cycle_log
               WHERE player_id = $1 AND cycle_end_slt IS NULL
               ORDER BY cycle_start_slt DESC LIMIT 1""", player_id)
    else:
        async with db.execute(
            """SELECT id, cycle_start_slt FROM cycle_log
               WHERE player_id = ? AND cycle_end_slt IS NULL
               ORDER BY cycle_start_slt DESC LIMIT 1""", (player_id,)
        ) as cur:
            cycle = await cur.fetchone()

    if not cycle:
        raise HTTPException(status_code=404, detail="No open cycle to end.")

    cycle_length = (end_date - date.fromisoformat(cycle["cycle_start_slt"][:10])).days
    is_ov        = 1 if body.is_override else 0

    if is_postgres():
        await db.execute(
            """UPDATE cycle_log SET cycle_end_slt=$1, cycle_length_days=$2,
               is_override=CASE WHEN $3=1 THEN 1 ELSE is_override END WHERE id=$4""",
            body.cycle_end_slt[:10], cycle_length, is_ov, cycle["id"])
    else:
        await db.execute(
            """UPDATE cycle_log SET cycle_end_slt=?, cycle_length_days=?,
               is_override=CASE WHEN ?=1 THEN 1 ELSE is_override END WHERE id=?""",
            (body.cycle_end_slt[:10], cycle_length, is_ov, cycle["id"]))
        await db.commit()

    prediction = await _recalculate_prediction(player_id, db)
    return {"status": "logged", "cycle_end": body.cycle_end_slt[:10],
            "cycle_length_days": cycle_length, "prediction": prediction}


# ── POST /cycle/override ──────────────────────────────────────────────────────

@router.post("/override")
async def override_cycle(body: OverrideCycle, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    action    = body.action.lower()

    if action == "late_start":
        if is_postgres():
            await db.execute(
                """INSERT INTO cycle_log
                   (player_id, cycle_start_slt, is_override, is_manual_override, override_note)
                   VALUES ($1,$2,1,1,$3) ON CONFLICT DO NOTHING""",
                player_id, body.date_slt[:10], body.note or "Late start")
        else:
            await db.execute(
                """INSERT OR IGNORE INTO cycle_log
                   (player_id, cycle_start_slt, is_override, is_manual_override, override_note)
                   VALUES (?,?,1,1,?)""",
                (player_id, body.date_slt[:10], body.note or "Late start"))
            await db.commit()

    elif action == "early_end":
        if is_postgres():
            cycle = await db.fetchrow(
                """SELECT id, cycle_start_slt FROM cycle_log
                   WHERE player_id=$1 AND cycle_end_slt IS NULL
                   ORDER BY cycle_start_slt DESC LIMIT 1""", player_id)
        else:
            async with db.execute(
                """SELECT id, cycle_start_slt FROM cycle_log
                   WHERE player_id=? AND cycle_end_slt IS NULL
                   ORDER BY cycle_start_slt DESC LIMIT 1""", (player_id,)
            ) as cur:
                cycle = await cur.fetchone()

        if cycle:
            length = (date.fromisoformat(body.date_slt[:10]) -
                      date.fromisoformat(cycle["cycle_start_slt"][:10])).days
            if is_postgres():
                await db.execute(
                    """UPDATE cycle_log SET cycle_end_slt=$1, cycle_length_days=$2,
                       is_override=1, override_note=$3 WHERE id=$4""",
                    body.date_slt[:10], length, body.note or "Early end", cycle["id"])
            else:
                await db.execute(
                    """UPDATE cycle_log SET cycle_end_slt=?, cycle_length_days=?,
                       is_override=1, override_note=? WHERE id=?""",
                    (body.date_slt[:10], length, body.note or "Early end", cycle["id"]))
                await db.commit()

    elif action in ("skip", "spotting"):
        note = body.note or action.capitalize()
        if is_postgres():
            await db.execute(
                """INSERT INTO cycle_log
                   (player_id, cycle_start_slt, is_manual_override, is_override, override_note)
                   VALUES ($1,$2,1,1,$3)""",
                player_id, body.date_slt[:10], note)
        else:
            await db.execute(
                """INSERT INTO cycle_log
                   (player_id, cycle_start_slt, is_manual_override, is_override, override_note)
                   VALUES (?,?,1,1,?)""",
                (player_id, body.date_slt[:10], note))
            await db.commit()

    prediction = await _recalculate_prediction(player_id, db)
    return {"status": "override_applied", "action": action, "prediction": prediction}


# ── POST /cycle/intimacy ──────────────────────────────────────────────────────

@router.post("/intimacy")
async def log_intimacy(body: LogIntimacy, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id   = player["id"]
    logged_date = body.logged_date or date.today().isoformat()

    if is_postgres():
        current_cycle = await db.fetchrow(
            """SELECT id FROM cycle_log WHERE player_id=$1 AND cycle_start_slt <= $2
               ORDER BY cycle_start_slt DESC LIMIT 1""", player_id, logged_date)
    else:
        async with db.execute(
            """SELECT id FROM cycle_log WHERE player_id=? AND cycle_start_slt <= ?
               ORDER BY cycle_start_slt DESC LIMIT 1""", (player_id, logged_date)
        ) as cur:
            current_cycle = await cur.fetchone()

    cycle_log_id = current_cycle["id"] if current_cycle else None

    if is_postgres():
        await db.execute(
            """INSERT INTO intimacy_log (player_id, logged_date, cycle_log_id, partner_uuid)
               VALUES ($1,$2,$3,$4)""",
            player_id, logged_date, cycle_log_id, body.partner_uuid)
    else:
        await db.execute(
            """INSERT INTO intimacy_log (player_id, logged_date, cycle_log_id, partner_uuid)
               VALUES (?,?,?,?)""",
            (player_id, logged_date, cycle_log_id, body.partner_uuid))
        await db.commit()

    return {"status": "logged", "date": logged_date}


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
               (player_id, cycle_start_slt, is_manual_override, override_note)
               VALUES ($1, now()::date::text, 1, $2)""",
            player_id, body.note or "Skipped")
    else:
        await db.execute(
            """INSERT INTO cycle_log
               (player_id, cycle_start_slt, is_manual_override, override_note)
               VALUES (?, date('now'), 1, ?)""",
            (player_id, body.note or "Skipped"))
        await db.commit()

    return {"status": "skipped"}


# ── GET /cycle/history ────────────────────────────────────────────────────────

@router.get("/history")
async def cycle_history(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    if is_postgres():
        rows = await db.fetch(
            """SELECT * FROM cycle_log WHERE player_id=$1
               ORDER BY cycle_start_slt DESC LIMIT 24""", player_id)
    else:
        async with db.execute(
            """SELECT * FROM cycle_log WHERE player_id=?
               ORDER BY cycle_start_slt DESC LIMIT 24""", (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    return {"history": [dict(r) for r in rows]}


# ── GET /cycle/prediction ─────────────────────────────────────────────────────

@router.get("/prediction")
async def cycle_prediction(token: str, db=Depends(get_db)):
    """
    Returns next period prediction, full phase calendar, and ovulation window.
    calendar_days values: confirmed_period | predicted_start | predicted_window |
    post_glow | ovulatory | fertile_window | phase_follicular | phase_luteal | phase_pms
    """
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id  = player["id"]
    profile    = await _get_profile(player_id, db)
    cycle_len  = int(profile.get("default_cycle_length") or 28)
    period_dur = int(profile.get("avg_period_duration") or 5)

    if is_postgres():
        latest = await db.fetchrow(
            """SELECT * FROM cycle_log WHERE player_id=$1
               ORDER BY cycle_start_slt DESC LIMIT 1""", player_id)
        all_cycles = await db.fetch(
            """SELECT cycle_start_slt, cycle_end_slt, period_duration_days, cycle_length_days
               FROM cycle_log WHERE player_id=$1
               ORDER BY cycle_start_slt DESC LIMIT 12""", player_id)
    else:
        async with db.execute(
            """SELECT * FROM cycle_log WHERE player_id=?
               ORDER BY cycle_start_slt DESC LIMIT 1""", (player_id,)
        ) as cur:
            latest = await cur.fetchone()
        async with db.execute(
            """SELECT cycle_start_slt, cycle_end_slt, period_duration_days, cycle_length_days
               FROM cycle_log WHERE player_id=?
               ORDER BY cycle_start_slt DESC LIMIT 12""", (player_id,)
        ) as cur:
            all_cycles = await cur.fetchall()

    if not latest:
        return {"has_data": False, "calendar_days": {}}

    calendar_days = {}

    # Mark confirmed period days + post glow
    for cycle in all_cycles:
        if not cycle["cycle_start_slt"]:
            continue
        try:
            s   = date.fromisoformat(cycle["cycle_start_slt"][:10])
            dur = cycle["period_duration_days"] or period_dur
            for i in range(dur):
                calendar_days[(s + timedelta(days=i)).isoformat()] = "confirmed_period"
            end = date.fromisoformat(cycle["cycle_end_slt"][:10]) if cycle["cycle_end_slt"] \
                  else s + timedelta(days=dur)
            for i in range(1, 4):
                k = (end + timedelta(days=i)).isoformat()
                if k not in calendar_days:
                    calendar_days[k] = "post_glow"
        except Exception:
            pass

    # Mark current cycle phases + fertile window
    try:
        s          = date.fromisoformat(latest["cycle_start_slt"][:10])
        used_len   = latest["cycle_length_days"] or cycle_len
        used_dur   = latest["period_duration_days"] or period_dur
        ov_day     = used_len - 14
        fert_start = ov_day - 4
        fert_end   = ov_day + 1
        pms_start  = used_len - 5

        for i in range(used_len):
            d   = s + timedelta(days=i)
            key = d.isoformat()
            if key in calendar_days:
                continue
            if i < used_dur:
                pass  # already confirmed_period
            elif fert_start <= i <= fert_end:
                calendar_days[key] = "ovulatory" if i == ov_day else "fertile_window"
            elif i < fert_start:
                calendar_days[key] = "phase_follicular"
            elif i >= pms_start:
                calendar_days[key] = "phase_pms"
            else:
                calendar_days[key] = "phase_luteal"
    except Exception:
        pass

    # Predicted next period + its fertile window
    next_start_str = latest["next_predicted_start"]
    if next_start_str:
        try:
            ns      = date.fromisoformat(next_start_str[:10])
            dur     = latest["period_duration_days"] or period_dur
            avg_len = latest["avg_cycle_length"] or cycle_len
            for i in range(-3, dur + 3):
                k = (ns + timedelta(days=i)).isoformat()
                if k not in calendar_days:
                    calendar_days[k] = "predicted_start" if 0 <= i < dur else "predicted_window"
            # Predicted ovulation for next cycle
            p_ov   = ns + timedelta(days=round(avg_len) - 14)
            p_fs   = p_ov - timedelta(days=4)
            p_fe   = p_ov + timedelta(days=1)
            d = p_fs
            while d <= p_fe:
                k = d.isoformat()
                if k not in calendar_days:
                    calendar_days[k] = "ovulatory" if d == p_ov else "fertile_window"
                d += timedelta(days=1)
        except Exception:
            pass

    return {
        "has_data":             True,
        "avg_cycle_length":     latest["avg_cycle_length"],
        "next_predicted_start": next_start_str,
        "calendar_days":        calendar_days,
    }


# ── GET /cycle/phase ──────────────────────────────────────────────────────────

@router.get("/phase")
async def current_phase(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id  = player["id"]
    profile    = await _get_profile(player_id, db)
    cycle_len  = int(profile.get("default_cycle_length") or 28)
    period_dur = int(profile.get("avg_period_duration") or 5)
    today      = date.today()

    if is_postgres():
        latest = await db.fetchrow(
            """SELECT * FROM cycle_log WHERE player_id=$1
               ORDER BY cycle_start_slt DESC LIMIT 1""", player_id)
    else:
        async with db.execute(
            """SELECT * FROM cycle_log WHERE player_id=?
               ORDER BY cycle_start_slt DESC LIMIT 1""", (player_id,)
        ) as cur:
            latest = await cur.fetchone()

    if not latest:
        return {"has_data": False}

    try:
        cycle_start = date.fromisoformat(latest["cycle_start_slt"][:10])
        used_len    = latest["cycle_length_days"] or cycle_len
        used_dur    = latest["period_duration_days"] or period_dur
    except Exception:
        return {"has_data": False}

    phase_info = _calc_cycle_phase(cycle_start, today, used_dur, used_len)
    phase      = phase_info["phase"]
    advice     = PHASE_ADVICE.get(phase, PHASE_ADVICE["luteal"])

    return {
        "has_data":      True,
        "phase":         phase,
        "cycle_day":     phase_info["cycle_day"],
        "cycle_length":  used_len,
        "days_remaining": phase_info["days_remaining"],
        "headline":      advice["headline"],
        "body":          advice["body"],
        "eats":          advice["eats"],
        "haul":          advice["haul"],
    }


# ── GET /cycle/fertile-window ─────────────────────────────────────────────────

@router.get("/fertile-window")
async def fertile_window(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id  = player["id"]
    profile    = await _get_profile(player_id, db)
    cycle_len  = int(profile.get("default_cycle_length") or 28)
    today      = date.today()

    if is_postgres():
        latest = await db.fetchrow(
            """SELECT * FROM cycle_log WHERE player_id=$1
               ORDER BY cycle_start_slt DESC LIMIT 1""", player_id)
    else:
        async with db.execute(
            """SELECT * FROM cycle_log WHERE player_id=?
               ORDER BY cycle_start_slt DESC LIMIT 1""", (player_id,)
        ) as cur:
            latest = await cur.fetchone()

    if not latest:
        return {"has_data": False}

    try:
        cycle_start   = date.fromisoformat(latest["cycle_start_slt"][:10])
        used_len      = latest["cycle_length_days"] or cycle_len
        ovulation_dt  = cycle_start + timedelta(days=used_len - 14)
        fertile_start = ovulation_dt - timedelta(days=4)
        fertile_end   = ovulation_dt + timedelta(days=1)
    except Exception:
        return {"has_data": False}

    start_str = fertile_start.isoformat()
    end_str   = fertile_end.isoformat()

    if is_postgres():
        intimacy_count = await db.fetchval(
            """SELECT COUNT(*) FROM intimacy_log
               WHERE player_id=$1 AND logged_date>=$2 AND logged_date<=$3""",
            player_id, start_str, end_str)
        peak_count = await db.fetchval(
            """SELECT COUNT(*) FROM intimacy_log
               WHERE player_id=$1 AND logged_date=$2""",
            player_id, ovulation_dt.isoformat())
    else:
        async with db.execute(
            """SELECT COUNT(*) as cnt FROM intimacy_log
               WHERE player_id=? AND logged_date>=? AND logged_date<=?""",
            (player_id, start_str, end_str)
        ) as cur:
            r = await cur.fetchone(); intimacy_count = r["cnt"] if r else 0
        async with db.execute(
            """SELECT COUNT(*) as cnt FROM intimacy_log
               WHERE player_id=? AND logged_date=?""",
            (player_id, ovulation_dt.isoformat())
        ) as cur:
            r = await cur.fetchone(); peak_count = r["cnt"] if r else 0

    return {
        "has_data":           True,
        "fertile_start":      start_str,
        "fertile_end":        end_str,
        "ovulation_date":     ovulation_dt.isoformat(),
        "is_fertile_today":   fertile_start <= today <= fertile_end,
        "is_ovulation_today": today == ovulation_dt,
        "days_to_window":     max(0, (fertile_start - today).days) if today < fertile_start else 0,
        "intimacy_count":     intimacy_count,
        "peak_day_hit":       peak_count > 0,
    }


# ── POST /cycle/conception-check ──────────────────────────────────────────────

@router.post("/conception-check")
async def conception_check(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    profile   = await _get_profile(player_id, db)

    if profile.get("birth_control_active") or profile.get("infertility_flag"):
        return {"status": "skipped", "reason": "gated"}
    if profile.get("cycle_tracking_mode") != "ttc_traditional":
        return {"status": "skipped", "reason": "not_ttc"}

    cycle_len = int(profile.get("default_cycle_length") or 28)
    today     = date.today()

    if is_postgres():
        latest = await db.fetchrow(
            """SELECT * FROM cycle_log WHERE player_id=$1
               ORDER BY cycle_start_slt DESC LIMIT 1""", player_id)
    else:
        async with db.execute(
            """SELECT * FROM cycle_log WHERE player_id=?
               ORDER BY cycle_start_slt DESC LIMIT 1""", (player_id,)
        ) as cur:
            latest = await cur.fetchone()

    if not latest:
        return {"status": "skipped", "reason": "no_data"}

    try:
        cycle_start  = date.fromisoformat(latest["cycle_start_slt"][:10])
        used_len     = latest["cycle_length_days"] or cycle_len
        ovulation_dt = cycle_start + timedelta(days=used_len - 14)
        fert_start   = ovulation_dt - timedelta(days=4)
        fert_end     = ovulation_dt + timedelta(days=1)
    except Exception:
        return {"status": "error"}

    if today <= fert_end:
        return {"status": "window_not_closed"}

    # Check already done this cycle
    if is_postgres():
        already = await db.fetchrow(
            "SELECT id FROM ttc_conception_checks WHERE player_id=$1 AND cycle_log_id=$2",
            player_id, latest["id"])
    else:
        async with db.execute(
            "SELECT id FROM ttc_conception_checks WHERE player_id=? AND cycle_log_id=?",
            (player_id, latest["id"])
        ) as cur:
            already = await cur.fetchone()
    if already:
        return {"status": "already_checked"}

    # Count intimacy during window
    if is_postgres():
        intimacy_count = await db.fetchval(
            """SELECT COUNT(*) FROM intimacy_log
               WHERE player_id=$1 AND logged_date>=$2 AND logged_date<=$3""",
            player_id, fert_start.isoformat(), fert_end.isoformat())
        peak_count = await db.fetchval(
            """SELECT COUNT(*) FROM intimacy_log
               WHERE player_id=$1 AND logged_date=$2""",
            player_id, ovulation_dt.isoformat())
    else:
        async with db.execute(
            """SELECT COUNT(*) as cnt FROM intimacy_log
               WHERE player_id=? AND logged_date>=? AND logged_date<=?""",
            (player_id, fert_start.isoformat(), fert_end.isoformat())
        ) as cur:
            r = await cur.fetchone(); intimacy_count = r["cnt"] if r else 0
        async with db.execute(
            """SELECT COUNT(*) as cnt FROM intimacy_log
               WHERE player_id=? AND logged_date=?""",
            (player_id, ovulation_dt.isoformat())
        ) as cur:
            r = await cur.fetchone(); peak_count = r["cnt"] if r else 0

    peak_hit = peak_count > 0
    prob     = min(0.30, (intimacy_count * 0.08) + (0.12 if peak_hit else 0))
    conceived = random.random() < prob
    result    = "conceived" if conceived else "not_conceived"

    if is_postgres():
        await db.execute(
            """INSERT INTO ttc_conception_checks
               (player_id, cycle_log_id, intimacy_count, peak_day_hit, result)
               VALUES ($1,$2,$3,$4,$5)""",
            player_id, latest["id"], intimacy_count, int(peak_hit), result)
    else:
        await db.execute(
            """INSERT INTO ttc_conception_checks
               (player_id, cycle_log_id, intimacy_count, peak_day_hit, result)
               VALUES (?,?,?,?,?)""",
            (player_id, latest["id"], intimacy_count, int(peak_hit), result))
        await db.commit()

    if conceived:
        await push_notification(
            player_id=player_id, app_source="ritual",
            title="Something might be different this cycle… 🌸",
            body="Tap to confirm your pregnancy.",
            priority="normal", db=db)

    return {"status": "checked", "result": result}


# ── POST /cycle/mode ──────────────────────────────────────────────────────────

@router.post("/mode")
async def change_mode(body: ChangeMode, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    mode      = body.tracking_mode.lower().strip()

    VALID_MODES = {
        "period_only", "ttc_traditional", "ttc_ivf",
        "ttc_surrogate_intended", "ttc_surrogate_carrier",
        "not_applicable", "infertile"
    }
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")

    fields = {"cycle_tracking_mode": mode}
    if mode == "infertile":
        fields["infertility_flag"] = 1

    await _upsert_profile(player_id, fields, db)

    if mode == "ttc_ivf" and body.ivf_stage:
        if is_postgres():
            await db.execute(
                """UPDATE player_occurrences SET sub_stage=$1
                   WHERE player_id=$2 AND occurrence_key='ttc_ivf' AND is_resolved=0""",
                body.ivf_stage, player_id)
        else:
            await db.execute(
                """UPDATE player_occurrences SET sub_stage=?
                   WHERE player_id=? AND occurrence_key='ttc_ivf' AND is_resolved=0""",
                (body.ivf_stage, player_id))
            await db.commit()

    return {"status": "mode_updated", "tracking_mode": mode}
