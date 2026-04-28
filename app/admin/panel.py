"""
Admin panel — password-protected web UI served at /admin
Compatible with both SQLite and PostgreSQL.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db, is_postgres
from app.services.needs import apply_moodlet
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
      .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
      .stat { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 0.75rem 1rem; }
      .stat-val { font-size: 1.6rem; font-weight: 600; color: #fff; }
      .stat-lbl { font-size: 0.72rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 2px; }
      form { display: flex; gap: 8px; flex-wrap: wrap; align-items: flex-end; margin-top: 0.5rem; }
      input, select { background: #111; border: 1px solid #333; color: #e0e0e0; padding: 6px 10px; border-radius: 6px; font-size: 0.82rem; }
      button { background: #7f77dd; color: #fff; border: none; padding: 7px 14px; border-radius: 6px; font-size: 0.82rem; cursor: pointer; font-weight: 500; }
      button:hover { background: #9b94e8; }
      .bar-wrap { background: #2a2a2a; border-radius: 4px; height: 8px; width: 120px; display: inline-block; vertical-align: middle; }
      .bar-fill { height: 100%; border-radius: 4px; }
      a { color: #7f77dd; text-decoration: none; }
      a:hover { text-decoration: underline; }
      .nav { display: flex; gap: 1rem; margin-bottom: 2rem; font-size: 0.85rem; }
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
    events = await fetch_val(db,
        "SELECT COUNT(*) FROM event_log", [],
        "SELECT COUNT(*) FROM event_log", [])
    active_moodlets = await fetch_val(db,
        "SELECT COUNT(*) FROM moodlets WHERE expires_at IS NULL OR expires_at > now()::text", [],
        "SELECT COUNT(*) FROM moodlets WHERE expires_at IS NULL OR expires_at > datetime('now')", [])

    players = await fetch_all(db,
        "SELECT * FROM players WHERE is_banned = 0 ORDER BY last_seen DESC", [],
        "SELECT * FROM players WHERE is_banned = 0 ORDER BY last_seen DESC", [])

    players_html = ""
    for p in players:
        pid = p["id"]
        needs = await fetch_all(db,
            "SELECT need_key, value FROM needs WHERE player_id = $1", [pid],
            "SELECT need_key, value FROM needs WHERE player_id = ?", (pid,))

        needs_dict = {n["need_key"]: n["value"] for n in needs}
        online_badge = '<span class="badge badge-green">online</span>' if p["is_online"] else '<span class="badge" style="background:#222;color:#666;">offline</span>'
        need_bars = " ".join([f'<span title="{k}">{bar_html(v)}</span>' for k, v in needs_dict.items()])

        players_html += f"""
        <tr>
          <td>{p['id']}</td>
          <td><a href="/admin/player/{pid}?secret={secret}">{p['display_name']}</a></td>
          <td style="font-size:0.72rem;color:#666;">{p['avatar_uuid'][:16]}...</td>
          <td>{online_badge}</td>
          <td style="font-size:0.75rem;">{need_bars}</td>
          <td style="font-size:0.72rem;color:#666;">{p['last_seen']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html><html><head><title>HUD Admin</title>{admin_style()}</head><body>
    <h1>✨ SL Phone HUD — Admin Panel</h1>
    <div class="subtitle">Decay interval: {cfg['server']['decay_interval_seconds']}s &nbsp;|&nbsp; <a href="/docs">API docs</a></div>
    <div class="grid">
      <div class="stat"><div class="stat-val">{total}</div><div class="stat-lbl">Total players</div></div>
      <div class="stat"><div class="stat-val" style="color:#4caf50;">{online}</div><div class="stat-lbl">Online now</div></div>
      <div class="stat"><div class="stat-val">{events}</div><div class="stat-lbl">Total events logged</div></div>
      <div class="stat"><div class="stat-val">{active_moodlets}</div><div class="stat-lbl">Active moodlets</div></div>
    </div>
    <h2>Players</h2>
    <table>
      <tr><th>ID</th><th>Name</th><th>UUID</th><th>Status</th><th>Needs</th><th>Last seen</th></tr>
      {players_html}
    </table>
    </body></html>"""
    return HTMLResponse(html)


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
        moodlets = await db.fetch(
            "SELECT * FROM moodlets WHERE player_id = $1 AND (expires_at IS NULL OR expires_at > now()::text)", player_id)
        logs = await db.fetch(
            "SELECT * FROM event_log WHERE player_id = $1 ORDER BY timestamp DESC LIMIT 30", player_id)
    else:
        async with db.execute(
            "SELECT * FROM moodlets WHERE player_id = ? AND (expires_at IS NULL OR expires_at > datetime('now'))", (player_id,)
        ) as cursor:
            moodlets = await cursor.fetchall()
        async with db.execute(
            "SELECT * FROM event_log WHERE player_id = ? ORDER BY timestamp DESC LIMIT 30", (player_id,)
        ) as cursor:
            logs = await cursor.fetchall()

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

    skills_rows = "".join([f"<tr><td>{s['skill_key']}</td><td>Level {s['level']}</td><td>{float(s['xp']):.1f} XP</td></tr>" for s in skills])
    moodlet_rows = "".join([f"<tr><td>{m['moodlet_key']}</td><td>{'negative' if m['is_negative'] else 'positive'}</td><td>{m['expires_at'] or 'permanent'}</td></tr>" for m in moodlets]) or "<tr><td colspan='3' style='color:#666;'>No active moodlets</td></tr>"
    log_rows = "".join([f"<tr><td style='color:#888;font-size:0.75rem;'>{l['timestamp']}</td><td>{l['need_key'] or '—'}</td><td>{l['action_text']}</td><td style='color:{'#4caf50' if l['delta'] >= 0 else '#f44336'};'>{'+' if l['delta'] >= 0 else ''}{l['delta']}</td></tr>" for l in logs])

    online_badge = '<span class="badge badge-green">online</span>' if player["is_online"] else '<span class="badge" style="background:#222;color:#666;">offline</span>'

    html = f"""<!DOCTYPE html><html><head><title>{player['display_name']} — HUD Admin</title>{admin_style()}</head><body>
    <div class="nav"><a href="/admin?secret={secret}">← Back to all players</a></div>
    <h1>{player['display_name']} {online_badge}</h1>
    <div class="subtitle">{player['avatar_uuid']} &nbsp;|&nbsp; Registered: {player['registered_at']}</div>
    <h2>Needs</h2>
    <table><tr><th>Need</th><th>Value</th><th>Override</th></tr>{needs_rows}</table>
    <h2>Apply moodlet</h2>
    <form method="post" action="/admin/player/{player_id}/apply_moodlet?secret={secret}">
      <select name="moodlet_key">{''.join([f'<option value="{k}">{k}</option>' for k in cfg['moodlets'].keys()])}</select>
      <button type="submit">Apply</button>
    </form>
    <h2>Active moodlets</h2>
    <table><tr><th>Moodlet</th><th>Type</th><th>Expires</th></tr>{moodlet_rows}</table>
    <h2>Skills</h2>
    <table><tr><th>Skill</th><th>Level</th><th>XP</th></tr>{skills_rows}</table>
    <h2>Event log (last 30)</h2>
    <table><tr><th>Time</th><th>Need</th><th>Action</th><th>Delta</th></tr>{log_rows}</table>
    </body></html>"""
    return HTMLResponse(html)


@router.post("/player/{player_id}/set_need", response_class=HTMLResponse)
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


@router.post("/player/{player_id}/apply_moodlet", response_class=HTMLResponse)
async def admin_apply_moodlet(player_id: int, request: Request, moodlet_key: str = Form(...), db=Depends(get_db)):
    check_admin(request)
    secret = request.query_params.get("secret", "")
    await apply_moodlet(player_id, moodlet_key, db)
    if not is_postgres():
        await db.commit()
    return RedirectResponse(f"/admin/player/{player_id}?secret={secret}", status_code=303)
