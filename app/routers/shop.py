"""
Shop router — Lumen economy endpoints.

POST /shop/buy           — buy an item, deduct Lumens, apply need effects
GET  /shop/items         — full catalog (optionally filtered by category)
GET  /wallet             — balance + transaction history
POST /wallet/topup       — credit Lumens (called by L$ vendor webhook)
"""

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from app.database import get_db, is_postgres
from app.config import get_config
from app.services.notifications import push_notification
from app.services.achievements import increment_stat, set_stat_if_greater

router = APIRouter(tags=["shop"])


# ── Auth helper ──────────────────────────────────────────────────────────────

async def _get_player_by_token(token: str, db):
    """Resolve Bearer token to player row."""
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


def _extract_token(authorization: Optional[str]) -> str:
    """Pull token from 'Bearer <token>' header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    return authorization.split(" ", 1)[1].strip()


# ── Pydantic models ──────────────────────────────────────────────────────────

class BuyRequest(BaseModel):
    item_key: str


class TopupRequest(BaseModel):
    avatar_uuid: str
    lindens: int
    webhook_secret: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def _get_wallet(db, player_id: int) -> dict | None:
    if is_postgres():
        row = await db.fetchrow(
            "SELECT * FROM wallets WHERE player_id = $1", player_id)
        return dict(row) if row else None
    else:
        async with db.execute(
            "SELECT * FROM wallets WHERE player_id = ?", (player_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _get_need_value(db, player_id: int, need_key: str) -> float:
    if is_postgres():
        row = await db.fetchrow(
            "SELECT value FROM needs WHERE player_id = $1 AND need_key = $2",
            player_id, need_key)
        return float(row["value"]) if row else 0.0
    else:
        async with db.execute(
            "SELECT value FROM needs WHERE player_id = ? AND need_key = ?",
            (player_id, need_key)
        ) as cur:
            row = await cur.fetchone()
            return float(row["value"]) if row else 0.0


# ── POST /shop/buy ────────────────────────────────────────────────────────────

@router.post("/shop/buy")
async def buy_item(
    body: BuyRequest,
    authorization: Optional[str] = Header(None),
    db=Depends(get_db),
):
    token = _extract_token(authorization)
    player = await _get_player_by_token(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    cfg = get_config()
    shop_items = cfg.get("shop_items", {})

    # Validate item
    item_cfg = shop_items.get(body.item_key)
    if not item_cfg:
        raise HTTPException(status_code=404, detail=f"Item '{body.item_key}' not found.")

    cost = float(item_cfg.get("lumen_cost", 0))
    display_name = item_cfg.get("display_name", body.item_key)
    need_effects = item_cfg.get("need_effects", {})
    vibe_key = item_cfg.get("vibe_granted")

    # Check if this is a weekly special with discounted price
    actual_cost = cost
    if is_postgres():
        special_row = await db.fetchrow(
            """SELECT special_price FROM weekly_specials
               WHERE item_key = $1 AND available_until > now()::text
               ORDER BY is_pinned DESC, created_at DESC LIMIT 1""",
            body.item_key)
    else:
        async with db.execute(
            """SELECT special_price FROM weekly_specials
               WHERE item_key = ? AND available_until > datetime('now')
               ORDER BY is_pinned DESC, created_at DESC LIMIT 1""",
            (body.item_key,)
        ) as cur:
            special_row = await cur.fetchone()

    if special_row:
        actual_cost = float(special_row["special_price"])

    # Check wallet balance
    wallet = await _get_wallet(db, player_id)
    if not wallet:
        raise HTTPException(status_code=400, detail="No wallet found. Contact support.")

    balance = float(wallet["balance"])
    if balance < actual_cost:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient Lumens. You have ✦{balance:.0f}, need ✦{actual_cost:.0f}."
        )

    now = _now_str()

    # ── Deduct Lumens ────────────────────────────────────────────────────────
    new_balance = balance - actual_cost

    if is_postgres():
        await db.execute(
            """UPDATE wallets
               SET balance = $1, total_spent = total_spent + $2, last_updated = $3
               WHERE player_id = $4""",
            new_balance, actual_cost, now, player_id)
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES ($1, $2, 'purchase', $3, $4)""",
            player_id, -actual_cost,
            f"Purchased {display_name}" + (f" (special ✦{actual_cost:.0f})" if special_row and actual_cost < cost else ""),
            now)
    else:
        await db.execute(
            """UPDATE wallets
               SET balance = ?, total_spent = total_spent + ?, last_updated = ?
               WHERE player_id = ?""",
            (new_balance, actual_cost, now, player_id))
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES (?, ?, 'purchase', ?, ?)""",
            (player_id, -actual_cost,
             f"Purchased {display_name}" + (f" (special ✦{actual_cost:.0f})" if special_row and actual_cost < cost else ""),
             now))

    # ── Apply need effects ───────────────────────────────────────────────────
    applied_effects = {}
    for need_key, gain in need_effects.items():
        current = await _get_need_value(db, player_id, need_key)
        new_val = min(100.0, current + float(gain))
        applied_effects[need_key] = round(new_val, 2)

        if is_postgres():
            await db.execute(
                """UPDATE needs SET value = $1, last_updated = $2
                   WHERE player_id = $3 AND need_key = $4""",
                round(new_val, 2), now, player_id, need_key)
            await db.execute(
                """INSERT INTO event_log (player_id, need_key, action_text, delta, value_after, timestamp)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                player_id, need_key,
                f"Ate {display_name}" if need_key == "hunger" else f"Drank {display_name}",
                float(gain), round(new_val, 2), now)
        else:
            await db.execute(
                """UPDATE needs SET value = ?, last_updated = ?
                   WHERE player_id = ? AND need_key = ?""",
                (round(new_val, 2), now, player_id, need_key))
            await db.execute(
                """INSERT INTO event_log (player_id, need_key, action_text, delta, value_after, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (player_id, need_key,
                 f"Ate {display_name}" if need_key == "hunger" else f"Drank {display_name}",
                 float(gain), round(new_val, 2), now))

    # ── Grant vibe ───────────────────────────────────────────────────────────
    if vibe_key:
        vibes_cfg = cfg.get("vibes", {})
        vibe_data = vibes_cfg.get(vibe_key, {})
        duration_min = vibe_data.get("duration_minutes", 60)
        if duration_min and duration_min > 0:
            from datetime import timedelta
            expires_dt = datetime.now(timezone.utc) + timedelta(minutes=duration_min)
            expires_str = expires_dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            expires_str = None

        is_negative = 1 if vibe_data.get("is_negative") else 0

        if is_postgres():
            await db.execute(
                """INSERT INTO vibes (player_id, vibe_key, applied_at, expires_at, is_negative)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (player_id, vibe_key) DO UPDATE
                   SET applied_at = $3, expires_at = $4""",
                player_id, vibe_key, now, expires_str, is_negative)
        else:
            await db.execute(
                """INSERT OR REPLACE INTO vibes (player_id, vibe_key, applied_at, expires_at, is_negative)
                   VALUES (?, ?, ?, ?, ?)""",
                (player_id, vibe_key, now, expires_str, is_negative))

    # ── Determine notification source app ────────────────────────────────────
    category = item_cfg.get("category", "")
    if "drink" in category or "free" in category:
        app_source = "sip"
    else:
        app_source = "lumen_eats"

    # ── Push purchase notification ────────────────────────────────────────────
    if actual_cost > 0:
        notif_title = "Order placed ✓"
        notif_body = f"{display_name} — ✦{actual_cost:.0f} spent."
        await push_notification(player_id, app_source, notif_title, notif_body, priority="low", db=db)
    
    if not is_postgres():
        await db.commit()

    # ── Achievement stat tracking ─────────────────────────────────────────────
    try:
        await increment_stat(player_id, "total_purchases")
    except Exception:
        pass
    if actual_cost > 0:
        try:
            await increment_stat(player_id, "lumens_spent_total", actual_cost)
        except Exception:
            pass
    try:
        await set_stat_if_greater(player_id, "max_wallet_balance", new_balance)
    except Exception:
        pass

    return {
        "ok": True,
        "item_key": body.item_key,
        "display_name": display_name,
        "cost_paid": actual_cost,
        "new_balance": round(new_balance, 2),
        "need_effects": applied_effects,
        "vibe_granted": vibe_key,
    }


# ── GET /shop/items ──────────────────────────────────────────────────────────

@router.get("/shop/items")
async def get_shop_items(
    category: Optional[str] = Query(None, description="Filter by category: food_meals, food_snacks, drinks_paid, drinks_free"),
    authorization: Optional[str] = Header(None),
    db=Depends(get_db),
):
    token = _extract_token(authorization)
    player = await _get_player_by_token(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    cfg = get_config()
    shop_items = cfg.get("shop_items", {})

    # Fetch active weekly specials for price overlay
    if is_postgres():
        special_rows = await db.fetch(
            """SELECT item_key, special_price FROM weekly_specials
               WHERE available_until > now()::text""")
        specials_map = {r["item_key"]: float(r["special_price"]) for r in special_rows}
    else:
        async with db.execute(
            """SELECT item_key, special_price FROM weekly_specials
               WHERE available_until > datetime('now')"""
        ) as cur:
            rows = await cur.fetchall()
        specials_map = {r["item_key"]: float(r["special_price"]) for r in rows}

    result = []
    for key, item_cfg in shop_items.items():
        cat = item_cfg.get("category", "")
        if category and cat != category:
            continue
        item = {
            "item_key": key,
            "display_name": item_cfg["display_name"],
            "category": cat,
            "lumen_cost": item_cfg.get("lumen_cost", 0),
            "need_effects": item_cfg.get("need_effects", {}),
            "vibe_granted": item_cfg.get("vibe_granted"),
        }
        if key in specials_map:
            item["special_price"] = specials_map[key]
        result.append(item)

    return {"items": result, "count": len(result)}


# ── GET /wallet ──────────────────────────────────────────────────────────────

@router.get("/wallet")
async def get_wallet(
    limit: int = Query(50, ge=1, le=200),
    tx_type: Optional[str] = Query(None, description="Filter by transaction type"),
    authorization: Optional[str] = Header(None),
    db=Depends(get_db),
):
    token = _extract_token(authorization)
    player = await _get_player_by_token(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    wallet = await _get_wallet(db, player_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found.")

    # Fetch transactions
    if is_postgres():
        if tx_type:
            tx_rows = await db.fetch(
                """SELECT amount, type, description, timestamp
                   FROM transactions WHERE player_id = $1 AND type = $2
                   ORDER BY timestamp DESC LIMIT $3""",
                player_id, tx_type, limit)
        else:
            tx_rows = await db.fetch(
                """SELECT amount, type, description, timestamp
                   FROM transactions WHERE player_id = $1
                   ORDER BY timestamp DESC LIMIT $2""",
                player_id, limit)

        # Weekly summary
        weekly = await db.fetchrow(
            """SELECT
                 COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS earned,
                 COALESCE(SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END), 0) AS spent
               FROM transactions
               WHERE player_id = $1
                 AND timestamp >= (now() - interval '7 days')::text""",
            player_id)
    else:
        if tx_type:
            async with db.execute(
                """SELECT amount, type, description, timestamp
                   FROM transactions WHERE player_id = ? AND type = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (player_id, tx_type, limit)
            ) as cur:
                tx_rows = await cur.fetchall()
        else:
            async with db.execute(
                """SELECT amount, type, description, timestamp
                   FROM transactions WHERE player_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (player_id, limit)
            ) as cur:
                tx_rows = await cur.fetchall()

        async with db.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS earned,
                 COALESCE(SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END), 0) AS spent
               FROM transactions
               WHERE player_id = ?
                 AND timestamp >= datetime('now', '-7 days')""",
            (player_id,)
        ) as cur:
            weekly = await cur.fetchone()

    transactions = [
        {
            "amount": float(r["amount"]),
            "type": r["type"],
            "description": r["description"],
            "timestamp": r["timestamp"],
        }
        for r in tx_rows
    ]

    cfg = get_config()
    topup_tiers = cfg.get("economy", {}).get("lumen_topup_rates", [])

    return {
        "balance": float(wallet["balance"]),
        "total_earned": float(wallet["total_earned"]),
        "total_spent": float(wallet["total_spent"]),
        "weekly_earned": float(weekly["earned"]) if weekly else 0.0,
        "weekly_spent": abs(float(weekly["spent"])) if weekly else 0.0,
        "transactions": transactions,
        "topup_tiers": topup_tiers,
    }


