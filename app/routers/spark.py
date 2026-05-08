"""
Spark — dating app router.

Endpoints:
  GET   /spark/profile                 — get own Spark profile (creates if missing)
  POST  /spark/profile/setup           — create/update Spark profile
  POST  /spark/profile/activate        — toggle profile active/paused
  POST  /spark/profile/filters         — update discovery filters

  GET   /spark/discover                — get next card(s) for the stack
  POST  /spark/swipe                   — like / pass / superlike
  POST  /spark/rewind                  — undo last pass (costs Lumens)
  POST  /spark/buy-likes               — buy extra likes
  POST  /spark/buy-superlikes          — buy extra superlikes

  GET   /spark/matches                 — list active matches
  POST  /spark/matches/{id}/cancel     — unmatch

  POST  /spark/report                  — report a profile
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import date, datetime, timezone

from app.database import get_db, is_postgres
from app.services.notifications import push_notification

router = APIRouter(prefix="/spark", tags=["spark"])

# ── Constants ─────────────────────────────────────────────────────────────────

PROMPT_QUESTIONS = [
    "The way to my heart is…",
    "I'm known for…",
    "Best SL date idea:",
    "I'll know we click if…",
    "My love language is…",
    "Something I'm proud of:",
    "A dealbreaker for me is…",
    "I'm looking for someone who…",
    "The most important thing in a relationship:",
    "Ask me about…",
    "I spend my time in SL…",
    "I can't stop thinking about…",
    "My ideal Sunday in SL:",
    "One thing I want you to know:",
    "I'm at my best when…",
]

LOOKING_FOR_OPTIONS    = ["casual", "serious", "friendship", "open"]
REL_STYLE_OPTIONS      = ["monogamous", "polyamorous", "open", "not_specified"]
ORIENTATION_OPTIONS    = ["straight", "gay", "lesbian", "bisexual", "pansexual",
                          "asexual", "queer", "questioning", "not_specified"]
SEEKING_OPTIONS        = ["men", "women", "nonbinary", "everyone"]
VISIBILITY_OPTIONS     = ["everyone", "followers_only", "mutual_follows_only"]
REPORT_REASONS         = ["inappropriate_content", "harassment", "fake_profile",
                          "spam", "other"]

LIKE_PACKS = {
    "small":  {"likes": 5,  "cost": 25},
    "large":  {"likes": 20, "cost": 80},
}
SUPERLIKE_PACK = {"superlikes": 3, "cost": 30}
REWIND_COST    = 15


# ── Schemas ───────────────────────────────────────────────────────────────────

class SetupProfile(BaseModel):
    token: str
    bio: str | None = None
    looking_for: str | None = None
    relationship_style: str | None = None
    orientation: str | None = None
    gender_identity: str | None = None
    seeking: str | None = None
    visibility: str | None = None
    prompt_1_question: str | None = None
    prompt_1_answer: str | None = None
    prompt_2_question: str | None = None
    prompt_2_answer: str | None = None
    prompt_3_question: str | None = None
    prompt_3_answer: str | None = None


class UpdateFilters(BaseModel):
    token: str
    filter_gender: str | None = None       # comma-separated or "everyone"
    filter_orientation: str | None = None  # comma-separated or "everyone"
    filter_looking_for: str | None = None  # comma-separated or "all"
    filter_age_min: str | None = None      # age_group string e.g. "22-25"
    filter_age_max: str | None = None


class SwipeBody(BaseModel):
    token: str
    target_id: int
    action: str   # like | pass | superlike


class CancelMatch(BaseModel):
    token: str


class ReportBody(BaseModel):
    token: str
    reported_id: int
    reason: str
    notes: str | None = None


class BuyBody(BaseModel):
    token: str
    pack: str


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


async def _get_or_create_spark_profile(player_id: int, db) -> dict:
    if is_postgres():
        row = await db.fetchrow(
            "SELECT * FROM spark_profiles WHERE player_id = $1", player_id)
        if not row:
            await db.execute(
                "INSERT INTO spark_profiles (player_id) VALUES ($1) ON CONFLICT DO NOTHING",
                player_id)
            row = await db.fetchrow(
                "SELECT * FROM spark_profiles WHERE player_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT * FROM spark_profiles WHERE player_id = ?", (player_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT OR IGNORE INTO spark_profiles (player_id) VALUES (?)", (player_id,))
            await db.commit()
            async with db.execute(
                "SELECT * FROM spark_profiles WHERE player_id = ?", (player_id,)
            ) as cur:
                row = await cur.fetchone()
    return dict(row) if row else {}


def _reset_daily_if_needed(profile: dict) -> dict:
    """Reset daily likes/superlikes if it's a new day."""
    today = date.today().isoformat()
    profile = dict(profile)
    if profile.get("daily_likes_reset_date") != today:
        profile["daily_likes_remaining"] = 10
        profile["daily_likes_reset_date"] = today
    if profile.get("daily_superlikes_reset_date") != today:
        profile["daily_superlikes_remaining"] = 1
        profile["daily_superlikes_reset_date"] = today
    return profile


