"""
Admin panel — password-protected web UI served at /admin
Compatible with both SQLite and PostgreSQL.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db, is_postgres
from app.services.needs import apply_vibe
from app.services.economy import rotate_weekly_specials as _rotate_specials
from app.config import get_config

router = APIRouter(prefix="/admin", tags=["admin"])


def check_admin(request: Request):
    cfg = get_config()
    secret = cfg["server"]["admin_secret"]
    provided = request.query_params.get("secret") or request.headers.get("X-Admin-Secret")
    if provided != secret:
        raise HTTPException(status_code=403, detail="Invalid admin secret.")


def admin_style():
    return """
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body { font-family: -apple-system, sans-serif; background: #0f0f0f; color: #e0e0e0; padding: 2rem; }
      h1 { font-size: 1.4rem; font-weight: 600; margin-bottom: 0.25rem; color: #fff; }
      h2 { font-size: 1rem; font-weight: 500; margin: 1.5rem 0 0.75rem; color: #ccc; border-bottom: 1px solid #333; padding-bottom: 0.4rem; }
      .subtitle { font-size: 0.8rem; color: #888; margin-bottom: 1.5rem; }
      table { width: 100%; border-collapse: collapse; font-size: 0.82rem; margin-bottom: 1rem; }
      th { text-align: left; padding: 6px 10px; background: #1a1a1a; color: #aaa; font-weight: 500; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
      td { padding: 7px 10px; border-bottom: 1px solid #1e1e1e; color: #ddd; }
      tr:hover td { background: #161616; }
      .badge { display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 0.7rem; font-weight: 500; }
      .badge-green { background: #1a3a1a; color: #4caf50; }
      .badge-red { background: #3a1a1a; color: #f44336; }
      .badge-yellow { background: #2a2a10; color: #ffeb3b; }
      .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
      .stat { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 0.75rem 1rem; }
      .stat-val { font-size: 1.6rem; font-weight: 600; color: #fff; }
      .stat-lbl { font-size: 0.72rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 2px; }
      form { display: flex; gap: 8px; flex-wrap: wrap; align-items: flex-end; margin-top: 0.5rem; }
      form.inline { display: inline-flex; margin: 0; }
      input, select { background: #111; border: 1px solid #333; color: #e0e0e0; padding: 6px 10px; border-radius: 6px; font-size: 0.82rem; }
      button { background: #7f77dd; color: #fff; border: none; padding: 7px 14px; border-radius: 6px; font-size: 0.82rem; cursor: pointer; font-weight: 500; }
      button:hover { background: #9b94e8; }
      button.btn-red { background: #8b2020; }
      button.btn-red:hover { background: #b02828; }
      button.btn-yellow { background: #7a6a10; }
      button.btn-yellow:hover { background: #9a8610; }
      button.btn-green { background: #1e6b2e; }
      button.btn-green:hover { background: #28883c; }
      button.btn-ghost { background: #2a2a2a; color: #aaa; }
      button.btn-ghost:hover { background: #333; color: #fff; }
      .bar-wrap { background: #2a2a2a; border-radius: 4px; height: 8px; width: 120px; display: inline-block; vertical-align: middle; }
      .bar-fill { height: 100%; border-radius: 4px; }
      a { color: #7f77dd; text-decoration: none; }
      a:hover { text-decoration: underline; }
      .nav { display: flex; gap: 1rem; margin-bottom: 2rem; font-size: 0.85rem; }
      .section-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 0.5rem; }
      .danger-zone { border: 1px solid #3a1a1a; border-radius: 8px; padding: 1rem; margin-top: 1rem; background: #0d0808; }
      .danger-zone h2 { color: #f44336; border-color: #3a1a1a; }
      .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; background: #222; color: #aaa; margin: 2px; }
      .tag-remove { background: #2a1a1a; color: #e57373; cursor: pointer; }
      .confirm-wrap { display: none; }
      .confirm-wrap.show { display: inline-flex; }
    </style>
    """


def bar_html(value: float) -> str:
    pct = max(0, min(100, float(value)))
    color = "#4caf50" if pct > 60 else "#ffeb3b" if pct > 30 else "#f44336"
    return f'<div class="bar-wrap"><div class="bar-fill" style="width:{pct:.0f}%;background:{color};"></div></div> {pct:.1f}'


async def fetch_one(db, pg_query, pg_params, sq_query, sq_params):
    if is_postgres():
        return await db.fetchrow(pg_query, *pg_params)
    else:
        async with db.execute(sq_query, sq_params) as cursor:
            return await cursor.fetchone()


async def fetch_all(db, pg_query, pg_params, sq_query, sq_params):
    if is_postgres():
        return await db.fetch(pg_query, *pg_params)
    else:
        async with db.execute(sq_query, sq_params) as cursor:
            return await cursor.fetchall()


async def fetch_val(db, pg_query, pg_params, sq_query, sq_params):
    if is_postgres():
        return await db.fetchval(pg_query, *pg_params)
    else:
        async with db.execute(sq_query, sq_params) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


# ── HOME ──────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def admin_home(request: Request, db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    cfg = get_config()

    total = await fetch_val(db,
        "SELECT COUNT(*) FROM players WHERE is_banned = 0", [],
        "SELECT COUNT(*) FROM players WHERE is_banned = 0", [])
    online = await fetch_val(db,
        "SELECT COUNT(*) FROM players WHERE is_online = 1 AND is_banned = 0", [],
        "SELECT COUNT(*) FROM players WHERE is_online = 1 AND is_banned = 0", [])
    banned = await fetch_val(db,
        "SELECT COUNT(*) FROM players WHERE is_banned = 1", [],
        "SELECT COUNT(*) FROM players WHERE is_banned = 1", [])
    events = await fetch_val(db,
        "SELECT COUNT(*) FROM event_log", [],
        "SELECT COUNT(*) FROM event_log", [])
    active_vibes = await fetch_val(db,
        "SELECT COUNT(*) FROM vibes WHERE expires_at IS NULL OR expires_at > now()::text", [],
        "SELECT COUNT(*) FROM vibes WHERE expires_at IS NULL OR expires_at > datetime('now')", [])

    players = await fetch_all(db,
        "SELECT * FROM players ORDER BY last_seen DESC", [],
        "SELECT * FROM players ORDER BY last_seen DESC", [])

    players_html = ""
    for p in players:
        pid = p["id"]
        needs = await fetch_all(db,
            "SELECT need_key, value FROM needs WHERE player_id = $1", [pid],
            "SELECT need_key, value FROM needs WHERE player_id = ?", (pid,))

        needs_dict = {n["need_key"]: n["value"] for n in needs}
        if p["is_banned"]:
            status_badge = '<span class="badge badge-red">banned</span>'
        elif p["is_online"]:
            status_badge = '<span class="badge badge-green">online</span>'
        else:
            status_badge = '<span class="badge" style="background:#222;color:#666;">offline</span>'

        need_bars = " ".join([f'<span title="{k}">{bar_html(v)}</span>' for k, v in needs_dict.items()])

        players_html += f"""
        <tr>
          <td>{p['id']}</td>
          <td><a href="/admin/player/{pid}?secret={secret}">{p['display_name']}</a></td>
          <td style="font-size:0.72rem;color:#666;">{p['avatar_uuid'][:16]}...</td>
          <td>{status_badge}</td>
          <td style="font-size:0.75rem;">{need_bars}</td>
          <td style="font-size:0.72rem;color:#666;">{p['last_seen']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html><html><head><title>HUD Admin</title>{admin_style()}</head><body>
    <h1>✨ SL Phone HUD — Admin Panel</h1>
    <div class="subtitle">Decay interval: {cfg['server']['decay_interval_seconds']}s &nbsp;|&nbsp; <a href="/docs">API docs</a></div>
    <div class="grid">
      <div class="stat"><div class="stat-val">{total}</div><div class="stat-lbl">Total players</div></div>
      <div class="stat"><div class="stat-val" style="color:#4caf50;">{online}</div><div class="stat-lbl">Online now</div></div>
      <div class="stat"><div class="stat-val" style="color:#f44336;">{banned}</div><div class="stat-lbl">Banned</div></div>
      <div class="stat"><div class="stat-val">{events}</div><div class="stat-lbl">Total events logged</div></div>
      <div class="stat"><div class="stat-val">{active_vibes}</div><div class="stat-lbl">Active vibes</div></div>
    </div>
    <h2>Actions</h2>
    <div class="section-actions">
      <form method="post" action="/admin/rotate_specials?secret={secret}">
        <button type="submit">🔄 Rotate Weekly Specials Now</button>
      </form>
    </div>
    <h2>Players</h2>
    <table>
      <tr><th>ID</th><th>Name</th><th>UUID</th><th>Status</th><th>Needs</th><th>Last seen</th></tr>
      {players_html}
    </table>
    </body></html>"""
    return HTMLResponse(html)


# ── PLAYER DETAIL ─────────────────────────────────────────────────────────────

@router.get("/player/{player_id}", response_class=HTMLResponse)
async def admin_player(player_id: int, request: Request, db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    cfg = get_config()

    player = await fetch_one(db,
        "SELECT * FROM players WHERE id = $1", [player_id],
        "SELECT * FROM players WHERE id = ?", (player_id,))
    if not player:
        raise HTTPException(status_code=404, detail="Player not found.")

    needs = await fetch_all(db,
        "SELECT * FROM needs WHERE player_id = $1", [player_id],
        "SELECT * FROM needs WHERE player_id = ?", (player_id,))
    skills = await fetch_all(db,
        "SELECT * FROM skills WHERE player_id = $1", [player_id],
        "SELECT * FROM skills WHERE player_id = ?", (player_id,))

    if is_postgres():
        vibes = await db.fetch(
            "SELECT * FROM vibes WHERE player_id = $1 AND (expires_at IS NULL OR expires_at > now()::text)", player_id)
        traits = await db.fetch(
            "SELECT * FROM player_traits WHERE player_id = $1", player_id)
        employment = await db.fetchrow(
            "SELECT * FROM employment WHERE player_id = $1", player_id)
        wallet = await db.fetchrow(
            "SELECT * FROM wallets WHERE player_id = $1", player_id)
        logs = await db.fetch(
            "SELECT * FROM event_log WHERE player_id = $1 ORDER BY timestamp DESC LIMIT 30", player_id)
    else:
        async with db.execute(
            "SELECT * FROM vibes WHERE player_id = ? AND (expires_at IS NULL OR expires_at > datetime('now'))", (player_id,)
        ) as cursor:
            vibes = await cursor.fetchall()
        async with db.execute(
            "SELECT * FROM player_traits WHERE player_id = ?", (player_id,)
        ) as cursor:
            traits = await cursor.fetchall()
        async with db.execute(
            "SELECT * FROM employment WHERE player_id = ?", (player_id,)
        ) as cursor:
            employment = await cursor.fetchone()
        async with db.execute(
            "SELECT * FROM wallets WHERE player_id = ?", (player_id,)
        ) as cursor:
            wallet = await cursor.fetchone()
        async with db.execute(
            "SELECT * FROM event_log WHERE player_id = ? ORDER BY timestamp DESC LIMIT 30", (player_id,)
        ) as cursor:
            logs = await cursor.fetchall()

    # ── Needs table
    needs_rows = "".join([f"""
        <tr>
          <td>{n['need_key']}</td>
          <td>{bar_html(n['value'])}</td>
          <td>
            <form method="post" action="/admin/player/{player_id}/set_need?secret={secret}">
              <input type="hidden" name="need_key" value="{n['need_key']}">
              <input type="number" name="value" value="{float(n['value']):.1f}" min="0" max="100" step="0.1" style="width:70px;">
              <button type="submit">Set</button>
            </form>
          </td>
        </tr>""" for n in needs])

    # ── Skills table
    skills_rows = "".join([f"""
        <tr>
          <td>{s['skill_key']}</td>
          <td>Level {s['level']}</td>
          <td>{float(s['xp']):.1f} XP</td>
          <td>
            <form method="post" action="/admin/player/{player_id}/set_skill?secret={secret}">
              <input type="hidden" name="skill_key" value="{s['skill_key']}">
              <input type="number" name="level" value="{s['level']}" min="0" max="10" step="1" style="width:55px;" placeholder="Lv">
              <input type="number" name="xp" value="{float(s['xp']):.1f}" min="0" step="1" style="width:70px;" placeholder="XP">
              <button type="submit">Set</button>
            </form>
          </td>
        </tr>""" for s in skills])

    # ── Vibes table
    vibe_rows = ""
    for v in vibes:
        vibe_rows += f"""
        <tr>
          <td>{v['vibe_key']}</td>
          <td>{'negative' if v['is_negative'] else 'positive'}</td>
          <td>{v['expires_at'] or 'permanent'}</td>
          <td>
            <form class="inline" method="post" action="/admin/player/{player_id}/remove_vibe?secret={secret}">
              <input type="hidden" name="vibe_key" value="{v['vibe_key']}">
              <button type="submit" class="btn-red" style="padding:4px 10px;font-size:0.75rem;">Remove</button>
            </form>
          </td>
        </tr>"""
    if not vibe_rows:
        vibe_rows = "<tr><td colspan='4' style='color:#666;'>No active vibes</td></tr>"

    # ── Traits tags
    trait_defs = cfg.get("traits", {}).get("definitions", {})
    active_trait_keys = {t["trait_key"] for t in traits}
    trait_tags = ""
    for tk in active_trait_keys:
        display = trait_defs.get(tk, {}).get("display", tk)
        trait_tags += f"""
        <span class="tag tag-remove" title="Click to remove">
          {display}
          <form class="inline" method="post" action="/admin/player/{player_id}/remove_trait?secret={secret}" style="display:inline;">
            <input type="hidden" name="trait_key" value="{tk}">
            <button type="submit" style="background:none;border:none;color:#e57373;cursor:pointer;padding:0 0 0 4px;font-size:0.75rem;">✕</button>
          </form>
        </span>"""
    if not trait_tags:
        trait_tags = "<span style='color:#666;font-size:0.82rem;'>No traits assigned</span>"

    # ── Add trait dropdown (only traits not already active)
    available_traits = [(k, v.get("display", k)) for k, v in trait_defs.items() if k not in active_trait_keys]
    trait_options = "".join([f'<option value="{k}">{display}</option>' for k, display in sorted(available_traits, key=lambda x: x[1])])

    # ── Vibe dropdown
    vibe_keys = cfg.get("vibes", {}).keys()
    vibe_options = "".join([f'<option value="{k}">{k}</option>' for k in vibe_keys])

    # ── Employment info
    emp_html = ""
    if employment and employment["career_path_key"]:
        careers_cfg = cfg.get("careers", {}).get("paths", {})
        path_cfg = careers_cfg.get(employment["career_path_key"], {})
        clocked = "🟢 Clocked in" if employment["is_clocked_in"] else "⚫ Clocked out"
        emp_html = f"""
        <table>
          <tr><th>Career</th><th>Title</th><th>Tier</th><th>Days</th><th>Shift status</th><th>Actions</th></tr>
          <tr>
            <td>{path_cfg.get('display_name', employment['career_path_key'])}</td>
            <td>{employment['job_title']}</td>
            <td>{employment['tier_level']}</td>
            <td>{employment['total_days_worked']}</td>
            <td>{clocked}</td>
            <td>
              <form class="inline" method="post" action="/admin/player/{player_id}/fire?secret={secret}">
                <button type="submit" class="btn-red" style="padding:4px 10px;font-size:0.75rem;">Fire</button>
              </form>
            </td>
          </tr>
        </table>"""
    else:
        # Hire form
        all_paths = cfg.get("careers", {}).get("paths", {})
        path_opts = "".join([f'<option value="{k}">{v.get("display_name", k)}</option>' for k, v in all_paths.items()])
        emp_html = f"""
        <p style="color:#666;font-size:0.82rem;margin-bottom:0.75rem;">No active employment.</p>
        <form method="post" action="/admin/player/{player_id}/hire?secret={secret}">
          <select name="career_path_key">{path_opts}</select>
          <button type="submit" class="btn-green">Hire</button>
        </form>"""

    # ── Wallet
    bal = float(wallet["balance"]) if wallet else 0.0
    wallet_html = f"""
    <div style="display:flex;gap:1rem;align-items:center;flex-wrap:wrap;">
      <span style="font-size:1.4rem;font-weight:600;color:#fff;">◈ {bal:.0f}</span>
      <form method="post" action="/admin/player/{player_id}/adjust_wallet?secret={secret}">
        <input type="number" name="amount" placeholder="±amount" style="width:90px;">
        <button type="submit">Adjust</button>
      </form>
    </div>"""

    # ── Event log
    log_rows = "".join([f"""
        <tr>
          <td style='color:#888;font-size:0.75rem;'>{l['timestamp']}</td>
          <td>{l['need_key'] or '—'}</td>
          <td>{l['action_text']}</td>
          <td style='color:{"#4caf50" if (l['delta'] or 0) >= 0 else "#f44336"};'>{'+' if (l['delta'] or 0) >= 0 else ''}{l['delta']}</td>
        </tr>""" for l in logs])

    online_badge = '<span class="badge badge-green">online</span>' if player["is_online"] else '<span class="badge" style="background:#222;color:#666;">offline</span>'
    ban_label = "Unban" if player["is_banned"] else "Ban"
    ban_class = "btn-green" if player["is_banned"] else "btn-red"

    html = f"""<!DOCTYPE html><html><head><title>{player['display_name']} — HUD Admin</title>{admin_style()}</head><body>
    <div class="nav"><a href="/admin?secret={secret}">← Back to all players</a></div>
    <h1>{player['display_name']} {online_badge}</h1>
    <div class="subtitle">{player['avatar_uuid']} &nbsp;|&nbsp; Registered: {player['registered_at']}</div>

    <h2>Wallet</h2>
    {wallet_html}

    <h2>Needs</h2>
    <table><tr><th>Need</th><th>Value</th><th>Override</th></tr>{needs_rows}</table>

    <h2>Vibes</h2>
    <table><tr><th>Vibe</th><th>Type</th><th>Expires</th><th></th></tr>{vibe_rows}</table>
    <form method="post" action="/admin/player/{player_id}/apply_vibe?secret={secret}">
      <select name="vibe_key">{vibe_options}</select>
      <button type="submit">+ Apply Vibe</button>
    </form>

    <h2>Traits</h2>
    <div style="margin-bottom:0.75rem;">{trait_tags}</div>
    <form method="post" action="/admin/player/{player_id}/add_trait?secret={secret}">
      <select name="trait_key">{trait_options}</select>
      <button type="submit">+ Add Trait</button>
    </form>

    <h2>Employment</h2>
    {emp_html}

    <h2>Skills</h2>
    <table><tr><th>Skill</th><th>Level</th><th>XP</th><th>Override</th></tr>{skills_rows}</table>

    <h2>Event log (last 30)</h2>
    <table><tr><th>Time</th><th>Need</th><th>Action</th><th>Delta</th></tr>{log_rows}</table>

    <div class="danger-zone">
      <h2>⚠ Danger Zone</h2>
      <div class="section-actions" style="margin-top:0.75rem;">
        <form method="post" action="/admin/player/{player_id}/toggle_ban?secret={secret}">
          <button type="submit" class="{ban_class}">{ban_label} Player</button>
        </form>
        <form method="post" action="/admin/player/{player_id}/reset_data?secret={secret}"
              onsubmit="return confirm('Reset ALL data for {player['display_name']}? This cannot be undone.');">
          <button type="submit" class="btn-yellow">Reset Data</button>
        </form>
        <form method="post" action="/admin/player/{player_id}/delete?secret={secret}"
              onsubmit="return confirm('PERMANENTLY DELETE {player['display_name']}? This cannot be undone.');">
          <button type="submit" class="btn-red">Delete Player</button>
        </form>
      </div>
    </div>

    </body></html>"""
    return HTMLResponse(html)


# ── NEEDS ─────────────────────────────────────────────────────────────────────

@router.post("/player/{player_id}/set_need")
async def set_need(player_id: int, request: Request, need_key: str = Form(...), value: float = Form(...), db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    value = max(0.0, min(100.0, value))
    if is_postgres():
        await db.execute("UPDATE needs SET value = $1, last_updated = now()::text WHERE player_id = $2 AND need_key = $3", value, player_id, need_key)
        await db.execute("INSERT INTO event_log (player_id, need_key, action_text, delta, value_after) VALUES ($1, $2, $3, 0, $4)",
            player_id, need_key, f"Admin override: {need_key} set to {value}", value)
    else:
        await db.execute("UPDATE needs SET value = ?, last_updated = datetime('now') WHERE player_id = ? AND need_key = ?", (value, player_id, need_key))
        await db.execute("INSERT INTO event_log (player_id, need_key, action_text, delta, value_after) VALUES (?, ?, ?, 0, ?)",
            (player_id, need_key, f"Admin override: {need_key} set to {value}", value))
        await db.commit()
    return RedirectResponse(f"/admin/player/{player_id}?secret={secret}", status_code=303)


# ── SKILLS ────────────────────────────────────────────────────────────────────

@router.post("/player/{player_id}/set_skill")
async def set_skill(player_id: int, request: Request, skill_key: str = Form(...), level: int = Form(...), xp: float = Form(...), db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    if is_postgres():
        await db.execute("UPDATE skills SET level = $1, xp = $2 WHERE player_id = $3 AND skill_key = $4", level, xp, player_id, skill_key)
    else:
        await db.execute("UPDATE skills SET level = ?, xp = ? WHERE player_id = ? AND skill_key = ?", (level, xp, player_id, skill_key))
        await db.commit()
    return RedirectResponse(f"/admin/player/{player_id}?secret={secret}", status_code=303)


# ── VIBES ─────────────────────────────────────────────────────────────────────

@router.post("/player/{player_id}/apply_vibe")
async def admin_apply_vibe(player_id: int, request: Request, vibe_key: str = Form(...), db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    await apply_vibe(player_id, vibe_key, db)
    if not is_postgres():
        await db.commit()
    return RedirectResponse(f"/admin/player/{player_id}?secret={secret}", status_code=303)


@router.post("/player/{player_id}/remove_vibe")
async def admin_remove_vibe(player_id: int, request: Request, vibe_key: str = Form(...), db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    if is_postgres():
        await db.execute("DELETE FROM vibes WHERE player_id = $1 AND vibe_key = $2", player_id, vibe_key)
    else:
        await db.execute("DELETE FROM vibes WHERE player_id = ? AND vibe_key = ?", (player_id, vibe_key))
        await db.commit()
    return RedirectResponse(f"/admin/player/{player_id}?secret={secret}", status_code=303)


# ── TRAITS ────────────────────────────────────────────────────────────────────

@router.post("/player/{player_id}/add_trait")
async def admin_add_trait(player_id: int, request: Request, trait_key: str = Form(...), db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    if is_postgres():
        await db.execute(
            "INSERT INTO player_traits (player_id, trait_key, applied_at) VALUES ($1, $2, now()::text) ON CONFLICT DO NOTHING",
            player_id, trait_key)
    else:
        await db.execute(
            "INSERT OR IGNORE INTO player_traits (player_id, trait_key, applied_at) VALUES (?, ?, datetime('now'))",
            (player_id, trait_key))
        await db.commit()
    return RedirectResponse(f"/admin/player/{player_id}?secret={secret}", status_code=303)


@router.post("/player/{player_id}/remove_trait")
async def admin_remove_trait(player_id: int, request: Request, trait_key: str = Form(...), db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    if is_postgres():
        await db.execute("DELETE FROM player_traits WHERE player_id = $1 AND trait_key = $2", player_id, trait_key)
    else:
        await db.execute("DELETE FROM player_traits WHERE player_id = ? AND trait_key = ?", (player_id, trait_key))
        await db.commit()
    return RedirectResponse(f"/admin/player/{player_id}?secret={secret}", status_code=303)


# ── EMPLOYMENT ────────────────────────────────────────────────────────────────

@router.post("/player/{player_id}/hire")
async def admin_hire(player_id: int, request: Request, career_path_key: str = Form(...), db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    cfg = get_config()
    path_cfg = cfg.get("careers", {}).get("paths", {}).get(career_path_key, {})
    tier1 = path_cfg.get("tiers", {}).get(1, {})
    job_title = tier1.get("title", career_path_key)

    if is_postgres():
        await db.execute("""
            INSERT INTO employment (player_id, career_path_key, tier_level, job_title, is_clocked_in, hours_today, days_at_tier, total_days_worked)
            VALUES ($1, $2, 1, $3, 0, 0, 0, 0)
            ON CONFLICT (player_id) DO UPDATE SET
              career_path_key = EXCLUDED.career_path_key,
              tier_level = 1, job_title = EXCLUDED.job_title,
              is_clocked_in = 0, hours_today = 0, days_at_tier = 0
        """, player_id, career_path_key, job_title)
    else:
        await db.execute("""
            INSERT INTO employment (player_id, career_path_key, tier_level, job_title, is_clocked_in, hours_today, days_at_tier, total_days_worked)
            VALUES (?, ?, 1, ?, 0, 0, 0, 0)
            ON CONFLICT (player_id) DO UPDATE SET
              career_path_key = excluded.career_path_key,
              tier_level = 1, job_title = excluded.job_title,
              is_clocked_in = 0, hours_today = 0, days_at_tier = 0
        """, (player_id, career_path_key, job_title))
        await db.commit()
    return RedirectResponse(f"/admin/player/{player_id}?secret={secret}", status_code=303)


@router.post("/player/{player_id}/fire")
async def admin_fire(player_id: int, request: Request, db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    if is_postgres():
        await db.execute("DELETE FROM employment WHERE player_id = $1", player_id)
    else:
        await db.execute("DELETE FROM employment WHERE player_id = ?", (player_id,))
        await db.commit()
    return RedirectResponse(f"/admin/player/{player_id}?secret={secret}", status_code=303)


# ── WALLET ────────────────────────────────────────────────────────────────────

@router.post("/player/{player_id}/adjust_wallet")
async def admin_adjust_wallet(player_id: int, request: Request, amount: float = Form(...), db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    desc = f"Admin adjustment: {'+' if amount >= 0 else ''}{amount:.0f} Lumen"
    if is_postgres():
        await db.execute("UPDATE wallets SET balance = balance + $1 WHERE player_id = $2", amount, player_id)
        await db.execute(
            "INSERT INTO transactions (player_id, amount, type, description) VALUES ($1, $2, 'admin', $3)",
            player_id, amount, desc)
    else:
        await db.execute("UPDATE wallets SET balance = balance + ? WHERE player_id = ?", (amount, player_id))
        await db.execute(
            "INSERT INTO transactions (player_id, amount, type, description) VALUES (?, ?, 'admin', ?)",
            (player_id, amount, desc))
        await db.commit()
    return RedirectResponse(f"/admin/player/{player_id}?secret={secret}", status_code=303)


# ── DANGER ZONE ───────────────────────────────────────────────────────────────

@router.post("/player/{player_id}/toggle_ban")
async def admin_toggle_ban(player_id: int, request: Request, db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    if is_postgres():
        await db.execute(
            "UPDATE players SET is_banned = CASE WHEN is_banned = 1 THEN 0 ELSE 1 END WHERE id = $1", player_id)
    else:
        await db.execute(
            "UPDATE players SET is_banned = CASE WHEN is_banned = 1 THEN 0 ELSE 1 END WHERE id = ?", (player_id,))
        await db.commit()
    return RedirectResponse(f"/admin/player/{player_id}?secret={secret}", status_code=303)


@router.post("/player/{player_id}/reset_data")
async def admin_reset_data(player_id: int, request: Request, db=Depends(get_db)):
    """Reset a player's gameplay data without deleting their account."""
    check_admin(request)
    secret = request.query_params.get("secret", "")

    tables_pg = [
        ("UPDATE needs SET value = 100.0 WHERE player_id = $1", [player_id]),
        ("UPDATE skills SET level = 0, xp = 0 WHERE player_id = $1", [player_id]),
        ("UPDATE wallets SET balance = 500.0, total_earned = 500.0, total_spent = 0 WHERE player_id = $1", [player_id]),
        ("DELETE FROM vibes WHERE player_id = $1", [player_id]),
        ("DELETE FROM player_traits WHERE player_id = $1", [player_id]),
        ("DELETE FROM employment WHERE player_id = $1", [player_id]),
        ("DELETE FROM transactions WHERE player_id = $1", [player_id]),
        ("DELETE FROM event_log WHERE player_id = $1", [player_id]),
        ("INSERT INTO event_log (player_id, need_key, action_text, delta, value_after) VALUES ($1, NULL, 'Admin: player data reset', 0, NULL)", [player_id]),
    ]
    tables_sq = [
        ("UPDATE needs SET value = 100.0 WHERE player_id = ?", (player_id,)),
        ("UPDATE skills SET level = 0, xp = 0 WHERE player_id = ?", (player_id,)),
        ("UPDATE wallets SET balance = 500.0, total_earned = 500.0, total_spent = 0 WHERE player_id = ?", (player_id,)),
        ("DELETE FROM vibes WHERE player_id = ?", (player_id,)),
        ("DELETE FROM player_traits WHERE player_id = ?", (player_id,)),
        ("DELETE FROM employment WHERE player_id = ?", (player_id,)),
        ("DELETE FROM transactions WHERE player_id = ?", (player_id,)),
        ("DELETE FROM event_log WHERE player_id = ?", (player_id,)),
        ("INSERT INTO event_log (player_id, need_key, action_text, delta, value_after) VALUES (?, NULL, 'Admin: player data reset', 0, NULL)", (player_id,)),
    ]

    if is_postgres():
        for q, p in tables_pg:
            await db.execute(q, *p)
    else:
        for q, p in tables_sq:
            await db.execute(q, p)
        await db.commit()

    return RedirectResponse(f"/admin/player/{player_id}?secret={secret}", status_code=303)


@router.post("/player/{player_id}/delete")
async def admin_delete_player(player_id: int, request: Request, db=Depends(get_db)):
    """Permanently delete a player and all their data."""
    check_admin(request)
    secret = request.query_params.get("secret", "")

    child_tables = ["needs", "skills", "vibes", "player_traits", "employment",
                    "wallets", "transactions", "event_log", "notifications",
                    "player_profiles", "player_stats", "player_settings",
                    "player_achievements", "player_traits", "flare_stats",
                    "posts", "follows", "message_threads", "career_history"]

    if is_postgres():
        for table in child_tables:
            try:
                await db.execute(f"DELETE FROM {table} WHERE player_id = $1", player_id)
            except Exception:
                pass
        await db.execute("DELETE FROM players WHERE id = $1", player_id)
    else:
        for table in child_tables:
            try:
                await db.execute(f"DELETE FROM {table} WHERE player_id = ?", (player_id,))
            except Exception:
                pass
        await db.execute("DELETE FROM players WHERE id = ?", (player_id,))
        await db.commit()

    return RedirectResponse(f"/admin?secret={secret}", status_code=303)


# ── SPECIALS ──────────────────────────────────────────────────────────────────

@router.post("/rotate_specials")
async def admin_rotate_specials(request: Request, db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    cfg = get_config()
    shop_items = cfg.get("shop_items", {})
    import random
    from datetime import datetime, timezone, timedelta

    food_categories = {"food_snacks", "food_meals"}
    pool = [
        k for k, v in shop_items.items()
        if v.get("lumen_cost", 0) > 0
        and v.get("category") in food_categories
    ]

    count = random.randint(2, min(2, len(pool))) if pool else 0
    chosen = random.sample(pool, count) if pool else []

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    next_week = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    if is_postgres():
        await db.execute("DELETE FROM weekly_specials WHERE is_pinned = 0")
        for item_key in chosen:
            base_cost = float(shop_items[item_key]["lumen_cost"])
            discount = random.uniform(0.10, 0.30)
            special_price = max(1.0, round(base_cost * (1 - discount)))
            await db.execute(
                """INSERT INTO weekly_specials
                   (item_key, special_price, available_from, available_until, is_pinned, created_at)
                   VALUES ($1, $2, $3, $4, 0, $5)""",
                item_key, special_price, now_str, next_week, now_str)
    else:
        await db.execute("DELETE FROM weekly_specials WHERE is_pinned = 0")
        for item_key in chosen:
            base_cost = float(shop_items[item_key]["lumen_cost"])
            discount = random.uniform(0.10, 0.30)
            special_price = max(1.0, round(base_cost * (1 - discount)))
            await db.execute(
                """INSERT INTO weekly_specials
                   (item_key, special_price, available_from, available_until, is_pinned, created_at)
                   VALUES (?, ?, ?, ?, 0, ?)""",
                (item_key, special_price, now_str, next_week, now_str))
        await db.commit()

    print(f"[admin] Manually rotated specials — {len(chosen)} items: {chosen}")
    return RedirectResponse(f"/admin?secret={secret}", status_code=303)
