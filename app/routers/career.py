"""
Career router — jobs, shifts, promotions, odd jobs.

GET  /career                    — current employment data
POST /career/apply              — apply for a career path
POST /career/clockin            — start a shift
POST /career/clockout           — end a shift, deposit pay
POST /career/heartbeat          — HUD heartbeat ping (keeps shift alive)
POST /career/promote            — attempt promotion to next tier
POST /career/odd-jobs/complete  — complete an odd job, deposit pay
GET  /career/history            — past shift/career history
"""

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta

from app.database import get_db, is_postgres
from app.config import get_config
from app.services.notifications import push_notification
from app.services.career import (
    do_clockout, get_tier_cfg, get_career_path_cfg,
    check_skill_requirements, _now_str
)

router = APIRouter(prefix="/career", tags=["career"])


# ── Auth ─────────────────────────────────────────────────────────────────────

async def _get_player(token: str, db) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="Missing token.")
    if is_postgres():
        row = await db.fetchrow(
            "SELECT * FROM players WHERE token = $1 AND is_banned = 0", token)
        p = dict(row) if row else None
    else:
        async with db.execute(
            "SELECT * FROM players WHERE token = ? AND is_banned = 0", (token,)
        ) as cur:
            row = await cur.fetchone()
            p = dict(row) if row else None
    if not p:
        raise HTTPException(status_code=401, detail="Invalid token.")
    return p


