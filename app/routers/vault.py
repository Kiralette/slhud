"""
app/routers/vault.py

Vault API — savings pots, investments, P2P transfers, bank selection.

Endpoints:
  GET  /vault/account          — player's bank + account summary
  POST /vault/account/bank     — choose or switch bank (30-day cooldown)
  GET  /vault/pots             — all savings pots
  POST /vault/pots             — create a pot
  POST /vault/pots/{pot_id}/deposit   — deposit lumens into pot
  POST /vault/pots/{pot_id}/withdraw  — withdraw from pot (fee may apply)
  DELETE /vault/pots/{pot_id}         — close pot and return balance to wallet
  GET  /vault/market           — all assets with price + player holdings
  POST /vault/market/buy       — buy shares
  POST /vault/market/sell      — sell shares
  GET  /vault/portfolio        — player's holdings with gain/loss detail
  GET  /vault/orders           — order history
  POST /vault/transfer         — send lumens to another player
  GET  /vault/transfers        — P2P transfer history
  POST /vault/market/refresh   — admin: manually trigger price tick
"""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.database import get_db, is_postgres
from app.services.auth import get_current_player
from app.services.investments import BANKS, run_price_tick
from app.services.notifications import push_notification

router = APIRouter(prefix="/vault", tags=["vault"])

# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_since(ts_str: str) -> float:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return 0.0


async def _get_wallet_balance(db, player_id: int, pg: bool) -> float:
    if pg:
        row = await db.fetchrow("SELECT balance FROM wallets WHERE player_id=$1", player_id)
    else:
        cursor = await db.execute("SELECT balance FROM wallets WHERE player_id=?", (player_id,))
        row = await cursor.fetchone()
    return float(row["balance"]) if row else 0.0


async def _ensure_wallet(db, player_id: int, pg: bool):
    """Create a wallet row for this player if one doesn't exist yet."""
    if pg:
        await db.execute(
            """INSERT INTO wallets (player_id, balance, total_earned, total_spent)
               VALUES ($1, 500.0, 0.0, 0.0)
               ON CONFLICT (player_id) DO NOTHING""",
            player_id
        )
    else:
        await db.execute(
            """INSERT OR IGNORE INTO wallets (player_id, balance, total_earned, total_spent)
               VALUES (?, 500.0, 0.0, 0.0)""",
            (player_id,)
        )


async def _debit_wallet(db, player_id: int, amount: float, tx_type: str, description: str, pg: bool):
    now = _now()
    await _ensure_wallet(db, player_id, pg)
    if pg:
        await db.execute(
            "UPDATE wallets SET balance=balance-$1, total_spent=total_spent+$1, last_updated=$2 WHERE player_id=$3",
            amount, now, player_id
        )
        await db.execute(
            "INSERT INTO transactions (player_id, amount, type, description, timestamp) VALUES ($1,$2,$3,$4,$5)",
            player_id, -amount, tx_type, description, now
        )
    else:
        await db.execute(
            "UPDATE wallets SET balance=balance-?, total_spent=total_spent+?, last_updated=? WHERE player_id=?",
            (amount, amount, now, player_id)
        )
        await db.execute(
            "INSERT INTO transactions (player_id, amount, type, description, timestamp) VALUES (?,?,?,?,?)",
            (player_id, -amount, tx_type, description, now)
        )


async def _credit_wallet(db, player_id: int, amount: float, tx_type: str, description: str, pg: bool):
    now = _now()
    await _ensure_wallet(db, player_id, pg)
    if pg:
        await db.execute(
            "UPDATE wallets SET balance=balance+$1, total_earned=total_earned+$1, last_updated=$2 WHERE player_id=$3",
            amount, now, player_id
        )
        await db.execute(
            "INSERT INTO transactions (player_id, amount, type, description, timestamp) VALUES ($1,$2,$3,$4,$5)",
            player_id, amount, tx_type, description, now
        )
    else:
        await db.execute(
            "UPDATE wallets SET balance=balance+?, total_earned=total_earned+?, last_updated=? WHERE player_id=?",
            (amount, amount, now, player_id)
        )
        await db.execute(
            "INSERT INTO transactions (player_id, amount, type, description, timestamp) VALUES (?,?,?,?,?)",
            (player_id, amount, tx_type, description, now)
        )


