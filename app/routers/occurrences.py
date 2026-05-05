"""
Occurrences router — life events that affect mechanics over time.

Max 5 active occurrences per player at once.
Mental health occurrences require opt-in.

Endpoints:
  POST   /occurrences/add        — add an occurrence
  DELETE /occurrences/{id}       — remove/resolve an occurrence
  GET    /occurrences            — list active occurrences
  GET    /occurrences/all        — list all (including resolved)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db, is_postgres
from app.services.achievements import increment_stat

router = APIRouter(prefix="/occurrences", tags=["occurrences"])

MAX_ACTIVE = 5

# Occurrences that require mental health opt-in
MH_OCCURRENCES = {
    "depression", "anxiety", "grief", "burnout", "dissociation",
    "disordered_eating", "trauma_response"
}

# Valid occurrence keys from docs
VALID_OCCURRENCES = {
    # Relationship
    "new_relationship", "breakup", "divorce", "long_distance", "engagement",
    "marriage", "open_relationship",
    # Career / financial
    "new_job", "job_loss", "promotion", "debt", "financial_windfall",
    # Physical health
    "injury", "illness", "recovery", "surgery", "chronic_condition",
    "pregnancy", "new_parent",
    # Life transitions
    "moving", "new_home", "studying", "graduation", "loss_of_loved_one",
    "major_birthday", "new_pet",
    # Mental health (opt-in)
    "depression", "anxiety", "grief", "burnout", "dissociation",
    "disordered_eating", "trauma_response",
    # Unexpected (server-generated)
    "robbery_aftermath", "illness_aftermath",
}

OCCURRENCE_DISPLAY = {
    "new_relationship":    ("New Relationship 💕",   "relationship"),
    "breakup":             ("Breakup 💔",             "relationship"),
    "divorce":             ("Divorce 💔",             "relationship"),
    "long_distance":       ("Long Distance 📱",       "relationship"),
    "engagement":          ("Engaged 💍",             "relationship"),
    "marriage":            ("Married 🌸",             "relationship"),
    "open_relationship":   ("Open Relationship 💞",   "relationship"),
    "new_job":             ("New Job 💼",             "career_financial"),
    "job_loss":            ("Job Loss 📦",            "career_financial"),
    "promotion":           ("Promotion 🎉",           "career_financial"),
    "debt":                ("In Debt 💸",             "career_financial"),
    "financial_windfall":  ("Financial Windfall 💰",  "career_financial"),
    "injury":              ("Injured 🩹",             "physical_health"),
    "illness":             ("Illness 🤒",             "physical_health"),
    "recovery":            ("Recovery 🌱",            "physical_health"),
    "surgery":             ("Post-Surgery 🏥",        "physical_health"),
    "chronic_condition":   ("Chronic Condition 💊",   "physical_health"),
    "pregnancy":           ("Pregnant 🤰",            "physical_health"),
    "new_parent":          ("New Parent 🍼",          "physical_health"),
    "moving":              ("Moving 📦",              "life_transition"),
    "new_home":            ("Settled In 🏠",          "life_transition"),
    "studying":            ("Studying 📚",            "life_transition"),
    "graduation":          ("Graduated 🎓",           "life_transition"),
    "loss_of_loved_one":   ("Loss 🕊️",               "life_transition"),
    "major_birthday":      ("Big Birthday 🎂",        "life_transition"),
    "new_pet":             ("New Pet 🐾",             "life_transition"),
    "depression":          ("Depression 🌧️",          "mental_health"),
    "anxiety":             ("Anxiety 🌀",             "mental_health"),
    "grief":               ("Grief 🌊",              "mental_health"),
    "burnout":             ("Burnout 🏳️",            "mental_health"),
    "dissociation":        ("Dissociation 🌫️",        "mental_health"),
    "disordered_eating":   ("ED Recovery 🌱",         "mental_health"),
    "trauma_response":     ("Trauma Response 💙",     "mental_health"),
    "robbery_aftermath":   ("Robbery Aftermath 😟",   "unexpected"),
    "illness_aftermath":   ("Recovering from Illness 🤒", "unexpected"),
}


# ── Schemas ───────────────────────────────────────────────────────────────────

class AddOccurrence(BaseModel):
    token: str
    occurrence_key: str
    sub_stage: str | None = None
    ends_at: str | None = None   # YYYY-MM-DD, optional
    metadata: dict | None = None
    meta: dict | None = None     # alias — frontend sends 'meta', merged into metadata


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


async def _check_mh_optin(player_id: int, db) -> bool:
    if is_postgres():
        row = await db.fetchrow(
            "SELECT is_mental_health_opted_in FROM player_profiles WHERE player_id = $1",
            player_id)
    else:
        async with db.execute(
            "SELECT is_mental_health_opted_in FROM player_profiles WHERE player_id = ?",
            (player_id,)
        ) as cur:
            row = await cur.fetchone()
    return bool(row and row["is_mental_health_opted_in"])


# ── POST /occurrences/add ─────────────────────────────────────────────────────

@router.post("/add")
async def add_occurrence(body: AddOccurrence, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    key = body.occurrence_key.lower().strip()
    if key not in VALID_OCCURRENCES:
        raise HTTPException(status_code=400, detail=f"Unknown occurrence key: {key}")

    player_id = player["id"]

    # Check mental health opt-in
    if key in MH_OCCURRENCES:
        if not await _check_mh_optin(player_id, db):
            raise HTTPException(
                status_code=403,
                detail="Mental health occurrences require opt-in in Settings."
            )

    # Check max active occurrences
    if is_postgres():
        active_count = await db.fetchval(
            """SELECT COUNT(*) FROM player_occurrences
               WHERE player_id = $1 AND is_resolved = 0""",
            player_id)
    else:
        async with db.execute(
            """SELECT COUNT(*) as cnt FROM player_occurrences
               WHERE player_id = ? AND is_resolved = 0""",
            (player_id,)
        ) as cur:
            row = await cur.fetchone()
            active_count = row["cnt"] if row else 0

    if active_count >= MAX_ACTIVE:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_ACTIVE} active occurrences reached."
        )

    # Check not already active
    if is_postgres():
        existing = await db.fetchrow(
            """SELECT id FROM player_occurrences
               WHERE player_id = $1 AND occurrence_key = $2 AND is_resolved = 0""",
            player_id, key)
    else:
        async with db.execute(
            """SELECT id FROM player_occurrences
               WHERE player_id = ? AND occurrence_key = ? AND is_resolved = 0""",
            (player_id, key)
        ) as cur:
            existing = await cur.fetchone()

    if existing:
        return {"status": "already_active"}

    import json
    # Merge body.meta (frontend key) into body.metadata, with meta taking precedence
    merged = {}
    if body.metadata:
        merged.update(body.metadata)
    if body.meta:
        merged.update(body.meta)
    meta = json.dumps(merged)

    sub_stage = body.sub_stage or None

    if is_postgres():
        occ_id = await db.fetchval(
            """INSERT INTO player_occurrences
               (player_id, occurrence_key, sub_stage, ends_at, metadata)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id""",
            player_id, key, sub_stage, body.ends_at, meta)
    else:
        async with db.execute(
            """INSERT INTO player_occurrences
               (player_id, occurrence_key, sub_stage, ends_at, metadata)
               VALUES (?, ?, ?, ?, ?)""",
            (player_id, key, sub_stage, body.ends_at, meta)
        ) as cur:
            occ_id = cur.lastrowid
        await db.commit()

    display = OCCURRENCE_DISPLAY.get(key, (key, "unknown"))
    try:
        await increment_stat(player_id, "total_occurrences_added")
    except Exception:
        pass
    return {"status": "added", "occurrence_id": occ_id, "display": display[0]}


# ── DELETE /occurrences/{id} ──────────────────────────────────────────────────

@router.delete("/{occurrence_id}")
async def remove_occurrence(occurrence_id: int, token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        row = await db.fetchrow(
            "SELECT id FROM player_occurrences WHERE id = $1 AND player_id = $2",
            occurrence_id, player_id)
    else:
        async with db.execute(
            "SELECT id FROM player_occurrences WHERE id = ? AND player_id = ?",
            (occurrence_id, player_id)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Occurrence not found.")

    if is_postgres():
        await db.execute(
            """UPDATE player_occurrences
               SET is_resolved = 1, ends_at = now()::date::text
               WHERE id = $1""",
            occurrence_id)
    else:
        await db.execute(
            """UPDATE player_occurrences
               SET is_resolved = 1, ends_at = date('now')
               WHERE id = ?""",
            (occurrence_id,))
        await db.commit()

    return {"status": "resolved"}


# ── GET /occurrences ──────────────────────────────────────────────────────────

@router.get("")
async def list_occurrences(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        rows = await db.fetch(
            """SELECT * FROM player_occurrences
               WHERE player_id = $1 AND is_resolved = 0
               ORDER BY started_at DESC""",
            player_id)
    else:
        async with db.execute(
            """SELECT * FROM player_occurrences
               WHERE player_id = ? AND is_resolved = 0
               ORDER BY started_at DESC""",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    result = []
    for r in rows:
        d = dict(r)
        info = OCCURRENCE_DISPLAY.get(d["occurrence_key"], (d["occurrence_key"], "unknown"))
        d["display_name"] = info[0]
        d["category"]     = info[1]
        result.append(d)

    return {"occurrences": result}


# ── GET /occurrences/all ──────────────────────────────────────────────────────

@router.get("/all")
async def list_all_occurrences(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        rows = await db.fetch(
            """SELECT * FROM player_occurrences
               WHERE player_id = $1
               ORDER BY started_at DESC LIMIT 50""",
            player_id)
    else:
        async with db.execute(
            """SELECT * FROM player_occurrences
               WHERE player_id = ?
               ORDER BY started_at DESC LIMIT 50""",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    result = []
    for r in rows:
        d = dict(r)
        info = OCCURRENCE_DISPLAY.get(d["occurrence_key"], (d["occurrence_key"], "unknown"))
        d["display_name"] = info[0]
        d["category"]     = info[1]
        result.append(d)

    return {"occurrences": result}
