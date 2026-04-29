"""
Trait scoring service.

Handles:
  score_questionnaire_answers()  — tallies trait points from answer keys
  apply_traits_to_player()       — writes top 3-5 traits to player_traits
  award_negative_bonuses()       — deposits ✦50 per negative trait (cap ✦100)
  get_player_traits()            — returns active trait keys for a player
  build_trait_multipliers()      — returns effective decay/xp multipliers from traits
"""

from datetime import datetime, timezone, time
from app.config import get_config
from app.database import is_postgres


# ── Score questionnaire answers ───────────────────────────────────────────────

def score_answers(answer_keys: list[str]) -> dict[str, float]:
    """
    Given a list of answer keys (e.g. ['q1_social', 'q2_exercise', ...]),
    returns a dict of {trait_key: total_points} sorted by points desc.
    """
    cfg = get_config()
    scoring = cfg.get("questionnaire", {}).get("scoring", {})
    totals: dict[str, float] = {}

    for answer_key in answer_keys:
        pairs = scoring.get(answer_key, [])
        for trait_key, points in pairs:
            totals[trait_key] = totals.get(trait_key, 0) + points

    return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))


def pick_traits(scored: dict[str, float], max_traits: int = 5, min_traits: int = 3) -> list[str]:
    """
    From a scored dict, pick the top N traits.
    - Always picks at least min_traits
    - Never picks more than max_traits
    - Drops traits with <= 0 total points
    """
    eligible = [k for k, v in scored.items() if v > 0]
    n = max(min_traits, min(max_traits, len(eligible)))
    return eligible[:n]


# ── Apply traits to player ────────────────────────────────────────────────────

async def apply_traits_to_player(player_id: int, trait_keys: list[str], db, source: str = "questionnaire"):
    """
    Writes trait_keys to player_traits (upsert).
    Clears all previous questionnaire traits first.
    """
    if is_postgres():
        await db.execute(
            "DELETE FROM player_traits WHERE player_id = $1 AND source = $2",
            player_id, source)
        for key in trait_keys:
            await db.execute(
                """INSERT INTO player_traits (player_id, trait_key, source)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (player_id, trait_key) DO NOTHING""",
                player_id, key, source)
    else:
        await db.execute(
            "DELETE FROM player_traits WHERE player_id = ? AND source = ?",
            (player_id, source))
        for key in trait_keys:
            await db.execute(
                """INSERT OR IGNORE INTO player_traits (player_id, trait_key, source)
                   VALUES (?, ?, ?)""",
                (player_id, key, source))
        await db.commit()


# ── Award negative bonuses ────────────────────────────────────────────────────

async def award_negative_bonuses(player_id: int, trait_keys: list[str], db):
    """
    For each negative trait in trait_keys, award ✦50 (capped at ✦100 total).
    """
    cfg = get_config()
    trait_defs = cfg.get("traits", {}).get("definitions", {})
    bonus_per = cfg.get("traits", {}).get("negative_bonus_lumens", 50)

    negative_count = sum(
        1 for k in trait_keys
        if trait_defs.get(k, {}).get("is_negative", False)
    )
    if negative_count == 0:
        return 0

    total_bonus = min(negative_count * bonus_per, 100)

    if is_postgres():
        await db.execute(
            """UPDATE wallets
               SET balance = balance + $1,
                   total_earned = total_earned + $1,
                   last_updated = now()::text
               WHERE player_id = $2""",
            total_bonus, player_id)
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description)
               VALUES ($1, $2, 'negative_trait_bonus', 'Starting bonus for personality traits')""",
            player_id, total_bonus)
    else:
        await db.execute(
            """UPDATE wallets
               SET balance = balance + ?,
                   total_earned = total_earned + ?,
                   last_updated = datetime('now')
               WHERE player_id = ?""",
            (total_bonus, total_bonus, player_id))
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description)
               VALUES (?, ?, 'negative_trait_bonus', 'Starting bonus for personality traits')""",
            (player_id, total_bonus))
        await db.commit()

    return total_bonus


# ── Get player traits ─────────────────────────────────────────────────────────

async def get_player_traits(player_id: int, db) -> list[str]:
    """Returns list of active trait_key strings for a player."""
    if is_postgres():
        rows = await db.fetch(
            "SELECT trait_key FROM player_traits WHERE player_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT trait_key FROM player_traits WHERE player_id = ?", (player_id,)
        ) as cur:
            rows = await cur.fetchall()
    return [r["trait_key"] for r in rows]


# ── Build trait multipliers ───────────────────────────────────────────────────

