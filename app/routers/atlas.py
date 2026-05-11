"""
Atlas — community location guide & personal bookmark manager.

Endpoints:
  POST   /atlas/locations                    — add location (or return existing public one)
  GET    /atlas/locations                    — discover / search locations
  GET    /atlas/locations/{id}               — full detail with reviews + save status
  PUT    /atlas/locations/{id}               — edit own location
  DELETE /atlas/locations/{id}               — delete own location

  POST   /atlas/locations/{id}/review        — add or update review/note
  POST   /atlas/locations/{id}/checkin       — check in
  POST   /atlas/locations/{id}/save          — save to Want to Go or Been There
  DELETE /atlas/locations/{id}/save          — remove from a list
  POST   /atlas/reviews/{id}/helpful         — toggle helpful vote

  GET    /atlas/my-places                    — player's Want to Go + Been There lists
  GET    /atlas/my-locations                 — locations added by the player
  GET    /atlas/nearby                       — locations in a given region
"""

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from datetime import datetime, timezone
import re
import httpx

from app.database import get_db, is_postgres
from app.services.notifications import push_notification

router = APIRouter(prefix="/atlas", tags=["atlas"])

# ── Constants ─────────────────────────────────────────────────────────────────

PARENT_CATEGORIES = ["places", "shopping"]

SUB_CATEGORIES = {
    "places": [
        "social_hangout", "nightlife_club", "art_gallery",
        "nature_scenic", "roleplay_community", "adult", "other",
    ],
    "shopping": [
        "mainstore", "shopping_event", "cosmetics_makeup", "skin",
        "shape_body", "hair", "clothing_fashion", "accessories_jewelry",
        "furniture_decor", "animations_ao", "mesh_body_head",
        "homes_land", "other_shopping",
    ],
}

VISIBILITY_OPTIONS = ["private", "friends", "public"]

SUB_CATEGORY_LABELS = {
    "social_hangout":      "Social & Hangout",
    "nightlife_club":      "Nightlife & Club",
    "art_gallery":         "Art & Gallery",
    "nature_scenic":       "Nature & Scenic",
    "roleplay_community":  "Roleplay & Community",
    "adult":               "Adult",
    "other":               "Other",
    "mainstore":           "Mainstore",
    "shopping_event":      "Shopping Event",
    "cosmetics_makeup":    "Cosmetics & Makeup",
    "skin":                "Skin",
    "shape_body":          "Shape & Body",
    "hair":                "Hair",
    "clothing_fashion":    "Clothing & Fashion",
    "accessories_jewelry": "Accessories & Jewelry",
    "furniture_decor":     "Furniture & Decor",
    "animations_ao":       "Animations & AO",
    "mesh_body_head":      "Mesh Body & Head",
    "homes_land":          "Homes & Land",
    "other_shopping":      "Other Shopping",
}


# ── Schemas ───────────────────────────────────────────────────────────────────

class AddLocation(BaseModel):
    token: str
    region_name: str
    parcel_name: str
    parcel_photo_uuid: str | None = None
    # x/y/z must be the parcel's landing point coordinates, not region centre.
    # In LSL: llGetParcelDetails(llGetPos(), [PARCEL_DETAILS_LANDING_POINT])
    # gives the exact teleport target; fall back to llGetPos() only when
    # PARCEL_DETAILS_LANDING_POINT returns ZERO_VECTOR.
    x: float = 0
    y: float = 0
    z: float = 0
    name: str
    description: str | None = None
    parent_category: str = "places"
    sub_category: str = "other"
    visibility: str = "public"
    marketplace_url: str | None = None
    instagram_url: str | None = None
    flickr_url: str | None = None
    primfeed_url: str | None = None
    website_url: str | None = None


class UpdateLocation(BaseModel):
    token: str
    name: str | None = None
    description: str | None = None
    parent_category: str | None = None
    sub_category: str | None = None
    visibility: str | None = None
    parcel_photo_uuid: str | None = None
    marketplace_url: str | None = None
    instagram_url: str | None = None
    flickr_url: str | None = None
    primfeed_url: str | None = None
    website_url: str | None = None


class AddReview(BaseModel):
    token: str
    stars: float | None = None
    body: str | None = None


class CheckIn(BaseModel):
    token: str


class SaveLocation(BaseModel):
    token: str
    list_type: str = "want_to_go"


class RemoveSave(BaseModel):
    token: str
    list_type: str = "want_to_go"


class HelpfulVote(BaseModel):
    token: str


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