# ── POST /wallet/topup ───────────────────────────────────────────────────────

@router.post("/wallet/topup")
async def topup_wallet(
    body: TopupRequest,
    db=Depends(get_db),
):
    """
    Called by L$ vendor webhook. Looks up player by avatar_uuid,
    converts Lindens to Lumens at configured rate, credits wallet.
    """
    cfg = get_config()
    topup_rates = cfg.get("economy", {}).get("lumen_topup_rates", [])

    # Validate webhook secret if configured
    admin_secret = cfg["server"].get("admin_secret", "")
    if admin_secret and body.webhook_secret != admin_secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret.")

    # Find player by avatar_uuid
    if is_postgres():
        player_row = await db.fetchrow(
            "SELECT id, display_name FROM players WHERE avatar_uuid = $1 AND is_banned = 0",
            body.avatar_uuid)
    else:
        async with db.execute(
            "SELECT id, display_name FROM players WHERE avatar_uuid = ? AND is_banned = 0",
            (body.avatar_uuid,)
        ) as cur:
            player_row = await cur.fetchone()

    if not player_row:
        raise HTTPException(status_code=404, detail="Player not found.")

    player_id = player_row["id"]

    # Match Linden amount to a top-up tier
    lumens_to_add = 0.0
    for tier in topup_rates:
        if tier["lindens"] == body.lindens:
            lumens_to_add = float(tier["lumens"])
            break

    if lumens_to_add == 0:
        # Fallback: pro-rate at base tier ratio (L$250 = ✦50 → 0.2 per Linden)
        base_rate = 50.0 / 250.0
        lumens_to_add = round(body.lindens * base_rate, 2)

    now = _now_str()

    if is_postgres():
        await db.execute(
            """UPDATE wallets
               SET balance = balance + $1,
                   total_earned = total_earned + $1,
                   last_updated = $2
               WHERE player_id = $3""",
            lumens_to_add, now, player_id)
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES ($1, $2, 'topup', $3, $4)""",
            player_id, lumens_to_add,
            f"Top-up — L${body.lindens} → ✦{lumens_to_add:.0f}", now)
    else:
        await db.execute(
            """UPDATE wallets
               SET balance = balance + ?,
                   total_earned = total_earned + ?,
                   last_updated = ?
               WHERE player_id = ?""",
            (lumens_to_add, lumens_to_add, now, player_id))
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES (?, ?, 'topup', ?, ?)""",
            (player_id, lumens_to_add,
             f"Top-up — L${body.lindens} → ✦{lumens_to_add:.0f}", now))
        await db.commit()

    # Notify player
    await push_notification(
        player_id, "vault",
        "Lumens topped up 🎉",
        f"✦{lumens_to_add:.0f} added to your wallet.",
        priority="low",
        db=db
    )

    return {
        "ok": True,
        "avatar_uuid": body.avatar_uuid,
        "lindens_paid": body.lindens,
        "lumens_added": lumens_to_add,
    }


