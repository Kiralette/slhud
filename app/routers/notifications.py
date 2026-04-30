"""
Notification endpoints.

GET  /notifications/unread-count   — HUD polls every 60s for red dot data
GET  /notifications/urgent-toast   — HUD polls every 60s for llOwnerSay messages
GET  /notifications                — Canvas history tab
PUT  /notifications/read           — mark all read
PUT  /notifications/read/{app}     — mark one app's notifications read
"""

from fastapi import APIRouter, Depends
from app.services.auth import get_current_player
from app.database import get_db
from app.services.notifications import (
    get_unread_counts,
    get_urgent_toasts,
    mark_app_read,
    mark_all_read,
    get_recent_notifications,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/unread-count")
async def unread_count(
    player: dict = Depends(get_current_player),
    db = Depends(get_db)
):
    """
    Lightweight endpoint — HUD polls this every 60s.
    Returns which app icons need a red dot and total count.

    LSL usage:
      llHTTPRequest(SERVER + "/notifications/unread-count", [HTTP_METHOD,"GET",
        HTTP_CUSTOM_HEADER,"Authorization","Bearer " + token], "");
    Response: {"total": 3, "by_app": {"lumen_eats": 1, "grind": 2}}
    """
    counts = await get_unread_counts(player["id"], db)
    return counts


@router.get("/urgent-toast")
async def urgent_toast(
    player: dict = Depends(get_current_player),
    db = Depends(get_db)
):
    """
    Returns urgent undelivered notifications for HUD toast display.
    Marks them as toasted so they won't repeat.

    LSL usage: poll every 60s. If list non-empty, llOwnerSay each message.
    Response: [{"app_source": "grind", "title": "Shift complete", "body": "✦60 deposited"}]
    """
    toasts = await get_urgent_toasts(player["id"], db)
    return {"toasts": toasts}


@router.get("")
async def get_notifications(
    player: dict = Depends(get_current_player),
    db = Depends(get_db)
):
    """Full notification history for Canvas notifications tab."""
    notifs = await get_recent_notifications(player["id"], db)
    return {"notifications": notifs}


@router.put("/read")
async def mark_read_all(
    player: dict = Depends(get_current_player),
    db = Depends(get_db)
):
    """Mark all notifications as read."""
    await mark_all_read(player["id"], db)
    return {"ok": True}


@router.put("/read/{app_source}")
async def mark_read_app(
    app_source: str,
    player: dict = Depends(get_current_player),
    db = Depends(get_db)
):
    """
    Mark one app's notifications as read.
    Called automatically when player opens that app's webapp.
    """
    await mark_app_read(player["id"], app_source, db)
    return {"ok": True, "app": app_source}

class MarkReadRequest(BaseModel):
    token: str
    notification_id: int

@router.post("/mark-read")
async def mark_single_read(body: MarkReadRequest, db=Depends(get_db)):
    """Mark a single notification as read by ID. Used by Canvas JS."""
    from app.routers.players import get_player_by_token as _get_player
    player = await _get_player(body.token, db)
    if not player:
        raise HTTPException(status_code=401, detail="Invalid token.")
    if is_postgres():
        await db.execute(
            "UPDATE notifications SET is_read = 1, is_toasted = 1 WHERE id = $1 AND player_id = $2",
            body.notification_id, player["id"])
    else:
        await db.execute(
            "UPDATE notifications SET is_read = 1, is_toasted = 1 WHERE id = ? AND player_id = ?",
            (body.notification_id, player["id"]))
        await db.commit()
    return {"ok": True}