async def _get_or_create_account(db, player_id: int, pg: bool) -> dict:
    """Return player's vault_account row, creating it with default bank if missing."""
    if pg:
        row = await db.fetchrow("SELECT * FROM vault_accounts WHERE player_id=$1", player_id)
        if not row:
            now = _now()
            await db.execute(
                "INSERT INTO vault_accounts (player_id, bank_key, switched_at, created_at) VALUES ($1,'luminos_trust',$2,$2)",
                player_id, now
            )
            row = await db.fetchrow("SELECT * FROM vault_accounts WHERE player_id=$1", player_id)
    else:
        cursor = await db.execute("SELECT * FROM vault_accounts WHERE player_id=?", (player_id,))
        row = await cursor.fetchone()
        if not row:
            now = _now()
            await db.execute(
                "INSERT INTO vault_accounts (player_id, bank_key, switched_at, created_at) VALUES (?,'luminos_trust',?,?)",
                (player_id, now, now)
            )
            await db.commit()
            cursor = await db.execute("SELECT * FROM vault_accounts WHERE player_id=?", (player_id,))
            row = await cursor.fetchone()
    return dict(row)


# ── Pydantic models ───────────────────────────────────────────────────────────

class BankSwitchRequest(BaseModel):
    bank_key: str

class CreatePotRequest(BaseModel):
    name: str = Field(..., max_length=40)
    emoji: str = Field("🏦", max_length=4)
    goal_amount: Optional[float] = Field(None, ge=1)
    deadline: Optional[str] = None   # ISO date string

class DepositRequest(BaseModel):
    amount: float = Field(..., gt=0)

class WithdrawRequest(BaseModel):
    amount: float = Field(..., gt=0)

class BuyRequest(BaseModel):
    ticker: str
    shares: float = Field(..., gt=0)

class SellRequest(BaseModel):
    ticker: str
    shares: float = Field(..., gt=0)

class TransferRequest(BaseModel):
    recipient_uuid: str
    amount: float = Field(..., gt=0)
    note: Optional[str] = Field(None, max_length=100)


# ── Account / bank endpoints ──────────────────────────────────────────────────

@router.get("/account")
async def get_vault_account(
    player=Depends(get_current_player),
    db=Depends(get_db)
):
    pg = is_postgres()
    account = await _get_or_create_account(db, player["id"], pg)
    bank_key = account["bank_key"]
    bank = BANKS.get(bank_key, BANKS["luminos_trust"])
    days_since_switch = _days_since(account["switched_at"])
    can_switch_in_days = max(0, 30 - days_since_switch)

    # Pot count + total saved
    if pg:
        pot_stats = await db.fetchrow(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(balance),0) as total FROM vault_pots WHERE player_id=$1",
            player["id"]
        )
    else:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(balance),0) as total FROM vault_pots WHERE player_id=?",
            (player["id"],)
        )
        pot_stats = await cursor.fetchone()

    return {
        "bank_key": bank_key,
        "bank_name": bank["name"],
        "bank_tagline": bank["tagline"],
        "bank_color": bank["color"],
        "weekly_interest_rate": bank["weekly_interest_rate"],
        "early_withdrawal_fee": bank["early_withdrawal_fee"],
        "pot_balance_cap": bank["pot_balance_cap"],
        "can_switch": can_switch_in_days == 0,
        "can_switch_in_days": round(can_switch_in_days, 1),
        "pot_count": pot_stats["cnt"],
        "total_saved": round(float(pot_stats["total"]), 2),
        "all_banks": [
            {
                "key": k,
                "name": v["name"],
                "tagline": v["tagline"],
                "color": v["color"],
                "weekly_interest_rate": v["weekly_interest_rate"],
                "early_withdrawal_fee": v["early_withdrawal_fee"],
                "pot_balance_cap": v["pot_balance_cap"],
                "is_current": k == bank_key,
            }
            for k, v in BANKS.items()
        ]
    }


