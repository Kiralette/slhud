"""
Flare service — background jobs for the Flare social feed.

Jobs:
  run_follower_engine()  — runs every 10 minutes
                           grows NPC follower counts for active players
                           checks for viral events on exceptional posts
  run_brand_deal_check() — runs Sunday midnight SLT
                           checks each player's follower milestone
                           assigns or upgrades brand deal, fires notification
"""

from datetime import datetime, timezone, timedelta

from app.config import get_config
from app.database import is_postgres
from app.services.notifications import push_notification
from app.services.achievements import check_achievements, increment_stat


# ── Follower Engine ───────────────────────────────────────────────────────────

async def run_follower_engine(db=None):
    """
    Every 10 minutes:
    - For each player with a flare_stats row, grow follower count
    - Boost growth window if player posted in last 4 hours
    - Roll for viral event if an exceptional (tier 3) post exists
    - Cap NPC like/comment counts on posts (simulate engagement drip)
    """
    if db is None:
        return

    cfg = get_config()
    engine_cfg  = cfg.get("flare", {}).get("follower_engine", {})
    base_gain   = engine_cfg.get("base_gain_per_tick", 2)
    boost_hours = engine_cfg.get("post_bonus_hours", 4)
    boost_mult  = engine_cfg.get("post_bonus_mult", 2.0)
    viral_tier  = engine_cfg.get("viral_threshold_tier", 3)
    viral_chance = engine_cfg.get("viral_chance", 0.05)
    viral_gain  = engine_cfg.get("viral_gain", 500)

    import random

    now = datetime.now(timezone.utc)
    boost_cutoff = (now - timedelta(hours=boost_hours)).isoformat()

    if is_postgres():
        players = await db.fetch("SELECT * FROM flare_stats")
    else:
        async with db.execute("SELECT * FROM flare_stats") as cur:
            players = await cur.fetchall()

    for row in players:
        player_id  = row["player_id"]
        last_post  = row["last_post_at"]
        in_boost   = last_post and last_post >= boost_cutoff

        gain = int(base_gain * (boost_mult if in_boost else 1.0))

        # Check for viral-eligible post
        went_viral = False
        if is_postgres():
            viral_post = await db.fetchrow(
                """SELECT id FROM posts
                   WHERE player_id = $1 AND quality_tier >= $2
                     AND created_at >= $3""",
                player_id, viral_tier, boost_cutoff)
        else:
            async with db.execute(
                """SELECT id FROM posts
                   WHERE player_id = ? AND quality_tier >= ?
                     AND created_at >= ?""",
                (player_id, viral_tier, boost_cutoff)
            ) as cur:
                viral_post = await cur.fetchone()

        if viral_post and random.random() < viral_chance:
            gain += viral_gain
            went_viral = True

        if gain <= 0:
            continue

        if is_postgres():
            await db.execute(
                """UPDATE flare_stats
                   SET follower_count = follower_count + $1
                   WHERE player_id = $2""",
                gain, player_id)

            # Update lifetime stat
            await db.execute(
                """INSERT INTO player_stats (player_id, lifetime_followers_gained)
                   VALUES ($1, $2)
                   ON CONFLICT (player_id)
                   DO UPDATE SET lifetime_followers_gained =
                       player_stats.lifetime_followers_gained + $2""",
                player_id, gain)

            if went_viral:
                await db.execute(
                    "UPDATE posts SET npc_likes = npc_likes + $1 WHERE id = $2",
                    random.randint(80, 200), viral_post["id"])
                await push_notification(
                    player_id=player_id,
                    app_source="flare",
                    title="Viral Moment! ✨",
                    body="Your post blew up.",
                    priority="normal",
                    db=db,
                )
        else:
            try:
                await increment_stat(player_id, "viral_moments")
            except Exception:
                pass
            await db.execute(
                """UPDATE flare_stats
                   SET follower_count = follower_count + ?
                   WHERE player_id = ?""",
                (gain, player_id))
            await db.execute(
                "INSERT OR IGNORE INTO player_stats (player_id) VALUES (?)", (player_id,))
            await db.execute(
                """UPDATE player_stats
                   SET lifetime_followers_gained = lifetime_followers_gained + ?
                   WHERE player_id = ?""",
                (gain, player_id))
            if went_viral:
                await db.execute(
                    "UPDATE posts SET npc_likes = npc_likes + ? WHERE id = ?",
                    (random.randint(80, 200), viral_post["id"]))
                await push_notification(
                    player_id=player_id,
                    app_source="flare",
                    title="Viral Moment! ✨",
                    body="Your post blew up.",
                    priority="normal",
                    db=db,
                )

    if not is_postgres():
        await db.commit()

    # Drip NPC engagement onto recent posts
    await _drip_npc_engagement(db)


