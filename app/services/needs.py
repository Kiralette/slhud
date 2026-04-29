"""
Needs service — all the logic for reading, updating, and calculating needs.
Compatible with both SQLite and PostgreSQL.
"""

from datetime import datetime
from app.config import get_config
from app.services.achievements import increment_stat
from app.database import is_postgres


def get_zone(value: float, need_cfg: dict) -> str:
    if value <= 0:
        return "zero"
    elif value < need_cfg["crit_threshold"]:
        return "critical"
    elif value < need_cfg["warn_threshold"]:
        return "struggling"
    elif value < 75:
        return "okay"
    else:
        return "thriving"


def clamp(value: float, min_val=0.0, max_val=100.0) -> float:
    return max(min_val, min(max_val, value))


async def get_all_needs(player_id: int, db) -> list[dict]:
    if is_postgres():
        rows = await db.fetch("SELECT * FROM needs WHERE player_id = $1 ORDER BY need_key", player_id)
    else:
        async with db.execute("SELECT * FROM needs WHERE player_id = ? ORDER BY need_key", (player_id,)) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_need_value(player_id: int, need_key: str, db) -> float:
    if is_postgres():
        row = await db.fetchrow("SELECT value FROM needs WHERE player_id = $1 AND need_key = $2", player_id, need_key)
    else:
        async with db.execute("SELECT value FROM needs WHERE player_id = ? AND need_key = ?", (player_id, need_key)) as cursor:
            row = await cursor.fetchone()
    return float(row["value"]) if row else 100.0


async def update_need(player_id: int, need_key: str, delta: float, db, action_text: str = "") -> float:
    current = await get_need_value(player_id, need_key, db)
    new_value = clamp(current + delta)

    if is_postgres():
        await db.execute(
            "UPDATE needs SET value = $1, last_updated = now()::text WHERE player_id = $2 AND need_key = $3",
            new_value, player_id, need_key
        )
        if action_text:
            await db.execute(
                "INSERT INTO event_log (player_id, need_key, action_text, delta, value_after) VALUES ($1, $2, $3, $4, $5)",
                player_id, need_key, action_text, delta, new_value
            )
    else:
        await db.execute(
            "UPDATE needs SET value = ?, last_updated = datetime('now') WHERE player_id = ? AND need_key = ?",
            (new_value, player_id, need_key)
        )
        if action_text:
            await db.execute(
                "INSERT INTO event_log (player_id, need_key, action_text, delta, value_after) VALUES (?, ?, ?, ?, ?)",
                (player_id, need_key, action_text, delta, new_value)
            )
    return new_value


async def apply_vibe(player_id: int, vibe_key: str, db):
    cfg = get_config()
    vibe_cfg = cfg.get("vibes", {}).get(vibe_key, {})
    duration = vibe_cfg.get("duration_minutes", 0)
    is_negative = 1 if vibe_cfg.get("is_negative", False) else 0

    if is_postgres():
        if duration > 0:
            await db.execute(
                """INSERT INTO vibes (player_id, vibe_key, is_negative, expires_at)
                   VALUES ($1, $2, $3, (now() + ($4 || ' minutes')::interval)::text)
                   ON CONFLICT (player_id, vibe_key) DO UPDATE SET
                   applied_at = now()::text,
                   expires_at = (now() + ($4 || ' minutes')::interval)::text""",
                player_id, vibe_key, is_negative, str(duration)
            )
        else:
            await db.execute(
                """INSERT INTO vibes (player_id, vibe_key, is_negative, expires_at)
                   VALUES ($1, $2, $3, NULL)
                   ON CONFLICT (player_id, vibe_key) DO UPDATE SET applied_at = now()::text, expires_at = NULL""",
                player_id, vibe_key, is_negative
            )
    else:
        if duration > 0:
            expires_sql = f"datetime('now', '+{duration} minutes')"
        else:
            expires_sql = "NULL"
        await db.execute(
            f"""INSERT INTO vibes (player_id, vibe_key, is_negative, expires_at)
                VALUES (?, ?, ?, {expires_sql})
                ON CONFLICT(player_id, vibe_key) DO UPDATE SET
                applied_at = datetime('now'), expires_at = {expires_sql}""",
            (player_id, vibe_key, is_negative)
        )


async def get_active_multipliers(player_id: int, db) -> dict:
    cfg = get_config()
    vibe_cfgs = cfg.get("vibes", {})

    if is_postgres():
        rows = await db.fetch(
            "SELECT vibe_key FROM vibes WHERE player_id = $1 AND (expires_at IS NULL OR expires_at > now()::text)",
            player_id
        )
    else:
        async with db.execute(
            "SELECT vibe_key FROM vibes WHERE player_id = ? AND (expires_at IS NULL OR expires_at > datetime('now'))",
            (player_id,)
        ) as cursor:
            rows = await cursor.fetchall()

    combined = {}
    for row in rows:
        key = row["vibe_key"]
        if key not in vibe_cfgs:
            continue
        mods = vibe_cfgs[key].get("modifiers", {})
        for mod_key, mod_val in mods.items():
            if mod_key in combined and isinstance(mod_val, float):
                combined[mod_key] *= mod_val
            else:
                combined[mod_key] = mod_val
    return combined


