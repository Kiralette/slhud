"""
Background jobs — weekly economy resets.

  rotate_weekly_specials()   — runs Sunday midnight SLT
  bill_subscriptions()       — runs Sunday midnight SLT
"""

import random
from datetime import datetime, timezone, timedelta

from app.config import get_config
from app.database import is_postgres, get_db_url, get_db_path


def _slt_now() -> datetime:
    """Return current time in SLT (UTC-7, no DST handling — SL uses PDT/PST loosely)."""
    return datetime.now(timezone.utc) - timedelta(hours=7)


def _next_sunday_midnight_slt() -> datetime:
    """Return the next Sunday midnight SLT as a UTC datetime."""
    slt = _slt_now()
    days_until_sunday = (6 - slt.weekday()) % 7
    if days_until_sunday == 0 and slt.hour == 0 and slt.minute < 5:
        # We just ran at midnight — next run is 7 days from now
        days_until_sunday = 7
    elif days_until_sunday == 0:
        days_until_sunday = 7
    next_midnight_slt = (slt + timedelta(days=days_until_sunday)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    # Convert back to UTC for storage
    return next_midnight_slt + timedelta(hours=7)


def _is_sunday_midnight_slt() -> bool:
    """True if current SLT time is Sunday between 00:00–00:02."""
    slt = _slt_now()
    return slt.weekday() == 6 and slt.hour == 0 and slt.minute < 2


async def rotate_weekly_specials():
    """
    Clears non-pinned weekly specials and picks 4–6 random items from the pool.
    Should run Sunday midnight SLT — but the scheduler calls every 60s, so
    we gate on the day/time check.
    """
    if not _is_sunday_midnight_slt():
        return

    cfg = get_config()
    shop_items = cfg.get("shop_items", {})

    # Build a pool of food items only (exclude drinks and free items)
    food_categories = {"food_snacks", "food_meals"}
    pool = [
        k for k, v in shop_items.items()
        if v.get("lumen_cost", 0) > 0
        and v.get("category") in food_categories
    ]
    if not pool:
        return

    # Pick 4–6 random items, apply 10–30% discount
    count = random.randint(4, min(6, len(pool)))
    chosen = random.sample(pool, count)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    next_week = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    if is_postgres():
        import asyncpg
        url = get_db_url()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        conn = await asyncpg.connect(url)
        try:
            # Remove old non-pinned specials
            await conn.execute(
                "DELETE FROM weekly_specials WHERE is_pinned = 0"
            )
            for item_key in chosen:
                base_cost = float(shop_items[item_key]["lumen_cost"])
                discount = random.uniform(0.10, 0.30)
                special_price = max(1.0, round(base_cost * (1 - discount)))
                await conn.execute(
                    """INSERT INTO weekly_specials
                       (item_key, special_price, available_from, available_until, is_pinned, created_at)
                       VALUES ($1, $2, $3, $4, 0, $5)""",
                    item_key, special_price, now_str, next_week, now_str
                )
        finally:
            await conn.close()
    else:
        import aiosqlite
        from pathlib import Path
        db_path = get_db_path()
        async with aiosqlite.connect(db_path) as db:
            await db.execute("DELETE FROM weekly_specials WHERE is_pinned = 0")
            for item_key in chosen:
                base_cost = float(shop_items[item_key]["lumen_cost"])
                discount = random.uniform(0.10, 0.30)
                special_price = max(1.0, round(base_cost * (1 - discount)))
                await db.execute(
                    """INSERT INTO weekly_specials
                       (item_key, special_price, available_from, available_until, is_pinned, created_at)
                       VALUES (?, ?, ?, ?, 0, ?)""",
                    (item_key, special_price, now_str, next_week, now_str)
                )
            await db.commit()

    print(f"[specials] Rotated weekly specials — {len(chosen)} items: {chosen}")


async def bill_subscriptions():
    """
    Deducts weekly subscription costs from all active subscribers.
    Cancels and notifies if insufficient balance.
    Also runs Sunday midnight SLT.
    """
    if not _is_sunday_midnight_slt():
        return

    cfg = get_config()
    subs_cfg = cfg.get("subscriptions", {})
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if is_postgres():
        import asyncpg
        url = get_db_url()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        conn = await asyncpg.connect(url)
        try:
            active_subs = await conn.fetch(
                "SELECT id, player_id, subscription_key FROM subscriptions WHERE is_active = 1"
            )
            for sub in active_subs:
                await _process_sub_pg(conn, sub, subs_cfg, now_str)
        finally:
            await conn.close()
    else:
        import aiosqlite
        db_path = get_db_path()
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, player_id, subscription_key FROM subscriptions WHERE is_active = 1"
            ) as cur:
                active_subs = await cur.fetchall()
            for sub in active_subs:
                await _process_sub_sqlite(db, sub, subs_cfg, now_str)
            await db.commit()

    print("[subscriptions] Weekly billing complete.")


