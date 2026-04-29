"""
Unexpected events service — daily per-player roll.

Each active player has a 4% chance per day of experiencing an unexpected event.
Events are weighted: windfall, good_news, found_item (positive)
vs robbery, minor_illness, bad_day (negative).

Runs: daily midnight SLT
"""

import random
from app.config import get_config
from app.database import is_postgres
from app.services.notifications import push_notification


async def run_unexpected_event_engine(db=None):
    if db is None:
        return

    cfg       = get_config()
    ue_cfg    = cfg.get("unexpected_events", {})
    roll_chance = ue_cfg.get("daily_roll_chance", 0.04)
    events_cfg  = ue_cfg.get("events", {})

    if not events_cfg:
        return

    # Build weighted pool
    pool = []
    for key, ev in events_cfg.items():
        weight = ev.get("weight", 10)
        pool.extend([key] * weight)

    if not pool:
        return

    # Get all active (online in last 7 days), non-banned players
    if is_postgres():
        players = await db.fetch(
            """SELECT id FROM players
               WHERE is_banned = 0
                 AND last_seen >= (now() - interval '7 days')::text""")
    else:
        async with db.execute(
            """SELECT id FROM players
               WHERE is_banned = 0
                 AND last_seen >= datetime('now', '-7 days')"""
        ) as cur:
            players = await cur.fetchall()

    for p in players:
        if random.random() > roll_chance:
            continue

        player_id  = p["id"]
        event_key  = random.choice(pool)
        event_cfg  = events_cfg.get(event_key, {})

        display     = event_cfg.get("display", "Something happened")
        description = event_cfg.get("description", "")
        priority    = event_cfg.get("notification_priority", "normal")

        # Apply lumen effects
        lumen_gain = event_cfg.get("lumen_gain", 0)
        lumen_loss_pct = event_cfg.get("lumen_loss_pct", 0)

        if lumen_gain > 0:
            await _apply_lumen_gain(player_id, lumen_gain, display, db)

        if lumen_loss_pct > 0:
            await _apply_lumen_loss(player_id, lumen_loss_pct, display, db)

        # Apply need effects
        need_bonus   = event_cfg.get("need_bonus", {})
        need_penalty = event_cfg.get("need_penalty", {})

        for need_key, delta in need_bonus.items():
            await _apply_need_delta(player_id, need_key, delta, db)

        for need_key, delta in need_penalty.items():
            await _apply_need_delta(player_id, need_key, delta, db)

        # Apply vibe
        vibe_key = event_cfg.get("vibe_key")
        if vibe_key:
            await _upsert_vibe(player_id, vibe_key, db)

        # Log the occurrence
        if is_postgres():
            await db.execute(
                """INSERT INTO player_occurrences
                   (player_id, occurrence_key, is_unexpected)
                   VALUES ($1, $2, 1)""",
                player_id, event_key)
        else:
            await db.execute(
                """INSERT INTO player_occurrences
                   (player_id, occurrence_key, is_unexpected)
                   VALUES (?, ?, 1)""",
                (player_id, event_key))

        # Push notification
        await push_notification(
            player_id=player_id,
            app_source="canvas",
            title=f"Unexpected event 🌊 — {display}",
            body=description,
            priority=priority,
            db=db,
        )

    if not is_postgres():
        await db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _apply_lumen_gain(player_id: int, amount: float, description: str, db):
    if is_postgres():
        await db.execute(
            """UPDATE wallets
               SET balance = balance + $1,
                   total_earned = total_earned + $1,
                   last_updated = now()::text
               WHERE player_id = $2""",
            amount, player_id)
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description)
               VALUES ($1, $2, 'unexpected_event', $3)""",
            player_id, amount, description)
    else:
        await db.execute(
            """UPDATE wallets
               SET balance = balance + ?,
                   total_earned = total_earned + ?,
                   last_updated = datetime('now')
               WHERE player_id = ?""",
            (amount, amount, player_id))
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description)
               VALUES (?, ?, 'unexpected_event', ?)""",
            (player_id, amount, description))


async def _apply_lumen_loss(player_id: int, loss_pct: float, description: str, db):
    if is_postgres():
        wallet = await db.fetchrow(
            "SELECT balance FROM wallets WHERE player_id = $1", player_id)
        if not wallet:
            return
        loss = max(1.0, float(wallet["balance"]) * loss_pct)
        loss = min(loss, float(wallet["balance"]))  # can't go below 0
        await db.execute(
            """UPDATE wallets
               SET balance = balance - $1,
                   total_spent = total_spent + $1,
                   last_updated = now()::text
               WHERE player_id = $2""",
            loss, player_id)
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description)
               VALUES ($1, $2, 'unexpected_event', $3)""",
            player_id, -loss, description)
    else:
        async with db.execute(
            "SELECT balance FROM wallets WHERE player_id = ?", (player_id,)
        ) as cur:
            wallet = await cur.fetchone()
        if not wallet:
            return
        loss = max(1.0, float(wallet["balance"]) * loss_pct)
        loss = min(loss, float(wallet["balance"]))
        await db.execute(
            """UPDATE wallets
               SET balance = balance - ?,
                   total_spent = total_spent + ?,
                   last_updated = datetime('now')
               WHERE player_id = ?""",
            (loss, loss, player_id))
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description)
               VALUES (?, ?, 'unexpected_event', ?)""",
            (player_id, -loss, description))


async def _apply_need_delta(player_id: int, need_key: str, delta: float, db):
    if is_postgres():
        await db.execute(
            """UPDATE needs
               SET value = MAX(0, MIN(100, value + $1)),
                   last_updated = now()::text
               WHERE player_id = $2 AND need_key = $3""",
            delta, player_id, need_key)
    else:
        await db.execute(
            """UPDATE needs
               SET value = MAX(0, MIN(100, value + ?)),
                   last_updated = datetime('now')
               WHERE player_id = ? AND need_key = ?""",
            (delta, player_id, need_key))


async def _upsert_vibe(player_id: int, vibe_key: str, db):
    is_neg = 1 if any(w in vibe_key for w in ("shaken", "under_weather", "off_day")) else 0
    if is_postgres():
        await db.execute(
            """INSERT INTO vibes (player_id, vibe_key, is_negative)
               VALUES ($1, $2, $3)
               ON CONFLICT (player_id, vibe_key) DO NOTHING""",
            player_id, vibe_key, is_neg)
    else:
        await db.execute(
            """INSERT OR IGNORE INTO vibes (player_id, vibe_key, is_negative)
               VALUES (?, ?, ?)""",
            (player_id, vibe_key, is_neg))