# ── POST /shop/subscribe ───────────────────────────────────────────────────────

class SubscribeRequest(BaseModel):
    token: str
    subscription_key: str

@router.post("/subscribe")
async def subscribe(body: SubscribeRequest, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    cfg = get_config()
    sub_defs = cfg.get("subscriptions", {})

    # Handle both list and dict formats in config
    if isinstance(sub_defs, list):
        valid_keys = set(sub_defs)
        sub_cost = {"wavelength_premium": cfg.get("wavelength", {}).get("premium_cost_weekly", 25),
                    "gym_membership": 30, "flare_verified": 20}.get(body.subscription_key, 25)
    else:
        if body.subscription_key not in sub_defs:
            raise HTTPException(status_code=400, detail="Unknown subscription.")
        sub_cost = sub_defs[body.subscription_key].get("weekly_cost", 25)
        valid_keys = set(sub_defs.keys())

    if body.subscription_key not in valid_keys:
        raise HTTPException(status_code=400, detail="Unknown subscription.")

    # Check balance
    if is_postgres():
        wallet_row = await db.fetchrow("SELECT balance FROM wallets WHERE player_id = $1", player_id)
    else:
        async with db.execute("SELECT balance FROM wallets WHERE player_id = ?", (player_id,)) as cur:
            wallet_row = await cur.fetchone()

    balance = float(wallet_row["balance"]) if wallet_row else 0.0
    if balance < sub_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient balance. Need ✦{sub_cost}.")

    now = datetime.now(timezone.utc).isoformat()

    # Check already subscribed
    if is_postgres():
        existing = await db.fetchrow(
            "SELECT id FROM subscriptions WHERE player_id = $1 AND subscription_key = $2 AND is_active = 1",
            player_id, body.subscription_key)
        if existing:
            return {"ok": True, "status": "already_active"}
        new_balance = balance - sub_cost
        await db.execute("UPDATE wallets SET balance = $1 WHERE player_id = $2", new_balance, player_id)
        await db.execute(
            "INSERT INTO subscriptions (player_id, subscription_key, started_at, renews_at, is_active) VALUES ($1, $2, $3, $3, 1)",
            player_id, body.subscription_key, now)
    else:
        async with db.execute(
            "SELECT id FROM subscriptions WHERE player_id = ? AND subscription_key = ? AND is_active = 1",
            (player_id, body.subscription_key)) as cur:
            existing = await cur.fetchone()
        if existing:
            return {"ok": True, "status": "already_active"}
        new_balance = balance - sub_cost
        await db.execute("UPDATE wallets SET balance = ? WHERE player_id = ?", (new_balance, player_id))
        await db.execute(
            "INSERT OR IGNORE INTO subscriptions (player_id, subscription_key, started_at, renews_at, is_active) VALUES (?, ?, ?, ?, 1)",
            (player_id, body.subscription_key, now, now))
        await db.commit()

    return {"ok": True, "status": "subscribed", "new_balance": round(new_balance, 2)}


# ── POST /shop/unsubscribe ────────────────────────────────────────────────────

class UnsubscribeRequest(BaseModel):
    token: str
    subscription_key: str

@router.post("/unsubscribe")
async def unsubscribe(body: UnsubscribeRequest, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    if is_postgres():
        await db.execute(
            "UPDATE subscriptions SET is_active = 0 WHERE player_id = $1 AND subscription_key = $2",
            player_id, body.subscription_key)
    else:
        await db.execute(
            "UPDATE subscriptions SET is_active = 0 WHERE player_id = ? AND subscription_key = ?",
            (player_id, body.subscription_key))
        await db.commit()

    return {"ok": True, "status": "cancelled"}
