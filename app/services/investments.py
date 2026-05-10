"""
app/services/investments.py

Two scheduled jobs:
  - run_price_tick()   — updates all asset prices every 30 min
  - run_pot_interest() — accrues weekly savings interest on all pots

Bank definitions (savings layer only — investments are flat):
  luminos_trust   : 0.8%/week, no withdrawal fee
  meridian_private: 1.8%/week, 2% fee on early withdrawal (before goal met)
  cove_community  : 1.2%/week, no fee, max pot balance ✦2,000

Asset seed data — inserted once on first price tick if table is empty.
"""

import random
import math
import logging
from datetime import datetime, timezone

from app.database import is_postgres, get_pg_pool, get_db_path

logger = logging.getLogger(__name__)

# ── Bank definitions ──────────────────────────────────────────────────────────

BANKS = {
    "luminos_trust": {
        "name": "Luminos Trust",
        "tagline": "Safe, steady, established.",
        "weekly_interest_rate": 0.008,   # 0.8%
        "early_withdrawal_fee": 0.0,     # none
        "pot_balance_cap": None,          # no cap
        "color": "#4a7fb5",
    },
    "meridian_private": {
        "name": "Meridian Private",
        "tagline": "High yield. Exclusive.",
        "weekly_interest_rate": 0.018,   # 1.8%
        "early_withdrawal_fee": 0.02,    # 2% if goal not yet met
        "pot_balance_cap": None,
        "color": "#9a7c4e",
    },
    "cove_community": {
        "name": "Cove Community",
        "tagline": "People first. Always.",
        "weekly_interest_rate": 0.012,   # 1.2%
        "early_withdrawal_fee": 0.0,
        "pot_balance_cap": 2000.0,       # ✦2,000 per pot
        "color": "#5a9e6f",
    },
}

# ── Asset seed data ───────────────────────────────────────────────────────────

ASSET_SEEDS = [
    {
        "ticker": "LMNS",
        "name": "Luminos Properties Group",
        "sector": "real_estate",
        "description": "Stable blue-chip real estate trust. Low volatility, reliable returns.",
        "base_price": 42.0,
        "volatility": 0.018,
    },
    {
        "ticker": "NBLM",
        "name": "NightBloom Entertainment",
        "sector": "nightlife",
        "description": "Venues, events, nightlife. Spikes on weekends, dips midweek.",
        "base_price": 18.0,
        "volatility": 0.065,
    },
    {
        "ticker": "AURX",
        "name": "Aura Collective",
        "sector": "beauty",
        "description": "Beauty and cosmetics brand. Steady grower, event-linked bumps.",
        "base_price": 27.0,
        "volatility": 0.032,
    },
    {
        "ticker": "SILV",
        "name": "Silverthread Couture",
        "sector": "fashion",
        "description": "Fashion and apparel house. Trends up during shopping events.",
        "base_price": 22.0,
        "volatility": 0.042,
    },
    {
        "ticker": "MRDN",
        "name": "Meridian Wellness",
        "sector": "health",
        "description": "Health and lifestyle brand. Slow and defensive, rarely crashes.",
        "base_price": 35.0,
        "volatility": 0.020,
    },
    {
        "ticker": "VLTX",
        "name": "Voltage Creative",
        "sector": "art_media",
        "description": "Art, media, and culture. Highly volatile — big swings both ways.",
        "base_price": 14.0,
        "volatility": 0.085,
    },
    {
        "ticker": "COVE",
        "name": "Cove & Harbor Living",
        "sector": "furniture",
        "description": "Furniture and home goods. Cyclical — dips and recovers predictably.",
        "base_price": 19.0,
        "volatility": 0.038,
    },
    {
        "ticker": "PRISM",
        "name": "Prism Social Group",
        "sector": "social",
        "description": "Social and community platform. Rises with active player counts.",
        "base_price": 31.0,
        "volatility": 0.055,
    },
    {
        "ticker": "OBSDN",
        "name": "Obsidian Finance",
        "sector": "fintech",
        "description": "Banking and fintech. Meta — players investing in the financial system itself.",
        "base_price": 48.0,
        "volatility": 0.025,
    },
    {
        "ticker": "WYLDE",
        "name": "Wylde Botanicals",
        "sector": "wellness",
        "description": "Nature and wellness brand. Slow, reliable, strong floor.",
        "base_price": 25.0,
        "volatility": 0.022,
    },
]

# ── Price tick logic ──────────────────────────────────────────────────────────

def _calc_new_price(current: float, base: float, volatility: float) -> float:
    """
    Weighted random walk with mean reversion.
    - Random component: normally distributed shock scaled by volatility
    - Mean reversion: gentle pull back toward base price (prevents runaway)
    - Floor: price never drops below 10% of base
    """
    shock = random.gauss(0, volatility)
    reversion_strength = 0.03
    reversion = reversion_strength * (base - current) / base
    pct_change = shock + reversion
    new_price = current * (1 + pct_change)
    floor = base * 0.10
    ceiling = base * 5.0
    return round(max(floor, min(ceiling, new_price)), 4)