@router.post("/account/bank")
async def switch_bank(
    req: BankSwitchRequest,
    player=Depends(get_current_player),
    db=Depends(get_db)
):
    if req.bank_key not in BANKS:
        raise HTTPException(400, "Unknown bank. Valid: luminos_trust, meridian_private, cove_community")
    pg = is_postgres()
    account = await _get_or_create_account(db, player["id"], pg)
    if account["bank_key"] == req.bank_key:
        raise HTTPException(400, "Already with that bank.")
    days_since = _days_since(account["switched_at"])
    if days_since < 30:
        raise HTTPException(400, f"Bank switch cooldown active. {round(30-days_since,1)} days remaining.")
    now = _now()
    if pg:
        await db.execute(
            "UPDATE vault_accounts SET bank_key=$1, switched_at=$2 WHERE player_id=$3",
            req.bank_key, now, player["id"]
        )
    else:
        await db.execute(
            "UPDATE vault_accounts SET bank_key=?, switched_at=? WHERE player_id=?",
            (req.bank_key, now, player["id"])
        )
        await db.commit()
    return {"ok": True, "bank_key": req.bank_key, "bank_name": BANKS[req.bank_key]["name"]}


# ── Savings pots ──────────────────────────────────────────────────────────────

@router.get("/pots")
async def get_pots(
    player=Depends(get_current_player),
    db=Depends(get_db)
):
    pg = is_postgres()
    account = await _get_or_create_account(db, player["id"], pg)
    bank = BANKS.get(account["bank_key"], BANKS["luminos_trust"])

    if pg:
        rows = await db.fetch(
            "SELECT * FROM vault_pots WHERE player_id=$1 ORDER BY created_at ASC",
            player["id"]
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM vault_pots WHERE player_id=? ORDER BY created_at ASC",
            (player["id"],)
        )
        rows = await cursor.fetchall()

    pots = []
    for r in rows:
        goal = float(r["goal_amount"]) if r["goal_amount"] else None
        balance = float(r["balance"])
        progress = (balance / goal * 100) if goal else None
        pots.append({
            "id": r["id"],
            "name": r["name"],
            "emoji": r["emoji"],
            "balance": round(balance, 2),
            "goal_amount": goal,
            "progress_pct": round(progress, 1) if progress is not None else None,
            "goal_met": balance >= goal if goal else False,
            "deadline": r["deadline"],
            "is_locked": bool(r["is_locked"]),
            "created_at": r["created_at"],
            "last_interest_at": r["last_interest_at"],
            "interest_rate": bank["weekly_interest_rate"],
        })
    return {"pots": pots, "bank_key": account["bank_key"]}


@router.post("/pots")
async def create_pot(
    req: CreatePotRequest,
    player=Depends(get_current_player),
    db=Depends(get_db)
):
    pg = is_postgres()
    now = _now()
    if pg:
        row = await db.fetchrow(
            """INSERT INTO vault_pots (player_id, name, emoji, goal_amount, deadline, created_at, last_interest_at)
               VALUES ($1,$2,$3,$4,$5,$6,$6) RETURNING id""",
            player["id"], req.name, req.emoji, req.goal_amount, req.deadline, now
        )
        pot_id = row["id"]
    else:
        cursor = await db.execute(
            """INSERT INTO vault_pots (player_id, name, emoji, goal_amount, deadline, created_at, last_interest_at)
               VALUES (?,?,?,?,?,?,?)""",
            (player["id"], req.name, req.emoji, req.goal_amount, req.deadline, now, now)
        )
        await db.commit()
        pot_id = cursor.lastrowid
    return {"ok": True, "pot_id": pot_id}


