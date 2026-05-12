"""
Flare router — social feed.

Post quality is calculated from the player's avg creativity + charisma level.
NPC followers grow via a background job in services/flare.py.

Endpoints:
  POST  /flare/post          — create a post
  GET   /flare/feed          — posts from players you follow
  POST  /flare/like          — like a post
  POST  /flare/comment       — comment on a post
  GET   /flare/profile       — own post history + flare stats
  GET   /flare/discover      — recent posts from all players (public)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db, is_postgres
from app.config import get_config
from app.services.notifications import push_notification
from app.services.achievements import increment_stat, set_stat_if_greater

router = APIRouter(prefix="/flare", tags=["flare"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class NewPost(BaseModel):
    token: str
    content_text: str
    category: str = "life"


class LikeRequest(BaseModel):
    token: str
    post_id: int


class CommentRequest(BaseModel):
    token: str
    post_id: int
    content: str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_player(token: str, db):
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


async def _get_skill_level(player_id: int, skill_key: str, db) -> int:
    if is_postgres():
        row = await db.fetchrow(
            "SELECT level FROM skills WHERE player_id = $1 AND skill_key = $2",
            player_id, skill_key)
        return int(row["level"]) if row else 0
    else:
        async with db.execute(
            "SELECT level FROM skills WHERE player_id = ? AND skill_key = ?",
            (player_id, skill_key)
        ) as cur:
            row = await cur.fetchone()
            return int(row["level"]) if row else 0


def _calculate_quality_tier(creativity: int, charisma: int, cfg: dict) -> int:
    avg = (creativity + charisma) / 2
    thresholds = cfg.get("flare", {}).get("quality_skill_thresholds", {})
    tier = 0
    for t, threshold in sorted(thresholds.items(), key=lambda x: int(x[0])):
        if avg >= threshold:
            tier = int(t)
    return tier


async def _ensure_flare_stats(player_id: int, db):
    """Upsert flare_stats row — idempotent."""
    if is_postgres():
        await db.execute(
            """INSERT INTO flare_stats (player_id)
               VALUES ($1)
               ON CONFLICT (player_id) DO NOTHING""",
            player_id)
    else:
        await db.execute(
            """INSERT OR IGNORE INTO flare_stats (player_id) VALUES (?)""",
            (player_id,))
        await db.commit()


def _format_post(row: dict, include_author: bool = True) -> dict:
    return {
        "id":                    row["id"],
        "player_id":             row["player_id"],
        "player_uuid":           row.get("avatar_uuid", ""),
        "display_name":          row.get("display_name", ""),
        "content_text":          row["content_text"],
        "category":              row["category"],
        "quality_tier":          row["quality_tier"],
        "npc_likes":             row["npc_likes"],
        "npc_comments":          row["npc_comments"],
        "is_brand_deal_post":    bool(row["is_brand_deal_post"]),
        "created_at":            row["created_at"],
    }


# ── POST /flare/post ──────────────────────────────────────────────────────────

@router.post("/post")
async def create_post(body: NewPost, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    cfg = get_config()
    player_id = player["id"]

    # Validate category
    valid_cats = cfg.get("flare", {}).get("categories", ["life"])
    category = body.category if body.category in valid_cats else "life"

    # Validate content
    content = body.content_text.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Post content cannot be empty.")
    if len(content) > 500:
        raise HTTPException(status_code=400, detail="Post too long (500 char max).")

    # Calculate quality tier
    creativity = await _get_skill_level(player_id, "creativity", db)
    charisma   = await _get_skill_level(player_id, "charisma",   db)
    quality_tier = _calculate_quality_tier(creativity, charisma, cfg)

    # Get current follower count for snapshot
    await _ensure_flare_stats(player_id, db)
    if is_postgres():
        stats_row = await db.fetchrow(
            "SELECT follower_count FROM flare_stats WHERE player_id = $1", player_id)
        follower_count = int(stats_row["follower_count"]) if stats_row else 0

        post_id = await db.fetchval(
            """INSERT INTO posts
               (player_id, content_text, category, quality_tier, follower_count_at_post)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id""",
            player_id, content, category, quality_tier, follower_count)

        # Update flare_stats
        await db.execute(
            """UPDATE flare_stats
               SET weekly_post_count = weekly_post_count + 1,
                   last_post_at = now()::text
               WHERE player_id = $1""",
            player_id)

        # Update player_stats
        await db.execute(
            """INSERT INTO player_stats (player_id, total_posts_made)
               VALUES ($1, 1)
               ON CONFLICT (player_id)
               DO UPDATE SET total_posts_made = player_stats.total_posts_made + 1,
                             last_updated = now()::text""",
            player_id)
    else:
        async with db.execute(
            "SELECT follower_count FROM flare_stats WHERE player_id = ?", (player_id,)
        ) as cur:
            stats_row = await cur.fetchone()
        follower_count = int(stats_row["follower_count"]) if stats_row else 0

        async with db.execute(
            """INSERT INTO posts
               (player_id, content_text, category, quality_tier, follower_count_at_post)
               VALUES (?, ?, ?, ?, ?)""",
            (player_id, content, category, quality_tier, follower_count)
        ) as cur:
            post_id = cur.lastrowid

        await db.execute(
            """UPDATE flare_stats
               SET weekly_post_count = weekly_post_count + 1,
                   last_post_at = datetime('now')
               WHERE player_id = ?""",
            (player_id,))

        await db.execute(
            """INSERT OR IGNORE INTO player_stats (player_id) VALUES (?)""",
            (player_id,))
        await db.execute(
            """UPDATE player_stats
               SET total_posts_made = total_posts_made + 1,
                   last_updated = datetime('now')
               WHERE player_id = ?""",
            (player_id,))
        await db.commit()

    # Achievement check — total_posts_made was just incremented in DB
    from app.services.achievements import check_achievements
    try:
        await check_achievements(player_id, "total_posts_made")
    except Exception:
        pass

    tier_labels = {0: "Standard", 1: "Good", 2: "Great", 3: "Exceptional"}
    return {
        "status":       "posted",
        "post_id":      post_id,
        "quality_tier": quality_tier,
        "tier_label":   tier_labels.get(quality_tier, "Standard"),
    }


# ── GET /flare/feed ───────────────────────────────────────────────────────────

@router.get("/feed")
async def get_feed(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        rows = await db.fetch(
            """SELECT p.*, pl.display_name, pl.avatar_uuid
               FROM posts p
               JOIN players pl ON pl.id = p.player_id
               WHERE p.player_id IN (
                   SELECT following_id FROM follows WHERE follower_id = $1
               )
               OR p.player_id = $1
               ORDER BY p.created_at DESC
               LIMIT 40""",
            player_id)
    else:
        async with db.execute(
            """SELECT p.*, pl.display_name, pl.avatar_uuid
               FROM posts p
               JOIN players pl ON pl.id = p.player_id
               WHERE p.player_id IN (
                   SELECT following_id FROM follows WHERE follower_id = ?
               )
               OR p.player_id = ?
               ORDER BY p.created_at DESC
               LIMIT 40""",
            (player_id, player_id)
        ) as cur:
            rows = await cur.fetchall()

    return {"feed": [_format_post(dict(r)) for r in rows]}


# ── GET /flare/discover ───────────────────────────────────────────────────────

@router.get("/discover")
async def discover(token: str, category: str | None = None, db=Depends(get_db)):
    """Recent posts from all players — sorted by quality then recency."""
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    if is_postgres():
        base = """SELECT p.*, pl.display_name, pl.avatar_uuid
               FROM posts p
               JOIN players pl ON pl.id = p.player_id
               WHERE p.visibility = 'public'"""
        if category:
            rows = await db.fetch(
                base + " AND p.category = $1 ORDER BY p.quality_tier DESC, p.created_at DESC LIMIT 30",
                category)
        else:
            rows = await db.fetch(
                base + " ORDER BY p.quality_tier DESC, p.created_at DESC LIMIT 30")
    else:
        if category:
            async with db.execute(
                """SELECT p.*, pl.display_name, pl.avatar_uuid
                   FROM posts p JOIN players pl ON pl.id = p.player_id
                   WHERE p.visibility = 'public' AND p.category = ?
                   ORDER BY p.quality_tier DESC, p.created_at DESC LIMIT 30""",
                (category,)
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                """SELECT p.*, pl.display_name, pl.avatar_uuid
                   FROM posts p JOIN players pl ON pl.id = p.player_id
                   WHERE p.visibility = 'public'
                   ORDER BY p.quality_tier DESC, p.created_at DESC LIMIT 30"""
            ) as cur:
                rows = await cur.fetchall()

    return {"discover": [_format_post(dict(r)) for r in rows]}


# ── GET /flare/profile ────────────────────────────────────────────────────────

@router.get("/profile")
async def get_profile(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    await _ensure_flare_stats(player_id, db)

    if is_postgres():
        stats_row = await db.fetchrow(
            "SELECT * FROM flare_stats WHERE player_id = $1", player_id)
        posts_rows = await db.fetch(
            """SELECT p.*, pl.display_name, pl.avatar_uuid FROM posts p
               JOIN players pl ON pl.id = p.player_id
               WHERE p.player_id = $1
               ORDER BY p.created_at DESC LIMIT 20""",
            player_id)
        following_count = await db.fetchval(
            "SELECT COUNT(*) FROM follows WHERE follower_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT * FROM flare_stats WHERE player_id = ?", (player_id,)
        ) as cur:
            stats_row = await cur.fetchone()
        async with db.execute(
            """SELECT p.*, pl.display_name, pl.avatar_uuid FROM posts p
               JOIN players pl ON pl.id = p.player_id
               WHERE p.player_id = ?
               ORDER BY p.created_at DESC LIMIT 20""",
            (player_id,)
        ) as cur:
            posts_rows = await cur.fetchall()
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM follows WHERE follower_id = ?", (player_id,)
        ) as cur:
            fc_row = await cur.fetchone()
        following_count = fc_row["cnt"] if fc_row else 0

    stats = dict(stats_row) if stats_row else {}

    return {
        "display_name":    player["display_name"],
        "follower_count":  stats.get("follower_count", 0),
        "following_count": following_count,
        "weekly_posts":    stats.get("weekly_post_count", 0),
        "post_streak":     stats.get("post_streak_days", 0),
        "active_deal":     stats.get("active_brand_deal_key"),
        "posts":           [_format_post(dict(r)) for r in posts_rows],
    }


# ── POST /flare/like ──────────────────────────────────────────────────────────

@router.post("/like")
async def like_post(body: LikeRequest, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    # Check post exists and get author
    if is_postgres():
        post_row = await db.fetchrow(
            "SELECT id, player_id FROM posts WHERE id = $1", body.post_id)
    else:
        async with db.execute(
            "SELECT id, player_id FROM posts WHERE id = ?", (body.post_id,)
        ) as cur:
            post_row = await cur.fetchone()

    if not post_row:
        raise HTTPException(status_code=404, detail="Post not found.")

    # Check already liked
    if is_postgres():
        existing = await db.fetchrow(
            "SELECT id FROM post_engagements WHERE post_id = $1 AND player_id = $2 AND type = 'like'",
            body.post_id, player_id)
        if existing:
            return {"status": "already_liked"}
        await db.execute(
            "INSERT INTO post_engagements (post_id, player_id, type) VALUES ($1, $2, 'like')",
            body.post_id, player_id)
    else:
        async with db.execute(
            "SELECT id FROM post_engagements WHERE post_id = ? AND player_id = ? AND type = 'like'",
            (body.post_id, player_id)
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            return {"status": "already_liked"}
        await db.execute(
            "INSERT INTO post_engagements (post_id, player_id, type) VALUES (?, ?, 'like')",
            (body.post_id, player_id, ))
        await db.commit()

    # Increment like count on the post
    if is_postgres():
        await db.execute(
            "UPDATE posts SET npc_likes = npc_likes + 1 WHERE id = $1", body.post_id)
    else:
        await db.execute(
            "UPDATE posts SET npc_likes = npc_likes + 1 WHERE id = ?", (body.post_id,))
        await db.commit()

    # Notify post author if it's not their own post
    if post_row["player_id"] != player_id:
        await push_notification(
            player_id=post_row["player_id"],
            app_source="flare",
            title=f"{player['display_name']} liked your post ❤️",
            body="",
            priority="low",
            db=db,
        )

    return {"status": "liked", "new_like_count": None}


# ── POST /flare/comment ───────────────────────────────────────────────────────

@router.post("/comment")
async def comment_post(body: CommentRequest, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Comment cannot be empty.")
    if len(content) > 280:
        raise HTTPException(status_code=400, detail="Comment too long (280 char max).")

    player_id = player["id"]

    if is_postgres():
        post_row = await db.fetchrow(
            "SELECT id, player_id FROM posts WHERE id = $1", body.post_id)
    else:
        async with db.execute(
            "SELECT id, player_id FROM posts WHERE id = ?", (body.post_id,)
        ) as cur:
            post_row = await cur.fetchone()

    if not post_row:
        raise HTTPException(status_code=404, detail="Post not found.")

    if is_postgres():
        await db.execute(
            """INSERT INTO post_engagements (post_id, player_id, type, content)
               VALUES ($1, $2, 'comment', $3)""",
            body.post_id, player_id, content)
    else:
        await db.execute(
            """INSERT INTO post_engagements (post_id, player_id, type, content)
               VALUES (?, ?, 'comment', ?)""",
            (body.post_id, player_id, content))
        await db.commit()

    # Increment comment count on the post
    if is_postgres():
        await db.execute(
            "UPDATE posts SET npc_comments = npc_comments + 1 WHERE id = $1", body.post_id)
    else:
        await db.execute(
            "UPDATE posts SET npc_comments = npc_comments + 1 WHERE id = ?", (body.post_id,))
        await db.commit()

    if post_row["player_id"] != player_id:
        preview = content[:60] + ("…" if len(content) > 60 else "")
        await push_notification(
            player_id=post_row["player_id"],
            app_source="flare",
            title=f"{player['display_name']} commented on your post 💬",
            body=preview,
            priority="low",
            db=db,
        )

    return {"status": "commented"}


# ── Schemas (Phase 1 additions) ───────────────────────────────────────────────

class RepostRequest(BaseModel):
    token: str
    post_id: int
    comment: str | None = None  # optional quote-repost comment


# ── Helpers (Phase 1) ─────────────────────────────────────────────────────────

import re as _re

def _parse_hashtags(text: str) -> list[str]:
    """Extract #hashtags from post text, normalised to lowercase."""
    return list({tag.lower() for tag in _re.findall(r'#([A-Za-z0-9_]+)', text)})