async def _save_daily_reset(player_id: int, profile: dict, db):
    """Persist daily reset to DB."""
    if is_postgres():
        await db.execute(
            """UPDATE spark_profiles
               SET daily_likes_remaining=$1, daily_likes_reset_date=$2,
                   daily_superlikes_remaining=$3, daily_superlikes_reset_date=$4
               WHERE player_id=$5""",
            profile["daily_likes_remaining"], profile["daily_likes_reset_date"],
            profile["daily_superlikes_remaining"], profile["daily_superlikes_reset_date"],
            player_id)
    else:
        await db.execute(
            """UPDATE spark_profiles
               SET daily_likes_remaining=?, daily_likes_reset_date=?,
                   daily_superlikes_remaining=?, daily_superlikes_reset_date=?
               WHERE player_id=?""",
            (profile["daily_likes_remaining"], profile["daily_likes_reset_date"],
             profile["daily_superlikes_remaining"], profile["daily_superlikes_reset_date"],
             player_id))
        await db.commit()


async def _get_blocked_ids(player_id: int, db) -> set:
    """Get all player IDs this player has blocked or been blocked by."""
    try:
        if is_postgres():
            rows = await db.fetch(
                """SELECT blocker_id, blocked_id FROM blocks
                   WHERE blocker_id = $1 OR blocked_id = $1""", player_id)
        else:
            async with db.execute(
                """SELECT blocker_id, blocked_id FROM blocks
                   WHERE blocker_id = ? OR blocked_id = ?""", (player_id, player_id)
            ) as cur:
                rows = await cur.fetchall()
        blocked = set()
        for r in rows:
            blocked.add(r["blocker_id"])
            blocked.add(r["blocked_id"])
        blocked.discard(player_id)
        return blocked
    except Exception:
        return set()  # blocks table may not exist yet


async def _check_match(player_id: int, target_id: int, db) -> bool:
    """Check if target has already liked player_id — if so, create a match."""
    if is_postgres():
        mutual = await db.fetchrow(
            """SELECT id FROM spark_interests
               WHERE player_id = $1 AND target_id = $2
               AND action IN ('like', 'superlike')""",
            target_id, player_id)
    else:
        async with db.execute(
            """SELECT id FROM spark_interests
               WHERE player_id = ? AND target_id = ?
               AND action IN ('like', 'superlike')""",
            (target_id, player_id)
        ) as cur:
            mutual = await cur.fetchone()

    if not mutual:
        return False

    # Create match — always store lower id as player_a for dedup
    a, b = min(player_id, target_id), max(player_id, target_id)
    if is_postgres():
        await db.execute(
            """INSERT INTO spark_matches (player_a_id, player_b_id)
               VALUES ($1, $2) ON CONFLICT DO NOTHING""",
            a, b)
    else:
        await db.execute(
            "INSERT OR IGNORE INTO spark_matches (player_a_id, player_b_id) VALUES (?, ?)",
            (a, b))
        await db.commit()
    return True


async def _enrich_spark_profile(sp: dict, db) -> dict:
    """Attach display_name, age_group, profile_pic_uuid to a spark profile row."""
    pid = sp["player_id"]
    if is_postgres():
        player = await db.fetchrow(
            "SELECT display_name FROM players WHERE id = $1", pid)
        prof   = await db.fetchrow(
            "SELECT age_group, sexuality, gender_expression, profile_pic_uuid FROM player_profiles WHERE player_id = $1",
            pid)
    else:
        async with db.execute(
            "SELECT display_name FROM players WHERE id = ?", (pid,)
        ) as cur:
            player = await cur.fetchone()
        async with db.execute(
            "SELECT age_group, sexuality, gender_expression, profile_pic_uuid FROM player_profiles WHERE player_id = ?",
            (pid,)
        ) as cur:
            prof = await cur.fetchone()

    sp["display_name"]      = player["display_name"] if player else "Unknown"
    sp["age_group"]         = prof["age_group"] if prof else None
    sp["profile_pic_uuid"]  = prof["profile_pic_uuid"] if prof else None
    sp["questionnaire_gender"] = prof["gender_expression"] if prof else None
    sp["questionnaire_sexuality"] = prof["sexuality"] if prof else None
    return sp


# ── GET /spark/profile ────────────────────────────────────────────────────────