@router.post("/pots/{pot_id}/deposit")
async def deposit_to_pot(
    pot_id: int,
    req: DepositRequest,
    player=Depends(get_current_player),
    db=Depends(get_db)
):
    pg = is_postgres()

    # Validate pot belongs to player
    if pg:
        pot = await db.fetchrow("SELECT * FROM vault_pots WHERE id=$1 AND player_id=$2", pot_id, player["id"])
    else:
        cursor = await db.execute("SELECT * FROM vault_pots WHERE id=? AND player_id=?", (pot_id, player["id"]))
        pot = await cursor.fetchone()
    if not pot:
        raise HTTPException(404, "Pot not found.")

    # Check Cove Community cap
    account = await _get_or_create_account(db, player["id"], pg)
    bank = BANKS.get(account["bank_key"], BANKS["luminos_trust"])
    current_balance = float(pot["balance"])
    cap = bank["pot_balance_cap"]
    amount = req.amount
    if cap is not None:
        if current_balance >= cap:
            raise HTTPException(400, f"Pot is at the {bank['name']} maximum of ✦{cap:.0f}.")
        amount = min(amount, cap - current_balance)

    # Check wallet balance
    wallet_balance = await _get_wallet_balance(db, player["id"], pg)
    if wallet_balance < amount:
        raise HTTPException(400, f"Insufficient Lumens. Balance: ✦{wallet_balance:.0f}")

    now = _now()
    await _debit_wallet(db, player["id"], amount, "pot_deposit", f"Saved to '{pot['name']}'", pg)

    if pg:
        await db.execute(
            "UPDATE vault_pots SET balance=balance+$1 WHERE id=$2",
            amount, pot_id
        )
        await db.execute(
            """INSERT INTO vault_pot_transactions (pot_id, player_id, type, amount, fee, note, created_at)
               VALUES ($1,$2,'deposit',$3,0,NULL,$4)""",
            pot_id, player["id"], amount, now
        )
    else:
        await db.execute("UPDATE vault_pots SET balance=balance+? WHERE id=?", (amount, pot_id))
        await db.execute(
            """INSERT INTO vault_pot_transactions (pot_id, player_id, type, amount, fee, note, created_at)
               VALUES (?,?,'deposit',?,0,NULL,?)""",
            (pot_id, player["id"], amount, now)
        )
        await db.commit()

    return {"ok": True, "deposited": round(amount, 2)}


@router.post("/pots/{pot_id}/withdraw")
async def withdraw_from_pot(
    pot_id: int,
    req: WithdrawRequest,
    player=Depends(get_current_player),
    db=Depends(get_db)
):
    pg = is_postgres()
    if pg:
        pot = await db.fetchrow("SELECT * FROM vault_pots WHERE id=$1 AND player_id=$2", pot_id, player["id"])
    else:
        cursor = await db.execute("SELECT * FROM vault_pots WHERE id=? AND player_id=?", (pot_id, player["id"]))
        pot = await cursor.fetchone()
    if not pot:
        raise HTTPException(404, "Pot not found.")

    balance = float(pot["balance"])
    amount = req.amount
    if amount > balance:
        raise HTTPException(400, f"Insufficient pot balance. Available: ✦{balance:.0f}")

    account = await _get_or_create_account(db, player["id"], pg)
    bank = BANKS.get(account["bank_key"], BANKS["luminos_trust"])

    # Meridian early withdrawal fee
    fee = 0.0
    goal = float(pot["goal_amount"]) if pot["goal_amount"] else None
    goal_met = (balance >= goal) if goal else True
    if not goal_met and bank["early_withdrawal_fee"] > 0:
        fee = round(amount * bank["early_withdrawal_fee"], 2)

    net = amount - fee
    now = _now()

    if pg:
        await db.execute("UPDATE vault_pots SET balance=balance-$1 WHERE id=$2", amount, pot_id)
        await db.execute(
            """INSERT INTO vault_pot_transactions (pot_id, player_id, type, amount, fee, note, created_at)
               VALUES ($1,$2,'withdrawal',$3,$4,NULL,$5)""",
            pot_id, player["id"], amount, fee, now
        )
    else:
        await db.execute("UPDATE vault_pots SET balance=balance-? WHERE id=?", (amount, pot_id))
        await db.execute(
            """INSERT INTO vault_pot_transactions (pot_id, player_id, type, amount, fee, note, created_at)
               VALUES (?,?,'withdrawal',?,?,NULL,?)""",
            (pot_id, player["id"], amount, fee, now)
        )

    await _credit_wallet(db, player["id"], net, "pot_withdrawal", f"Withdrew from '{pot['name']}'", pg)
    if not pg:
        await db.commit()

    return {"ok": True, "withdrawn": round(amount, 2), "fee": round(fee, 2), "net_credited": round(net, 2)}