async def _process_sub_pg(conn, sub, subs_cfg, now_str):
    sub_key = sub["subscription_key"]
    player_id = sub["player_id"]
    sub_id = sub["id"]

    sub_cfg = subs_cfg.get(sub_key)
    if not sub_cfg:
        return

    cost = float(sub_cfg.get("lumen_cost_weekly", 0))
    display = sub_cfg.get("display_name", sub_key)

    wallet = await conn.fetchrow(
        "SELECT balance FROM wallets WHERE player_id = $1", player_id)
    if not wallet:
        return

    balance = float(wallet["balance"])
    if balance >= cost:
        # Deduct
        await conn.execute(
            """UPDATE wallets
               SET balance = balance - $1, total_spent = total_spent + $1, last_updated = $2
               WHERE player_id = $3""",
            cost, now_str, player_id)
        await conn.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES ($1, $2, 'subscription', $3, $4)""",
            player_id, -cost, f"{display} — weekly renewal", now_str)
        await conn.execute(
            """INSERT INTO notifications (player_id, app_source, title, body, priority, created_at)
               VALUES ($1, 'haul', 'Subscription renewed 📅', $2, 'low', $3)""",
            player_id, f"{display} — ✦{cost:.0f} deducted.", now_str)
    else:
        # Cancel
        await conn.execute(
            """UPDATE subscriptions SET is_active = 0, cancelled_at = $1 WHERE id = $2""",
            now_str, sub_id)
        await conn.execute(
            """INSERT INTO notifications (player_id, app_source, title, body, priority, created_at)
               VALUES ($1, 'haul', 'Subscription cancelled ⚠️', $2, 'normal', $3)""",
            player_id, f"{display} — insufficient funds.", now_str)


async def _process_sub_sqlite(db, sub, subs_cfg, now_str):
    sub_key = sub["subscription_key"]
    player_id = sub["player_id"]
    sub_id = sub["id"]

    sub_cfg = subs_cfg.get(sub_key)
    if not sub_cfg:
        return

    cost = float(sub_cfg.get("lumen_cost_weekly", 0))
    display = sub_cfg.get("display_name", sub_key)

    async with db.execute(
        "SELECT balance FROM wallets WHERE player_id = ?", (player_id,)
    ) as cur:
        wallet = await cur.fetchone()

    if not wallet:
        return

    balance = float(wallet["balance"])
    if balance >= cost:
        await db.execute(
            """UPDATE wallets
               SET balance = balance - ?, total_spent = total_spent + ?, last_updated = ?
               WHERE player_id = ?""",
            (cost, cost, now_str, player_id))
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES (?, ?, 'subscription', ?, ?)""",
            (player_id, -cost, f"{display} — weekly renewal", now_str))
        await db.execute(
            """INSERT INTO notifications (player_id, app_source, title, body, priority, created_at)
               VALUES (?, 'haul', 'Subscription renewed 📅', ?, 'low', ?)""",
            (player_id, f"{display} — ✦{cost:.0f} deducted.", now_str))
    else:
        await db.execute(
            "UPDATE subscriptions SET is_active = 0, cancelled_at = ? WHERE id = ?",
            (now_str, sub_id))
        await db.execute(
            """INSERT INTO notifications (player_id, app_source, title, body, priority, created_at)
               VALUES (?, 'haul', 'Subscription cancelled ⚠️', ?, 'normal', ?)""",
            (player_id, f"{display} — insufficient funds.", now_str))
