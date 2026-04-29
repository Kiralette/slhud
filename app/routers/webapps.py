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


# ── VAULT ─────────────────────────────────────────────────────────────────────
@router.get("/vault", response_class=HTMLResponse)
async def vault(
    request: Request,
    token: str = Query(""),
    db=Depends(get_db)
):
    player = await get_player_by_token(token, db)
    if not player:
        return HTMLResponse("<h2 style='font-family:sans-serif;padding:40px;color:#888;'>Invalid or missing token.</h2>", status_code=401)

    player_id = player["id"]
    cfg = get_config()

    if is_postgres():
        wallet_row = await db.fetchrow(
            "SELECT * FROM wallets WHERE player_id = $1", player_id)
        tx_rows = await db.fetch(
            """SELECT amount, type, description, timestamp
               FROM transactions WHERE player_id = $1
               ORDER BY timestamp DESC LIMIT 60""", player_id)
        weekly = await db.fetchrow(
            """SELECT
                 COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS earned,
                 COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0) AS spent
               FROM transactions
               WHERE player_id = $1
                 AND timestamp >= (now() - interval '7 days')::text""",
            player_id)
    else:
        async with db.execute(
            "SELECT * FROM wallets WHERE player_id = ?", (player_id,)
        ) as cur:
            wallet_row = await cur.fetchone()
        async with db.execute(
            """SELECT amount, type, description, timestamp
               FROM transactions WHERE player_id = ?
               ORDER BY timestamp DESC LIMIT 60""", (player_id,)
        ) as cur:
            tx_rows = await cur.fetchall()
        async with db.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS earned,
                 COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0) AS spent
               FROM transactions
               WHERE player_id = ?
                 AND timestamp >= datetime('now', '-7 days')""",
            (player_id,)
        ) as cur:
            weekly = await cur.fetchone()

    wallet = {
        "balance":       float(wallet_row["balance"]) if wallet_row else 500.0,
        "total_earned":  float(wallet_row["total_earned"]) if wallet_row else 0.0,
        "total_spent":   float(wallet_row["total_spent"]) if wallet_row else 0.0,
        "weekly_earned": float(weekly["earned"]) if weekly else 0.0,
        "weekly_spent":  float(weekly["spent"]) if weekly else 0.0,
    }

    transactions = [
        {
            "amount":      float(r["amount"]),
            "type":        r["type"],
            "description": r["description"],
            "time_ago":    time_ago(r["timestamp"]),
        }
        for r in tx_rows
    ]

    topup_tiers = cfg.get("economy", {}).get("lumen_topup_rates", [])

    return templates.TemplateResponse("apps/vault.html", {
        "request":      request,
        "token":        token,
        "player":       player,
        "wallet":       wallet,
        "transactions": transactions,
        "topup_tiers":  topup_tiers,
    })


# ── SIP ───────────────────────────────────────────────────────────────────────
@router.get("/sip", response_class=HTMLResponse)
async def sip(
    request: Request,
    token: str = Query(""),
    db=Depends(get_db)
):
    player = await get_player_by_token(token, db)
    if not player:
        return HTMLResponse("<h2 style='font-family:sans-serif;padding:40px;color:#888;'>Invalid or missing token.</h2>", status_code=401)

    player_id = player["id"]
    cfg = get_config()

    if is_postgres():
        need_row = await db.fetchrow(
            "SELECT value FROM needs WHERE player_id = $1 AND need_key = 'thirst'", player_id)
        wallet_row = await db.fetchrow(
            "SELECT balance FROM wallets WHERE player_id = $1", player_id)
        log_rows = await db.fetch(
            """SELECT action_text, delta, value_after, timestamp
               FROM event_log
               WHERE player_id = $1 AND need_key = 'thirst'
               ORDER BY timestamp DESC LIMIT 20""", player_id)
    else:
        async with db.execute(
            "SELECT value FROM needs WHERE player_id = ? AND need_key = 'thirst'", (player_id,)
        ) as cur:
            need_row = await cur.fetchone()
        async with db.execute(
            "SELECT balance FROM wallets WHERE player_id = ?", (player_id,)
        ) as cur:
            wallet_row = await cur.fetchone()
        async with db.execute(
            """SELECT action_text, delta, value_after, timestamp
               FROM event_log
               WHERE player_id = ? AND need_key = 'thirst'
               ORDER BY timestamp DESC LIMIT 20""", (player_id,)
        ) as cur:
            log_rows = await cur.fetchall()

    thirst_value = float(need_row["value"]) if need_row else 100.0
    wallet_balance = float(wallet_row["balance"]) if wallet_row else 500.0

    # Zone calculation for thirst
    def thirst_zone(v):
        if v >= 50: return "ok"
        elif v >= 25: return "warn"
        return "crit"

    # All drink shop items
    drink_items = build_shop_items(cfg, categories=["drinks_free", "drinks_paid"])

    thirst_log = [
        {
            "action_text": row["action_text"],
            "delta":       float(row["delta"]),
            "value_after": float(row["value_after"]) if row["value_after"] else None,
            "time_ago":    time_ago(row["timestamp"]),
        }
        for row in log_rows
    ]

    return templates.TemplateResponse("apps/sip.html", {
        "request":        request,
        "token":          token,
        "player":         player,
        "thirst_value":   thirst_value,
        "thirst_zone":    thirst_zone(thirst_value),
        "wallet_balance": wallet_balance,
        "drink_items":    drink_items,
        "thirst_log":     thirst_log,
    })


# ── GRIND ─────────────────────────────────────────────────────────────────────
@router.get("/grind", response_class=HTMLResponse)
async def grind(
    request: Request,
    token: str = Query(""),
    db=Depends(get_db)
):
    player = await get_player_by_token(token, db)
    if not player:
        return HTMLResponse("<h2 style='font-family:sans-serif;padding:40px;color:#888;'>Invalid or missing token.</h2>", status_code=401)

    player_id = player["id"]
    cfg = get_config()

    # Employment row
    if is_postgres():
        emp_row = await db.fetchrow(
            "SELECT * FROM employment WHERE player_id = $1", player_id)
        wallet_row = await db.fetchrow(
            "SELECT balance FROM wallets WHERE player_id = $1", player_id)
        history_rows = await db.fetch(
            """SELECT career_path_key, tier_level, job_title, started_at, ended_at, total_earned
               FROM career_history WHERE player_id = $1
               ORDER BY started_at DESC LIMIT 15""", player_id)
        odd_rows = await db.fetch(
            """SELECT odd_job_key, completed_at, amount_earned
               FROM odd_job_log WHERE player_id = $1
               ORDER BY completed_at DESC LIMIT 10""", player_id)
    else:
        async with db.execute(
            "SELECT * FROM employment WHERE player_id = ?", (player_id,)
        ) as cur:
            emp_row = await cur.fetchone()
        async with db.execute(
            "SELECT balance FROM wallets WHERE player_id = ?", (player_id,)
        ) as cur:
            wallet_row = await cur.fetchone()
        async with db.execute(
            """SELECT career_path_key, tier_level, job_title, started_at, ended_at, total_earned
               FROM career_history WHERE player_id = ?
               ORDER BY started_at DESC LIMIT 15""", (player_id,)
        ) as cur:
            history_rows = await cur.fetchall()
        async with db.execute(
            """SELECT odd_job_key, completed_at, amount_earned
               FROM odd_job_log WHERE player_id = ?
               ORDER BY completed_at DESC LIMIT 10""", (player_id,)
        ) as cur:
            odd_rows = await cur.fetchall()

    wallet_balance = float(wallet_row["balance"]) if wallet_row else 500.0
    emp = dict(emp_row) if emp_row else None

    # Build employment context
    employment = None
    promotion_ready = False
    promotion_missing = []
    next_tier_info = None
    shift_seconds = None

    if emp and emp.get("career_path_key"):
        path_key  = emp["career_path_key"]
        tier      = int(emp["tier_level"])
        path_cfg  = cfg.get("careers", {}).get("paths", {}).get(path_key, {})
        tier_cfg  = path_cfg.get("tiers", {}).get(tier, {})
        next_tier_cfg = path_cfg.get("tiers", {}).get(tier + 1)

        # Shift timer
        if emp.get("is_clocked_in") and emp.get("clocked_in_at"):
            try:
                start = datetime.fromisoformat(str(emp["clocked_in_at"]).replace("Z", "+00:00"))
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                shift_seconds = int((datetime.now(timezone.utc) - start).total_seconds())
            except Exception:
                shift_seconds = 0

        # Skill check for promotion
        if next_tier_cfg:
            if is_postgres():
                skill_rows = await db.fetch(
                    "SELECT skill_key, level FROM skills WHERE player_id = $1", player_id)
            else:
                async with db.execute(
                    "SELECT skill_key, level FROM skills WHERE player_id = ?", (player_id,)
                ) as cur:
                    skill_rows = await cur.fetchall()
            player_skills = {r["skill_key"]: int(r["level"]) for r in skill_rows}

            skill_reqs = next_tier_cfg.get("skill_req") or {}
            days_req   = next_tier_cfg.get("days_required") or 0
            days_ok    = int(emp["days_at_tier"]) >= days_req
            skills_ok  = all(player_skills.get(k, 0) >= v for k, v in skill_reqs.items())
            promotion_ready = days_ok and skills_ok

            if not skills_ok:
                for k, v in skill_reqs.items():
                    if player_skills.get(k, 0) < v:
                        promotion_missing.append(f"{k.title()} Lv.{v}")

            next_tier_info = {
                "title":         next_tier_cfg.get("title"),
                "daily_pay":     next_tier_cfg.get("daily_pay"),
                "days_required": days_req,
            }

        employment = {
            "career_path_key":  path_key,
            "career_name":      path_cfg.get("display_name", path_key),
            "career_icon":      path_cfg.get("icon", "💼"),
            "is_grey_area":     bool(path_cfg.get("is_grey_area", False)),
            "tier_level":       tier,
            "job_title":        emp["job_title"],
            "daily_pay":        tier_cfg.get("daily_pay", 0),
            "is_clocked_in":    bool(emp["is_clocked_in"]),
            "shift_seconds":    shift_seconds,
            "hours_today":      float(emp["hours_today"]),
            "days_at_tier":     int(emp["days_at_tier"]),
            "total_days_worked":int(emp["total_days_worked"]),
            "shift_max_hours":  float(cfg["careers"]["shift_max_hours"]),
        }

    # Odd job slots
    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%d") + " 00:00:00"
    if is_postgres():
        odd_today_row = await db.fetchrow(
            """SELECT COUNT(*) as cnt FROM odd_job_log
               WHERE player_id = $1 AND completed_at >= $2""",
            player_id, today_start)
    else:
        async with db.execute(
            """SELECT COUNT(*) as cnt FROM odd_job_log
               WHERE player_id = ? AND completed_at >= ?""",
            (player_id, today_start)
        ) as cur:
            odd_today_row = await cur.fetchone()

    odd_jobs_used = int(odd_today_row["cnt"]) if odd_today_row else 0
    odd_jobs_limit = int(cfg["economy"]["odd_jobs"]["daily_limit"])
    odd_jobs_remaining = max(0, odd_jobs_limit - odd_jobs_used)

    # All career paths for Apply section
    all_paths = []
    for pk, pc in cfg.get("careers", {}).get("paths", {}).items():
        tier1 = pc.get("tiers", {}).get(1, {})
        all_paths.append({
            "key":         pk,
            "name":        pc.get("display_name", pk),
            "icon":        pc.get("icon", "💼"),
            "is_grey_area": bool(pc.get("is_grey_area", False)),
            "entry_title": tier1.get("title", "—"),
            "entry_pay":   tier1.get("daily_pay", 0),
            "skill_req":   tier1.get("skill_req"),
        })

    # Odd jobs config
    odd_jobs_available = [
        {
            "key":         k,
            "display_name": v.get("display_name", k),
            "pay":         v.get("pay", 0),
            "min_duration_minutes": v.get("min_duration_minutes", 15),
            "how":         v.get("how", ""),
        }
        for k, v in cfg["economy"]["odd_jobs"]["jobs"].items()
    ]

    # Format history
    paths_cfg_map = cfg.get("careers", {}).get("paths", {})
    career_history = []
    for r in history_rows:
        pk = r["career_path_key"]
        pi = paths_cfg_map.get(pk, {})
        career_history.append({
            "career_name":  pi.get("display_name", pk),
            "career_icon":  pi.get("icon", "💼"),
            "job_title":    r["job_title"],
            "tier_level":   int(r["tier_level"]),
            "started_at":   time_ago(r["started_at"]),
            "ended_at":     time_ago(r["ended_at"]) if r["ended_at"] else "Current",
            "total_earned": float(r["total_earned"]),
        })

    odd_job_cfg_map = cfg["economy"]["odd_jobs"]["jobs"]
    odd_history = []
    for r in odd_rows:
        jk = r["odd_job_key"]
        jcfg = odd_job_cfg_map.get(jk, {})
        odd_history.append({
            "display_name":  jcfg.get("display_name", jk),
            "amount_earned": float(r["amount_earned"]),
            "completed_at":  time_ago(r["completed_at"]),
        })

    return templates.TemplateResponse("apps/grind.html", {
        "request":             request,
        "token":               token,
        "player":              player,
        "wallet_balance":      wallet_balance,
        "employment":          employment,
        "promotion_ready":     promotion_ready,
        "promotion_missing":   promotion_missing,
        "next_tier_info":      next_tier_info,
        "odd_jobs_remaining":  odd_jobs_remaining,
        "odd_jobs_used":       odd_jobs_used,
        "odd_jobs_limit":      odd_jobs_limit,
        "odd_jobs_available":  odd_jobs_available,
        "all_paths":           all_paths,
        "career_history":      career_history,
        "odd_history":         odd_history,
        "shift_max_hours":     float(cfg["careers"]["shift_max_hours"]),
    })



# ── FLARE ─────────────────────────────────────────────────────────────────────
@router.get("/flare", response_class=HTMLResponse)
async def flare(
    request: Request,
    token: str = Query(""),
    db=Depends(get_db)
):
    player = await get_player_by_token(token, db)
    if not player:
        return HTMLResponse("<h2 style='font-family:sans-serif;padding:40px;color:#888;'>Invalid or missing token.</h2>", status_code=401)

    player_id = player["id"]
    cfg = get_config()

    # Wallet
    if is_postgres():
        wallet_row = await db.fetchrow("SELECT balance FROM wallets WHERE player_id = $1", player_id)
        stats_row  = await db.fetchrow("SELECT * FROM flare_stats WHERE player_id = $1", player_id)
        following_count = await db.fetchval("SELECT COUNT(*) FROM follows WHERE follower_id = $1", player_id)
        feed_rows  = await db.fetch(
            """SELECT p.*, pl.display_name FROM posts p
               JOIN players pl ON pl.id = p.player_id
               WHERE p.player_id IN (SELECT following_id FROM follows WHERE follower_id = $1)
                  OR p.player_id = $1
               ORDER BY p.created_at DESC LIMIT 40""", player_id)
        discover_rows = await db.fetch(
            """SELECT p.*, pl.display_name FROM posts p
               JOIN players pl ON pl.id = p.player_id
               ORDER BY p.quality_tier DESC, p.created_at DESC LIMIT 30""")
        profile_posts_rows = await db.fetch(
            """SELECT p.*, pl.display_name FROM posts p
               JOIN players pl ON pl.id = p.player_id
               WHERE p.player_id = $1
               ORDER BY p.created_at DESC LIMIT 20""", player_id)
    else:
        async with db.execute("SELECT balance FROM wallets WHERE player_id = ?", (player_id,)) as cur:
            wallet_row = await cur.fetchone()
        async with db.execute("SELECT * FROM flare_stats WHERE player_id = ?", (player_id,)) as cur:
            stats_row = await cur.fetchone()
        async with db.execute("SELECT COUNT(*) as cnt FROM follows WHERE follower_id = ?", (player_id,)) as cur:
            fc = await cur.fetchone()
        following_count = fc["cnt"] if fc else 0
        async with db.execute(
            """SELECT p.*, pl.display_name FROM posts p
               JOIN players pl ON pl.id = p.player_id
               WHERE p.player_id IN (SELECT following_id FROM follows WHERE follower_id = ?)
                  OR p.player_id = ?
               ORDER BY p.created_at DESC LIMIT 40""", (player_id, player_id)) as cur:
            feed_rows = await cur.fetchall()
        async with db.execute(
            """SELECT p.*, pl.display_name FROM posts p
               JOIN players pl ON pl.id = p.player_id
               ORDER BY p.quality_tier DESC, p.created_at DESC LIMIT 30""") as cur:
            discover_rows = await cur.fetchall()
        async with db.execute(
            """SELECT p.*, pl.display_name FROM posts p
               JOIN players pl ON pl.id = p.player_id
               WHERE p.player_id = ?
               ORDER BY p.created_at DESC LIMIT 20""", (player_id,)) as cur:
            profile_posts_rows = await cur.fetchall()

    def fmt_post(row):
        d = dict(row)
        d["content_text"] = d.get("content_text", "")
        return d

    wallet_balance = float(wallet_row["balance"]) if wallet_row else 500.0
    fs = dict(stats_row) if stats_row else {}
    flare_stats = {
        "follower_count":  fs.get("follower_count", 0),
        "following_count": following_count,
        "weekly_posts":    fs.get("weekly_post_count", 0),
        "post_streak":     fs.get("post_streak_days", 0),
        "active_deal":     fs.get("active_brand_deal_key"),
    }

    categories = cfg.get("flare", {}).get("categories", ["life"])

    return templates.TemplateResponse("apps/flare.html", {
        "request":       request,
        "token":         token,
        "player":        player,
        "wallet_balance": wallet_balance,
        "feed":          [fmt_post(r) for r in feed_rows],
        "discover":      [fmt_post(r) for r in discover_rows],
        "profile_posts": [fmt_post(r) for r in profile_posts_rows],
        "flare_stats":   flare_stats,
        "categories":    categories,
    })


# ── PING ──────────────────────────────────────────────────────────────────────
@router.get("/ping", response_class=HTMLResponse)
async def ping(
    request: Request,
    token: str = Query(""),
    db=Depends(get_db)
):
    player = await get_player_by_token(token, db)
    if not player:
        return HTMLResponse("<h2 style='font-family:sans-serif;padding:40px;color:#888;'>Invalid or missing token.</h2>", status_code=401)

    player_id = player["id"]

    if is_postgres():
        thread_rows = await db.fetch(
            """SELECT
                 mt.id,
                 mt.last_message_at,
                 CASE WHEN mt.player_a_id = $1 THEN mt.unread_count_a ELSE mt.unread_count_b END AS unread_count,
                 CASE WHEN mt.player_a_id = $1 THEN pb.display_name ELSE pa.display_name END AS other_name,
                 CASE WHEN mt.player_a_id = $1 THEN pb.avatar_uuid  ELSE pa.avatar_uuid  END AS other_uuid
               FROM message_threads mt
               JOIN players pa ON pa.id = mt.player_a_id
               JOIN players pb ON pb.id = mt.player_b_id
               WHERE mt.player_a_id = $1 OR mt.player_b_id = $1
               ORDER BY mt.last_message_at DESC NULLS LAST""",
            player_id)
    else:
        async with db.execute(
            """SELECT
                 mt.id,
                 mt.last_message_at,
                 CASE WHEN mt.player_a_id = ? THEN mt.unread_count_a ELSE mt.unread_count_b END AS unread_count,
                 CASE WHEN mt.player_a_id = ? THEN pb.display_name ELSE pa.display_name END AS other_name,
                 CASE WHEN mt.player_a_id = ? THEN pb.avatar_uuid  ELSE pa.avatar_uuid  END AS other_uuid
               FROM message_threads mt
               JOIN players pa ON pa.id = mt.player_a_id
               JOIN players pb ON pb.id = mt.player_b_id
               WHERE mt.player_a_id = ? OR mt.player_b_id = ?
               ORDER BY mt.last_message_at DESC""",
            (player_id, player_id, player_id, player_id, player_id)
        ) as cur:
            thread_rows = await cur.fetchall()

    threads = [dict(r) for r in thread_rows]
    total_unread = sum(t["unread_count"] for t in threads if t["unread_count"])

    return templates.TemplateResponse("apps/ping.html", {
        "request":      request,
        "token":        token,
        "player":       player,
        "threads":      threads,
        "total_unread": total_unread,
    })


# ── RITUAL ────────────────────────────────────────────────────────────────────
@router.get("/ritual", response_class=HTMLResponse)
async def ritual(
    request: Request,
    token: str = Query(""),
    db=Depends(get_db)
):
    player = await get_player_by_token(token, db)
    if not player:
        return HTMLResponse("<h2 style='font-family:sans-serif;padding:40px;color:#888;'>Invalid or missing token.</h2>", status_code=401)

    player_id = player["id"]
    cfg = get_config()

    from datetime import date, timedelta
    today = date.today()
    current_year  = today.year
    current_month = today.month

    # Month display
    month_names = ['January','February','March','April','May','June',
                   'July','August','September','October','November','December']
    current_month_label = f"{month_names[current_month-1]} {current_year}"

    # Check cycle eligibility
    if is_postgres():
        profile_row = await db.fetchrow(
            "SELECT biology_agab FROM player_profiles WHERE player_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT biology_agab FROM player_profiles WHERE player_id = ?", (player_id,)
        ) as cur:
            profile_row = await cur.fetchone()

    agab = (dict(profile_row)["biology_agab"] if profile_row else "") or ""
    show_cycle_tab = agab.lower() in ("female", "intersex", "")

    # Events for current month
    month_start = f"{current_year:04d}-{current_month:02d}-01"
    next_month  = current_month + 1
    next_year   = current_year
    if next_month > 12:
        next_month = 1
        next_year += 1
    month_end = f"{next_year:04d}-{next_month:02d}-01"

    if is_postgres():
        all_events_rows = await db.fetch(
            """SELECT * FROM calendar_events WHERE player_id = $1
               AND event_date_slt >= $2 AND event_date_slt < $3
               ORDER BY event_date_slt ASC""",
            player_id, month_start, month_end)
        upcoming_rows = await db.fetch(
            """SELECT * FROM calendar_events WHERE player_id = $1
               AND event_date_slt >= $2
               AND event_date_slt <= $3
               ORDER BY event_date_slt ASC""",
            player_id, today.isoformat(), (today + timedelta(days=7)).isoformat())
        community_rows = await db.fetch(
            """SELECT ce.*, p.display_name AS creator_name FROM calendar_events ce
               JOIN players p ON p.id = ce.player_id
               WHERE ce.is_public = 1 AND ce.event_date_slt >= $1
               AND ce.event_date_slt <= $2
               ORDER BY ce.event_date_slt ASC""",
            today.isoformat(), (today + timedelta(days=30)).isoformat())
    else:
        async with db.execute(
            """SELECT * FROM calendar_events WHERE player_id = ?
               AND event_date_slt >= ? AND event_date_slt < ?
               ORDER BY event_date_slt ASC""",
            (player_id, month_start, month_end)) as cur:
            all_events_rows = await cur.fetchall()
        async with db.execute(
            """SELECT * FROM calendar_events WHERE player_id = ?
               AND event_date_slt >= ? AND event_date_slt <= ?
               ORDER BY event_date_slt ASC""",
            (player_id, today.isoformat(), (today + timedelta(days=7)).isoformat())) as cur:
            upcoming_rows = await cur.fetchall()
        async with db.execute(
            """SELECT ce.*, p.display_name AS creator_name FROM calendar_events ce
               JOIN players p ON p.id = ce.player_id
               WHERE ce.is_public = 1 AND ce.event_date_slt >= ?
               AND ce.event_date_slt <= ?
               ORDER BY ce.event_date_slt ASC""",
            (today.isoformat(), (today + timedelta(days=30)).isoformat())) as cur:
            community_rows = await cur.fetchall()

    # Cycle data
    cycle_history = []
    cycle_prediction = {"has_data": False, "calendar_days": {}}
    if show_cycle_tab:
        if is_postgres():
            ch_rows = await db.fetch(
                "SELECT * FROM cycle_log WHERE player_id = $1 ORDER BY cycle_start_slt DESC LIMIT 24", player_id)
            latest_cycle = await db.fetchrow(
                """SELECT avg_cycle_length, next_predicted_start, period_duration_days
                   FROM cycle_log WHERE player_id = $1 ORDER BY cycle_start_slt DESC LIMIT 1""", player_id)
        else:
            async with db.execute(
                "SELECT * FROM cycle_log WHERE player_id = ? ORDER BY cycle_start_slt DESC LIMIT 24", (player_id,)) as cur:
                ch_rows = await cur.fetchall()
            async with db.execute(
                """SELECT avg_cycle_length, next_predicted_start, period_duration_days
                   FROM cycle_log WHERE player_id = ? ORDER BY cycle_start_slt DESC LIMIT 1""", (player_id,)) as cur:
                latest_cycle = await cur.fetchone()

        cycle_history = [dict(r) for r in ch_rows]

        if latest_cycle and latest_cycle["avg_cycle_length"]:
            from datetime import date, timedelta
            calendar_days = {}
            for c in cycle_history:
                if c.get("cycle_start_slt"):
                    try:
                        s = date.fromisoformat(c["cycle_start_slt"][:10])
                        dur = c.get("period_duration_days") or 5
                        for i in range(dur):
                            calendar_days[(s + timedelta(days=i)).isoformat()] = "confirmed_period"
                        end = date.fromisoformat(c["cycle_end_slt"][:10]) if c.get("cycle_end_slt") else s + timedelta(days=dur)
                        for i in range(1, 4):
                            k = (end + timedelta(days=i)).isoformat()
                            if k not in calendar_days:
                                calendar_days[k] = "post_glow"
                    except Exception:
                        pass
            nxt = latest_cycle["next_predicted_start"]
            if nxt:
                try:
                    ns = date.fromisoformat(nxt[:10])
                    dur = latest_cycle["period_duration_days"] or 5
                    for i in range(-3, dur + 3):
                        k = (ns + timedelta(days=i)).isoformat()
                        if k not in calendar_days:
                            calendar_days[k] = "predicted_start" if 0 <= i < dur else "predicted_window"
                except Exception:
                    pass
            cycle_prediction = {"has_data": True, "avg_cycle_length": latest_cycle["avg_cycle_length"],
                                 "next_predicted_start": nxt, "calendar_days": calendar_days}

    # Holidays for this month as {MM-DD: emoji}
    all_holidays = cfg.get("holidays", {})
    holidays_this_month = {k: v["emoji"] for k, v in all_holidays.items()
                           if k.startswith(f"{current_month:02d}-")}

    return templates.TemplateResponse("apps/ritual.html", {
        "request":              request,
        "token":                token,
        "player":               player,
        "today":                today.isoformat(),
        "current_year":         current_year,
        "current_month":        current_month,
        "current_month_label":  current_month_label,
        "all_events":           [dict(r) for r in all_events_rows],
        "upcoming":             [dict(r) for r in upcoming_rows],
        "community":            [dict(r) for r in community_rows],
        "show_cycle_tab":       show_cycle_tab,
        "cycle_history":        cycle_history,
        "cycle_prediction":     cycle_prediction,
        "cycle_calendar_days":  cycle_prediction.get("calendar_days", {}),
        "holidays_this_month":  holidays_this_month,
    })


# ── QUESTIONNAIRE ─────────────────────────────────────────────────────────────
@router.get("/questionnaire", response_class=HTMLResponse)
async def questionnaire_app(
    request: Request,
    token: str = Query(""),
    db=Depends(get_db)
):
    player = await get_player_by_token(token, db)
    if not player:
        return HTMLResponse("<h2 style='font-family:sans-serif;padding:40px;color:#888;'>Invalid or missing token.</h2>", status_code=401)

    cfg = get_config()
    trait_defs = cfg.get("traits", {}).get("definitions", {})

    # Build trait list for the Build path
    traits = []
    for key, tdef in trait_defs.items():
        traits.append({
            "key":         key,
            "display":     tdef.get("display", key),
            "is_negative": tdef.get("is_negative", False),
            "category":    tdef.get("category", ""),
        })

    return templates.TemplateResponse("apps/questionnaire.html", {
        "request": request,
        "token":   token,
        "player":  player,
        "traits":  traits,
    })


# ── CANVAS ────────────────────────────────────────────────────────────────────
@router.get("/canvas", response_class=HTMLResponse)
async def canvas(
    request: Request,
    token: str = Query(""),
    db=Depends(get_db)
):
    player = await get_player_by_token(token, db)
    if not player:
        return HTMLResponse("<h2 style='font-family:sans-serif;padding:40px;color:#888;'>Invalid or missing token.</h2>", status_code=401)

    player_id = player["id"]
    cfg = get_config()
    trait_defs = cfg.get("traits", {}).get("definitions", {})

    if is_postgres():
        profile_row   = await db.fetchrow("SELECT * FROM player_profiles WHERE player_id = $1", player_id)
        stats_row     = await db.fetchrow("SELECT * FROM player_stats WHERE player_id = $1", player_id)
        trait_rows    = await db.fetch("SELECT trait_key, applied_at FROM player_traits WHERE player_id = $1", player_id)
        vibe_rows     = await db.fetch("SELECT * FROM vibes WHERE player_id = $1 ORDER BY applied_at DESC", player_id)
        occ_rows      = await db.fetch(
            "SELECT * FROM player_occurrences WHERE player_id = $1 AND is_resolved = 0 ORDER BY started_at DESC", player_id)
        notif_rows    = await db.fetch(
            "SELECT * FROM notifications WHERE player_id = $1 ORDER BY created_at DESC LIMIT 60", player_id)
        wallet_row    = await db.fetchrow("SELECT balance FROM wallets WHERE player_id = $1", player_id)
        settings_row  = await db.fetchrow("SELECT * FROM player_settings WHERE player_id = $1", player_id)
        achieve_rows  = await db.fetch(
            "SELECT * FROM player_achievements WHERE player_id = $1 ORDER BY unlocked_at DESC", player_id)
    else:
        async with db.execute("SELECT * FROM player_profiles WHERE player_id = ?", (player_id,)) as cur:
            profile_row = await cur.fetchone()
        async with db.execute("SELECT * FROM player_stats WHERE player_id = ?", (player_id,)) as cur:
            stats_row = await cur.fetchone()
        async with db.execute("SELECT trait_key, applied_at FROM player_traits WHERE player_id = ?", (player_id,)) as cur:
            trait_rows = await cur.fetchall()
        async with db.execute("SELECT * FROM vibes WHERE player_id = ? ORDER BY applied_at DESC", (player_id,)) as cur:
            vibe_rows = await cur.fetchall()
        async with db.execute(
            "SELECT * FROM player_occurrences WHERE player_id = ? AND is_resolved = 0 ORDER BY started_at DESC", (player_id,)) as cur:
            occ_rows = await cur.fetchall()
        async with db.execute(
            "SELECT * FROM notifications WHERE player_id = ? ORDER BY created_at DESC LIMIT 60", (player_id,)) as cur:
            notif_rows = await cur.fetchall()
        async with db.execute("SELECT balance FROM wallets WHERE player_id = ?", (player_id,)) as cur:
            wallet_row = await cur.fetchone()
        async with db.execute("SELECT * FROM player_settings WHERE player_id = ?", (player_id,)) as cur:
            settings_row = await cur.fetchone()
        async with db.execute(
            "SELECT * FROM player_achievements WHERE player_id = ? ORDER BY unlocked_at DESC", (player_id,)) as cur:
            achieve_rows = await cur.fetchall()

    # Occurrence display names
    from app.routers.occurrences import OCCURRENCE_DISPLAY
    occurrences = []
    for r in occ_rows:
        d = dict(r)
        info = OCCURRENCE_DISPLAY.get(d["occurrence_key"], (d["occurrence_key"], "unknown"))
        d["display_name"] = info[0]
        occurrences.append(d)

    # Trait edit cooldown
    days_until_trait_edit = 0
    if trait_rows:
        from datetime import datetime, timezone
        try:
            last_applied = sorted([r["applied_at"] for r in trait_rows if r["applied_at"]])[-1]
            last_dt = datetime.fromisoformat(last_applied.replace("Z", "+00:00"))
            days_since = (datetime.now(timezone.utc) - last_dt).days
            days_until_trait_edit = max(0, 14 - days_since)
        except Exception:
            pass

    profile  = dict(profile_row)  if profile_row  else {}
    settings = dict(settings_row) if settings_row else {}
    settings["is_mental_health_opted_in"] = bool(profile.get("is_mental_health_opted_in", 0))

    app_icons = {
        "flare": "✦", "ping": "💬", "ritual": "🗓", "grind": "💼",
        "vault": "💰", "canvas": "✦", "aura": "👋", "system": "📡",
        "lumen_eats": "🍽", "sip": "💧", "recharge": "⚡",
        "thrill": "🎉", "glow": "✨", "luminary": "🕯",
    }

    return templates.TemplateResponse("apps/canvas.html", {
        "request":               request,
        "token":                 token,
        "player":                player,
        "profile":               profile,
        "stats":                 dict(stats_row) if stats_row else {},
        "traits":                [r["trait_key"] for r in trait_rows],
        "trait_defs":            {k: {"display": v.get("display", k), "category": v.get("category", "")}
                                  for k, v in trait_defs.items()},
        "vibes":                 [dict(r) for r in vibe_rows],
        "occurrences":           occurrences,
        "mh_opted_in":           bool(profile.get("is_mental_health_opted_in", 0)),
        "notifications":         [dict(r) for r in notif_rows],
        "balance":               float(wallet_row["balance"]) if wallet_row else 0.0,
        "settings":              settings,
        "achievements":          [dict(r) for r in achieve_rows],
        "app_icons":             app_icons,
        "days_until_trait_edit": days_until_trait_edit,
    })