@router.delete("/pots/{pot_id}")
async def close_pot(
    pot_id: int,
    player=Depends(get_current_player),
    db=Depends(get_db)
):
    pg = is_postgres()
    if pg:
        pot = await db.fetchrow("SELECT * FROM vault_pots WHERE id=$1 AND player_id=$2", pot_id, player["id"])
    else:
        cursor = await db.execute("SELECT * FROM vault_pots WHERE id=? AND player_id=?", (pot_id, player["id"]))
        pot = await cursor.fetchone()
    if not pot:
        raise HTTPException(404, "Pot not found.")

    balance = float(pot["balance"])
    if balance > 0:
        await _credit_wallet(db, player["id"], balance, "pot_closed", f"Closed pot '{pot['name']}'", pg)

    if pg:
        await db.execute("DELETE FROM vault_pots WHERE id=$1", pot_id)
    else:
        await db.execute("DELETE FROM vault_pots WHERE id=?", (pot_id,))
        await db.commit()

    return {"ok": True, "returned": round(balance, 2)}


# ── Market / investments ──────────────────────────────────────────────────────

@router.get("/market")
async def get_market(
    player=Depends(get_current_player),
    db=Depends(get_db)
):
    pg = is_postgres()
    if pg:
        assets = await db.fetch("SELECT * FROM vault_assets ORDER BY ticker ASC")
        holdings_rows = await db.fetch(
            "SELECT asset_id, shares, avg_cost FROM vault_holdings WHERE player_id=$1",
            player["id"]
        )
    else:
        cursor = await db.execute("SELECT * FROM vault_assets ORDER BY ticker ASC")
        assets = await cursor.fetchall()
        cursor = await db.execute(
            "SELECT asset_id, shares, avg_cost FROM vault_holdings WHERE player_id=?",
            (player["id"],)
        )
        holdings_rows = await cursor.fetchall()

    holdings_map = {r["asset_id"]: {"shares": float(r["shares"]), "avg_cost": float(r["avg_cost"])} for r in holdings_rows}

    result = []
    for a in assets:
        asset_id = a["id"]
        current = float(a["current_price"])
        prev = float(a["prev_price"])
        change_pct = ((current - prev) / prev * 100) if prev else 0
        holding = holdings_map.get(asset_id, {"shares": 0.0, "avg_cost": 0.0})
        shares = holding["shares"]
        avg_cost = holding["avg_cost"]
        market_value = shares * current
        gain_loss = (current - avg_cost) * shares
        result.append({
            "id": asset_id,
            "ticker": a["ticker"],
            "name": a["name"],
            "sector": a["sector"],
            "description": a["description"],
            "current_price": round(current, 4),
            "prev_price": round(prev, 4),
            "change_pct": round(change_pct, 2),
            "direction": "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat"),
            "last_updated": a["last_updated"],
            "shares_held": round(shares, 4),
            "avg_cost": round(avg_cost, 4),
            "market_value": round(market_value, 2),
            "gain_loss": round(gain_loss, 2),
        })
    return {"assets": result}