def _build_slurl(region_name: str, x: float, y: float, z: float) -> str:
    region_encoded = region_name.replace(" ", "%20")
    return f"secondlife://{region_encoded}/{int(x)}/{int(y)}/{int(z)}"


async def _fetch_parcel_picture_uuid(parcel_uuid: str) -> str | None:
    """
    Fetches the parcel page from world.secondlife.com/place/{uuid}
    and extracts the picture-service UUID.

    Does NOT modify any other parcel data.
    """

    if not parcel_uuid:
        return None

    try:
        url = f"https://world.secondlife.com/place/{parcel_uuid}"

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"}
            )

        html = response.text

        match = re.search(
            r'https://picture-service\.secondlife\.com/([a-f0-9\-]+)/',
            html,
            re.IGNORECASE
        )

        if not match:
            return None

        return match.group(1)

    except Exception:
        return None


async def _recalculate_stars(location_id: int, db):
    if is_postgres():
        row = await db.fetchrow(
            """SELECT COUNT(*) as cnt, AVG(stars) as avg
               FROM atlas_reviews WHERE location_id = $1 AND stars IS NOT NULL""",
            location_id)
        await db.execute(
            """UPDATE atlas_locations
               SET review_count = $1, average_stars = $2, updated_at = $3
               WHERE id = $4""",
            row["cnt"], round(float(row["avg"] or 0), 2),
            datetime.now(timezone.utc).isoformat(), location_id)
    else:
        async with db.execute(
            """SELECT COUNT(*) as cnt, AVG(stars) as avg
               FROM atlas_reviews WHERE location_id = ? AND stars IS NOT NULL""",
            (location_id,)
        ) as cur:
            row = await cur.fetchone()
        await db.execute(
            """UPDATE atlas_locations
               SET review_count = ?, average_stars = ?, updated_at = ?
               WHERE id = ?""",
            (row["cnt"], round(float(row["avg"] or 0), 2),
             datetime.now(timezone.utc).isoformat(), location_id))
        await db.commit()


# ── POST /atlas/locations ─────────────────────────────────────────────────────