@router.get("/profile")
async def get_spark_profile(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    profile   = await _get_or_create_spark_profile(player_id, db)
    profile   = _reset_daily_if_needed(profile)
    await _save_daily_reset(player_id, profile, db)
    profile   = await _enrich_spark_profile(profile, db)

    return {
        "profile": profile,
        "prompt_questions": PROMPT_QUESTIONS,
        "looking_for_options": LOOKING_FOR_OPTIONS,
        "relationship_style_options": REL_STYLE_OPTIONS,
        "orientation_options": ORIENTATION_OPTIONS,
        "seeking_options": SEEKING_OPTIONS,
        "visibility_options": VISIBILITY_OPTIONS,
    }


# ── POST /spark/profile/setup ─────────────────────────────────────────────────

@router.post("/profile/setup")
async def setup_spark_profile(body: SetupProfile, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    await _get_or_create_spark_profile(player_id, db)

    fields = {}
    if body.bio is not None:
        fields["bio"] = body.bio.strip()[:400]
    if body.looking_for in LOOKING_FOR_OPTIONS:
        fields["looking_for"] = body.looking_for
    if body.relationship_style in REL_STYLE_OPTIONS:
        fields["relationship_style"] = body.relationship_style
    if body.orientation in ORIENTATION_OPTIONS:
        fields["orientation"] = body.orientation
    if body.gender_identity is not None:
        fields["gender_identity"] = body.gender_identity.strip()[:60]
    if body.seeking is not None:
        fields["seeking"] = body.seeking
    if body.visibility in VISIBILITY_OPTIONS:
        fields["visibility"] = body.visibility
    for n in (1, 2, 3):
        q = getattr(body, f"prompt_{n}_question")
        a = getattr(body, f"prompt_{n}_answer")
        if q is not None and q in PROMPT_QUESTIONS:
            fields[f"prompt_{n}_question"] = q
        if a is not None:
            fields[f"prompt_{n}_answer"] = a.strip()[:300]

    fields["updated_at"] = datetime.now(timezone.utc).isoformat()

    if not fields:
        return {"status": "no_changes"}

    if is_postgres():
        sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
        await db.execute(
            f"UPDATE spark_profiles SET {sets} WHERE player_id = $1",
            player_id, *fields.values())
    else:
        sets = ", ".join(f"{k} = ?" for k in fields)
        await db.execute(
            f"UPDATE spark_profiles SET {sets} WHERE player_id = ?",
            (*fields.values(), player_id))
        await db.commit()

    return {"status": "updated"}


# ── POST /spark/profile/activate ──────────────────────────────────────────────

@router.post("/profile/activate")
async def toggle_activate(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    profile   = await _get_or_create_spark_profile(player_id, db)
    new_state = 0 if profile.get("is_active") else 1

    if is_postgres():
        await db.execute(
            "UPDATE spark_profiles SET is_active = $1 WHERE player_id = $2",
            new_state, player_id)
    else:
        await db.execute(
            "UPDATE spark_profiles SET is_active = ? WHERE player_id = ?",
            (new_state, player_id))
        await db.commit()

    return {"status": "active" if new_state else "paused", "is_active": bool(new_state)}


# ── POST /spark/profile/filters ───────────────────────────────────────────────

@router.post("/profile/filters")
async def update_filters(body: UpdateFilters, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    await _get_or_create_spark_profile(player_id, db)

    fields = {}
    if body.filter_gender is not None:      fields["filter_gender"]      = body.filter_gender
    if body.filter_orientation is not None: fields["filter_orientation"] = body.filter_orientation
    if body.filter_looking_for is not None: fields["filter_looking_for"] = body.filter_looking_for
    if body.filter_age_min is not None:     fields["filter_age_min"]     = body.filter_age_min
    if body.filter_age_max is not None:     fields["filter_age_max"]     = body.filter_age_max

    if not fields:
        return {"status": "no_changes"}

    if is_postgres():
        sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
        await db.execute(
            f"UPDATE spark_profiles SET {sets} WHERE player_id = $1",
            player_id, *fields.values())
    else:
        sets = ", ".join(f"{k} = ?" for k in fields)
        await db.execute(
            f"UPDATE spark_profiles SET {sets} WHERE player_id = ?",
            (*fields.values(), player_id))
        await db.commit()

    return {"status": "updated", "filters": fields}


# ── GET /spark/discover ───────────────────────────────────────────────────────

@router.get("/discover")
async def discover(token: str, db=Depends(get_db)):
    """Return next batch of profiles for the card stack."""
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    profile   = await _get_or_create_spark_profile(player_id, db)
    blocked   = await _get_blocked_ids(player_id, db)

    # IDs already swiped
    if is_postgres():
        swiped_rows = await db.fetch(
            "SELECT target_id FROM spark_interests WHERE player_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT target_id FROM spark_interests WHERE player_id = ?", (player_id,)
        ) as cur:
            swiped_rows = await cur.fetchall()
    swiped = {r["target_id"] for r in swiped_rows}
    exclude = swiped | blocked | {player_id}

    # Build visibility filter
    # Everyone = always visible
    # followers_only = viewer follows them
    # mutual_follows_only = both follow each other
    try:
        if is_postgres():
            candidates = await db.fetch(
                """SELECT sp2.*, p.display_name, pp.age_group, pp.gender_expression,
                          pp.sexuality, pp.profile_pic_uuid
                   FROM spark_profiles sp2
                   JOIN players p ON p.id = sp2.player_id
                   LEFT JOIN player_profiles pp ON pp.player_id = sp2.player_id
                   WHERE sp2.player_id != $1
                   AND sp2.is_active = 1
                   AND (
                       sp2.visibility = 'everyone'
                       OR (sp2.visibility = 'followers_only' AND EXISTS (
                           SELECT 1 FROM follows WHERE follower_id = $1 AND following_id = sp2.player_id
                       ))
                       OR (sp2.visibility = 'mutual_follows_only' AND EXISTS (
                           SELECT 1 FROM follows WHERE follower_id = $1 AND following_id = sp2.player_id
                       ) AND EXISTS (
                           SELECT 1 FROM follows WHERE follower_id = sp2.player_id AND following_id = $1
                       ))
                   )
                   ORDER BY
                       CASE WHEN EXISTS (
                           SELECT 1 FROM follows WHERE follower_id = $1 AND following_id = sp2.player_id
                       ) AND EXISTS (
                           SELECT 1 FROM follows WHERE follower_id = sp2.player_id AND following_id = $1
                       ) THEN 0
                       WHEN EXISTS (
                           SELECT 1 FROM follows WHERE follower_id = sp2.player_id AND following_id = $1
                       ) THEN 1
                       ELSE 2 END,
                       sp2.updated_at DESC
                   LIMIT 30""", player_id)
        else:
            async with db.execute(
                """SELECT sp2.*, p.display_name, pp.age_group, pp.gender_expression,
                          pp.sexuality, pp.profile_pic_uuid
                   FROM spark_profiles sp2
                   JOIN players p ON p.id = sp2.player_id
                   LEFT JOIN player_profiles pp ON pp.player_id = sp2.player_id
                   WHERE sp2.player_id != ?
                   AND sp2.is_active = 1
                   AND (
                       sp2.visibility = 'everyone'
                       OR (sp2.visibility = 'followers_only' AND EXISTS (
                           SELECT 1 FROM follows WHERE follower_id = ? AND following_id = sp2.player_id
                       ))
                       OR (sp2.visibility = 'mutual_follows_only' AND EXISTS (
                           SELECT 1 FROM follows WHERE follower_id = ? AND following_id = sp2.player_id
                       ) AND EXISTS (
                           SELECT 1 FROM follows WHERE follower_id = sp2.player_id AND following_id = ?
                       ))
                   )
                   ORDER BY sp2.updated_at DESC
                   LIMIT 30""",
                (player_id, player_id, player_id, player_id)
            ) as cur:
                candidates = await cur.fetchall()
    except Exception as e:
        return {"cards": [], "remaining": 0, "error": str(e)}

    # Apply filters and exclusions in Python
    filters = {
        "gender":      (profile.get("filter_gender") or "").split(",") if profile.get("filter_gender") else [],
        "orientation": (profile.get("filter_orientation") or "").split(",") if profile.get("filter_orientation") else [],
        "looking_for": (profile.get("filter_looking_for") or "").split(",") if profile.get("filter_looking_for") else [],
        "age_min":     profile.get("filter_age_min"),
        "age_max":     profile.get("filter_age_max"),
    }

    AGE_ORDER = ["18-21", "22-25", "26-30", "31-35", "36-40", "40+"]

    def age_passes(candidate_age: str) -> bool:
        if not filters["age_min"] and not filters["age_max"]:
            return True
        if not candidate_age:
            return True
        try:
            ci = AGE_ORDER.index(candidate_age)
            if filters["age_min"]:
                mi = AGE_ORDER.index(filters["age_min"])
                if ci < mi:
                    return False
            if filters["age_max"]:
                ma = AGE_ORDER.index(filters["age_max"])
                if ci > ma:
                    return False
        except ValueError:
            pass
        return True

    results = []
    for c in candidates:
        cd = dict(c)
        if cd["player_id"] in exclude:
            continue
        # Gender filter
        if filters["gender"] and "everyone" not in filters["gender"]:
            g = cd.get("gender_expression") or cd.get("gender_identity") or ""
            if g not in filters["gender"]:
                continue
        # Orientation filter
        if filters["orientation"] and "everyone" not in filters["orientation"]:
            o = cd.get("sexuality") or cd.get("orientation") or ""
            if o not in filters["orientation"]:
                continue
        # Looking for filter
        if filters["looking_for"] and "all" not in filters["looking_for"]:
            if cd.get("looking_for") not in filters["looking_for"]:
                continue
        # Age filter
        if not age_passes(cd.get("age_group") or ""):
            continue
        results.append(cd)
        if len(results) >= 10:
            break

    return {"cards": results, "remaining": len(results)}


# ── POST /spark/swipe ─────────────────────────────────────────────────────────

@router.post("/swipe")
async def swipe(body: SwipeBody, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if body.action not in ("like", "pass", "superlike"):
        raise HTTPException(status_code=400, detail="Invalid action.")

    profile = await _get_or_create_spark_profile(player_id, db)
    profile = _reset_daily_if_needed(profile)

    # Check like / superlike quotas
    if body.action == "like":
        if profile["daily_likes_remaining"] <= 0:
            raise HTTPException(status_code=429, detail="No likes remaining today. Buy more or wait until tomorrow.")
        profile["daily_likes_remaining"] -= 1
    elif body.action == "superlike":
        if profile["daily_superlikes_remaining"] <= 0:
            raise HTTPException(status_code=429, detail="No superlikes remaining today.")
        profile["daily_superlikes_remaining"] -= 1

    await _save_daily_reset(player_id, profile, db)

    # Record the swipe
    if is_postgres():
        await db.execute(
            """INSERT INTO spark_interests (player_id, target_id, action)
               VALUES ($1, $2, $3)
               ON CONFLICT (player_id, target_id) DO UPDATE SET action = $3""",
            player_id, body.target_id, body.action)
    else:
        await db.execute(
            """INSERT OR REPLACE INTO spark_interests (player_id, target_id, action)
               VALUES (?, ?, ?)""",
            (player_id, body.target_id, body.action))
        await db.commit()

    # Superlike — notify immediately
    if body.action == "superlike":
        await push_notification(
            player_id=body.target_id, app_source="spark",
            title="Someone sent you a Spark ⚡",
            body="Open Spark to find out who.",
            priority="normal", db=db)

    # Check for mutual match
    matched = False
    if body.action in ("like", "superlike"):
        matched = await _check_match(player_id, body.target_id, db)
        if matched:
            # Notify both
            target_name = player["display_name"]
            if is_postgres():
                tp = await db.fetchrow(
                    "SELECT display_name FROM players WHERE id = $1", body.target_id)
            else:
                async with db.execute(
                    "SELECT display_name FROM players WHERE id = ?", (body.target_id,)
                ) as cur:
                    tp = await cur.fetchone()
            my_name     = player["display_name"]
            their_name  = tp["display_name"] if tp else "Someone"

            await push_notification(
                player_id=player_id, app_source="spark",
                title=f"It's a match ✨",
                body=f"You and {their_name} both liked each other. Say something.",
                priority="high", db=db)
            await push_notification(
                player_id=body.target_id, app_source="spark",
                title=f"It's a match ✨",
                body=f"You and {my_name} both liked each other. Say something.",
                priority="high", db=db)

            # Apply vibe
            vibe_key = "new_spark_match"
            for pid in (player_id, body.target_id):
                try:
                    if is_postgres():
                        await db.execute(
                            "INSERT INTO vibes (player_id, vibe_key, is_negative) VALUES ($1,$2,0) ON CONFLICT DO NOTHING",
                            pid, vibe_key)
                    else:
                        await db.execute(
                            "INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative) VALUES (?,?,0)",
                            (pid, vibe_key))
                except Exception:
                    pass
            if not is_postgres():
                await db.commit()

    return {
        "status": "swiped",
        "action": body.action,
        "matched": matched,
        "likes_remaining": profile["daily_likes_remaining"],
        "superlikes_remaining": profile["daily_superlikes_remaining"],
    }


# ── POST /spark/rewind ────────────────────────────────────────────────────────

@router.post("/rewind")
async def rewind(token: str, db=Depends(get_db)):
    """Undo the last pass. Costs Lumens."""
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    # Get last pass
    if is_postgres():
        last = await db.fetchrow(
            """SELECT target_id FROM spark_interests
               WHERE player_id = $1 AND action = 'pass'
               ORDER BY created_at DESC LIMIT 1""", player_id)
    else:
        async with db.execute(
            """SELECT target_id FROM spark_interests
               WHERE player_id = ? AND action = 'pass'
               ORDER BY created_at DESC LIMIT 1""", (player_id,)
        ) as cur:
            last = await cur.fetchone()

    if not last:
        raise HTTPException(status_code=404, detail="No recent passes to rewind.")

    # Check wallet
    if is_postgres():
        wallet = await db.fetchrow(
            "SELECT balance FROM wallets WHERE player_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT balance FROM wallets WHERE player_id = ?", (player_id,)
        ) as cur:
            wallet = await cur.fetchone()

    if not wallet or float(wallet["balance"]) < REWIND_COST:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient Lumens. Rewind costs ✦{REWIND_COST}.")

    # Deduct and delete the pass
    now = datetime.now(timezone.utc).isoformat()
    if is_postgres():
        await db.execute(
            """UPDATE wallets SET balance = balance - $1,
               total_spent = total_spent + $2, last_updated = $3
               WHERE player_id = $4""",
            REWIND_COST, REWIND_COST, now, player_id)
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES ($1, $2, 'purchase', 'Spark rewind', $3)""",
            player_id, -REWIND_COST, now)
        await db.execute(
            "DELETE FROM spark_interests WHERE player_id = $1 AND target_id = $2",
            player_id, last["target_id"])
    else:
        await db.execute(
            """UPDATE wallets SET balance = balance - ?,
               total_spent = total_spent + ?, last_updated = ?
               WHERE player_id = ?""",
            (REWIND_COST, REWIND_COST, now, player_id))
        await db.execute(
            "DELETE FROM spark_interests WHERE player_id = ? AND target_id = ?",
            (player_id, last["target_id"]))
        await db.commit()

    return {"status": "rewound", "target_id": last["target_id"], "cost": REWIND_COST}


# ── POST /spark/buy-likes ─────────────────────────────────────────────────────

@router.post("/buy-likes")
async def buy_likes(body: BuyBody, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    pack = LIKE_PACKS.get(body.pack)
    if not pack:
        raise HTTPException(status_code=400, detail="Invalid pack. Choose 'small' or 'large'.")

    player_id = player["id"]

    if is_postgres():
        wallet = await db.fetchrow(
            "SELECT balance FROM wallets WHERE player_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT balance FROM wallets WHERE player_id = ?", (player_id,)
        ) as cur:
            wallet = await cur.fetchone()

    if not wallet or float(wallet["balance"]) < pack["cost"]:
        raise HTTPException(status_code=400, detail=f"Insufficient Lumens. Need ✦{pack['cost']}.")

    now = datetime.now(timezone.utc).isoformat()
    if is_postgres():
        await db.execute(
            """UPDATE wallets SET balance = balance - $1,
               total_spent = total_spent + $2, last_updated = $3
               WHERE player_id = $4""",
            pack["cost"], pack["cost"], now, player_id)
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES ($1, $2, 'purchase', $3, $4)""",
            player_id, -pack["cost"], f"Spark likes pack ({pack['likes']} likes)", now)
        await db.execute(
            "UPDATE spark_profiles SET daily_likes_remaining = daily_likes_remaining + $1 WHERE player_id = $2",
            pack["likes"], player_id)
    else:
        await db.execute(
            """UPDATE wallets SET balance = balance - ?,
               total_spent = total_spent + ?, last_updated = ?
               WHERE player_id = ?""",
            (pack["cost"], pack["cost"], now, player_id))
        await db.execute(
            "UPDATE spark_profiles SET daily_likes_remaining = daily_likes_remaining + ? WHERE player_id = ?",
            (pack["likes"], player_id))
        await db.commit()

    return {"status": "purchased", "likes_added": pack["likes"], "cost": pack["cost"]}


# ── POST /spark/buy-superlikes ────────────────────────────────────────────────

@router.post("/buy-superlikes")
async def buy_superlikes(body: BuyBody, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    cost      = SUPERLIKE_PACK["cost"]
    count     = SUPERLIKE_PACK["superlikes"]

    if is_postgres():
        wallet = await db.fetchrow("SELECT balance FROM wallets WHERE player_id = $1", player_id)
    else:
        async with db.execute("SELECT balance FROM wallets WHERE player_id = ?", (player_id,)) as cur:
            wallet = await cur.fetchone()

    if not wallet or float(wallet["balance"]) < cost:
        raise HTTPException(status_code=400, detail=f"Insufficient Lumens. Need ✦{cost}.")

    now = datetime.now(timezone.utc).isoformat()
    if is_postgres():
        await db.execute(
            """UPDATE wallets SET balance = balance - $1,
               total_spent = total_spent + $2, last_updated = $3 WHERE player_id = $4""",
            cost, cost, now, player_id)
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES ($1, $2, 'purchase', $3, $4)""",
            player_id, -cost, f"Spark superlikes pack ({count} superlikes)", now)
        await db.execute(
            "UPDATE spark_profiles SET daily_superlikes_remaining = daily_superlikes_remaining + $1 WHERE player_id = $2",
            count, player_id)
    else:
        await db.execute(
            """UPDATE wallets SET balance = balance - ?,
               total_spent = total_spent + ?, last_updated = ? WHERE player_id = ?""",
            (cost, cost, now, player_id))
        await db.execute(
            "UPDATE spark_profiles SET daily_superlikes_remaining = daily_superlikes_remaining + ? WHERE player_id = ?",
            (count, player_id))
        await db.commit()

    return {"status": "purchased", "superlikes_added": count, "cost": cost}


# ── GET /spark/matches ────────────────────────────────────────────────────────

@router.get("/matches")
async def list_matches(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        rows = await db.fetch(
            """SELECT sm.*, p.display_name, pp.profile_pic_uuid, pp.age_group
               FROM spark_matches sm
               JOIN players p ON p.id = CASE WHEN sm.player_a_id = $1 THEN sm.player_b_id ELSE sm.player_a_id END
               LEFT JOIN player_profiles pp ON pp.player_id = p.id
               WHERE (sm.player_a_id = $1 OR sm.player_b_id = $1)
               AND sm.status = 'active'
               ORDER BY sm.matched_at DESC""", player_id)
    else:
        async with db.execute(
            """SELECT sm.*, p.display_name, pp.profile_pic_uuid, pp.age_group
               FROM spark_matches sm
               JOIN players p ON p.id = CASE WHEN sm.player_a_id = ? THEN sm.player_b_id ELSE sm.player_a_id END
               LEFT JOIN player_profiles pp ON pp.player_id = p.id
               WHERE (sm.player_a_id = ? OR sm.player_b_id = ?)
               AND sm.status = 'active'
               ORDER BY sm.matched_at DESC""",
            (player_id, player_id, player_id)
        ) as cur:
            rows = await cur.fetchall()

    matches = []
    for r in rows:
        d = dict(r)
        d["other_player_id"] = d["player_b_id"] if d["player_a_id"] == player_id else d["player_a_id"]
        matches.append(d)

    return {"matches": matches}


# ── POST /spark/matches/{id}/cancel ──────────────────────────────────────────

@router.post("/matches/{match_id}/cancel")
async def cancel_match(match_id: int, body: CancelMatch, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    now       = datetime.now(timezone.utc).isoformat()

    if is_postgres():
        match = await db.fetchrow(
            """SELECT * FROM spark_matches WHERE id = $1
               AND (player_a_id = $2 OR player_b_id = $2) AND status = 'active'""",
            match_id, player_id)
    else:
        async with db.execute(
            """SELECT * FROM spark_matches WHERE id = ?
               AND (player_a_id = ? OR player_b_id = ?) AND status = 'active'""",
            (match_id, player_id, player_id)
        ) as cur:
            match = await cur.fetchone()

    if not match:
        raise HTTPException(status_code=404, detail="Match not found.")

    if is_postgres():
        await db.execute(
            """UPDATE spark_matches SET status = 'cancelled',
               cancelled_by = $1, cancelled_at = $2 WHERE id = $3""",
            player_id, now, match_id)
    else:
        await db.execute(
            """UPDATE spark_matches SET status = 'cancelled',
               cancelled_by = ?, cancelled_at = ? WHERE id = ?""",
            (player_id, now, match_id))
        await db.commit()

    # Hide both players from each other's queue by adding pass entries if not already there
    other_id = match["player_b_id"] if match["player_a_id"] == player_id else match["player_a_id"]
    for swiper, target in [(player_id, other_id), (other_id, player_id)]:
        if is_postgres():
            await db.execute(
                """INSERT INTO spark_interests (player_id, target_id, action)
                   VALUES ($1, $2, 'pass') ON CONFLICT (player_id, target_id) DO UPDATE SET action = 'pass'""",
                swiper, target)
        else:
            await db.execute(
                "INSERT OR REPLACE INTO spark_interests (player_id, target_id, action) VALUES (?, ?, 'pass')",
                (swiper, target))
    if not is_postgres():
        await db.commit()

    return {"status": "cancelled"}


# ── POST /spark/report ────────────────────────────────────────────────────────

@router.post("/report")
async def report_profile(body: ReportBody, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    if body.reason not in REPORT_REASONS:
        raise HTTPException(status_code=400, detail="Invalid reason.")

    player_id = player["id"]

    if is_postgres():
        await db.execute(
            """INSERT INTO spark_reports (reporter_id, reported_id, reason, notes)
               VALUES ($1, $2, $3, $4)""",
            player_id, body.reported_id, body.reason, body.notes)
    else:
        await db.execute(
            """INSERT INTO spark_reports (reporter_id, reported_id, reason, notes)
               VALUES (?, ?, ?, ?)""",
            (player_id, body.reported_id, body.reason, body.notes))
        await db.commit()

    return {"status": "reported"}


# ── Spark Messages ────────────────────────────────────────────────────────────

class SendMessage(BaseModel):
    token: str
    body: str


@router.get("/matches/{match_id}/messages")
async def get_match_messages(match_id: int, token: str, db=Depends(get_db)):
    """Fetch messages for a match thread. Only accessible by the two matched players."""
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    # Verify player is part of this match
    if is_postgres():
        match = await db.fetchrow(
            """SELECT * FROM spark_matches WHERE id = $1
               AND (player_a_id = $2 OR player_b_id = $2)""",
            match_id, player_id)
    else:
        async with db.execute(
            """SELECT * FROM spark_matches WHERE id = ?
               AND (player_a_id = ? OR player_b_id = ?)""",
            (match_id, player_id, player_id)
        ) as cur:
            match = await cur.fetchone()

    if not match:
        raise HTTPException(status_code=404, detail="Match not found.")

    other_id = match["player_b_id"] if match["player_a_id"] == player_id else match["player_a_id"]

    # Get other player's display name
    if is_postgres():
        other = await db.fetchrow(
            "SELECT display_name FROM players WHERE id = $1", other_id)
        messages = await db.fetch(
            """SELECT * FROM spark_messages WHERE match_id = $1
               ORDER BY sent_at ASC LIMIT 200""", match_id)
        # Mark unread messages as read
        await db.execute(
            """UPDATE spark_messages SET is_read = 1
               WHERE match_id = $1 AND sender_id != $2 AND is_read = 0""",
            match_id, player_id)
    else:
        async with db.execute(
            "SELECT display_name FROM players WHERE id = ?", (other_id,)
        ) as cur:
            other = await cur.fetchone()
        async with db.execute(
            """SELECT * FROM spark_messages WHERE match_id = ?
               ORDER BY sent_at ASC LIMIT 200""", (match_id,)
        ) as cur:
            messages = await cur.fetchall()
        await db.execute(
            """UPDATE spark_messages SET is_read = 1
               WHERE match_id = ? AND sender_id != ? AND is_read = 0""",
            (match_id, player_id))
        await db.commit()

    return {
        "match_id":      match_id,
        "match_status":  match["status"],
        "other_name":    other["display_name"] if other else "Unknown",
        "other_id":      other_id,
        "player_id":     player_id,
        "messages":      [dict(m) for m in messages],
    }


@router.post("/matches/{match_id}/messages")
async def send_match_message(match_id: int, body: SendMessage, db=Depends(get_db)):
    """Send a message in a Spark match thread."""
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    text      = body.body.strip()[:1000]

    if not text:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Verify player is part of this active match
    if is_postgres():
        match = await db.fetchrow(
            """SELECT * FROM spark_matches WHERE id = $1
               AND (player_a_id = $2 OR player_b_id = $2)
               AND status = 'active'""",
            match_id, player_id)
    else:
        async with db.execute(
            """SELECT * FROM spark_matches WHERE id = ?
               AND (player_a_id = ? OR player_b_id = ?)
               AND status = 'active'""",
            (match_id, player_id, player_id)
        ) as cur:
            match = await cur.fetchone()

    if not match:
        raise HTTPException(status_code=404, detail="Active match not found.")

    other_id = match["player_b_id"] if match["player_a_id"] == player_id else match["player_a_id"]
    now      = datetime.now(timezone.utc).isoformat()

    if is_postgres():
        msg_id = await db.fetchval(
            """INSERT INTO spark_messages (match_id, sender_id, body, sent_at)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            match_id, player_id, text, now)
    else:
        async with db.execute(
            """INSERT INTO spark_messages (match_id, sender_id, body, sent_at)
               VALUES (?, ?, ?, ?)""",
            (match_id, player_id, text, now)
        ) as cur:
            msg_id = cur.lastrowid
        await db.commit()

    # Notify the other player
    await push_notification(
        player_id=other_id, app_source="spark",
        title=f"{player['display_name']} sent you a message ⚡",
        body=text[:80] + ("…" if len(text) > 80 else ""),
        priority="normal", db=db)

    return {
        "status":   "sent",
        "message":  {"id": msg_id, "match_id": match_id, "sender_id": player_id,
                     "body": text, "sent_at": now, "is_read": 0}
    }