@router.post("/market/buy")
async def buy_shares(
    req: BuyRequest,
    player=Depends(get_current_player),
    db=Depends(get_db)
):
    pg = is_postgres()
    if pg:
        asset = await db.fetchrow("SELECT * FROM vault_assets WHERE ticker=$1", req.ticker.upper())
    else:
        cursor = await db.execute("SELECT * FROM vault_assets WHERE ticker=?", (req.ticker.upper(),))
        asset = await cursor.fetchone()
    if not asset:
        raise HTTPException(404, "Asset not found.")

    price = float(asset["current_price"])
    total_cost = round(price * req.shares, 2)
    wallet_balance = await _get_wallet_balance(db, player["id"], pg)
    if wallet_balance < total_cost:
        raise HTTPException(400, f"Insufficient Lumens. Need ✦{total_cost:.2f}, have ✦{wallet_balance:.2f}")

    await _debit_wallet(db, player["id"], total_cost, "investment_buy", f"Bought {req.shares:.4f} {asset['ticker']}", pg)

    now = _now()
    asset_id = asset["id"]

    # Upsert holdings with weighted avg cost
    if pg:
        existing = await db.fetchrow(
            "SELECT shares, avg_cost FROM vault_holdings WHERE player_id=$1 AND asset_id=$2",
            player["id"], asset_id
        )
        if existing:
            old_shares = float(existing["shares"])
            old_cost = float(existing["avg_cost"])
            new_shares = old_shares + req.shares
            new_avg = ((old_shares * old_cost) + (req.shares * price)) / new_shares
            await db.execute(
                "UPDATE vault_holdings SET shares=$1, avg_cost=$2 WHERE player_id=$3 AND asset_id=$4",
                new_shares, new_avg, player["id"], asset_id
            )
        else:
            await db.execute(
                "INSERT INTO vault_holdings (player_id, asset_id, shares, avg_cost) VALUES ($1,$2,$3,$4)",
                player["id"], asset_id, req.shares, price
            )
        await db.execute(
            """INSERT INTO vault_orders (player_id, asset_id, order_type, shares, price_at_order, total_value, created_at)
               VALUES ($1,$2,'buy',$3,$4,$5,$6)""",
            player["id"], asset_id, req.shares, price, total_cost, now
        )
    else:
        cursor = await db.execute(
            "SELECT shares, avg_cost FROM vault_holdings WHERE player_id=? AND asset_id=?",
            (player["id"], asset_id)
        )
        existing = await cursor.fetchone()
        if existing:
            old_shares = float(existing["shares"])
            old_cost = float(existing["avg_cost"])
            new_shares = old_shares + req.shares
            new_avg = ((old_shares * old_cost) + (req.shares * price)) / new_shares
            await db.execute(
                "UPDATE vault_holdings SET shares=?, avg_cost=? WHERE player_id=? AND asset_id=?",
                (new_shares, new_avg, player["id"], asset_id)
            )
        else:
            await db.execute(
                "INSERT INTO vault_holdings (player_id, asset_id, shares, avg_cost) VALUES (?,?,?,?)",
                (player["id"], asset_id, req.shares, price)
            )
        await db.execute(
            """INSERT INTO vault_orders (player_id, asset_id, order_type, shares, price_at_order, total_value, created_at)
               VALUES (?,?,'buy',?,?,?,?)""",
            (player["id"], asset_id, req.shares, price, total_cost, now)
        )
        await db.commit()

    return {"ok": True, "ticker": asset["ticker"], "shares": req.shares, "price": price, "total_cost": total_cost}


@router.post("/market/sell")
async def sell_shares(
    req: SellRequest,
    player=Depends(get_current_player),
    db=Depends(get_db)
):
    pg = is_postgres()
    if pg:
        asset = await db.fetchrow("SELECT * FROM vault_assets WHERE ticker=$1", req.ticker.upper())
    else:
        cursor = await db.execute("SELECT * FROM vault_assets WHERE ticker=?", (req.ticker.upper(),))
        asset = await cursor.fetchone()
    if not asset:
        raise HTTPException(404, "Asset not found.")

    asset_id = asset["id"]
    if pg:
        holding = await db.fetchrow(
            "SELECT shares, avg_cost FROM vault_holdings WHERE player_id=$1 AND asset_id=$2",
            player["id"], asset_id
        )
    else:
        cursor = await db.execute(
            "SELECT shares, avg_cost FROM vault_holdings WHERE player_id=? AND asset_id=?",
            (player["id"], asset_id)
        )
        holding = await cursor.fetchone()

    if not holding or float(holding["shares"]) < req.shares:
        held = float(holding["shares"]) if holding else 0
        raise HTTPException(400, f"Insufficient shares. You hold {held:.4f} {asset['ticker']}.")

    price = float(asset["current_price"])
    total_proceeds = round(price * req.shares, 2)
    now = _now()

    new_shares = float(holding["shares"]) - req.shares
    if pg:
        if new_shares <= 0:
            await db.execute(
                "DELETE FROM vault_holdings WHERE player_id=$1 AND asset_id=$2",
                player["id"], asset_id
            )
        else:
            await db.execute(
                "UPDATE vault_holdings SET shares=$1 WHERE player_id=$2 AND asset_id=$3",
                new_shares, player["id"], asset_id
            )
        await db.execute(
            """INSERT INTO vault_orders (player_id, asset_id, order_type, shares, price_at_order, total_value, created_at)
               VALUES ($1,$2,'sell',$3,$4,$5,$6)""",
            player["id"], asset_id, req.shares, price, total_proceeds, now
        )
    else:
        if new_shares <= 0:
            await db.execute(
                "DELETE FROM vault_holdings WHERE player_id=? AND asset_id=?",
                (player["id"], asset_id)
            )
        else:
            await db.execute(
                "UPDATE vault_holdings SET shares=? WHERE player_id=? AND asset_id=?",
                (new_shares, player["id"], asset_id)
            )
        await db.execute(
            """INSERT INTO vault_orders (player_id, asset_id, order_type, shares, price_at_order, total_value, created_at)
               VALUES (?,?,'sell',?,?,?,?)""",
            (player["id"], asset_id, req.shares, price, total_proceeds, now)
        )

    await _credit_wallet(db, player["id"], total_proceeds, "investment_sell", f"Sold {req.shares:.4f} {asset['ticker']}", pg)
    if not pg:
        await db.commit()

    gain_loss = round((price - float(holding["avg_cost"])) * req.shares, 2)
    return {"ok": True, "ticker": asset["ticker"], "shares": req.shares, "price": price, "proceeds": total_proceeds, "gain_loss": gain_loss}


