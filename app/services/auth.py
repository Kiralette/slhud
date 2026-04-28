"""
Auth service — generates and verifies player tokens.
A token is just a long random string that acts like a password.
The HUD gets one on first registration and sends it with every request.
"""

import secrets
from fastapi import Header, HTTPException, Depends
from app.database import get_db
import aiosqlite


def generate_token() -> str:
    """
    Creates a secure random token — 32 random bytes turned into
    a 64-character hex string. Unique enough that guessing one
    is effectively impossible.
    Example: 'a3f8c2d1e9b047f6a1c3d8e2f0b9a7c4d6e1f3a2b8c9d0e7f1a4b5c6d2e3f8a1'
    """
    return secrets.token_hex(32)


async def get_current_player(
    authorization: str = Header(..., description="Bearer token from registration"),
    db: aiosqlite.Connection = Depends(get_db)
) -> dict:
    """
    FastAPI dependency — any endpoint that needs to know WHO is
    making the request uses this function.

    The HUD sends a header like:  Authorization: Bearer <token>
    This function checks the token against the database and returns
    the player row if valid, or raises a 401 error if not.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization header must start with 'Bearer '"
        )

    token = authorization.removeprefix("Bearer ").strip()

    async with db.execute(
        "SELECT * FROM players WHERE token = ? AND is_banned = 0",
        (token,)
    ) as cursor:
        player = await cursor.fetchone()

    if not player:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token. Re-attach the HUD to re-register."
        )

    return dict(player)