def _token_from_header(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    return authorization.split(" ", 1)[1].strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_employment(db, player_id: int) -> dict | None:
    if is_postgres():
        row = await db.fetchrow(
            "SELECT * FROM employment WHERE player_id = $1", player_id)
        return dict(row) if row else None
    else:
        async with db.execute(
            "SELECT * FROM employment WHERE player_id = ?", (player_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _get_player_skills(db, player_id: int) -> dict:
    if is_postgres():
        rows = await db.fetch(
            "SELECT skill_key, level FROM skills WHERE player_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT skill_key, level FROM skills WHERE player_id = ?", (player_id,)
        ) as cur:
            rows = await cur.fetchall()
    return {r["skill_key"]: int(r["level"]) for r in rows}


async def _count_odd_jobs_today(db, player_id: int) -> int:
    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%d") + " 00:00:00"
    if is_postgres():
        row = await db.fetchrow(
            """SELECT COUNT(*) as cnt FROM odd_job_log
               WHERE player_id = $1 AND completed_at >= $2""",
            player_id, today_start)
    else:
        async with db.execute(
            """SELECT COUNT(*) as cnt FROM odd_job_log
               WHERE player_id = ? AND completed_at >= ?""",
            (player_id, today_start)
        ) as cur:
            row = await cur.fetchone()
    return int(row["cnt"]) if row else 0


# ── Models ────────────────────────────────────────────────────────────────────

class ApplyRequest(BaseModel):
    career_path_key: str

class OddJobRequest(BaseModel):
    odd_job_key: str


# ── GET /career ───────────────────────────────────────────────────────────────

@router.get("")
async def get_career(
    authorization: Optional[str] = Header(None),
    db=Depends(get_db)
):
    token = _token_from_header(authorization)
    player = await _get_player(token, db)
    player_id = player["id"]

    cfg = get_config()
    emp = await _get_employment(db, player_id)

    if not emp or not emp.get("career_path_key"):
        return {"employed": False, "employment": None}

    path_key  = emp["career_path_key"]
    tier      = int(emp["tier_level"])
    tier_cfg  = get_tier_cfg(cfg, path_key, tier)
    path_cfg  = get_career_path_cfg(cfg, path_key)

    # Next tier info
    next_tier_cfg = get_tier_cfg(cfg, path_key, tier + 1)
    skills = await _get_player_skills(db, player_id)

    promotion_ready = False
    promotion_missing = []
    if next_tier_cfg:
        skill_reqs = next_tier_cfg.get("skill_req") or {}
        days_req   = next_tier_cfg.get("days_required") or 0
        days_ok    = int(emp["days_at_tier"]) >= days_req
        skills_ok, promotion_missing = check_skill_requirements(skill_reqs, skills)
        promotion_ready = days_ok and skills_ok

    # Shift timer
    shift_hours = None
    shift_seconds = None
    if emp.get("is_clocked_in") and emp.get("clocked_in_at"):
        try:
            start = datetime.fromisoformat(str(emp["clocked_in_at"]).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            shift_seconds = int(elapsed)
            shift_hours = round(elapsed / 3600, 3)
        except Exception:
            pass

    odd_jobs_today = await _count_odd_jobs_today(db, player_id)
    odd_jobs_remaining = max(0, cfg["economy"]["odd_jobs"]["daily_limit"] - odd_jobs_today)

    return {
        "employed": True,
        "employment": {
            "career_path_key":  path_key,
            "career_name":      path_cfg.get("display_name", path_key) if path_cfg else path_key,
            "career_icon":      path_cfg.get("icon", "💼") if path_cfg else "💼",
            "is_grey_area":     bool(path_cfg.get("is_grey_area", False)) if path_cfg else False,
            "tier_level":       tier,
            "job_title":        emp["job_title"],
            "daily_pay":        tier_cfg.get("daily_pay", 0) if tier_cfg else 0,
            "is_clocked_in":    bool(emp["is_clocked_in"]),
            "shift_seconds":    shift_seconds,
            "shift_hours":      shift_hours,
            "hours_today":      float(emp["hours_today"]),
            "days_at_tier":     int(emp["days_at_tier"]),
            "total_days_worked":int(emp["total_days_worked"]),
            "next_tier":        {
                "title":   next_tier_cfg.get("title") if next_tier_cfg else None,
                "pay":     next_tier_cfg.get("daily_pay") if next_tier_cfg else None,
                "days_required": next_tier_cfg.get("days_required") if next_tier_cfg else None,
            } if next_tier_cfg else None,
            "promotion_ready":  promotion_ready,
            "promotion_missing": promotion_missing,
        },
        "odd_jobs_today":     odd_jobs_today,
        "odd_jobs_remaining": odd_jobs_remaining,
    }


# ── POST /career/apply ────────────────────────────────────────────────────────

@router.post("/apply")
async def apply_career(
    body: ApplyRequest,
    authorization: Optional[str] = Header(None),
    db=Depends(get_db)
):
    token = _token_from_header(authorization)
    player = await _get_player(token, db)
    player_id = player["id"]

    cfg = get_config()
    path_cfg = get_career_path_cfg(cfg, body.career_path_key)
    if not path_cfg:
        raise HTTPException(status_code=404, detail=f"Career path '{body.career_path_key}' not found.")

    # Get tier 1 config
    tier1 = path_cfg.get("tiers", {}).get(1)
    if not tier1:
        raise HTTPException(status_code=500, detail="Career has no tier 1 defined.")

    # Check skill requirements for tier 1
    skills = await _get_player_skills(db, player_id)
    skill_reqs = tier1.get("skill_req") or {}
    met, missing = check_skill_requirements(skill_reqs, skills)
    if not met:
        raise HTTPException(
            status_code=400,
            detail=f"Skill requirements not met: {', '.join(missing)}"
        )

    # Check not already employed in this path
    emp = await _get_employment(db, player_id)
    now = _now_str()

    if emp and emp.get("career_path_key") == body.career_path_key:
        raise HTTPException(status_code=400, detail="Already employed in this career path.")

    # If switching careers, archive old career
    if emp and emp.get("career_path_key"):
        if is_postgres():
            await db.execute(
                """UPDATE career_history SET ended_at = $1
                   WHERE player_id = $2 AND ended_at IS NULL""",
                now, player_id)
        else:
            await db.execute(
                """UPDATE career_history SET ended_at = ?
                   WHERE player_id = ? AND ended_at IS NULL""",
                (now, player_id))

    title = tier1["title"]

    if emp:
        # Update existing employment row
        if is_postgres():
            await db.execute(
                """UPDATE employment
                   SET career_path_key = $1, tier_level = 1, job_title = $2,
                       is_clocked_in = 0, clocked_in_at = NULL, last_heartbeat_at = NULL,
                       hours_today = 0, days_at_tier = 0
                   WHERE player_id = $3""",
                body.career_path_key, title, player_id)
        else:
            await db.execute(
                """UPDATE employment
                   SET career_path_key = ?, tier_level = 1, job_title = ?,
                       is_clocked_in = 0, clocked_in_at = NULL, last_heartbeat_at = NULL,
                       hours_today = 0, days_at_tier = 0
                   WHERE player_id = ?""",
                (body.career_path_key, title, player_id))
    else:
        # Create new employment row
        if is_postgres():
            await db.execute(
                """INSERT INTO employment
                   (player_id, career_path_key, tier_level, job_title,
                    is_clocked_in, hours_today, days_at_tier, total_days_worked)
                   VALUES ($1, $2, 1, $3, 0, 0, 0, 0)""",
                player_id, body.career_path_key, title)
        else:
            await db.execute(
                """INSERT INTO employment
                   (player_id, career_path_key, tier_level, job_title,
                    is_clocked_in, hours_today, days_at_tier, total_days_worked)
                   VALUES (?, ?, 1, ?, 0, 0, 0, 0)""",
                (player_id, body.career_path_key, title))

    # Log to career history
    if is_postgres():
        await db.execute(
            """INSERT INTO career_history
               (player_id, career_path_key, tier_level, job_title, started_at)
               VALUES ($1, $2, 1, $3, $4)""",
            player_id, body.career_path_key, title, now)
    else:
        await db.execute(
            """INSERT INTO career_history
               (player_id, career_path_key, tier_level, job_title, started_at)
               VALUES (?, ?, 1, ?, ?)""",
            (player_id, body.career_path_key, title, now))
        await db.commit()

    return {
        "ok": True,
        "career_path_key": body.career_path_key,
        "tier_level": 1,
        "job_title": title,
        "daily_pay": tier1["daily_pay"],
    }


# ── POST /career/clockin ──────────────────────────────────────────────────────

@router.post("/clockin")
async def clockin(
    authorization: Optional[str] = Header(None),
    db=Depends(get_db)
):
    token = _token_from_header(authorization)
    player = await _get_player(token, db)
    player_id = player["id"]

    cfg = get_config()
    emp = await _get_employment(db, player_id)

    if not emp or not emp.get("career_path_key"):
        raise HTTPException(status_code=400, detail="Not currently employed. Apply for a job first.")

    if emp.get("is_clocked_in"):
        raise HTTPException(status_code=400, detail="Already clocked in.")

    max_hours = float(cfg["careers"]["shift_max_hours"])
    if float(emp["hours_today"]) >= max_hours:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum shift hours ({max_hours}h) already reached today. Come back tomorrow."
        )

    now = _now_str()

    if is_postgres():
        await db.execute(
            """UPDATE employment
               SET is_clocked_in = 1, clocked_in_at = $1, last_heartbeat_at = $1
               WHERE player_id = $2""",
            now, player_id)
    else:
        await db.execute(
            """UPDATE employment
               SET is_clocked_in = 1, clocked_in_at = ?, last_heartbeat_at = ?
               WHERE player_id = ?""",
            (now, now, player_id))
        await db.commit()

    return {
        "ok": True,
        "clocked_in_at": now,
        "job_title": emp["job_title"],
        "shift_max_hours": max_hours,
    }


# ── POST /career/clockout ─────────────────────────────────────────────────────

@router.post("/clockout")
async def clockout(
    authorization: Optional[str] = Header(None),
    db=Depends(get_db)
):
    token = _token_from_header(authorization)
    player = await _get_player(token, db)
    player_id = player["id"]

    emp = await _get_employment(db, player_id)

    if not emp or not emp.get("is_clocked_in"):
        raise HTTPException(status_code=400, detail="Not currently clocked in.")

    result = await do_clockout(db, player_id, emp, reason="manual")

    return {
        "ok": True,
        "hours_worked": result["hours"],
        "pay_deposited": result["pay"],
        "job_title": emp["job_title"],
    }


# ── POST /career/heartbeat ────────────────────────────────────────────────────

@router.post("/heartbeat")
async def heartbeat(
    authorization: Optional[str] = Header(None),
    db=Depends(get_db)
):
    """
    Called by LSL HUD script every 60s while attachment is worn.
    Updates last_heartbeat_at. Auto-clock-out handled by background sweep.
    Also fires 30-min warning notification if approaching max shift.
    """
    token = _token_from_header(authorization)
    player = await _get_player(token, db)
    player_id = player["id"]

    emp = await _get_employment(db, player_id)
    if not emp:
        return {"ok": True, "clocked_in": False}

    now_str = _now_str()
    now = datetime.now(timezone.utc)

    if is_postgres():
        await db.execute(
            "UPDATE employment SET last_heartbeat_at = $1 WHERE player_id = $2",
            now_str, player_id)
    else:
        await db.execute(
            "UPDATE employment SET last_heartbeat_at = ? WHERE player_id = ?",
            (now_str, player_id))
        await db.commit()

    # 30-min warning check
    cfg = get_config()
    warning_minutes = float(cfg["careers"].get("shift_warning_minutes", 30))
    max_hours = float(cfg["careers"]["shift_max_hours"])

    if emp.get("is_clocked_in") and emp.get("clocked_in_at"):
        try:
            start = datetime.fromisoformat(str(emp["clocked_in_at"]).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            elapsed_min = (now - start).total_seconds() / 60
            remaining_min = (max_hours * 60) - elapsed_min

            if 0 < remaining_min <= warning_minutes:
                # Only fire once — check for existing unread warning
                warn_title = "30 minutes left in your shift ⏱️"
                if is_postgres():
                    exists = await db.fetchrow(
                        """SELECT id FROM notifications
                           WHERE player_id = $1 AND title = $2 AND is_read = 0 LIMIT 1""",
                        player_id, warn_title)
                else:
                    async with db.execute(
                        """SELECT id FROM notifications
                           WHERE player_id = ? AND title = ? AND is_read = 0 LIMIT 1""",
                        (player_id, warn_title)
                    ) as cur:
                        exists = await cur.fetchone()

                if not exists:
                    await push_notification(
                        player_id, "grind", warn_title,
                        "Auto clock-out in 30 minutes.",
                        priority="normal", db=db
                    )
        except Exception:
            pass

    return {
        "ok": True,
        "clocked_in": bool(emp.get("is_clocked_in")),
        "last_heartbeat_at": now_str,
    }


# ── POST /career/promote ──────────────────────────────────────────────────────

@router.post("/promote")
async def promote(
    authorization: Optional[str] = Header(None),
    db=Depends(get_db)
):
    token = _token_from_header(authorization)
    player = await _get_player(token, db)
    player_id = player["id"]

    cfg = get_config()
    emp = await _get_employment(db, player_id)

    if not emp or not emp.get("career_path_key"):
        raise HTTPException(status_code=400, detail="Not employed.")

    if emp.get("is_clocked_in"):
        raise HTTPException(status_code=400, detail="Cannot promote while clocked in. Clock out first.")

    path_key    = emp["career_path_key"]
    current_tier = int(emp["tier_level"])
    next_tier    = current_tier + 1

    next_tier_cfg = get_tier_cfg(cfg, path_key, next_tier)
    if not next_tier_cfg:
        raise HTTPException(status_code=400, detail="Already at the highest tier.")

    # Check days at current tier
    days_required = next_tier_cfg.get("days_required") or 0
    days_at_tier  = int(emp["days_at_tier"])
    if days_at_tier < days_required:
        raise HTTPException(
            status_code=400,
            detail=f"Need {days_required} days at current tier — you have {days_at_tier}."
        )

    # Check skill requirements
    skills = await _get_player_skills(db, player_id)
    skill_reqs = next_tier_cfg.get("skill_req") or {}
    met, missing = check_skill_requirements(skill_reqs, skills)
    if not met:
        raise HTTPException(
            status_code=400,
            detail=f"Skill requirements not met: {', '.join(missing)}"
        )

    new_title = next_tier_cfg["title"]
    new_pay   = next_tier_cfg["daily_pay"]
    now       = _now_str()

    if is_postgres():
        await db.execute(
            """UPDATE employment
               SET tier_level = $1, job_title = $2, days_at_tier = 0
               WHERE player_id = $3""",
            next_tier, new_title, player_id)
        await db.execute(
            """INSERT INTO career_history
               (player_id, career_path_key, tier_level, job_title, started_at)
               VALUES ($1, $2, $3, $4, $5)""",
            player_id, path_key, next_tier, new_title, now)
    else:
        await db.execute(
            """UPDATE employment
               SET tier_level = ?, job_title = ?, days_at_tier = 0
               WHERE player_id = ?""",
            (next_tier, new_title, player_id))
        await db.execute(
            """INSERT INTO career_history
               (player_id, career_path_key, tier_level, job_title, started_at)
               VALUES (?, ?, ?, ?, ?)""",
            (player_id, path_key, next_tier, new_title, now))
        await db.commit()

    await push_notification(
        player_id, "grind",
        f"Promoted to {new_title} 🎉",
        f"New rate: ✦{new_pay}/shift. Congratulations.",
        priority="normal", db=db
    )

    return {
        "ok": True,
        "new_tier": next_tier,
        "new_title": new_title,
        "new_daily_pay": new_pay,
    }


# ── POST /career/odd-jobs/complete ────────────────────────────────────────────

@router.post("/odd-jobs/complete")
async def complete_odd_job(
    body: OddJobRequest,
    authorization: Optional[str] = Header(None),
    db=Depends(get_db)
):
    token = _token_from_header(authorization)
    player = await _get_player(token, db)
    player_id = player["id"]

    cfg = get_config()
    odd_jobs_cfg = cfg["economy"]["odd_jobs"]
    daily_limit  = int(odd_jobs_cfg["daily_limit"])
    job_cfg      = odd_jobs_cfg["jobs"].get(body.odd_job_key)

    if not job_cfg:
        raise HTTPException(status_code=404, detail=f"Odd job '{body.odd_job_key}' not found.")

    # Check daily limit
    count_today = await _count_odd_jobs_today(db, player_id)
    if count_today >= daily_limit:
        raise HTTPException(
            status_code=400,
            detail=f"Daily odd job limit ({daily_limit}) reached. Resets at midnight SLT."
        )

    pay = float(job_cfg["pay"])
    display = job_cfg["display_name"]
    now = _now_str()

    # Credit wallet + log
    if is_postgres():
        await db.execute(
            """UPDATE wallets
               SET balance = balance + $1, total_earned = total_earned + $1, last_updated = $2
               WHERE player_id = $3""",
            pay, now, player_id)
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES ($1, $2, 'odd_job', $3, $4)""",
            player_id, pay, f"Odd job — {display}", now)
        await db.execute(
            """INSERT INTO odd_job_log (player_id, odd_job_key, completed_at, amount_earned)
               VALUES ($1, $2, $3, $4)""",
            player_id, body.odd_job_key, now, pay)
    else:
        await db.execute(
            """UPDATE wallets
               SET balance = balance + ?, total_earned = total_earned + ?, last_updated = ?
               WHERE player_id = ?""",
            (pay, pay, now, player_id))
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES (?, ?, 'odd_job', ?, ?)""",
            (player_id, pay, f"Odd job — {display}", now))
        await db.execute(
            """INSERT INTO odd_job_log (player_id, odd_job_key, completed_at, amount_earned)
               VALUES (?, ?, ?, ?)""",
            (player_id, body.odd_job_key, now, pay))
        await db.commit()

    remaining = daily_limit - count_today - 1

    await push_notification(
        player_id, "grind",
        f"Odd job complete ✦{pay:.0f} 💼",
        f"{display} — {remaining} slot{'s' if remaining != 1 else ''} left today.",
        priority="low", db=db
    )

    return {
        "ok": True,
        "odd_job_key": body.odd_job_key,
        "display_name": display,
        "pay_deposited": pay,
        "slots_remaining_today": remaining,
    }


# ── GET /career/history ───────────────────────────────────────────────────────

@router.get("/history")
async def career_history(
    limit: int = Query(20, ge=1, le=100),
    authorization: Optional[str] = Header(None),
    db=Depends(get_db)
):
    token = _token_from_header(authorization)
    player = await _get_player(token, db)
    player_id = player["id"]

    cfg = get_config()

    if is_postgres():
        rows = await db.fetch(
            """SELECT career_path_key, tier_level, job_title,
                      started_at, ended_at, total_shifts, total_earned
               FROM career_history WHERE player_id = $1
               ORDER BY started_at DESC LIMIT $2""",
            player_id, limit)
        odd_rows = await db.fetch(
            """SELECT odd_job_key, completed_at, amount_earned
               FROM odd_job_log WHERE player_id = $1
               ORDER BY completed_at DESC LIMIT 20""",
            player_id)
    else:
        async with db.execute(
            """SELECT career_path_key, tier_level, job_title,
                      started_at, ended_at, total_shifts, total_earned
               FROM career_history WHERE player_id = ?
               ORDER BY started_at DESC LIMIT ?""",
            (player_id, limit)
        ) as cur:
            rows = await cur.fetchall()
        async with db.execute(
            """SELECT odd_job_key, completed_at, amount_earned
               FROM odd_job_log WHERE player_id = ?
               ORDER BY completed_at DESC LIMIT 20""",
            (player_id,)
        ) as cur:
            odd_rows = await cur.fetchall()

    paths_cfg = cfg.get("careers", {}).get("paths", {})
    odd_jobs_cfg = cfg.get("economy", {}).get("odd_jobs", {}).get("jobs", {})

    history = []
    for r in rows:
        pk = r["career_path_key"]
        path_info = paths_cfg.get(pk, {})
        history.append({
            "career_path_key": pk,
            "career_name": path_info.get("display_name", pk),
            "career_icon": path_info.get("icon", "💼"),
            "tier_level":  int(r["tier_level"]),
            "job_title":   r["job_title"],
            "started_at":  r["started_at"],
            "ended_at":    r["ended_at"],
            "total_earned": float(r["total_earned"]),
        })

    odd_history = []
    for r in odd_rows:
        jk = r["odd_job_key"]
        jcfg = odd_jobs_cfg.get(jk, {})
        odd_history.append({
            "odd_job_key":  jk,
            "display_name": jcfg.get("display_name", jk),
            "completed_at": r["completed_at"],
            "amount_earned": float(r["amount_earned"]),
        })

    return {
        "career_history": history,
        "odd_job_history": odd_history,
    }