@router.get("/portfolio")
async def get_portfolio(
    player=Depends(get_current_player),
    db=Depends(get_db)
):
    pg = is_postgres()
    if pg:
        rows = await db.fetch("""
            SELECT vh.shares, vh.avg_cost, va.id, va.ticker, va.name, va.sector,
                   va.current_price, va.prev_price
            FROM vault_holdings vh
            JOIN vault_assets va ON va.id = vh.asset_id
            WHERE vh.player_id=$1 AND vh.shares > 0
            ORDER BY va.ticker ASC
        """, player["id"])
    else:
        cursor = await db.execute("""
            SELECT vh.shares, vh.avg_cost, va.id, va.ticker, va.name, va.sector,
                   va.current_price, va.prev_price
            FROM vault_holdings vh
            JOIN vault_assets va ON va.id = vh.asset_id
            WHERE vh.player_id=? AND vh.shares > 0
            ORDER BY va.ticker ASC
        """, (player["id"],))
        rows = await cursor.fetchall()

    holdings = []
    total_value = 0.0
    total_cost_basis = 0.0
    for r in rows:
        shares = float(r["shares"])
        avg_cost = float(r["avg_cost"])
        current = float(r["current_price"])
        market_value = shares * current
        cost_basis = shares * avg_cost
        gain_loss = market_value - cost_basis
        gain_loss_pct = (gain_loss / cost_basis * 100) if cost_basis else 0
        total_value += market_value
        total_cost_basis += cost_basis
        holdings.append({
            "ticker": r["ticker"],
            "name": r["name"],
            "sector": r["sector"],
            "shares": round(shares, 4),
            "avg_cost": round(avg_cost, 4),
            "current_price": round(current, 4),
            "market_value": round(market_value, 2),
            "cost_basis": round(cost_basis, 2),
            "gain_loss": round(gain_loss, 2),
            "gain_loss_pct": round(gain_loss_pct, 2),
        })

    total_gain_loss = total_value - total_cost_basis
    return {
        "holdings": holdings,
        "total_market_value": round(total_value, 2),
        "total_cost_basis": round(total_cost_basis, 2),
        "total_gain_loss": round(total_gain_loss, 2),
        "total_gain_loss_pct": round((total_gain_loss / total_cost_basis * 100) if total_cost_basis else 0, 2),
    }


@router.get("/orders")
async def get_orders(
    player=Depends(get_current_player),
    db=Depends(get_db),
    limit: int = 50
):
    pg = is_postgres()
    if pg:
        rows = await db.fetch("""
            SELECT vo.*, va.ticker, va.name
            FROM vault_orders vo
            JOIN vault_assets va ON va.id = vo.asset_id
            WHERE vo.player_id=$1
            ORDER BY vo.created_at DESC LIMIT $2
        """, player["id"], limit)
    else:
        cursor = await db.execute("""
            SELECT vo.*, va.ticker, va.name
            FROM vault_orders vo
            JOIN vault_assets va ON va.id = vo.asset_id
            WHERE vo.player_id=?
            ORDER BY vo.created_at DESC LIMIT ?
        """, (player["id"], limit))
        rows = await cursor.fetchall()

    return {"orders": [dict(r) for r in rows]}


# ── P2P Transfers ─────────────────────────────────────────────────────────────

