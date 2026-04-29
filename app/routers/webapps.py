"""
Webapp router — serves HTML pages for all HUD apps.
Each page is a Jinja2 template rendered with live player data.
Auth is token-in-URL: /app/lumen-eats?token=abc123
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime, timezone
import json

from app.database import get_db, is_postgres
from app.config import get_config

router = APIRouter(prefix="/app", tags=["webapps"])

# Templates directory
_here = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(_here / "templates"))


# ── Auth helper ──────────────────────────────────────────────
async def get_player_by_token(token: str, db) -> dict | None:
    """Fetch player by URL token. Returns None if invalid."""
    if not token:
        return None
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


def time_ago(dt_str: str) -> str:
    """Convert a datetime string to a human-readable 'X ago' string."""
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            return f"{seconds // 60}m ago"
        elif seconds < 86400:
            return f"{seconds // 3600}h ago"
        else:
            return f"{seconds // 86400}d ago"
    except Exception:
        return dt_str[:10] if dt_str else "—"


def hunger_zone(value: float) -> str:
    if value >= 50:
        return "ok"
    elif value >= 25:
        return "warn"
    return "crit"


# ── Shop item builder ────────────────────────────────────────
def build_shop_items(cfg: dict, categories: list[str] | None = None) -> list[dict]:
    """Build display-ready shop items from config."""
    items = []
    emoji_map = {
        "water":         ("💧", "Crisp and free. Always.",          "free"),
        "basic_snack":   ("🥨", "Quick bite, light hunger fill.",    "snacks"),
        "basic_meal":    ("🍱", "Simple, filling, affordable.",      "meals"),
        "good_meal":     ("🍝", "A proper meal. Hits the spot.",     "meals"),
        "nice_meal":     ("🍽️", "Restaurant quality. Worth it.",     "meals"),
        "coffee":        ("☕", "The essential. Buzzing vibe.",      "drinks"),
        "juice":         ("🧃", "Fresh pressed. Light thirst fill.", "drinks"),
        "energy_drink":  ("⚡", "Big energy. Use wisely.",          "drinks"),
        "specialty_drink":("🧋","Something special. Fun +5.",       "drinks"),
    }
    vibe_names = {
        "well_fed":   "Well Fed ✨",
        "caffeinated": "Buzzing ☕",
    }
    for key, item_cfg in cfg.get("shop_items", {}).items():
        emoji, desc, cat = emoji_map.get(key, ("🍴", item_cfg.get("display_name", key), "meals"))
        if categories and cat not in categories:
            continue
        hunger = item_cfg.get("need_effects", {}).get("hunger", 0)
        vibe_key = item_cfg.get("vibe_granted")
        items.append({
            "item_key":    key,
            "display_name": item_cfg["display_name"],
            "lumen_cost":  item_cfg["lumen_cost"],
            "emoji":       emoji,
            "description": desc,
            "hunger_gain": hunger,
            "category":    cat,
            "vibe_granted": vibe_key,
            "vibe_name":   vibe_names.get(vibe_key, "") if vibe_key else None,
        })
    return items


# ── LUMEN EATS ───────────────────────────────────────────────
@router.get("/lumen-eats", response_class=HTMLResponse)
async def lumen_eats(
    request: Request,
    token: str = Query(""),
    db=Depends(get_db)
):
    # Auth
    player = await get_player_by_token(token, db)
    if not player:
        return HTMLResponse("<h2 style='font-family:sans-serif;padding:40px;color:#888;'>Invalid or missing token.</h2>", status_code=401)

    player_id = player["id"]
    cfg = get_config()

    # Fetch hunger need
    if is_postgres():
        need_row = await db.fetchrow(
            "SELECT value FROM needs WHERE player_id = $1 AND need_key = 'hunger'", player_id)
        wallet_row = await db.fetchrow(
            "SELECT balance FROM wallets WHERE player_id = $1", player_id)
        log_rows = await db.fetch(
            """SELECT action_text, delta, value_after, timestamp
               FROM event_log
               WHERE player_id = $1 AND need_key = 'hunger'
               ORDER BY timestamp DESC LIMIT 20""", player_id)
        # Weekly specials
        specials_rows = await db.fetch(
            """SELECT * FROM weekly_specials
               WHERE available_until > now()::text
               ORDER BY is_pinned DESC, created_at DESC LIMIT 6""")
    else:
        async with db.execute(
            "SELECT value FROM needs WHERE player_id = ? AND need_key = 'hunger'", (player_id,)
        ) as cur:
            need_row = await cur.fetchone()
        async with db.execute(
            "SELECT balance FROM wallets WHERE player_id = ?", (player_id,)
        ) as cur:
            wallet_row = await cur.fetchone()
        async with db.execute(
            """SELECT action_text, delta, value_after, timestamp
               FROM event_log
               WHERE player_id = ? AND need_key = 'hunger'
               ORDER BY timestamp DESC LIMIT 20""", (player_id,)
        ) as cur:
            log_rows = await cur.fetchall()
        async with db.execute(
            """SELECT * FROM weekly_specials
               WHERE available_until > datetime('now')
               ORDER BY is_pinned DESC, created_at DESC LIMIT 6"""
        ) as cur:
            specials_rows = await cur.fetchall()

    hunger_value = float(need_row["value"]) if need_row else 100.0
    wallet_balance = float(wallet_row["balance"]) if wallet_row else 500.0

    # Format log
    hunger_log = []
    for row in log_rows:
        hunger_log.append({
            "action_text": row["action_text"],
            "delta":       float(row["delta"]),
            "value_after": float(row["value_after"]) if row["value_after"] else None,
            "time_ago":    time_ago(row["timestamp"]),
        })

    # Weekly specials with emoji map
    emoji_map_specials = {
        "basic_snack": "🥨", "basic_meal": "🍱", "good_meal": "🍝",
        "nice_meal": "🍽️", "coffee": "☕", "juice": "🧃",
        "energy_drink": "⚡", "specialty_drink": "🧋",
    }
    weekly_specials = []
    for row in specials_rows:
        item_key = row["item_key"]
        base_cfg = cfg["shop_items"].get(item_key, {})
        weekly_specials.append({
            "item_key":      item_key,
            "display_name":  row["display_name_override"] or base_cfg.get("display_name", item_key),
            "special_price": int(row["special_price"]),
            "was_price":     int(base_cfg.get("lumen_cost", 0)) if row["special_price"] < base_cfg.get("lumen_cost", 0) else None,
            "emoji":         emoji_map_specials.get(item_key, "🍴"),
        })

    # Days left in specials week
    now = datetime.now(timezone.utc)
    days_left = 7 - now.weekday() if now.weekday() <= 6 else 1

    # All base shop items
    shop_items = build_shop_items(cfg)

    # Nearby vendors (placeholder — populated by LSL zone data in future)
    nearby_vendors = []

    return templates.TemplateResponse("apps/lumen_eats.html", {
        "request":        request,
        "token":          token,
        "player":         player,
        "hunger_value":   hunger_value,
        "hunger_zone":    hunger_zone(hunger_value),
        "wallet_balance": wallet_balance,
        "hunger_log":     hunger_log,
        "weekly_specials": weekly_specials,
        "specials_days_left": days_left,
        "shop_items":     shop_items,
        "nearby_vendors": nearby_vendors,
    })
