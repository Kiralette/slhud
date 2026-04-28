"""
Decay engine — runs in the background on a timer, draining needs.
This is what makes the game tick even when nobody is online.

Online players decay at the full rate.
Offline players decay at 1/3 the rate (configurable).
Purpose decays normally but also gains passively if overall wellbeing is high.
"""

import aiosqlite
from datetime import datetime
from app.config import get_config


async def run_decay_tick():
    """
    Called every N seconds by APScheduler.
    Processes one decay tick for every active (non-banned) player.
    """
    cfg = get_config()
    db_path = cfg["database"]["path"]
    needs_cfg = cfg["needs"]
    interval_seconds = cfg["server"]["decay_interval_seconds"]
    interval_minutes = interval_seconds / 60

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")

        # Get all non-banned players
        async with db.execute(
            "SELECT id, is_online, display_name FROM players WHERE is_banned = 0"
        ) as cursor:
            players = await cursor.fetchall()

        for player in players:
            player_id = player["id"]
            is_online = bool(player["is_online"])

            # Get all needs for this player
            async with db.execute(
                "SELECT need_key, value FROM needs WHERE player_id = ?",
                (player_id,)
            ) as cursor:
                needs = await cursor.fetchall()

            needs_dict = {n["need_key"]: float(n["value"]) for n in needs}

            # Apply decay to each need
            for need_key, need_cfg in needs_cfg.items():
                if need_key not in needs_dict:
                    continue

                current_value = needs_dict[need_key]

                # Purpose is handled separately below
                if need_cfg.get("is_composite"):
                    continue

                # Pick decay rate based on online/offline status
                rate = need_cfg["decay_online"] if is_online else need_cfg["decay_offline"]
                delta = -(rate * interval_minutes)

                new_value = max(0.0, current_value + delta)
                needs_dict[need_key] = new_value

                await db.execute(
                    """UPDATE needs
                       SET value = ?, last_updated = datetime('now')
                       WHERE player_id = ? AND need_key = ?""",
                    (round(new_value, 2), player_id, need_key)
                )

            # Handle Purpose separately — it's composite
            await _process_purpose(
                player_id, needs_dict, needs_cfg, interval_minutes, is_online, db
            )

            # Check and apply automatic negative moodlets
            await _check_automatic_moodlets(player_id, needs_dict, needs_cfg, db)

        await db.commit()


async def _process_purpose(
    player_id: int,
    needs_dict: dict,
    needs_cfg: dict,
    interval_minutes: float,
    is_online: bool,
    db: aiosqlite.Connection
):
    """
    Purpose is special — it decays normally but also gains passively
    when the player's overall wellbeing is high.
    """
    purpose_cfg = needs_cfg.get("purpose", {})
    if not purpose_cfg:
        return

    current_purpose = needs_dict.get("purpose", 100.0)

    # Calculate average wellbeing of all non-purpose needs
    other_needs = [v for k, v in needs_dict.items() if k != "purpose"]
    if not other_needs:
        return
    wellbeing_score = sum(other_needs) / len(other_needs)

    # Passive gain if wellbeing is high enough
    passive_gain_threshold = purpose_cfg.get("passive_gain_threshold", 60)
    passive_drain_threshold = purpose_cfg.get("passive_drain_threshold", 40)
    passive_gain_rate = purpose_cfg.get("passive_gain_rate", 0.2)

    rate = purpose_cfg["decay_online"] if is_online else purpose_cfg["decay_offline"]
    delta = -(rate * interval_minutes)

    if wellbeing_score >= passive_gain_threshold:
        # Good wellbeing — add passive gain on top
        delta += passive_gain_rate * interval_minutes
    elif wellbeing_score < passive_drain_threshold:
        # Poor wellbeing — drain faster
        delta *= 1.5

    new_purpose = max(0.0, min(100.0, current_purpose + delta))

    await db.execute(
        """UPDATE needs
           SET value = ?, last_updated = datetime('now')
           WHERE player_id = ? AND need_key = 'purpose'""",
        (round(new_purpose, 2), player_id)
    )


async def _check_automatic_moodlets(
    player_id: int,
    needs_dict: dict,
    needs_cfg: dict,
    db: aiosqlite.Connection
):
    """
    Checks conditions for automatic negative moodlets and applies
    or removes them based on current need values.
    Currently handles: stinky (hygiene < 20) and drained (2+ critical needs).
    """
    cfg = get_config()
    moodlets_cfg = cfg["moodlets"]

    # Stinky — applied when hygiene drops below threshold
    hygiene = needs_dict.get("hygiene", 100.0)
    stinky_threshold = moodlets_cfg.get("stinky", {}).get("trigger_threshold", 20)

    if hygiene < stinky_threshold:
        await db.execute(
            """INSERT INTO moodlets (player_id, moodlet_key, is_negative, expires_at)
               VALUES (?, 'stinky', 1, NULL)
               ON CONFLICT(player_id, moodlet_key) DO NOTHING""",
            (player_id,)
        )
    else:
        # Remove stinky if hygiene recovered
        await db.execute(
            "DELETE FROM moodlets WHERE player_id = ? AND moodlet_key = 'stinky'",
            (player_id,)
        )

    # Drained — applied when 2+ needs are in critical zone
    critical_count = sum(
        1 for need_key, value in needs_dict.items()
        if value < needs_cfg.get(need_key, {}).get("crit_threshold", 20)
    )
    drained_threshold = moodlets_cfg.get("drained", {}).get("trigger_critical_count", 2)

    if critical_count >= drained_threshold:
        await db.execute(
            """INSERT INTO moodlets (player_id, moodlet_key, is_negative, expires_at)
               VALUES (?, 'drained', 1, NULL)
               ON CONFLICT(player_id, moodlet_key) DO NOTHING""",
            (player_id,)
        )
    else:
        await db.execute(
            "DELETE FROM moodlets WHERE player_id = ? AND moodlet_key = 'drained'",
            (player_id,)
        )