async def _seed_assets_if_empty_sqlite(db):
    cursor = await db.execute("SELECT COUNT(*) FROM vault_assets")
    row = await cursor.fetchone()
    if row[0] > 0:
        return
    for asset in ASSET_SEEDS:
        await db.execute(
            """INSERT OR IGNORE INTO vault_assets
               (ticker, name, sector, description, current_price, prev_price, base_price, volatility)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (asset["ticker"], asset["name"], asset["sector"], asset["description"],
             asset["base_price"], asset["base_price"], asset["base_price"], asset["volatility"])
        )
    await db.commit()
    logger.info("vault_assets seeded with 10 assets (SQLite)")


async def _seed_assets_if_empty_pg(conn):
    count = await conn.fetchval("SELECT COUNT(*) FROM vault_assets")
    if count > 0:
        return
    for asset in ASSET_SEEDS:
        await conn.execute(
            """INSERT INTO vault_assets
               (ticker, name, sector, description, current_price, prev_price, base_price, volatility)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (ticker) DO NOTHING""",
            asset["ticker"], asset["name"], asset["sector"], asset["description"],
            asset["base_price"], asset["base_price"], asset["base_price"], asset["volatility"]
        )
    logger.info("vault_assets seeded with 10 assets (PostgreSQL)")


async def run_price_tick():
    """
    Update prices for all assets. Runs every 30 minutes via scheduler.
    Also seeds asset table on first run.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        if is_postgres():
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                await _seed_assets_if_empty_pg(conn)
                assets = await conn.fetch("SELECT id, current_price, base_price, volatility FROM vault_assets")
                for asset in assets:
                    new_price = _calc_new_price(
                        float(asset["current_price"]),
                        float(asset["base_price"]),
                        float(asset["volatility"])
                    )
                    await conn.execute(
                        """UPDATE vault_assets
                           SET prev_price = current_price, current_price = $1, last_updated = $2
                           WHERE id = $3""",
                        new_price, now, asset["id"]
                    )
                    await conn.execute(
                        "INSERT INTO vault_asset_prices (asset_id, price, recorded_at) VALUES ($1,$2,$3)",
                        asset["id"], new_price, now
                    )
        else:
            import aiosqlite
            from pathlib import Path
            db_path = get_db_path()
            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                await _seed_assets_if_empty_sqlite(db)
                cursor = await db.execute("SELECT id, current_price, base_price, volatility FROM vault_assets")
                assets = await cursor.fetchall()
                for asset in assets:
                    new_price = _calc_new_price(
                        float(asset["current_price"]),
                        float(asset["base_price"]),
                        float(asset["volatility"])
                    )
                    await db.execute(
                        """UPDATE vault_assets
                           SET prev_price = current_price, current_price = ?, last_updated = ?
                           WHERE id = ?""",
                        (new_price, now, asset["id"])
                    )
                    await db.execute(
                        "INSERT INTO vault_asset_prices (asset_id, price, recorded_at) VALUES (?,?,?)",
                        (asset["id"], new_price, now)
                    )
                await db.commit()

        logger.info("vault price tick complete")

    except Exception as e:
        logger.error(f"run_price_tick error: {e}", exc_info=True)


# ── Savings pot interest ──────────────────────────────────────────────────────

async def run_pot_interest():
    """
    Accrue weekly interest on all savings pots.
    Rate comes from the player's chosen bank.
    Runs weekly (Sunday midnight SLT via scheduler).
    Cove Community caps pot balance at ✦2,000 — interest does not push past cap.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        if is_postgres():
            pool = await get_pg_pool()
            async with pool.acquire() as conn:
                # Get all pots with their player's bank key
                pots = await conn.fetch("""
                    SELECT vp.id, vp.player_id, vp.balance,
                           COALESCE(va.bank_key, 'luminos_trust') AS bank_key
                    FROM vault_pots vp
                    LEFT JOIN vault_accounts va ON va.player_id = vp.player_id
                    WHERE vp.balance > 0
                """)
                for pot in pots:
                    bank = BANKS.get(pot["bank_key"], BANKS["luminos_trust"])
                    rate = bank["weekly_interest_rate"]
                    cap = bank["pot_balance_cap"]
                    interest = round(float(pot["balance"]) * rate, 2)
                    new_balance = float(pot["balance"]) + interest
                    if cap is not None:
                        new_balance = min(new_balance, cap)
                        interest = new_balance - float(pot["balance"])
                    if interest <= 0:
                        continue
                    await conn.execute(
                        "UPDATE vault_pots SET balance=$1, last_interest_at=$2 WHERE id=$3",
                        new_balance, now, pot["id"]
                    )
                    await conn.execute(
                        """INSERT INTO vault_pot_transactions
                           (pot_id, player_id, type, amount, fee, note, created_at)
                           VALUES ($1,$2,'interest',$3,0,'Weekly interest',$4)""",
                        pot["id"], pot["player_id"], interest, now
                    )
        else:
            import aiosqlite
            from pathlib import Path
            db_path = get_db_path()
            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT vp.id, vp.player_id, vp.balance,
                           COALESCE(va.bank_key, 'luminos_trust') AS bank_key
                    FROM vault_pots vp
                    LEFT JOIN vault_accounts va ON va.player_id = vp.player_id
                    WHERE vp.balance > 0
                """)
                pots = await cursor.fetchall()
                for pot in pots:
                    bank = BANKS.get(pot["bank_key"], BANKS["luminos_trust"])
                    rate = bank["weekly_interest_rate"]
                    cap = bank["pot_balance_cap"]
                    interest = round(float(pot["balance"]) * rate, 2)
                    new_balance = float(pot["balance"]) + interest
                    if cap is not None:
                        new_balance = min(new_balance, cap)
                        interest = new_balance - float(pot["balance"])
                    if interest <= 0:
                        continue
                    await db.execute(
                        "UPDATE vault_pots SET balance=?, last_interest_at=? WHERE id=?",
                        (new_balance, now, pot["id"])
                    )
                    await db.execute(
                        """INSERT INTO vault_pot_transactions
                           (pot_id, player_id, type, amount, fee, note, created_at)
                           VALUES (?,?,'interest',?,0,'Weekly interest',?)""",
                        (pot["id"], pot["player_id"], interest, now)
                    )
                await db.commit()

        logger.info("pot interest accrual complete")

    except Exception as e:
        logger.error(f"run_pot_interest error: {e}", exc_info=True)