@router.post("/locations")
async def add_location(body: AddLocation, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    region    = body.region_name.strip()[:120]
    parcel    = body.parcel_name.strip()[:120]
    name      = body.name.strip()[:120]

    if not region or not parcel or not name:
        raise HTTPException(status_code=400, detail="Region, parcel name, and name are required.")

    parent = body.parent_category if body.parent_category in PARENT_CATEGORIES else "places"
    sub    = body.sub_category if body.sub_category in SUB_CATEGORIES.get(parent, []) else "other"
    vis    = body.visibility if body.visibility in VISIBILITY_OPTIONS else "public"
    slurl  = _build_slurl(region, body.x, body.y, body.z)
    now    = datetime.now(timezone.utc).isoformat()

    # Deduplicate: same region + parcel name = same physical place.
    # Display name is intentionally excluded — players may customise it
    # for private listings, so it's not a reliable uniqueness signal.
    if vis in ("public", "friends"):
        if is_postgres():
            existing = await db.fetchrow(
                """SELECT id FROM atlas_locations
                   WHERE region_name = $1 AND parcel_name = $2
                   AND visibility IN ('public','friends')""",
                region, parcel)
        else:
            async with db.execute(
                """SELECT id FROM atlas_locations
                   WHERE region_name = ? AND parcel_name = ?
                   AND visibility IN ('public','friends')""",
                (region, parcel)
            ) as cur:
                existing = await cur.fetchone()

        if existing:
            loc_id = existing["id"]
            # Merge any new links/photo that the original listing is missing
            if is_postgres():
                orig = await db.fetchrow(
                    """SELECT parcel_photo_uuid, marketplace_url, instagram_url,
                              flickr_url, primfeed_url, description
                       FROM atlas_locations WHERE id = $1""", loc_id)
            else:
                async with db.execute(
                    """SELECT parcel_photo_uuid, marketplace_url, instagram_url,
                              flickr_url, primfeed_url, description
                       FROM atlas_locations WHERE id = ?""", (loc_id,)
                ) as cur:
                    orig = await cur.fetchone()

            # Only fill in fields that are currently NULL/empty on the original
            merge = {}
            for field, new_val in [
                ("parcel_photo_uuid", body.parcel_photo_uuid),
                ("marketplace_url",   body.marketplace_url),
                ("instagram_url",     body.instagram_url),
                ("flickr_url",        body.flickr_url),
                ("primfeed_url",      body.primfeed_url),
                ("description",       body.description),
            ]:
                if new_val and not orig[field]:
                    merge[field] = new_val

            if merge:
                merge["updated_at"] = now
                if is_postgres():
                    sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(merge))
                    await db.execute(
                        f"UPDATE atlas_locations SET {sets} WHERE id = $1",
                        loc_id, *merge.values())
                else:
                    sets = ", ".join(f"{k} = ?" for k in merge)
                    await db.execute(
                        f"UPDATE atlas_locations SET {sets} WHERE id = ?",
                        (*merge.values(), loc_id))
                    await db.commit()

            return {"status": "existing", "location_id": loc_id, "created": False,
                    "merged_fields": list(merge.keys())}

    if is_postgres():
        loc_id = await db.fetchval(
            """INSERT INTO atlas_locations
               (player_id, region_name, parcel_name, parcel_photo_uuid,
                x, y, z, name, description, parent_category, sub_category,
                visibility, slurl, marketplace_url, instagram_url,
                flickr_url, primfeed_url, website_url, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
               RETURNING id""",
            player_id, region, parcel, body.parcel_photo_uuid,
            body.x, body.y, body.z, name, body.description,
            parent, sub, vis, slurl,
            body.marketplace_url, body.instagram_url,
            body.flickr_url, body.primfeed_url, body.website_url, now, now)
    else:
        async with db.execute(
            """INSERT INTO atlas_locations
               (player_id, region_name, parcel_name, parcel_photo_uuid,
                x, y, z, name, description, parent_category, sub_category,
                visibility, slurl, marketplace_url, instagram_url,
                flickr_url, primfeed_url, website_url, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (player_id, region, parcel, body.parcel_photo_uuid,
             body.x, body.y, body.z, name, body.description,
             parent, sub, vis, slurl,
             body.marketplace_url, body.instagram_url,
             body.flickr_url, body.primfeed_url, body.website_url, now, now)
        ) as cur:
            loc_id = cur.lastrowid
        await db.commit()

    return {"status": "created", "location_id": loc_id, "created": True}


# ── GET /atlas/locations ──────────────────────────────────────────────────────

@router.get("/locations")
async def list_locations(
    token: str,
    parent_category: str | None = None,
    sub_category: str | None = None,
    min_stars: float | None = None,
    region: str | None = None,
    sort: str = "trending",
    limit: int = 20,
    offset: int = 0,
    db=Depends(get_db)
):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    conditions_pg = ["al.visibility = 'public'"]
    conditions_sq = ["al.visibility = 'public'"]
    params_pg: list = [player_id, player_id]
    params_sq: list = [player_id, player_id]
    i = 3  # $1 and $2 used for player_id in subqueries

    if parent_category and parent_category in PARENT_CATEGORIES:
        conditions_pg.append(f"al.parent_category = ${i}")
        conditions_sq.append("al.parent_category = ?")
        params_pg.append(parent_category)
        params_sq.append(parent_category)
        i += 1

    if sub_category:
        conditions_pg.append(f"al.sub_category = ${i}")
        conditions_sq.append("al.sub_category = ?")
        params_pg.append(sub_category)
        params_sq.append(sub_category)
        i += 1

    if min_stars:
        conditions_pg.append(f"al.average_stars >= ${i}")
        conditions_sq.append("al.average_stars >= ?")
        params_pg.append(min_stars)
        params_sq.append(min_stars)
        i += 1

    if region:
        conditions_pg.append(f"al.region_name ILIKE ${i}")
        conditions_sq.append("al.region_name LIKE ?")
        params_pg.append(f"%{region}%")
        params_sq.append(f"%{region}%")
        i += 1

    ORDER_MAP = {
        "trending":   "al.checkin_count DESC, al.save_count DESC",
        "newest":     "al.created_at DESC",
        "top_rated":  "al.average_stars DESC, al.review_count DESC",
        "most_saved": "al.save_count DESC",
    }
    order = ORDER_MAP.get(sort, "al.checkin_count DESC")
    where_pg = " AND ".join(conditions_pg)
    where_sq = " AND ".join(conditions_sq)

    if is_postgres():
        rows = await db.fetch(
            f"""SELECT al.*, p.display_name AS added_by_name,
                       EXISTS(SELECT 1 FROM atlas_saves
                              WHERE player_id = $1 AND location_id = al.id
                              AND list_type = 'want_to_go') AS in_want_to_go,
                       EXISTS(SELECT 1 FROM atlas_saves
                              WHERE player_id = $2 AND location_id = al.id
                              AND list_type = 'been_there') AS in_been_there
                FROM atlas_locations al
                JOIN players p ON p.id = al.player_id
                WHERE {where_pg}
                ORDER BY {order}
                LIMIT ${i} OFFSET ${i+1}""",
            *params_pg, limit, offset)
    else:
        async with db.execute(
            f"""SELECT al.*, p.display_name AS added_by_name,
                       EXISTS(SELECT 1 FROM atlas_saves
                              WHERE player_id = ? AND location_id = al.id
                              AND list_type = 'want_to_go') AS in_want_to_go,
                       EXISTS(SELECT 1 FROM atlas_saves
                              WHERE player_id = ? AND location_id = al.id
                              AND list_type = 'been_there') AS in_been_there
                FROM atlas_locations al
                JOIN players p ON p.id = al.player_id
                WHERE {where_sq}
                ORDER BY {order}
                LIMIT ? OFFSET ?""",
            (*params_sq, *params_sq[2:], limit, offset)
        ) as cur:
            rows = await cur.fetchall()

    return {"locations": [dict(r) for r in rows], "offset": offset, "limit": limit}


# ── GET /atlas/locations/{id} ─────────────────────────────────────────────────

@router.get("/locations/{location_id}")
async def get_location(location_id: int, token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        loc = await db.fetchrow(
            """SELECT al.*, p.display_name AS added_by_name
               FROM atlas_locations al
               JOIN players p ON p.id = al.player_id
               WHERE al.id = $1""", location_id)
        reviews = await db.fetch(
            """SELECT ar.*, p.display_name AS reviewer_name,
                      (SELECT COUNT(*) FROM atlas_helpful_votes WHERE review_id = ar.id) AS helpful_count,
                      EXISTS(SELECT 1 FROM atlas_helpful_votes
                             WHERE review_id = ar.id AND player_id = $2) AS viewer_found_helpful
               FROM atlas_reviews ar
               JOIN players p ON p.id = ar.player_id
               WHERE ar.location_id = $1
               ORDER BY helpful_count DESC, ar.created_at DESC""",
            location_id, player_id)
        my_review = await db.fetchrow(
            "SELECT * FROM atlas_reviews WHERE location_id = $1 AND player_id = $2",
            location_id, player_id)
        saves = await db.fetch(
            "SELECT list_type FROM atlas_saves WHERE player_id = $1 AND location_id = $2",
            player_id, location_id)
    else:
        async with db.execute(
            """SELECT al.*, p.display_name AS added_by_name
               FROM atlas_locations al
               JOIN players p ON p.id = al.player_id
               WHERE al.id = ?""", (location_id,)
        ) as cur:
            loc = await cur.fetchone()
        async with db.execute(
            """SELECT ar.*, p.display_name AS reviewer_name,
                      (SELECT COUNT(*) FROM atlas_helpful_votes WHERE review_id = ar.id) AS helpful_count,
                      EXISTS(SELECT 1 FROM atlas_helpful_votes
                             WHERE review_id = ar.id AND player_id = ?) AS viewer_found_helpful
               FROM atlas_reviews ar
               JOIN players p ON p.id = ar.player_id
               WHERE ar.location_id = ?
               ORDER BY helpful_count DESC, ar.created_at DESC""",
            (player_id, location_id)
        ) as cur:
            reviews = await cur.fetchall()
        async with db.execute(
            "SELECT * FROM atlas_reviews WHERE location_id = ? AND player_id = ?",
            (location_id, player_id)
        ) as cur:
            my_review = await cur.fetchone()
        async with db.execute(
            "SELECT list_type FROM atlas_saves WHERE player_id = ? AND location_id = ?",
            (player_id, location_id)
        ) as cur:
            saves = await cur.fetchall()

    if not loc:
        raise HTTPException(status_code=404, detail="Location not found.")

    saved_lists = {r["list_type"] for r in saves}

    return {
        "location":      dict(loc),
        "reviews":       [dict(r) for r in reviews],
        "my_review":     dict(my_review) if my_review else None,
        "in_want_to_go": "want_to_go" in saved_lists,
        "in_been_there": "been_there" in saved_lists,
    }


# ── PUT /atlas/locations/{id} ─────────────────────────────────────────────────

@router.put("/locations/{location_id}")
async def update_location(location_id: int, body: UpdateLocation, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        existing = await db.fetchrow(
            "SELECT id FROM atlas_locations WHERE id = $1 AND player_id = $2",
            location_id, player_id)
    else:
        async with db.execute(
            "SELECT id FROM atlas_locations WHERE id = ? AND player_id = ?",
            (location_id, player_id)
        ) as cur:
            existing = await cur.fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="Location not found or not yours.")

    fields = {}
    if body.name is not None:             fields["name"]              = body.name.strip()[:120]
    if body.description is not None:      fields["description"]       = body.description
    if body.parent_category in PARENT_CATEGORIES: fields["parent_category"] = body.parent_category
    if body.sub_category is not None:     fields["sub_category"]      = body.sub_category
    if body.visibility in VISIBILITY_OPTIONS:     fields["visibility"]      = body.visibility
    if body.parcel_photo_uuid is not None: fields["parcel_photo_uuid"] = body.parcel_photo_uuid
    if body.marketplace_url is not None:  fields["marketplace_url"]   = body.marketplace_url
    if body.instagram_url is not None:    fields["instagram_url"]     = body.instagram_url
    if body.flickr_url is not None:       fields["flickr_url"]        = body.flickr_url
    if body.primfeed_url is not None:     fields["primfeed_url"]      = body.primfeed_url
    if body.website_url is not None:      fields["website_url"]       = body.website_url
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()

    if is_postgres():
        sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
        await db.execute(
            f"UPDATE atlas_locations SET {sets} WHERE id = $1",
            location_id, *fields.values())
    else:
        sets = ", ".join(f"{k} = ?" for k in fields)
        await db.execute(
            f"UPDATE atlas_locations SET {sets} WHERE id = ?",
            (*fields.values(), location_id))
        await db.commit()

    return {"status": "updated"}


# ── DELETE /atlas/locations/{id} ──────────────────────────────────────────────

@router.delete("/locations/{location_id}")
async def delete_location(location_id: int, token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    if is_postgres():
        await db.execute(
            "DELETE FROM atlas_locations WHERE id = $1 AND player_id = $2",
            location_id, player["id"])
    else:
        await db.execute(
            "DELETE FROM atlas_locations WHERE id = ? AND player_id = ?",
            (location_id, player["id"]))
        await db.commit()

    return {"status": "deleted"}


# ── POST /atlas/locations/{id}/review ────────────────────────────────────────

@router.post("/locations/{location_id}/review")
async def add_review(location_id: int, body: AddReview, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    stars     = max(1.0, min(5.0, float(body.stars))) if body.stars else None
    text      = (body.body or "").strip()[:500] or None
    now       = datetime.now(timezone.utc).isoformat()

    if is_postgres():
        await db.execute(
            """INSERT INTO atlas_reviews (location_id, player_id, stars, body, created_at)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (location_id, player_id)
               DO UPDATE SET stars = $3, body = $4, created_at = $5""",
            location_id, player_id, stars, text, now)
    else:
        await db.execute(
            """INSERT OR REPLACE INTO atlas_reviews
               (location_id, player_id, stars, body, created_at)
               VALUES (?,?,?,?,?)""",
            (location_id, player_id, stars, text, now))
        await db.commit()

    await _recalculate_stars(location_id, db)
    return {"status": "reviewed"}


# ── POST /atlas/locations/{id}/checkin ───────────────────────────────────────

@router.post("/locations/{location_id}/checkin")
async def checkin(location_id: int, body: CheckIn, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    now       = datetime.now(timezone.utc).isoformat()

    if is_postgres():
        await db.execute(
            "INSERT INTO atlas_checkins (player_id,location_id,visited_at) VALUES ($1,$2,$3)",
            player_id, location_id, now)
        await db.execute(
            "UPDATE atlas_locations SET checkin_count = checkin_count + 1 WHERE id = $1",
            location_id)
        # Auto-add to Been There
        existing_been = await db.fetchrow(
            "SELECT id FROM atlas_saves WHERE player_id=$1 AND location_id=$2 AND list_type='been_there'",
            player_id, location_id)
        if not existing_been:
            await db.execute(
                """INSERT INTO atlas_saves (player_id,location_id,list_type,saved_at)
                   VALUES ($1,$2,'been_there',$3) ON CONFLICT DO NOTHING""",
                player_id, location_id, now)
            await db.execute(
                "UPDATE atlas_locations SET save_count = save_count + 1 WHERE id = $1",
                location_id)
    else:
        await db.execute(
            "INSERT INTO atlas_checkins (player_id,location_id,visited_at) VALUES (?,?,?)",
            (player_id, location_id, now))
        await db.execute(
            "UPDATE atlas_locations SET checkin_count = checkin_count + 1 WHERE id = ?",
            (location_id,))
        async with db.execute(
            "SELECT id FROM atlas_saves WHERE player_id=? AND location_id=? AND list_type='been_there'",
            (player_id, location_id)
        ) as cur:
            existing_been = await cur.fetchone()
        if not existing_been:
            await db.execute(
                "INSERT OR IGNORE INTO atlas_saves (player_id,location_id,list_type,saved_at) VALUES (?,?,'been_there',?)",
                (player_id, location_id, now))
            await db.execute(
                "UPDATE atlas_locations SET save_count = save_count + 1 WHERE id = ?",
                (location_id,))
        await db.commit()

    # Apply explorer vibe
    try:
        if is_postgres():
            await db.execute(
                "INSERT INTO vibes (player_id,vibe_key,is_negative) VALUES ($1,'atlas_explorer',0) ON CONFLICT DO NOTHING",
                player_id)
        else:
            await db.execute(
                "INSERT OR IGNORE INTO vibes (player_id,vibe_key,is_negative) VALUES (?,'atlas_explorer',0)",
                (player_id,))
            await db.commit()
    except Exception:
        pass

    return {"status": "checked_in", "prompt_review": True}


# ── POST /atlas/locations/{id}/save ──────────────────────────────────────────

@router.post("/locations/{location_id}/save")
async def save_location(location_id: int, body: SaveLocation, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    list_type = body.list_type if body.list_type in ("want_to_go", "been_there") else "want_to_go"
    now       = datetime.now(timezone.utc).isoformat()

    if is_postgres():
        existing = await db.fetchrow(
            "SELECT id FROM atlas_saves WHERE player_id=$1 AND location_id=$2 AND list_type=$3",
            player_id, location_id, list_type)
        if not existing:
            await db.execute(
                """INSERT INTO atlas_saves (player_id,location_id,list_type,saved_at)
                   VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING""",
                player_id, location_id, list_type, now)
            await db.execute(
                "UPDATE atlas_locations SET save_count = save_count + 1 WHERE id = $1",
                location_id)
    else:
        async with db.execute(
            "SELECT id FROM atlas_saves WHERE player_id=? AND location_id=? AND list_type=?",
            (player_id, location_id, list_type)
        ) as cur:
            existing = await cur.fetchone()
        if not existing:
            await db.execute(
                "INSERT OR IGNORE INTO atlas_saves (player_id,location_id,list_type,saved_at) VALUES (?,?,?,?)",
                (player_id, location_id, list_type, now))
            await db.execute(
                "UPDATE atlas_locations SET save_count = save_count + 1 WHERE id = ?",
                (location_id,))
        await db.commit()

    return {"status": "saved", "list_type": list_type}


# ── DELETE /atlas/locations/{id}/save ────────────────────────────────────────

@router.delete("/locations/{location_id}/save")
async def unsave_location(location_id: int, token: str, list_type: str = "want_to_go", db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        await db.execute(
            "DELETE FROM atlas_saves WHERE player_id=$1 AND location_id=$2 AND list_type=$3",
            player_id, location_id, list_type)
        await db.execute(
            "UPDATE atlas_locations SET save_count = GREATEST(0, save_count - 1) WHERE id = $1",
            location_id)
    else:
        await db.execute(
            "DELETE FROM atlas_saves WHERE player_id=? AND location_id=? AND list_type=?",
            (player_id, location_id, list_type))
        await db.execute(
            "UPDATE atlas_locations SET save_count = MAX(0, save_count - 1) WHERE id = ?",
            (location_id,))
        await db.commit()

    return {"status": "removed", "list_type": list_type}


# ── POST /atlas/reviews/{id}/helpful ─────────────────────────────────────────

@router.post("/reviews/{review_id}/helpful")
async def toggle_helpful(review_id: int, body: HelpfulVote, db=Depends(get_db)):
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    now       = datetime.now(timezone.utc).isoformat()

    if is_postgres():
        existing = await db.fetchrow(
            "SELECT id FROM atlas_helpful_votes WHERE review_id=$1 AND player_id=$2",
            review_id, player_id)
        if existing:
            await db.execute(
                "DELETE FROM atlas_helpful_votes WHERE review_id=$1 AND player_id=$2",
                review_id, player_id)
            return {"status": "removed"}
        await db.execute(
            "INSERT INTO atlas_helpful_votes (review_id,player_id,created_at) VALUES ($1,$2,$3)",
            review_id, player_id, now)
        return {"status": "marked_helpful"}
    else:
        async with db.execute(
            "SELECT id FROM atlas_helpful_votes WHERE review_id=? AND player_id=?",
            (review_id, player_id)
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            await db.execute(
                "DELETE FROM atlas_helpful_votes WHERE review_id=? AND player_id=?",
                (review_id, player_id))
            await db.commit()
            return {"status": "removed"}
        await db.execute(
            "INSERT INTO atlas_helpful_votes (review_id,player_id,created_at) VALUES (?,?,?)",
            (review_id, player_id, now))
        await db.commit()
        return {"status": "marked_helpful"}


# ── GET /atlas/my-places ──────────────────────────────────────────────────────

@router.get("/my-places")
async def my_places(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        want_rows = await db.fetch(
            """SELECT al.* FROM atlas_saves s
               JOIN atlas_locations al ON al.id = s.location_id
               WHERE s.player_id = $1 AND s.list_type = 'want_to_go'
               ORDER BY s.saved_at DESC""", player_id)
        been_rows = await db.fetch(
            """SELECT al.* FROM atlas_saves s
               JOIN atlas_locations al ON al.id = s.location_id
               WHERE s.player_id = $1 AND s.list_type = 'been_there'
               ORDER BY s.saved_at DESC""", player_id)
    else:
        async with db.execute(
            """SELECT al.* FROM atlas_saves s
               JOIN atlas_locations al ON al.id = s.location_id
               WHERE s.player_id = ? AND s.list_type = 'want_to_go'
               ORDER BY s.saved_at DESC""", (player_id,)
        ) as cur:
            want_rows = await cur.fetchall()
        async with db.execute(
            """SELECT al.* FROM atlas_saves s
               JOIN atlas_locations al ON al.id = s.location_id
               WHERE s.player_id = ? AND s.list_type = 'been_there'
               ORDER BY s.saved_at DESC""", (player_id,)
        ) as cur:
            been_rows = await cur.fetchall()

    return {
        "want_to_go": [dict(r) for r in want_rows],
        "been_there": [dict(r) for r in been_rows],
    }


# ── GET /atlas/my-locations ───────────────────────────────────────────────────

@router.get("/my-locations")
async def my_locations(token: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        rows = await db.fetch(
            "SELECT * FROM atlas_locations WHERE player_id = $1 ORDER BY created_at DESC",
            player_id)
    else:
        async with db.execute(
            "SELECT * FROM atlas_locations WHERE player_id = ? ORDER BY created_at DESC",
            (player_id,)
        ) as cur:
            rows = await cur.fetchall()

    return {"locations": [dict(r) for r in rows]}


# ── POST /atlas/heartbeat ─────────────────────────────────────────────────────

class AtlasHeartbeat(BaseModel):
    region_name: str
    parcel_name: str
    parcel_uuid: str | None = None
    parcel_photo_uuid: str | None = None
    # Send the parcel landing point here, not the agent's current position.
    # In LSL: llGetParcelDetails(llGetPos(), [PARCEL_DETAILS_LANDING_POINT])
    # Returns ZERO_VECTOR when no landing point is set — fall back to llGetPos().
    x: float = 0
    y: float = 0
    z: float = 0


@router.post("/heartbeat")
async def atlas_heartbeat(
    body: AtlasHeartbeat,
    authorization: str | None = Header(None),
    db=Depends(get_db)
):
    """
    Called by LSL HUD every 60s alongside the career heartbeat.
    Captures the player's current region, parcel, photo UUID, and coordinates.
    Stored in player_location (one row per player, upserted each tick).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    token = authorization.split(" ", 1)[1].strip()

    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    region    = body.region_name.strip()[:120]
    parcel    = body.parcel_name.strip()[:120]
    slurl = _build_slurl(region, body.x, body.y, body.z)
    now   = datetime.now(timezone.utc).isoformat()

    # Preserve HUD-provided image UUID if present.
    # Otherwise attempt automatic scrape from parcel UUID.
    photo_uuid = body.parcel_photo_uuid

    if not photo_uuid and body.parcel_uuid:
        scraped_uuid = await _fetch_parcel_picture_uuid(body.parcel_uuid)

        if scraped_uuid:
            photo_uuid = scraped_uuid

    if is_postgres():
        await db.execute(
            """INSERT INTO player_location
               (player_id, region_name, parcel_name, parcel_photo_uuid, x, y, z, slurl, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               ON CONFLICT (player_id) DO UPDATE SET
                 region_name       = EXCLUDED.region_name,
                 parcel_name       = EXCLUDED.parcel_name,
                 parcel_photo_uuid = EXCLUDED.parcel_photo_uuid,
                 x                 = EXCLUDED.x,
                 y                 = EXCLUDED.y,
                 z                 = EXCLUDED.z,
                 slurl             = EXCLUDED.slurl,
                 updated_at        = EXCLUDED.updated_at""",
            player_id, region, parcel, photo_uuid,
            body.x, body.y, body.z, slurl, now)
    else:
        await db.execute(
            """INSERT INTO player_location
               (player_id, region_name, parcel_name, parcel_photo_uuid, x, y, z, slurl, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(player_id) DO UPDATE SET
                 region_name       = excluded.region_name,
                 parcel_name       = excluded.parcel_name,
                 parcel_photo_uuid = excluded.parcel_photo_uuid,
                 x                 = excluded.x,
                 y                 = excluded.y,
                 z                 = excluded.z,
                 slurl             = excluded.slurl,
                 updated_at        = excluded.updated_at""",
            (player_id, region, parcel, photo_uuid,
             body.x, body.y, body.z, slurl, now))
        await db.commit()

    return {"ok": True}


# ── POST /atlas/location-pic ──────────────────────────────────────────────────

class LocationPic(BaseModel):
    parcel_picture_uuid: str


@router.post("/location-pic")
async def location_pic(
    body: LocationPic,
    authorization: str | None = Header(None),
    db=Depends(get_db)
):
    """
    Called by LSL after scraping the parcel picture UUID from world.secondlife.com/place/.
    Updates player_location.parcel_photo_uuid with the real picture-service UUID.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    token = authorization.split(" ", 1)[1].strip()

    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]
    now = datetime.now(timezone.utc).isoformat()

    if is_postgres():
        await db.execute(
            """UPDATE player_location
               SET parcel_photo_uuid = $1, updated_at = $2
               WHERE player_id = $3""",
            body.parcel_picture_uuid, now, player_id)
    else:
        await db.execute(
            """UPDATE player_location
               SET parcel_photo_uuid = ?, updated_at = ?
               WHERE player_id = ?""",
            (body.parcel_picture_uuid, now, player_id))
        await db.commit()

    return {"ok": True}


# ── GET /atlas/current-location ───────────────────────────────────────────────

@router.get("/current-location")
async def current_location(token: str, db=Depends(get_db)):
    """
    Returns the player's last known location from the atlas heartbeat cache.
    Called by the webapp when the player taps 'Add this location' — pre-populates
    the Add form with region, parcel, coords, photo UUID, and suggested name.
    Returns nulls gracefully if no heartbeat has been received yet.
    """
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    player_id = player["id"]

    if is_postgres():
        row = await db.fetchrow(
            "SELECT * FROM player_location WHERE player_id = $1", player_id)
        loc = dict(row) if row else None
    else:
        async with db.execute(
            "SELECT * FROM player_location WHERE player_id = ?", (player_id,)
        ) as cur:
            row = await cur.fetchone()
            loc = dict(row) if row else None

    if not loc:
        return {
            "region_name":       None,
            "parcel_name":       None,
            "parcel_photo_uuid": None,
            "x":                 None,
            "y":                 None,
            "z":                 None,
            "slurl":             None,
            "suggested_name":    None,
            "updated_at":        None,
        }

    return {
        "region_name":       loc["region_name"],
        "parcel_name":       loc["parcel_name"],
        "parcel_photo_uuid": loc["parcel_photo_uuid"],
        "x":                 loc["x"],
        "y":                 loc["y"],
        "z":                 loc["z"],
        "slurl":             loc["slurl"],
        "suggested_name":    loc["parcel_name"],  # parcel name is the best default display name
        "updated_at":        loc["updated_at"],
    }


# ── GET /atlas/nearby ─────────────────────────────────────────────────────────

@router.get("/nearby")
async def nearby(token: str, region: str, db=Depends(get_db)):
    player = await _get_player(token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")

    if is_postgres():
        rows = await db.fetch(
            """SELECT * FROM atlas_locations
               WHERE region_name ILIKE $1 AND visibility = 'public'
               ORDER BY average_stars DESC, checkin_count DESC LIMIT 20""",
            f"%{region}%")
    else:
        async with db.execute(
            """SELECT * FROM atlas_locations
               WHERE region_name LIKE ? AND visibility = 'public'
               ORDER BY average_stars DESC, checkin_count DESC LIMIT 20""",
            (f"%{region}%",)
        ) as cur:
            rows = await cur.fetchall()

    return {"region": region, "locations": [dict(r) for r in rows]}