def _parse_mentions(text: str) -> list[str]:
    """Extract @mentions from post text."""
    return list({m.lower() for m in _re.findall(r'@([A-Za-z0-9_. ]+?)(?=\s|$|[^A-Za-z0-9_.])', text)})


# ── Patch create_post to handle new fields ────────────────────────────────────
# (original create_post is above; this adds a new route that wraps it)

class NewPostV2(BaseModel):
    token: str
    content_text: str
    category: str = "life"
    image_uuid: str | None = None
    visibility: str = "public"   # public | friends
    is_locked: int = 0           # 1 = subscriber-only
    ppv_price: int = 0           # Lumens to unlock, 0 = not PPV
    is_adult: int = 0            # 1 = 18+ tag


@router.post("/post/v2")
async def create_post_v2(body: NewPostV2, db=Depends(get_db)):
    """Enhanced create post — supports image, visibility, hashtags, mentions."""
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    cfg = get_config()
    player_id = player["id"]

    valid_cats = cfg.get("flare", {}).get("categories", ["life"])
    category   = body.category if body.category in valid_cats else "life"
    visibility = body.visibility if body.visibility in ("public", "friends") else "public"

    content = body.content_text.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Post content cannot be empty.")
    if len(content) > 500:
        raise HTTPException(status_code=400, detail="Post too long (500 char max).")

    # Validate image_uuid format (basic check)
    image_uuid = None
    if body.image_uuid:
        uuid_clean = body.image_uuid.strip()
        if len(uuid_clean) in (32, 36):
            image_uuid = uuid_clean

    hashtags = _parse_hashtags(content)
    hashtags_str = ",".join(hashtags) if hashtags else None

    creativity   = await _get_skill_level(player_id, "creativity", db)
    charisma     = await _get_skill_level(player_id, "charisma",   db)
    quality_tier = _calculate_quality_tier(creativity, charisma, cfg)

    await _ensure_flare_stats(player_id, db)

    now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()

    if is_postgres():
        stats_row = await db.fetchrow(
            "SELECT follower_count FROM flare_stats WHERE player_id = $1", player_id)
        follower_count = int(stats_row["follower_count"]) if stats_row else 0

        post_id = await db.fetchval(
            """INSERT INTO posts
               (player_id, content_text, category, quality_tier, follower_count_at_post,
                image_uuid, visibility, hashtags, is_locked, ppv_price, is_adult)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id""",
            player_id, content, category, quality_tier, follower_count,
            image_uuid, visibility, hashtags_str,
            min(1, max(0, int(body.is_locked))),
            max(0, int(body.ppv_price)),
            min(1, max(0, int(body.is_adult))))

        await db.execute(
            """UPDATE flare_stats SET weekly_post_count = weekly_post_count + 1,
               last_post_at = $1 WHERE player_id = $2""",
            now, player_id)
        await db.execute(
            """INSERT INTO player_stats (player_id, total_posts_made) VALUES ($1, 1)
               ON CONFLICT (player_id) DO UPDATE SET
               total_posts_made = player_stats.total_posts_made + 1,
               last_updated = $2""",
            player_id, now)

        # Index hashtags
        for tag in hashtags:
            await db.execute(
                "INSERT INTO post_hashtags (post_id, tag, created_at) VALUES ($1,$2,$3)",
                post_id, tag, now)

        # Parse and notify mentions
        mentions = _parse_mentions(content)
        for mention_name in mentions:
            mentioned = await db.fetchrow(
                "SELECT id FROM players WHERE LOWER(display_name) = $1 AND is_banned = 0",
                mention_name)
            if mentioned and mentioned["id"] != player_id:
                await db.execute(
                    "INSERT INTO post_mentions (post_id, player_id, created_at) VALUES ($1,$2,$3)",
                    post_id, mentioned["id"], now)
                await push_notification(
                    player_id=mentioned["id"], app_source="flare",
                    title=f"{player['display_name']} mentioned you in a post",
                    body=content[:80], priority="normal", db=db)

    else:
        async with db.execute(
            "SELECT follower_count FROM flare_stats WHERE player_id = ?", (player_id,)
        ) as cur:
            stats_row = await cur.fetchone()
        follower_count = int(stats_row["follower_count"]) if stats_row else 0

        async with db.execute(
            """INSERT INTO posts
               (player_id, content_text, category, quality_tier, follower_count_at_post,
                image_uuid, visibility, hashtags, is_locked, ppv_price, is_adult)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (player_id, content, category, quality_tier, follower_count,
             image_uuid, visibility, hashtags_str,
             min(1, max(0, int(body.is_locked))),
             max(0, int(body.ppv_price)),
             min(1, max(0, int(body.is_adult))))
        ) as cur:
            post_id = cur.lastrowid

        await db.execute(
            """UPDATE flare_stats SET weekly_post_count = weekly_post_count + 1,
               last_post_at = ? WHERE player_id = ?""",
            (now, player_id))
        await db.execute(
            "INSERT OR IGNORE INTO player_stats (player_id) VALUES (?)", (player_id,))
        await db.execute(
            """UPDATE player_stats SET total_posts_made = total_posts_made + 1,
               last_updated = ? WHERE player_id = ?""",
            (now, player_id))

        for tag in hashtags:
            await db.execute(
                "INSERT INTO post_hashtags (post_id, tag, created_at) VALUES (?,?,?)",
                (post_id, tag, now))

        mentions = _parse_mentions(content)
        for mention_name in mentions:
            async with db.execute(
                "SELECT id FROM players WHERE LOWER(display_name) = ? AND is_banned = 0",
                (mention_name,)
            ) as cur:
                mentioned = await cur.fetchone()
            if mentioned and mentioned["id"] != player_id:
                await db.execute(
                    "INSERT INTO post_mentions (post_id, player_id, created_at) VALUES (?,?,?)",
                    (post_id, mentioned["id"], now))
                await push_notification(
                    player_id=mentioned["id"], app_source="flare",
                    title=f"{player['display_name']} mentioned you in a post",
                    body=content[:80], priority="normal", db=db)

        await db.commit()

    try:
        from app.services.achievements import check_achievements
        await check_achievements(player_id, "total_posts_made")
    except Exception:
        pass

    return {
        "status": "posted", "post_id": post_id,
        "quality_tier": quality_tier,
        "hashtags": hashtags,
        "image_url": f"https://secondlife.com/app/image/{image_uuid}/2" if image_uuid else None,
    }


# ── GET /flare/post/{id} — post detail with real comments ────────────────────

@router.get("/post/{post_id}")
async def get_post_detail(post_id: int, token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        post = await db.fetchrow(
            """SELECT p.*, pl.display_name, pl.avatar_uuid
               FROM posts p JOIN players pl ON pl.id = p.player_id
               WHERE p.id = $1""", post_id)
        comments = await db.fetch(
            """SELECT pe.*, pl.display_name, pl.avatar_uuid
               FROM post_engagements pe
               JOIN players pl ON pl.id = pe.player_id
               WHERE pe.post_id = $1 AND pe.type = 'comment'
               ORDER BY pe.created_at ASC""", post_id)
        real_likes = await db.fetchval(
            "SELECT COUNT(*) FROM post_engagements WHERE post_id = $1 AND type = 'like'",
            post_id)
        viewer_liked = await db.fetchrow(
            "SELECT id FROM post_engagements WHERE post_id=$1 AND player_id=$2 AND type='like'",
            post_id, player_id)
        viewer_following = await db.fetchrow(
            "SELECT id FROM follows WHERE follower_id=$1 AND following_id=$2",
            player_id, post["player_id"]) if post else None
    else:
        async with db.execute(
            """SELECT p.*, pl.display_name, pl.avatar_uuid
               FROM posts p JOIN players pl ON pl.id = p.player_id
               WHERE p.id = ?""", (post_id,)
        ) as cur:
            post = await cur.fetchone()
        async with db.execute(
            """SELECT pe.*, pl.display_name, pl.avatar_uuid
               FROM post_engagements pe
               JOIN players pl ON pl.id = pe.player_id
               WHERE pe.post_id = ? AND pe.type = 'comment'
               ORDER BY pe.created_at ASC""", (post_id,)
        ) as cur:
            comments = await cur.fetchall()
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM post_engagements WHERE post_id=? AND type='like'",
            (post_id,)
        ) as cur:
            rl = await cur.fetchone()
        real_likes = rl["cnt"] if rl else 0
        async with db.execute(
            "SELECT id FROM post_engagements WHERE post_id=? AND player_id=? AND type='like'",
            (post_id, player_id)
        ) as cur:
            viewer_liked = await cur.fetchone()
        async with db.execute(
            "SELECT id FROM follows WHERE follower_id=? AND following_id=?",
            (player_id, post["player_id"])
        ) as cur:
            viewer_following = await cur.fetchone()

    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")

    post = dict(post)
    total_likes    = (post.get("npc_likes") or 0) + (real_likes or 0)
    total_comments = len(comments)

    image_uuid = post.get("image_uuid")
    post["image_url"] = f"https://secondlife.com/app/image/{image_uuid}/2" if image_uuid else None
    post["total_likes"]    = total_likes
    post["total_comments"] = total_comments
    post["viewer_has_liked"]    = bool(viewer_liked)
    post["viewer_is_following"] = bool(viewer_following)
    post["is_own_post"] = post["player_id"] == player_id

    return {
        "post":     post,
        "comments": [dict(c) for c in comments],
    }


# ── POST /flare/repost ────────────────────────────────────────────────────────

@router.post("/repost")
async def repost(body: RepostRequest, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    # Get original post
    if is_postgres():
        orig = await db.fetchrow("SELECT * FROM posts WHERE id = $1", body.post_id)
    else:
        async with db.execute("SELECT * FROM posts WHERE id = ?", (body.post_id,)) as cur:
            orig = await cur.fetchone()

    if not orig:
        raise HTTPException(status_code=404, detail="Post not found.")

    cfg = get_config()
    creativity   = await _get_skill_level(player_id, "creativity", db)
    charisma     = await _get_skill_level(player_id, "charisma",   db)
    quality_tier = _calculate_quality_tier(creativity, charisma, cfg)

    await _ensure_flare_stats(player_id, db)

    content  = body.comment.strip() if body.comment else ""
    now      = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()

    if is_postgres():
        stats_row = await db.fetchrow(
            "SELECT follower_count FROM flare_stats WHERE player_id = $1", player_id)
        follower_count = int(stats_row["follower_count"]) if stats_row else 0

        post_id = await db.fetchval(
            """INSERT INTO posts
               (player_id, content_text, category, quality_tier, follower_count_at_post,
                is_repost, original_post_id, visibility)
               VALUES ($1,$2,$3,$4,$5,1,$6,'public') RETURNING id""",
            player_id, content, orig["category"], quality_tier,
            follower_count, body.post_id)

        await db.execute(
            """UPDATE flare_stats SET weekly_post_count = weekly_post_count + 1,
               last_post_at = $1 WHERE player_id = $2""", now, player_id)

    else:
        async with db.execute(
            "SELECT follower_count FROM flare_stats WHERE player_id = ?", (player_id,)
        ) as cur:
            stats_row = await cur.fetchone()
        follower_count = int(stats_row["follower_count"]) if stats_row else 0

        async with db.execute(
            """INSERT INTO posts
               (player_id, content_text, category, quality_tier, follower_count_at_post,
                is_repost, original_post_id, visibility)
               VALUES (?,?,?,?,?,1,?,'public')""",
            (player_id, content, orig["category"], quality_tier,
             follower_count, body.post_id)
        ) as cur:
            post_id = cur.lastrowid

        await db.execute(
            """UPDATE flare_stats SET weekly_post_count = weekly_post_count + 1,
               last_post_at = ? WHERE player_id = ?""", (now, player_id))
        await db.commit()

    # Notify original author
    if orig["player_id"] != player_id:
        await push_notification(
            player_id=orig["player_id"], app_source="flare",
            title=f"{player['display_name']} reposted your post 🔁",
            body=content[:60] if content else "Reposted your post.",
            priority="low", db=db)

    return {"status": "reposted", "post_id": post_id}


# ── GET /flare/hashtag/{tag} ──────────────────────────────────────────────────

@router.get("/hashtag/{tag}")
async def hashtag_feed(tag: str, token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    tag_clean = tag.lower().lstrip('#')

    if is_postgres():
        rows = await db.fetch(
            """SELECT p.*, pl.display_name, pl.avatar_uuid
               FROM post_hashtags ph
               JOIN posts p ON p.id = ph.post_id
               JOIN players pl ON pl.id = p.player_id
               WHERE ph.tag = $1 AND p.visibility = 'public'
               ORDER BY p.created_at DESC LIMIT 40""",
            tag_clean)
    else:
        async with db.execute(
            """SELECT p.*, pl.display_name, pl.avatar_uuid
               FROM post_hashtags ph
               JOIN posts p ON p.id = ph.post_id
               JOIN players pl ON pl.id = p.player_id
               WHERE ph.tag = ? AND p.visibility = 'public'
               ORDER BY p.created_at DESC LIMIT 40""",
            (tag_clean,)
        ) as cur:
            rows = await cur.fetchall()

    return {"tag": tag_clean, "posts": [dict(r) for r in rows]}


# ── GET /flare/trending-hashtags ──────────────────────────────────────────────

@router.get("/trending-hashtags")
async def trending_hashtags(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    if is_postgres():
        rows = await db.fetch(
            """SELECT ph.tag, COUNT(*) as post_count
               FROM post_hashtags ph
               JOIN posts p ON p.id = ph.post_id
               WHERE ph.created_at >= (now() - interval '24 hours')::text
               AND p.visibility = 'public'
               GROUP BY ph.tag
               ORDER BY post_count DESC LIMIT 15""")
    else:
        async with db.execute(
            """SELECT ph.tag, COUNT(*) as post_count
               FROM post_hashtags ph
               JOIN posts p ON p.id = ph.post_id
               WHERE ph.created_at >= datetime('now', '-24 hours')
               AND p.visibility = 'public'
               GROUP BY ph.tag
               ORDER BY post_count DESC LIMIT 15"""
        ) as cur:
            rows = await cur.fetchall()

    return {"trending": [dict(r) for r in rows]}


# ── GET /flare/mention-search ─────────────────────────────────────────────────

@router.get("/mention-search")
async def mention_search(token: str, q: str, db=Depends(get_db)):
    """Search players by display_name prefix for @mention autocomplete."""
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    q_clean = q.strip()[:30]
    if len(q_clean) < 1:
        return {"results": []}

    if is_postgres():
        rows = await db.fetch(
            """SELECT p.id, p.display_name, p.avatar_uuid,
                      pp.profile_pic_uuid
               FROM players p
               LEFT JOIN player_profiles pp ON pp.player_id = p.id
               WHERE LOWER(p.display_name) LIKE $1
               AND p.is_banned = 0
               ORDER BY p.display_name ASC LIMIT 8""",
            f"{q_clean.lower()}%")
    else:
        async with db.execute(
            """SELECT p.id, p.display_name, p.avatar_uuid,
                      pp.profile_pic_uuid
               FROM players p
               LEFT JOIN player_profiles pp ON pp.player_id = p.id
               WHERE LOWER(p.display_name) LIKE ?
               AND p.is_banned = 0
               ORDER BY p.display_name ASC LIMIT 8""",
            (f"{q_clean.lower()}%",)
        ) as cur:
            rows = await cur.fetchall()

    return {
        "results": [
            {
                "id":           r["id"],
                "display_name": r["display_name"],
                "avatar_url":   f"https://secondlife.com/app/image/{r['profile_pic_uuid']}/2"
                                if r.get("profile_pic_uuid") else None,
            }
            for r in rows
        ]
    }


# ── Flare DM Schemas ──────────────────────────────────────────────────────────

class FlareMessage(BaseModel):
    token: str
    body: str

class InterestsBody(BaseModel):
    token: str
    categories: list[str]   # list of category strings to save


# ── Flare DM helpers ──────────────────────────────────────────────────────────

async def _get_or_create_flare_thread(player_a: int, player_b: int, db) -> int:
    """Return existing thread id or create one. Lower id is always player_a."""
    a, b = min(player_a, player_b), max(player_a, player_b)
    if is_postgres():
        row = await db.fetchrow(
            "SELECT id FROM flare_threads WHERE player_a_id=$1 AND player_b_id=$2", a, b)
        if row:
            return row["id"]
        return await db.fetchval(
            "INSERT INTO flare_threads (player_a_id,player_b_id) VALUES ($1,$2) RETURNING id", a, b)
    else:
        async with db.execute(
            "SELECT id FROM flare_threads WHERE player_a_id=? AND player_b_id=?", (a, b)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return row["id"]
        async with db.execute(
            "INSERT INTO flare_threads (player_a_id,player_b_id) VALUES (?,?)", (a, b)
        ) as cur:
            tid = cur.lastrowid
        await db.commit()
        return tid


# ── GET /flare/dms — thread list ──────────────────────────────────────────────

@router.get("/dms")
async def list_dm_threads(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")
    player_id = player["id"]

    if is_postgres():
        rows = await db.fetch(
            """SELECT ft.*,
                      p.display_name AS other_name, p.avatar_uuid AS other_avatar,
                      pp.profile_pic_uuid AS other_pic,
                      (SELECT COUNT(*) FROM flare_messages
                       WHERE thread_id=ft.id AND sender_id!=? AND is_read=0) AS unread,
                      (SELECT body FROM flare_messages
                       WHERE thread_id=ft.id ORDER BY sent_at DESC LIMIT 1) AS last_body
               FROM flare_threads ft
               JOIN players p ON p.id = CASE WHEN ft.player_a_id=? THEN ft.player_b_id ELSE ft.player_a_id END
               LEFT JOIN player_profiles pp ON pp.player_id = p.id
               WHERE ft.player_a_id=? OR ft.player_b_id=?
               ORDER BY ft.last_message_at DESC NULLS LAST""",
            player_id, player_id, player_id, player_id)
    else:
        async with db.execute(
            """SELECT ft.*,
                      p.display_name AS other_name, p.avatar_uuid AS other_avatar,
                      pp.profile_pic_uuid AS other_pic,
                      (SELECT COUNT(*) FROM flare_messages
                       WHERE thread_id=ft.id AND sender_id!=? AND is_read=0) AS unread,
                      (SELECT body FROM flare_messages
                       WHERE thread_id=ft.id ORDER BY sent_at DESC LIMIT 1) AS last_body
               FROM flare_threads ft
               JOIN players p ON p.id = CASE WHEN ft.player_a_id=? THEN ft.player_b_id ELSE ft.player_a_id END
               LEFT JOIN player_profiles pp ON pp.player_id = p.id
               WHERE ft.player_a_id=? OR ft.player_b_id=?
               ORDER BY ft.last_message_at DESC""",
            (player_id, player_id, player_id, player_id)
        ) as cur:
            rows = await cur.fetchall()

    threads = []
    for r in rows:
        d = dict(r)
        d["other_id"] = d["player_b_id"] if d["player_a_id"] == player_id else d["player_a_id"]
        threads.append(d)
    return {"threads": threads}


# ── GET /flare/dms/{thread_id} — messages ────────────────────────────────────

@router.get("/dms/{thread_id}")
async def get_dm_thread(thread_id: int, token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")
    player_id = player["id"]

    # Verify membership
    if is_postgres():
        thread = await db.fetchrow(
            "SELECT * FROM flare_threads WHERE id=$1 AND (player_a_id=$2 OR player_b_id=$2)",
            thread_id, player_id)
        messages = await db.fetch(
            "SELECT * FROM flare_messages WHERE thread_id=$1 ORDER BY sent_at ASC LIMIT 200",
            thread_id)
        await db.execute(
            "UPDATE flare_messages SET is_read=1 WHERE thread_id=$1 AND sender_id!=$2 AND is_read=0",
            thread_id, player_id)
        other_id = thread["player_b_id"] if thread["player_a_id"] == player_id else thread["player_a_id"]
        other = await db.fetchrow("SELECT display_name, avatar_uuid FROM players WHERE id=$1", other_id)
    else:
        async with db.execute(
            "SELECT * FROM flare_threads WHERE id=? AND (player_a_id=? OR player_b_id=?)",
            (thread_id, player_id, player_id)
        ) as cur:
            thread = await cur.fetchone()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found.")
        async with db.execute(
            "SELECT * FROM flare_messages WHERE thread_id=? ORDER BY sent_at ASC LIMIT 200",
            (thread_id,)
        ) as cur:
            messages = await cur.fetchall()
        await db.execute(
            "UPDATE flare_messages SET is_read=1 WHERE thread_id=? AND sender_id!=? AND is_read=0",
            (thread_id, player_id))
        other_id = thread["player_b_id"] if thread["player_a_id"] == player_id else thread["player_a_id"]
        async with db.execute(
            "SELECT display_name, avatar_uuid FROM players WHERE id=?", (other_id,)
        ) as cur:
            other = await cur.fetchone()
        await db.commit()

    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found.")

    return {
        "thread_id":    thread_id,
        "player_id":    player_id,
        "other_id":     other_id,
        "other_name":   other["display_name"] if other else "Unknown",
        "other_avatar": other["avatar_uuid"]  if other else None,
        "messages":     [dict(m) for m in messages],
    }


# ── POST /flare/dms/{player_id} — send or start DM ───────────────────────────

@router.post("/dms/{other_player_id}")
async def send_flare_dm(other_player_id: int, body: FlareMessage, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")
    player_id = player["id"]
    if player_id == other_player_id:
        raise HTTPException(status_code=400, detail="Cannot DM yourself.")

    text = body.body.strip()[:1000]
    if not text:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Verify other player exists
    if is_postgres():
        other = await db.fetchrow("SELECT id, display_name FROM players WHERE id=$1 AND is_banned=0", other_player_id)
    else:
        async with db.execute("SELECT id, display_name FROM players WHERE id=? AND is_banned=0", (other_player_id,)) as cur:
            other = await cur.fetchone()
    if not other:
        raise HTTPException(status_code=404, detail="Player not found.")

    thread_id = await _get_or_create_flare_thread(player_id, other_player_id, db)
    now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()

    if is_postgres():
        msg_id = await db.fetchval(
            "INSERT INTO flare_messages (thread_id,sender_id,body,sent_at) VALUES ($1,$2,$3,$4) RETURNING id",
            thread_id, player_id, text, now)
        await db.execute(
            "UPDATE flare_threads SET last_message_at=$1 WHERE id=$2", now, thread_id)
    else:
        async with db.execute(
            "INSERT INTO flare_messages (thread_id,sender_id,body,sent_at) VALUES (?,?,?,?)",
            (thread_id, player_id, text, now)
        ) as cur:
            msg_id = cur.lastrowid
        await db.execute("UPDATE flare_threads SET last_message_at=? WHERE id=?", (now, thread_id))
        await db.commit()

    await push_notification(
        player_id=other_player_id, app_source="flare",
        title=f"{player['display_name']} sent you a message ✦",
        body=text[:80] + ("…" if len(text) > 80 else ""),
        priority="normal", db=db)

    return {"status": "sent", "thread_id": thread_id, "message_id": msg_id}


# ── POST /flare/interests — save player interests ─────────────────────────────

@router.post("/interests")
async def save_interests(body: InterestsBody, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    from app.config import get_config
    cfg = get_config()
    valid_cats = set(cfg.get("flare", {}).get("categories", []))
    cats = [c for c in body.categories if c in valid_cats][:15]
    player_id = player["id"]
    now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()

    if is_postgres():
        # Clear existing, insert new
        await db.execute("DELETE FROM player_interests WHERE player_id=$1", player_id)
        for cat in cats:
            await db.execute(
                "INSERT INTO player_interests (player_id,category,weight,updated_at) VALUES ($1,$2,1,$3)",
                player_id, cat, now)
    else:
        await db.execute("DELETE FROM player_interests WHERE player_id=?", (player_id,))
        for cat in cats:
            await db.execute(
                "INSERT INTO player_interests (player_id,category,weight,updated_at) VALUES (?,?,1,?)",
                (player_id, cat, now))
        await db.commit()

    return {"status": "saved", "categories": cats}


# ── GET /flare/for-you — interest-weighted algorithm feed ────────────────────

@router.get("/for-you")
async def for_you(token: str, sort: str = "top", db=Depends(get_db)):
    """
    Algorithm-weighted discover feed.
    sort=top  → engagement score × recency decay × interest boost
    sort=new  → recency only × interest boost
    """
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")
    player_id = player["id"]

    # Get player interests
    if is_postgres():
        interest_rows = await db.fetch(
            "SELECT category, weight FROM player_interests WHERE player_id=$1", player_id)
        rows = await db.fetch(
            """SELECT p.*, pl.display_name, pl.avatar_uuid
               FROM posts p JOIN players pl ON pl.id = p.player_id
               WHERE p.visibility = 'public'
               ORDER BY p.created_at DESC LIMIT 200""")
        # Real likes per post
        like_rows = await db.fetch(
            "SELECT post_id, COUNT(*) as cnt FROM post_engagements WHERE type='like' GROUP BY post_id")
        comment_rows = await db.fetch(
            "SELECT post_id, COUNT(*) as cnt FROM post_engagements WHERE type='comment' GROUP BY post_id")
    else:
        async with db.execute(
            "SELECT category, weight FROM player_interests WHERE player_id=?", (player_id,)
        ) as cur:
            interest_rows = await cur.fetchall()
        async with db.execute(
            """SELECT p.*, pl.display_name, pl.avatar_uuid
               FROM posts p JOIN players pl ON pl.id = p.player_id
               WHERE p.visibility = 'public'
               ORDER BY p.created_at DESC LIMIT 200"""
        ) as cur:
            rows = await cur.fetchall()
        async with db.execute(
            "SELECT post_id, COUNT(*) as cnt FROM post_engagements WHERE type='like' GROUP BY post_id"
        ) as cur:
            like_rows = await cur.fetchall()
        async with db.execute(
            "SELECT post_id, COUNT(*) as cnt FROM post_engagements WHERE type='comment' GROUP BY post_id"
        ) as cur:
            comment_rows = await cur.fetchall()

    interests = {r["category"]: int(r["weight"]) for r in interest_rows}
    likes_map    = {r["post_id"]: int(r["cnt"]) for r in like_rows}
    comments_map = {r["post_id"]: int(r["cnt"]) for r in comment_rows}

    import math
    from datetime import datetime, timezone

    now_ts = datetime.now(timezone.utc).timestamp()

    scored = []
    for r in rows:
        d = dict(r)
        post_id = d["id"]

        # Recency decay
        try:
            post_ts = datetime.fromisoformat(d["created_at"].replace("Z","")).replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            post_ts = now_ts
        age_hours = (now_ts - post_ts) / 3600
        if age_hours < 24:
            decay = 1.0
        elif age_hours < 72:
            decay = 0.5
        else:
            decay = 0.2

        # Interest multiplier
        cat = d.get("category", "")
        interest_mult = 1.0 + (interests.get(cat, 0) * 0.5)

        # Engagement score
        real_likes    = likes_map.get(post_id, 0)
        real_comments = comments_map.get(post_id, 0)
        npc_likes     = d.get("npc_likes", 0)
        engagement    = (real_likes * 1.0 + real_comments * 2.0 + npc_likes * 0.1)

        if sort == "new":
            score = decay * interest_mult * (1 + math.log1p(engagement))
        else:  # top
            score = engagement * decay * interest_mult

        d["algo_score"]      = score
        d["total_likes"]     = real_likes + npc_likes
        d["total_comments"]  = real_comments + d.get("npc_comments", 0)
        d["viewer_has_liked"] = False  # caller checks separately if needed
        image_uuid = d.get("image_uuid")
        d["image_url"] = f"https://secondlife.com/app/image/{image_uuid}/2" if image_uuid else None
        scored.append(d)

    scored.sort(key=lambda x: x["algo_score"], reverse=True)

    return {"posts": scored[:40], "sort": sort}


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — CREATOR SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

class CreatorProfileBody(BaseModel):
    token: str
    is_active: bool | None = None
    subscription_price: int | None = None   # Lumens/month, 0 = free
    banner_uuid: str | None = None
    bio: str | None = None


class SubscribeBody(BaseModel):
    token: str


class UnlockPostBody(BaseModel):
    token: str


class AdultSettingBody(BaseModel):
    token: str
    show_adult_content: bool


# ── GET /flare/creator/{player_id} ───────────────────────────────────────────

@router.get("/creator/{creator_player_id}")
async def get_creator_profile(creator_player_id: int, token: str, db=Depends(get_db)):
    """Get a creator profile and subscription status for the viewer."""
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    viewer_id = player["id"]

    if is_postgres():
        cp = await db.fetchrow(
            "SELECT * FROM creator_profiles WHERE player_id = $1 AND is_active = 1",
            creator_player_id)
        is_subscribed = bool(await db.fetchrow(
            """SELECT id FROM creator_subscriptions
               WHERE subscriber_id = $1 AND creator_id = $2
               AND is_active = 1 AND expires_at > $3""",
            viewer_id, creator_player_id,
            __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()))
        sub_count = await db.fetchval(
            "SELECT COUNT(*) FROM creator_subscriptions WHERE creator_id = $1 AND is_active = 1",
            creator_player_id) or 0
    else:
        async with db.execute(
            "SELECT * FROM creator_profiles WHERE player_id = ? AND is_active = 1",
            (creator_player_id,)
        ) as cur:
            cp = await cur.fetchone()
        now_iso = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
        async with db.execute(
            """SELECT id FROM creator_subscriptions
               WHERE subscriber_id = ? AND creator_id = ?
               AND is_active = 1 AND expires_at > ?""",
            (viewer_id, creator_player_id, now_iso)
        ) as cur:
            sub_row = await cur.fetchone()
        is_subscribed = bool(sub_row)
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM creator_subscriptions WHERE creator_id = ? AND is_active = 1",
            (creator_player_id,)
        ) as cur:
            sc = await cur.fetchone()
        sub_count = sc["cnt"] if sc else 0

    if not cp:
        return {"creator": None, "is_subscribed": False, "subscriber_count": 0}

    cp = dict(cp)
    cp["banner_url"] = (
        f"https://secondlife.com/app/image/{cp['banner_uuid']}/2"
        if cp.get("banner_uuid") else None)

    return {
        "creator":          cp,
        "is_subscribed":    is_subscribed,
        "subscriber_count": sub_count,
        "is_own":           viewer_id == creator_player_id,
    }


# ── POST /flare/creator/setup ─────────────────────────────────────────────────

@router.post("/creator/setup")
async def setup_creator_profile(body: CreatorProfileBody, db=Depends(get_db)):
    """Create or update the player's creator profile."""
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()

    # Upsert creator_profiles row
    if is_postgres():
        await db.execute(
            """INSERT INTO creator_profiles (player_id, created_at, updated_at)
               VALUES ($1, $2, $2) ON CONFLICT (player_id) DO NOTHING""",
            player_id, now)
    else:
        await db.execute(
            "INSERT OR IGNORE INTO creator_profiles (player_id, created_at, updated_at) VALUES (?,?,?)",
            (player_id, now, now))
        await db.commit()

    fields = {"updated_at": now}
    if body.is_active is not None:
        fields["is_active"] = int(body.is_active)
    if body.subscription_price is not None:
        fields["subscription_price"] = max(0, int(body.subscription_price))
    if body.banner_uuid is not None:
        fields["banner_uuid"] = body.banner_uuid.strip()[:36] or None
    if body.bio is not None:
        fields["bio"] = body.bio.strip()[:400] or None

    if is_postgres():
        sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
        await db.execute(
            f"UPDATE creator_profiles SET {sets} WHERE player_id = $1",
            player_id, *fields.values())
    else:
        sets = ", ".join(f"{k} = ?" for k in fields)
        await db.execute(
            f"UPDATE creator_profiles SET {sets} WHERE player_id = ?",
            (*fields.values(), player_id))
        await db.commit()

    return {"status": "updated"}


# ── POST /flare/creator/{creator_id}/subscribe ────────────────────────────────

@router.post("/creator/{creator_player_id}/subscribe")
async def subscribe_to_creator(creator_player_id: int, body: SubscribeBody, db=Depends(get_db)):
    """Subscribe to a creator for one month."""
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    subscriber_id = player["id"]
    if subscriber_id == creator_player_id:
        raise HTTPException(status_code=400, detail="Cannot subscribe to yourself.")

    # Get creator profile
    if is_postgres():
        cp = await db.fetchrow(
            "SELECT * FROM creator_profiles WHERE player_id = $1 AND is_active = 1",
            creator_player_id)
    else:
        async with db.execute(
            "SELECT * FROM creator_profiles WHERE player_id = ? AND is_active = 1",
            (creator_player_id,)
        ) as cur:
            cp = await cur.fetchone()

    if not cp:
        raise HTTPException(status_code=404, detail="Creator not found.")

    price = int(cp["subscription_price"])
    now   = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
    from datetime import timedelta
    expires_at = (now + timedelta(days=30)).isoformat()
    now_iso    = now.isoformat()

    # Check wallet if price > 0
    if price > 0:
        if is_postgres():
            wallet = await db.fetchrow(
                "SELECT balance FROM wallets WHERE player_id = $1", subscriber_id)
        else:
            async with db.execute(
                "SELECT balance FROM wallets WHERE player_id = ?", (subscriber_id,)
            ) as cur:
                wallet = await cur.fetchone()

        if not wallet or float(wallet["balance"]) < price:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient Lumens. Subscription costs ✦{price}/month.")

        # Deduct from subscriber
        creator_cut = int(price * 0.8)
        if is_postgres():
            await db.execute(
                """UPDATE wallets SET balance = balance - $1,
                   total_spent = total_spent + $2, last_updated = $3
                   WHERE player_id = $4""",
                price, price, now_iso, subscriber_id)
            await db.execute(
                """INSERT INTO transactions (player_id, amount, type, description, timestamp)
                   VALUES ($1, $2, 'purchase', $3, $4)""",
                subscriber_id, -price,
                f"Flare creator subscription", now_iso)
            # Pay creator 80%
            await db.execute(
                """UPDATE wallets SET balance = balance + $1,
                   total_earned = total_earned + $2, last_updated = $3
                   WHERE player_id = $4""",
                creator_cut, creator_cut, now_iso, creator_player_id)
            await db.execute(
                """INSERT INTO transactions (player_id, amount, type, description, timestamp)
                   VALUES ($1, $2, 'creator_sub', $3, $4)""",
                creator_player_id, creator_cut,
                f"Subscription from {player['display_name']}", now_iso)
        else:
            await db.execute(
                """UPDATE wallets SET balance = balance - ?,
                   total_spent = total_spent + ?, last_updated = ?
                   WHERE player_id = ?""",
                (price, price, now_iso, subscriber_id))
            await db.execute(
                """INSERT INTO transactions (player_id, amount, type, description, timestamp)
                   VALUES (?, ?, 'purchase', ?, ?)""",
                (subscriber_id, -price, "Flare creator subscription", now_iso))
            await db.execute(
                """UPDATE wallets SET balance = balance + ?,
                   total_earned = total_earned + ?, last_updated = ?
                   WHERE player_id = ?""",
                (creator_cut, creator_cut, now_iso, creator_player_id))
            await db.execute(
                """INSERT INTO transactions (player_id, amount, type, description, timestamp)
                   VALUES (?, ?, 'creator_sub', ?, ?)""",
                (creator_player_id, creator_cut,
                 f"Subscription from {player['display_name']}", now_iso))

    # Upsert subscription row
    if is_postgres():
        await db.execute(
            """INSERT INTO creator_subscriptions
               (subscriber_id, creator_id, started_at, expires_at, price_paid, is_active)
               VALUES ($1,$2,$3,$4,$5,1)
               ON CONFLICT (subscriber_id, creator_id)
               DO UPDATE SET expires_at=$4, price_paid=$5, is_active=1, started_at=$3""",
            subscriber_id, creator_player_id, now_iso, expires_at, price)
    else:
        await db.execute(
            """INSERT OR REPLACE INTO creator_subscriptions
               (subscriber_id, creator_id, started_at, expires_at, price_paid, is_active)
               VALUES (?,?,?,?,?,1)""",
            (subscriber_id, creator_player_id, now_iso, expires_at, price))
        await db.commit()

    # Notify creator
    await push_notification(
        player_id=creator_player_id, app_source="flare",
        title=f"{player['display_name']} subscribed to you ✦",
        body=f"New subscriber! ✦{price}/month" if price else "New free subscriber!",
        priority="normal", db=db)

    return {"status": "subscribed", "expires_at": expires_at, "price_paid": price}


# ── DELETE /flare/creator/{creator_id}/subscribe ──────────────────────────────

@router.delete("/creator/{creator_player_id}/subscribe")
async def unsubscribe(creator_player_id: int, token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    subscriber_id = player["id"]

    if is_postgres():
        await db.execute(
            """UPDATE creator_subscriptions SET is_active = 0
               WHERE subscriber_id = $1 AND creator_id = $2""",
            subscriber_id, creator_player_id)
    else:
        await db.execute(
            """UPDATE creator_subscriptions SET is_active = 0
               WHERE subscriber_id = ? AND creator_id = ?""",
            (subscriber_id, creator_player_id))
        await db.commit()

    return {"status": "unsubscribed"}


# ── POST /flare/post/{id}/unlock ──────────────────────────────────────────────

@router.post("/post/{post_id}/unlock")
async def unlock_post(post_id: int, body: UnlockPostBody, db=Depends(get_db)):
    """Pay-per-view unlock for a specific post."""
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        post = await db.fetchrow(
            "SELECT id, player_id, ppv_price, is_locked FROM posts WHERE id = $1", post_id)
    else:
        async with db.execute(
            "SELECT id, player_id, ppv_price, is_locked FROM posts WHERE id = ?", (post_id,)
        ) as cur:
            post = await cur.fetchone()

    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    if not post["ppv_price"]:
        raise HTTPException(status_code=400, detail="Post is not PPV.")
    if post["player_id"] == player_id:
        raise HTTPException(status_code=400, detail="Cannot unlock your own post.")

    price   = int(post["ppv_price"])
    now_iso = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()

    # Check already unlocked
    if is_postgres():
        existing = await db.fetchrow(
            "SELECT id FROM post_unlocks WHERE player_id = $1 AND post_id = $2",
            player_id, post_id)
    else:
        async with db.execute(
            "SELECT id FROM post_unlocks WHERE player_id = ? AND post_id = ?",
            (player_id, post_id)
        ) as cur:
            existing = await cur.fetchone()

    if existing:
        return {"status": "already_unlocked"}

    # Check wallet
    if is_postgres():
        wallet = await db.fetchrow(
            "SELECT balance FROM wallets WHERE player_id = $1", player_id)
    else:
        async with db.execute(
            "SELECT balance FROM wallets WHERE player_id = ?", (player_id,)
        ) as cur:
            wallet = await cur.fetchone()

    if not wallet or float(wallet["balance"]) < price:
        raise HTTPException(status_code=400, detail=f"Insufficient Lumens. Costs ✦{price}.")

    creator_cut = int(price * 0.8)

    if is_postgres():
        await db.execute(
            """UPDATE wallets SET balance = balance - $1,
               total_spent = total_spent + $2, last_updated = $3
               WHERE player_id = $4""",
            price, price, now_iso, player_id)
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES ($1,$2,'purchase','PPV post unlock',$3)""",
            player_id, -price, now_iso)
        await db.execute(
            """UPDATE wallets SET balance = balance + $1,
               total_earned = total_earned + $2, last_updated = $3
               WHERE player_id = $4""",
            creator_cut, creator_cut, now_iso, post["player_id"])
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES ($1,$2,'creator_ppv','PPV post unlock revenue',$3)""",
            post["player_id"], creator_cut, now_iso)
        await db.execute(
            "INSERT INTO post_unlocks (player_id,post_id,unlocked_at,price_paid) VALUES ($1,$2,$3,$4)",
            player_id, post_id, now_iso, price)
    else:
        await db.execute(
            """UPDATE wallets SET balance = balance - ?,
               total_spent = total_spent + ?, last_updated = ?
               WHERE player_id = ?""",
            (price, price, now_iso, player_id))
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES (?,?,'purchase','PPV post unlock',?)""",
            (player_id, -price, now_iso))
        await db.execute(
            """UPDATE wallets SET balance = balance + ?,
               total_earned = total_earned + ?, last_updated = ?
               WHERE player_id = ?""",
            (creator_cut, creator_cut, now_iso, post["player_id"]))
        await db.execute(
            """INSERT INTO transactions (player_id, amount, type, description, timestamp)
               VALUES (?,?,'creator_ppv','PPV post unlock revenue',?)""",
            (post["player_id"], creator_cut, now_iso))
        await db.execute(
            "INSERT INTO post_unlocks (player_id,post_id,unlocked_at,price_paid) VALUES (?,?,?,?)",
            (player_id, post_id, now_iso, price))
        await db.commit()

    return {"status": "unlocked", "price_paid": price}


# ── POST /flare/settings/adult ────────────────────────────────────────────────

@router.post("/settings/adult")
async def set_adult_preference(body: AdultSettingBody, db=Depends(get_db)):
    """Toggle 18+ content visibility."""
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    val = int(body.show_adult_content)

    if is_postgres():
        await db.execute(
            "INSERT INTO player_profiles (player_id) VALUES ($1) ON CONFLICT (player_id) DO NOTHING",
            player_id)
        await db.execute(
            "UPDATE player_profiles SET show_adult_content = $1 WHERE player_id = $2",
            val, player_id)
    else:
        await db.execute(
            "INSERT OR IGNORE INTO player_profiles (player_id) VALUES (?)", (player_id,))
        await db.execute(
            "UPDATE player_profiles SET show_adult_content = ? WHERE player_id = ?",
            (val, player_id))
        await db.commit()

    return {"status": "updated", "show_adult_content": bool(val)}