@router.post("/transfer")
async def send_transfer(
    req: TransferRequest,
    player=Depends(get_current_player),
    db=Depends(get_db)
):
    pg = is_postgres()

    # Resolve recipient
    if pg:
        recipient = await db.fetchrow(
            "SELECT id, display_name FROM players WHERE avatar_uuid=$1 AND is_banned=0",
            req.recipient_uuid
        )
    else:
        cursor = await db.execute(
            "SELECT id, display_name FROM players WHERE avatar_uuid=? AND is_banned=0",
            (req.recipient_uuid,)
        )
        recipient = await cursor.fetchone()

    if not recipient:
        raise HTTPException(404, "Recipient not found or unavailable.")
    if recipient["id"] == player["id"]:
        raise HTTPException(400, "You cannot send Lumens to yourself.")

    wallet_balance = await _get_wallet_balance(db, player["id"], pg)
    if wallet_balance < req.amount:
        raise HTTPException(400, f"Insufficient Lumens. Balance: ✦{wallet_balance:.0f}")

    now = _now()
    desc_sent = f"Sent to {recipient['display_name']}"
    desc_recv = f"Received from {player['display_name']}"
    if req.note:
        desc_sent += f" — {req.note}"
        desc_recv += f" — {req.note}"

    await _debit_wallet(db, player["id"], req.amount, "transfer_out", desc_sent, pg)
    await _credit_wallet(db, recipient["id"], req.amount, "transfer_in", desc_recv, pg)

    if pg:
        await db.execute(
            """INSERT INTO vault_transfers (sender_id, recipient_id, amount, note, created_at)
               VALUES ($1,$2,$3,$4,$5)""",
            player["id"], recipient["id"], req.amount, req.note, now
        )
    else:
        await db.execute(
            """INSERT INTO vault_transfers (sender_id, recipient_id, amount, note, created_at)
               VALUES (?,?,?,?,?)""",
            (player["id"], recipient["id"], req.amount, req.note, now)
        )
        await db.commit()

    # Notify recipient
    note_preview = f" — {req.note}" if req.note else ""
    await push_notification(
        player_id=recipient["id"],
        app_source="vault",
        title=f"✦{req.amount:.0f} received",
        body=f"From {player['display_name']}{note_preview}",
        priority="normal",
        action_url="/apps/vault",
        db=db,
    )

    return {
        "ok": True,
        "sent_to": recipient["display_name"],
        "amount": req.amount,
        "note": req.note,
    }


@router.get("/transfers")
async def get_transfers(
    player=Depends(get_current_player),
    db=Depends(get_db),
    limit: int = 30
):
    pg = is_postgres()
    if pg:
        rows = await db.fetch("""
            SELECT vt.*,
                   sp.display_name AS sender_name,
                   rp.display_name AS recipient_name
            FROM vault_transfers vt
            JOIN players sp ON sp.id = vt.sender_id
            JOIN players rp ON rp.id = vt.recipient_id
            WHERE vt.sender_id=$1 OR vt.recipient_id=$1
            ORDER BY vt.created_at DESC LIMIT $2
        """, player["id"], limit)
    else:
        cursor = await db.execute("""
            SELECT vt.*,
                   sp.display_name AS sender_name,
                   rp.display_name AS recipient_name
            FROM vault_transfers vt
            JOIN players sp ON sp.id = vt.sender_id
            JOIN players rp ON rp.id = vt.recipient_id
            WHERE vt.sender_id=? OR vt.recipient_id=?
            ORDER BY vt.created_at DESC LIMIT ?
        """, (player["id"], player["id"], limit))
        rows = await cursor.fetchall()

    transfers = []
    for r in rows:
        is_outgoing = r["sender_id"] == player["id"]
        transfers.append({
            "id": r["id"],
            "direction": "out" if is_outgoing else "in",
            "other_party": r["recipient_name"] if is_outgoing else r["sender_name"],
            "amount": float(r["amount"]),
            "note": r["note"],
            "created_at": r["created_at"],
        })
    return {"transfers": transfers}


# ── Admin: manual price tick ──────────────────────────────────────────────────

@router.post("/market/refresh")
async def manual_price_refresh(secret: str = ""):
    import os
    admin_secret = os.environ.get("ADMIN_SECRET", "changeme")
    if secret != admin_secret:
        raise HTTPException(403, "Forbidden.")
    await run_price_tick()
    return {"ok": True, "message": "Price tick complete."}