async def award_skill_xp(player_id: int, skill_key: str, xp_amount: float, db):
    cfg = get_config()
    skill_cfg = cfg.get("skills", {}).get(skill_key)
    if not skill_cfg:
        return

    xp_per_level = skill_cfg["xp_per_level"]
    max_level = skill_cfg["max_level"]

    if is_postgres():
        row = await db.fetchrow("SELECT level, xp FROM skills WHERE player_id = $1 AND skill_key = $2", player_id, skill_key)
    else:
        async with db.execute("SELECT level, xp FROM skills WHERE player_id = ? AND skill_key = ?", (player_id, skill_key)) as cursor:
            row = await cursor.fetchone()

    if not row:
        return

    current_level = row["level"]
    current_xp = row["xp"] + xp_amount
    start_level = current_level

    if current_level == 0:
        current_level = 1

    while current_level < max_level:
        xp_needed = xp_per_level[current_level - 1]
        if current_xp >= xp_needed:
            current_xp -= xp_needed
            current_level += 1
            purpose_bonus = cfg["needs"]["purpose"].get("skill_levelup_bonus", 5)
            await update_need(player_id, "purpose", purpose_bonus, db,
                f"{skill_cfg['display_name']} reached level {current_level}! +{purpose_bonus} Purpose")
        else:
            break

    # Track levelups for achievements
    if current_level > start_level:
        await increment_stat(player_id, "total_skill_levelups", current_level - start_level)

    if is_postgres():
        await db.execute("UPDATE skills SET level = $1, xp = $2 WHERE player_id = $3 AND skill_key = $4",
            current_level, current_xp, player_id, skill_key)
    else:
        await db.execute("UPDATE skills SET level = ?, xp = ? WHERE player_id = ? AND skill_key = ?",
            (current_level, current_xp, player_id, skill_key))


async def process_action(player_id: int, object_key: str, duration_seconds: int, quality_tier: int, db) -> dict:
    cfg = get_config()
    objects = cfg.get("objects", {})

    if object_key not in objects:
        return {"changes": [], "log_entries": [], "message": f"Unknown object: {object_key}", "vibes_applied": []}

    obj = objects[object_key]
    obj_name = obj.get("display_name", object_key)
    duration_minutes = duration_seconds / 60
    multipliers = await get_active_multipliers(player_id, db)
    skill_xp_mult = multipliers.get("skill_xp_mult", 1.0)

    changes, log_entries, messages, vibes_applied = [], [], [], []

    for need_key, gain_cfg in obj.get("needs_affected", {}).items():
        if need_key not in cfg["needs"]:
            continue
        base_gain = gain_cfg.get("base_gain", 0)
        gain_per_minute = gain_cfg.get("gain_per_minute", 0)
        quality_bonus = gain_cfg.get("quality_bonus", 0)
        total_gain = round(base_gain + (gain_per_minute * duration_minutes) + (quality_bonus * quality_tier), 1)
        if total_gain == 0:
            continue
        sign = "+" if total_gain > 0 else ""
        action_text = f"Used {obj_name} · {sign}{total_gain} {need_key.capitalize()}"
        new_value = await update_need(player_id, need_key, total_gain, db, action_text)
        changes.append({"need_key": need_key, "delta": total_gain, "new_value": new_value})
        log_entries.append({"action_text": action_text, "delta": total_gain, "need_key": need_key, "timestamp": datetime.utcnow().isoformat()})
        messages.append(f"{sign}{total_gain} {need_key.capitalize()}")

    for skill_key, xp_amount in obj.get("skill_xp", {}).items():
        adjusted_xp = round(xp_amount * skill_xp_mult, 1)
        await award_skill_xp(player_id, skill_key, adjusted_xp, db)
        log_entries.append({"action_text": f"{skill_key.capitalize()} +{adjusted_xp} XP", "delta": adjusted_xp, "need_key": None, "timestamp": datetime.utcnow().isoformat()})

    grant_vibe = obj.get("grants_vibe")
    if grant_vibe:
        if grant_vibe == "well_rested":
            min_energy = obj.get("vibe_min_energy", 90)
            energy_now = await get_need_value(player_id, "energy", db)
            if energy_now >= min_energy:
                await apply_vibe(player_id, grant_vibe, db)
                vibes_applied.append(grant_vibe)
        else:
            await apply_vibe(player_id, grant_vibe, db)
            vibes_applied.append(grant_vibe)

    summary = f"Used {obj_name}" + (f" · {', '.join(messages)}" if messages else "")
    return {"changes": changes, "log_entries": log_entries, "message": summary, "vibes_applied": vibes_applied}
