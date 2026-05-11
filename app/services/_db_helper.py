"""
Shared async database connection helper for scheduled services.
All service functions that run from the APScheduler (db=None) should use
_with_db() to acquire their own connection rather than bailing out.
"""
from contextlib import asynccontextmanager
from app.database import is_postgres, get_db_url, get_db_path


@asynccontextmanager
async def service_db():
    """
    Async context manager that yields a live DB connection/session.
    Works for both Postgres (asyncpg) and SQLite (aiosqlite).

    Usage:
        async with service_db() as db:
            rows = await db.fetch(...)  # postgres
            # or
            async with db.execute(...) as cur:  # sqlite
                rows = await cur.fetchall()
    """
    if is_postgres():
        import asyncpg
        url = get_db_url()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        conn = await asyncpg.connect(url)
        try:
            yield conn
        finally:
            await conn.close()
    else:
        import aiosqlite
        db_path = get_db_path()
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            yield db
