"""
Needs service — all the logic for reading, updating, and calculating needs.
This is the brain of the action system.
"""

from datetime import datetime
from app.config import get_config
import aiosqlite


def get_zone(value: float, need_cfg: dict) -> str:
    """
    Returns the named zone for a need value.
    Zones match what the phone HUD displays as the mood/status label.
    """
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
    """Keeps a value between 0 and 100. Simple but used everywhere."""
    return max(min_val, min(max_val, value))


async def get_all_needs(player_id: int, db: aiosqlite.Connection) -> list[dict]:
    """Fetch all needs for a player as a list of dicts."""
    async with db.execute(
        "SELECT * FROM needs WHERE player_id = ? ORDER BY need_key",
        (player_id,)
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_need_value(player_id: int, need_key: str, db: aiosqlite.Connection) -> float:
    """Fetch just the current value of one need."""
    async with db.execute(
        "SELECT value FROM needs WHERE player_id = ? AND need_key = ?",
        (player_id, need_key)
    ) as cursor:
        row = await cursor.fetchone()
    return float(row["value"]) if row else 100.0


async def update_need(
    player_id: int,
    need_key: str,
    delta: float,
    db: aiosqlite.Connection,
    action_text: str = ""
) -> float:
    """
    Adds delta to a need's current value, clamps to 0-100,
    saves it, and writes to the event log.
    Returns the new value.
    """
    current = await get_need_value(player_id, need_key, db)
    new_value = clamp(current + delta)

    await db.execute(
        """UPDATE needs
           SET value = ?, last_updated = datetime('now')
           WHERE player_id = ? AND need_key = ?""",
        (new_value, player_id, need_key)
    )

    # Write to event log so the phone app can show history
    if action_text:
        await db.execute(
            """INSERT INTO event_log
               (player_id, need_key, action_text, delta, value_after)
               VALUES (?, ?, ?, ?, ?)""",
            (player_id, need_key, action_text, delta, new_value)
        )

    return new_value


async def process_action(
    player_id: int,
    object_key: str,
    duration_seconds: int,
    quality_tier: int,
    db: aiosqlite.Connection
) -> dict:
    """
    The main action processor. Given a player and an object they used:
    1. Looks up the object in config.yaml
    2. Calculates gain for each affected need
    3. Applies any active moodlet multipliers
    4. Updates the database
    5. Returns a summary of what changed

    Returns a dict with keys: changes, log_entries, message
    """
    cfg = get_config()
    objects = cfg.get("objects", {})

    if object_key not in objects:
        return {
            "changes": [],
            "log_entries": [],
            "message": f"Unknown object: {object_key}"
        }

    obj = objects[object_key]
    obj_name = obj.get("display_name", object_key)
    duration_minutes = duration_seconds / 60

    # Get active moodlet multipliers for this player
    multipliers = await get_active_multipliers(player_id, db)
    skill_xp_mult = multipliers.get("skill_xp_mult", 1.0)

    changes = []
    log_entries = []
    messages = []

    needs_affected = obj.get("needs_affected", {})

    for need_key, gain_cfg in needs_affected.items():
        if need_key not in cfg["needs"]:
            continue

        # Calculate the gain from this object
        base_gain = gain_cfg.get("base_gain", 0)
        gain_per_minute = gain_cfg.get("gain_per_minute", 0)
        quality_bonus = gain_cfg.get("quality_bonus", 0)

        total_gain = (
            base_gain
            + (gain_per_minute * duration_minutes)
            + (quality_bonus * quality_tier)
        )

        # Round to 1 decimal place — keeps values clean
        total_gain = round(total_gain, 1)

        if total_gain == 0:
            continue

        # Build the log text shown in the phone app
        sign = "+" if total_gain > 0 else ""
        action_text = f"Used {obj_name} · {sign}{total_gain} {need_key.capitalize()}"

        new_value = await update_need(
            player_id, need_key, total_gain, db, action_text
        )

        changes.append({
            "need_key": need_key,
            "delta": total_gain,
            "new_value": new_value
        })
        log_entries.append({
            "action_text": action_text,
            "delta": total_gain,
            "need_key": need_key,
            "timestamp": datetime.utcnow().isoformat()
        })
        messages.append(f"{sign}{total_gain} {need_key.capitalize()}")

    # Handle skill XP if the object grants any
    skill_xp = obj.get("skill_xp", {})
    for skill_key, xp_amount in skill_xp.items():
        adjusted_xp = round(xp_amount * skill_xp_mult, 1)
        await award_skill_xp(player_id, skill_key, adjusted_xp, db)
        log_entries.append({
            "action_text": f"{skill_key.capitalize()} +{adjusted_xp} XP",
            "delta": adjusted_xp,
            "need_key": None,
            "timestamp": datetime.utcnow().isoformat()
        })

    # Check if a moodlet should be granted
    moodlets_applied = []
    grant_moodlet = obj.get("grants_moodlet")
    if grant_moodlet:
        # Special case: well_rested only if energy ended above threshold
        if grant_moodlet == "well_rested":
            min_energy = obj.get("moodlet_min_energy", 90)
            energy_now = await get_need_value(player_id, "energy", db)
            if energy_now >= min_energy:
                await apply_moodlet(player_id, grant_moodlet, db)
                moodlets_applied.append(grant_moodlet)
        else:
            await apply_moodlet(player_id, grant_moodlet, db)
            moodlets_applied.append(grant_moodlet)

    summary = f"Used {obj_name}" + (f" · {', '.join(messages)}" if messages else "")

    return {
        "changes": changes,
        "log_entries": log_entries,
        "message": summary,
        "moodlets_applied": moodlets_applied
    }


async def get_active_multipliers(player_id: int, db: aiosqlite.Connection) -> dict:
    """
    Reads all active (non-expired) moodlets for a player and
    combines their modifiers into a single dict.
    Multiple moodlets stack multiplicatively.
    """
    cfg = get_config()
    moodlet_cfgs = cfg.get("moodlets", {})

    async with db.execute(
        """SELECT moodlet_key FROM moodlets
           WHERE player_id = ?
           AND (expires_at IS NULL OR expires_at > datetime('now'))""",
        (player_id,)
    ) as cursor:
        rows = await cursor.fetchall()

    combined = {}
    for row in rows:
        key = row["moodlet_key"]
        if key not in moodlet_cfgs:
            continue
        mods = moodlet_cfgs[key].get("modifiers", {})
        for mod_key, mod_val in mods.items():
            if mod_key in combined:
                # Stack multiplicatively for multipliers
                if isinstance(mod_val, float):
                    combined[mod_key] *= mod_val
                else:
                    combined[mod_key] = mod_val
            else:
                combined[mod_key] = mod_val

    return combined


async def apply_moodlet(player_id: int, moodlet_key: str, db: aiosqlite.Connection):
    """Apply a moodlet to a player, setting its expiry from config."""
    cfg = get_config()
    moodlet_cfg = cfg.get("moodlets", {}).get(moodlet_key, {})
    duration = moodlet_cfg.get("duration_minutes", 0)
    is_negative = 1 if moodlet_cfg.get("is_negative", False) else 0

    if duration > 0:
        expires_sql = f"datetime('now', '+{duration} minutes')"
    else:
        expires_sql = "NULL"

    await db.execute(
        f"""INSERT INTO moodlets (player_id, moodlet_key, is_negative, expires_at)
            VALUES (?, ?, ?, {expires_sql})
            ON CONFLICT(player_id, moodlet_key) DO UPDATE SET
              applied_at = datetime('now'),
              expires_at = {expires_sql}""",
        (player_id, moodlet_key, is_negative)
    )


async def award_skill_xp(
    player_id: int,
    skill_key: str,
    xp_amount: float,
    db: aiosqlite.Connection
):
    """
    Adds XP to a skill and checks if a level-up has occurred.
    Skills are unlocked (set to level 1) on first XP award.
    """
    cfg = get_config()
    skill_cfg = cfg.get("skills", {}).get(skill_key)
    if not skill_cfg:
        return

    xp_per_level = skill_cfg["xp_per_level"]
    max_level = skill_cfg["max_level"]

    async with db.execute(
        "SELECT level, xp FROM skills WHERE player_id = ? AND skill_key = ?",
        (player_id, skill_key)
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        return

    current_level = row["level"]
    current_xp = row["xp"] + xp_amount

    # Unlock skill on first use
    if current_level == 0:
        current_level = 1

    # Check for level-ups
    while current_level < max_level:
        xp_needed = xp_per_level[current_level - 1]
        if current_xp >= xp_needed:
            current_xp -= xp_needed
            current_level += 1
            # Grant Purpose bonus on level-up
            purpose_bonus = cfg["needs"]["purpose"].get("skill_levelup_bonus", 5)
            await update_need(
                player_id, "purpose", purpose_bonus, db,
                f"{skill_cfg['display_name']} reached level {current_level}! +{purpose_bonus} Purpose"
            )
        else:
            break

    await db.execute(
        "UPDATE skills SET level = ?, xp = ? WHERE player_id = ? AND skill_key = ?",
        (current_level, current_xp, player_id, skill_key)
    )