def build_trait_multipliers(trait_keys: list[str], current_hour_slt: int = None) -> dict:
    """
    Returns a dict of effective multipliers based on active traits.

    Returns:
      {
        "decay_mults":  { need_key: mult, ... },  # <1 = slower decay, >1 = faster
        "xp_mults":     { skill_key: mult, ... },  # <1 = less XP, >1 = more
      }

    Multipliers from multiple traits are composed (multiplied together).
    Hour-window traits only apply if current_hour_slt is within their window.
    """
    if current_hour_slt is None:
        now = datetime.now(timezone.utc)
        current_hour_slt = now.hour  # approximate SLT (UTC-7 offset not applied here for simplicity)

    cfg = get_config()
    trait_defs = cfg.get("traits", {}).get("definitions", {})

    decay_mults: dict[str, float] = {}
    xp_mults:   dict[str, float] = {}

    for key in trait_keys:
        tdef = trait_defs.get(key, {})

        # ── Standard decay mults ──
        for need_key, mult in tdef.get("decay_mults", {}).items():
            if need_key == "all":
                for nk in ["hunger", "thirst", "energy", "fun", "social", "hygiene", "purpose"]:
                    decay_mults[nk] = decay_mults.get(nk, 1.0) * mult
            else:
                decay_mults[need_key] = decay_mults.get(need_key, 1.0) * mult

        # ── Standard XP mults ──
        for skill_key, mult in tdef.get("xp_mult", {}).items():
            if skill_key == "all":
                for sk in ["cooking", "creativity", "charisma", "fitness", "gaming", "music", "knowledge"]:
                    xp_mults[sk] = xp_mults.get(sk, 1.0) * mult
            else:
                xp_mults[skill_key] = xp_mults.get(skill_key, 1.0) * mult

        # ── Hour-window traits (night_owl, morning_person) ──
        hw = tdef.get("hour_window")
        if hw:
            active_start = hw.get("active_start", 0)
            active_end   = hw.get("active_end", 24)
            in_window    = _in_hour_window(current_hour_slt, active_start, active_end)

            if in_window:
                for need_key, mult in tdef.get("decay_mults_in_window", {}).get("all", {}).items():
                    pass  # handled below

                window_decay = tdef.get("decay_mults_in_window", {})
                for need_key, mult in window_decay.items():
                    if need_key == "all":
                        for nk in ["hunger", "thirst", "energy", "fun", "social", "hygiene", "purpose"]:
                            decay_mults[nk] = decay_mults.get(nk, 1.0) * mult
                    else:
                        decay_mults[need_key] = decay_mults.get(need_key, 1.0) * mult

                window_xp = tdef.get("xp_mult_in_window", {})
                for skill_key, mult in window_xp.items():
                    if skill_key == "all":
                        for sk in ["cooking", "creativity", "charisma", "fitness", "gaming", "music", "knowledge"]:
                            xp_mults[sk] = xp_mults.get(sk, 1.0) * mult
                    else:
                        xp_mults[skill_key] = xp_mults.get(skill_key, 1.0) * mult

        # ── Homebody zone decay (applied when zone is 'home') ──
        # Zone info isn't available in the decay tick directly, so homebody
        # zone effects are flagged here and decay engine checks zone separately.

    return {"decay_mults": decay_mults, "xp_mults": xp_mults}


def _in_hour_window(current_hour: int, start: int, end: int) -> bool:
    """Handle windows that wrap midnight (e.g. 20–4)."""
    if start <= end:
        return start <= current_hour < end
    else:
        # Wraps midnight
        return current_hour >= start or current_hour < end


# ── Trait vibe engine ─────────────────────────────────────────────────────────