async def _drip_npc_engagement(db):
    """Add small NPC like/comment counts to recent posts based on quality."""
    import random

    if is_postgres():
        posts = await db.fetch(
            """SELECT id, quality_tier FROM posts
               WHERE created_at >= (now() - interval '48 hours')::text""")
    else:
        async with db.execute(
            """SELECT id, quality_tier FROM posts
               WHERE created_at >= datetime('now', '-48 hours')"""
        ) as cur:
            posts = await cur.fetchall()

    for post in posts:
        tier = post["quality_tier"]
        if tier == 0:
            like_gain = random.randint(0, 2)
        elif tier == 1:
            like_gain = random.randint(1, 5)
        elif tier == 2:
            like_gain = random.randint(3, 12)
        else:
            like_gain = random.randint(8, 30)

        comment_gain = 1 if random.random() < (tier * 0.1) else 0

        if like_gain > 0 or comment_gain > 0:
            if is_postgres():
                await db.execute(
                    """UPDATE posts
                       SET npc_likes    = npc_likes    + $1,
                           npc_comments = npc_comments + $2
                       WHERE id = $3""",
                    like_gain, comment_gain, post["id"])
            else:
                await db.execute(
                    """UPDATE posts
                       SET npc_likes    = npc_likes    + ?,
                           npc_comments = npc_comments + ?
                       WHERE id = ?""",
                    (like_gain, comment_gain, post["id"]))

    if not is_postgres():
        await db.commit()


# ── Brand Deal Check ──────────────────────────────────────────────────────────

async def run_brand_deal_check(db=None):
    """
    Runs Sunday midnight SLT.
    For each player, checks follower_count against brand deal milestones.
    If they've crossed a new tier, assigns the deal and notifies them.
    Also deposits weekly pay for active deals.
    """
    if db is None:
        return

    cfg = get_config()
    deals_cfg = cfg.get("flare", {}).get("brand_deals", {})

    # Sort milestones descending so we assign the highest qualifying tier
    milestones = sorted(
        [(int(k), v) for k, v in deals_cfg.items()],
        key=lambda x: x[0],
        reverse=True
    )

    if is_postgres():
        players = await db.fetch(
            "SELECT player_id, follower_count, active_brand_deal_key FROM flare_stats")
    else:
        async with db.execute(
            "SELECT player_id, follower_count, active_brand_deal_key FROM flare_stats"
        ) as cur:
            players = await cur.fetchall()

    for row in players:
        player_id    = row["player_id"]
        followers    = int(row["follower_count"])
        current_deal = row["active_brand_deal_key"]

        # Find best qualifying deal
        best_deal_key = None
        best_pay      = 0
        best_display  = ""

        for milestone, deal in milestones:
            if followers >= milestone:
                best_deal_key = deal["key"]
                best_pay      = deal["weekly_pay"]
                best_display  = deal["display"]
                break

        if best_deal_key is None:
            continue

        # Assign new or upgraded deal
        if best_deal_key != current_deal:
            if is_postgres():
                await db.execute(
                    """UPDATE flare_stats
                       SET active_brand_deal_key = $1,
                           brand_deal_started_at = now()::text
                       WHERE player_id = $2""",
                    best_deal_key, player_id)
            else:
                await db.execute(
                    """UPDATE flare_stats
                       SET active_brand_deal_key = ?,
                           brand_deal_started_at = datetime('now')
                       WHERE player_id = ?""",
                    (best_deal_key, player_id))

            await push_notification(
                player_id=player_id,
                app_source="flare",
                title="New brand deal offer 💼",
                body=f"{best_display} wants to work with you.",
                priority="normal",
                db=db,
            )

        # Deposit weekly pay for current deal
        if best_pay > 0:
            if is_postgres():
                await db.execute(
                    """UPDATE wallets
                       SET balance = balance + $1,
                           total_earned = total_earned + $1,
                           last_updated = now()::text
                       WHERE player_id = $2""",
                    best_pay, player_id)
                await db.execute(
                    """INSERT INTO transactions (player_id, amount, type, description)
                       VALUES ($1, $2, 'brand_deal', $3)""",
                    player_id, best_pay, f"Weekly brand deal payout — {best_display}")
            else:
                await db.execute(
                    """UPDATE wallets
                       SET balance = balance + ?,
                           total_earned = total_earned + ?,
                           last_updated = datetime('now')
                       WHERE player_id = ?""",
                    (best_pay, best_pay, player_id))
                await db.execute(
                    """INSERT INTO transactions (player_id, amount, type, description)
                       VALUES (?, ?, 'brand_deal', ?)""",
                    (player_id, best_pay, f"Weekly brand deal payout — {best_display}"))

            await push_notification(
                player_id=player_id,
                app_source="flare",
                title=f"Brand deal payout 💸",
                body=f"✦{best_pay} deposited from {best_display}.",
                priority="low",
                db=db,
            )

    # Reset weekly post counts
    if is_postgres():
        await db.execute("UPDATE flare_stats SET weekly_post_count = 0")
    else:
        await db.execute("UPDATE flare_stats SET weekly_post_count = 0")
        await db.commit()
