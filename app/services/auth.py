"""
Auth service — generates and verifies player tokens.
Compatible with both SQLite and PostgreSQL.
"""

import secrets
from fastapi import Header, HTTPException, Depends
from app.database import get_db, is_postgres


def generate_token() -> str:
    return secrets.token_hex(32)


async def get_current_player(
    authorization: str = Header(..., description="Bearer token from registration"),
    db=Depends(get_db)
) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must start with 'Bearer '")

    token = authorization.removeprefix("Bearer ").strip()

    if is_postgres():
        row = await db.fetchrow(
            "SELECT * FROM players WHERE token = $1 AND is_banned = 0", token
        )
    else:
        async with db.execute(
            "SELECT * FROM players WHERE token = ? AND is_banned = 0", (token,)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid or expired token. Re-attach the HUD to re-register.")

    return dict(row)