async def run_trait_vibe_engine(db=None):
    """
    Daily job: checks each player's traits against their current state
    and fires appropriate vibes.
    """
    if db is None:
        return

    import random
    cfg = get_config()
    trait_defs = cfg.get("traits", {}).get("definitions", {})

    if is_postgres():
        players = await db.fetch(
            "SELECT id FROM players WHERE is_banned = 0")
    else:
        async with db.execute(
            "SELECT id FROM players WHERE is_banned = 0"
        ) as cur:
            players = await cur.fetchall()

    now = datetime.now(timezone.utc)
    current_hour = now.hour

    for p in players:
        player_id = p["id"]
        trait_keys = await get_player_traits(player_id, db)
        if not trait_keys:
            continue

        # Get current needs
        if is_postgres():
            need_rows = await db.fetch(
                "SELECT need_key, value FROM needs WHERE player_id = $1", player_id)
        else:
            async with db.execute(
                "SELECT need_key, value FROM needs WHERE player_id = ?", (player_id,)
            ) as cur:
                need_rows = await cur.fetchall()

        needs = {r["need_key"]: float(r["value"]) for r in need_rows}

        # Check proximity (for extrovert/introvert triggers)
        if is_postgres():
            nearby = await db.fetchval(
                """SELECT COUNT(*) FROM proximity_log
                   WHERE player_id = $1
                   AND last_seen_at >= (now() - interval '90 seconds')::text""",
                player_id) or 0
            no_proximity_24h = not await db.fetchval(
                """SELECT 1 FROM proximity_log
                   WHERE player_id = $1
                   AND last_seen_at >= (now() - interval '24 hours')::text""",
                player_id)
        else:
            async with db.execute(
                """SELECT COUNT(*) as cnt FROM proximity_log
                   WHERE player_id = ?
                   AND last_seen_at >= datetime('now', '-90 seconds')""",
                (player_id,)
            ) as cur:
                row = await cur.fetchone()
            nearby = row["cnt"] if row else 0
            async with db.execute(
                """SELECT 1 FROM proximity_log
                   WHERE player_id = ?
                   AND last_seen_at >= datetime('now', '-24 hours') LIMIT 1""",
                (player_id,)
            ) as cur:
                no_prox_row = await cur.fetchone()
            no_proximity_24h = not no_prox_row

        # Check worked today
        if is_postgres():
            worked_today = bool(await db.fetchval(
                """SELECT 1 FROM career_history
                   WHERE player_id = $1
                   AND started_at >= (now() - interval '24 hours')::text LIMIT 1""",
                player_id))
        else:
            async with db.execute(
                """SELECT 1 FROM career_history
                   WHERE player_id = ?
                   AND started_at >= datetime('now', '-24 hours') LIMIT 1""",
                (player_id,)
            ) as cur:
                worked_today = bool(await cur.fetchone())

        # Check relationship occurrence
        if is_postgres():
            has_relationship = bool(await db.fetchval(
                """SELECT 1 FROM player_occurrences
                   WHERE player_id = $1 AND occurrence_key = 'new_relationship'
                   AND is_resolved = 0 LIMIT 1""",
                player_id))
        else:
            async with db.execute(
                """SELECT 1 FROM player_occurrences
                   WHERE player_id = ? AND occurrence_key = 'new_relationship'
                   AND is_resolved = 0 LIMIT 1""",
                (player_id,)
            ) as cur:
                has_relationship = bool(await cur.fetchone())

        # Evaluate each trait's vibe triggers
        for trait_key in trait_keys:
            tdef = trait_defs.get(trait_key, {})
            hw   = tdef.get("hour_window")

            for trigger in tdef.get("vibe_triggers", []):
                condition = trigger.get("condition")
                vibe_key  = trigger.get("vibe_key")
                is_neg    = int(trigger.get("is_negative", False))

                should_fire = _evaluate_condition(
                    condition, needs, nearby, no_proximity_24h,
                    worked_today, has_relationship, hw, current_hour, random
                )

                if should_fire:
                    await _upsert_vibe(player_id, vibe_key, is_neg, db)

    if not is_postgres():
        await db.commit()


def _evaluate_condition(condition, needs, nearby, no_proximity_24h,
                         worked_today, has_relationship, hw, current_hour, random_module):
    """Evaluate a trait trigger condition string."""
    if not condition:
        return False

    c = condition

    if c == "social_above_70":         return needs.get("social", 0) > 70
    if c == "social_below_30":         return needs.get("social", 0) < 30
    if c == "social_below_25":         return needs.get("social", 0) < 25
    if c == "social_above_80":         return needs.get("social", 0) > 80
    if c == "fun_above_75":            return needs.get("fun", 0) > 75
    if c == "fun_below_40":            return needs.get("fun", 0) < 40
    if c == "purpose_above_70":        return needs.get("purpose", 0) > 70
    if c == "purpose_below_30":        return needs.get("purpose", 0) < 30
    if c == "purpose_below_40":        return needs.get("purpose", 0) < 40
    if c == "purpose_below_50":        return needs.get("purpose", 0) < 50
    if c == "nearby_players_above_0":  return nearby > 0
    if c == "nearby_players_above_2":  return nearby > 2
    if c == "no_proximity_24h":        return no_proximity_24h
    if c == "worked_today":            return worked_today
    if c == "no_work_3_days":          return not worked_today  # simplified
    if c == "has_relationship_occurrence": return has_relationship
    if c == "in_home_zone":            return False  # zone info not in this tick
    if c == "not_home_4h":             return False  # zone info not in this tick
    if c == "all_needs_above_60":      return all(v > 60 for v in needs.values())
    if c == "random_daily_20pct":      return random_module.random() < 0.20
    if c == "random_daily_15pct":      return random_module.random() < 0.15
    if c == "knowledge_xp_today_above_50": return False  # requires XP log query — skip for now
    if c == "fitness_xp_today_above_30":   return False  # same
    if c == "in_hour_window" and hw:
        return _in_hour_window(current_hour, hw.get("active_start", 0), hw.get("active_end", 24))

    return False


async def _upsert_vibe(player_id: int, vibe_key: str, is_negative: int, db):
    if is_postgres():
        await db.execute(
            """INSERT INTO vibes (player_id, vibe_key, is_negative)
               VALUES ($1, $2, $3)
               ON CONFLICT (player_id, vibe_key) DO NOTHING""",
            player_id, vibe_key, is_negative)
    else:
        await db.execute(
            """INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative)
               VALUES (?, ?, ?)""",
            (player_id, vibe_key, is_negative))
