"""
Questionnaire router.

Handles profile setup + trait scoring from the questionnaire webapp.
Also supports the 'Build' path (direct trait pick list).

Endpoints:
  POST /questionnaire/submit        — submit profile + questionnaire answers
  POST /questionnaire/build         — direct trait selection (Build path)
  GET  /questionnaire/status        — check if questionnaire completed + cooldown
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta

from app.database import get_db, is_postgres
from app.services.traits import (
    score_answers, pick_traits, apply_traits_to_player, award_negative_bonuses
)
from app.services.notifications import push_notification

router = APIRouter(prefix="/questionnaire", tags=["questionnaire"])

VALID_PRONOUNS     = ["she/her", "he/him", "they/them", "she/they", "he/they", "any/all", "other"]
VALID_AGAB         = ["female", "male", "intersex", "prefer_not_to_say"]
VALID_GENDER_EXPR  = ["feminine", "masculine", "androgynous", "fluid", "nonbinary", "other"]
VALID_AGE_GROUPS   = ["18-21", "22-25", "26-30", "31-35", "36-40", "40+"]
VALID_SEXUALITY    = ["straight", "gay_lesbian", "bisexual", "pansexual", "asexual", "queer", "questioning", "other"]


# ── Schemas ───────────────────────────────────────────────────────────────────

class QuestionnaireSubmit(BaseModel):
    token: str
    # Profile fields
    display_name: str | None = None
    pronouns: str | None = None
    biology_agab: str | None = None
    gender_expression: str | None = None
    age_group: str | None = None
    sexuality: str | None = None
    # Questionnaire answer keys (7 answers, one per question)
    answers: list[str]


class BuildSubmit(BaseModel):
    token: str
    trait_keys: list[str]   # directly chosen traits, max 5


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


async def _update_profile(player_id: int, data: dict, db):
    """Upsert player_profiles with provided fields."""
    if is_postgres():
        await db.execute(
            """INSERT INTO player_profiles (player_id)
               VALUES ($1)
               ON CONFLICT (player_id) DO NOTHING""",
            player_id)
        if data:
            sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(data))
            await db.execute(
                f"UPDATE player_profiles SET {sets}, questionnaire_completed_at = now()::text WHERE player_id = $1",
                player_id, *data.values())
    else:
        await db.execute(
            "INSERT OR IGNORE INTO player_profiles (player_id) VALUES (?)", (player_id,))
        if data:
            sets = ", ".join(f"{k} = ?" for k in data)
            await db.execute(
                f"UPDATE player_profiles SET {sets}, questionnaire_completed_at = datetime('now') WHERE player_id = ?",
                (*data.values(), player_id))
        await db.commit()


async def _update_display_name(player_id: int, display_name: str, db):
    if is_postgres():
        await db.execute(
            "UPDATE players SET display_name = $1 WHERE id = $2",
            display_name, player_id)
    else:
        await db.execute(
            "UPDATE players SET display_name = ? WHERE id = ?",
            (display_name, player_id))
        await db.commit()


# ── POST /questionnaire/submit ────────────────────────────────────────────────

@router.post("/submit")
async def submit_questionnaire(body: QuestionnaireSubmit, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    # ── Update display name ──
    if body.display_name:
        name = body.display_name.strip()[:40]
        if name:
            await _update_display_name(player_id, name, db)

    # ── Update profile fields ──
    profile_data = {}
    if body.pronouns and body.pronouns in VALID_PRONOUNS:
        profile_data["pronouns"] = body.pronouns
    if body.biology_agab and body.biology_agab in VALID_AGAB:
        profile_data["biology_agab"] = body.biology_agab
    if body.gender_expression and body.gender_expression in VALID_GENDER_EXPR:
        profile_data["gender_expression"] = body.gender_expression
    if body.age_group and body.age_group in VALID_AGE_GROUPS:
        profile_data["age_group"] = body.age_group
    if body.sexuality and body.sexuality in VALID_SEXUALITY:
        profile_data["sexuality"] = body.sexuality

    await _update_profile(player_id, profile_data, db)

    # ── Score answers ──
    if not body.answers:
        raise HTTPException(status_code=400, detail="No answers provided.")

    scored   = score_answers(body.answers)
    selected = pick_traits(scored)

    await apply_traits_to_player(player_id, selected, db)
    bonus = await award_negative_bonuses(player_id, selected, db)

    # ── Auto-apply cycle trait if eligible biology ──
    if body.biology_agab in ("female", "intersex"):
        if is_postgres():
            await db.execute(
                """INSERT INTO player_traits (player_id, trait_key, source)
                   VALUES ($1, 'cycle', 'biology')
                   ON CONFLICT (player_id, trait_key) DO NOTHING""",
                player_id)
        else:
            await db.execute(
                """INSERT OR IGNORE INTO player_traits (player_id, trait_key, source)
                   VALUES (?, 'cycle', 'biology')""",
                (player_id,))
            await db.commit()

    await push_notification(
        player_id=player_id,
        app_source="canvas",
        title="Welcome to the city 🌆",
        body="Your HUD is ready. Check your needs and get started.",
        priority="normal",
        db=db,
    )

    from app.config import get_config
    cfg = get_config()
    trait_defs = cfg.get("traits", {}).get("definitions", {})
    display_names = [trait_defs.get(k, {}).get("display", k) for k in selected]

    return {
        "status":        "complete",
        "traits_applied": selected,
        "trait_displays": display_names,
        "lumen_bonus":   bonus,
    }


# ── POST /questionnaire/build ─────────────────────────────────────────────────

@router.post("/build")
async def build_traits(body: BuildSubmit, db=Depends(get_db)):
    """Direct trait picker path — player manually selects up to 5 traits."""
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    # Check 14-day cooldown
    if is_postgres():
        existing = await db.fetchrow(
            "SELECT applied_at FROM player_traits WHERE player_id = $1 ORDER BY applied_at DESC LIMIT 1",
            player_id)
    else:
        async with db.execute(
            "SELECT applied_at FROM player_traits WHERE player_id = ? ORDER BY applied_at DESC LIMIT 1",
            (player_id,)
        ) as cur:
            existing = await cur.fetchone()

    if existing and existing["applied_at"]:
        try:
            last = datetime.fromisoformat(existing["applied_at"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - last).days < 14:
                raise HTTPException(
                    status_code=400,
                    detail="Traits can only be changed every 14 days.")
        except (ValueError, TypeError):
            pass

    from app.config import get_config
    cfg       = get_config()
    trait_defs = cfg.get("traits", {}).get("definitions", {})
    valid_keys = set(trait_defs.keys())

    selected = [k for k in body.trait_keys[:5] if k in valid_keys]
    if not selected:
        raise HTTPException(status_code=400, detail="No valid trait keys provided.")

    await apply_traits_to_player(player_id, selected, db, source="manual")
    bonus = await award_negative_bonuses(player_id, selected, db)

    return {
        "status":        "applied",
        "traits_applied": selected,
        "lumen_bonus":   bonus,
    }


# ── GET /questionnaire/status ─────────────────────────────────────────────────

@router.get("/status")
async def questionnaire_status(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        profile = await db.fetchrow(
            "SELECT questionnaire_completed_at FROM player_profiles WHERE player_id = $1",
            player_id)
        trait_rows = await db.fetch(
            "SELECT trait_key, applied_at FROM player_traits WHERE player_id = $1",
            player_id)
    else:
        async with db.execute(
            "SELECT questionnaire_completed_at FROM player_profiles WHERE player_id = ?",
            (player_id,)
        ) as cur:
            profile = await cur.fetchone()
        async with db.execute(
            "SELECT trait_key, applied_at FROM player_traits WHERE player_id = ?",
            (player_id,)
        ) as cur:
            trait_rows = await cur.fetchall()

    completed_at = profile["questionnaire_completed_at"] if profile else None
    traits       = [r["trait_key"] for r in trait_rows]

    days_until_edit = 0
    if trait_rows:
        try:
            last_applied = sorted([r["applied_at"] for r in trait_rows if r["applied_at"]])[-1]
            last_dt      = datetime.fromisoformat(last_applied.replace("Z", "+00:00"))
            days_since   = (datetime.now(timezone.utc) - last_dt).days
            days_until_edit = max(0, 14 - days_since)
        except Exception:
            pass

    return {
        "completed":        bool(completed_at),
        "completed_at":     completed_at,
        "traits":           traits,
        "can_edit":         days_until_edit == 0,
        "days_until_edit":  days_until_edit,
    }
