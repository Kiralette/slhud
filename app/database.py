"""
Database — connection helper and table setup.

Automatically uses:
  - PostgreSQL when DATABASE_URL environment variable is set (Render, production)
  - SQLite when running locally (development)
"""

import os
import aiosqlite
from pathlib import Path
from app.config import get_config


def get_db_url():
    return os.environ.get("DATABASE_URL")


def get_db_path():
    return get_config()["database"]["path"]


def is_postgres():
    url = get_db_url()
    return url is not None and url.startswith("postgres")


async def get_db():
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
        db_path = get_db_path()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys = ON")
            yield db


async def init_db():
    if is_postgres():
        await _init_postgres()
    else:
        await _init_sqlite()


async def _init_sqlite():
    db_path = get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                avatar_uuid   TEXT    NOT NULL UNIQUE,
                display_name  TEXT    NOT NULL DEFAULT 'Unknown',
                token         TEXT    NOT NULL UNIQUE,
                registered_at TEXT    NOT NULL DEFAULT (datetime('now')),
                last_seen     TEXT    NOT NULL DEFAULT (datetime('now')),
                is_online     INTEGER NOT NULL DEFAULT 0,
                is_banned     INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS needs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id    INTEGER NOT NULL REFERENCES players(id),
                need_key     TEXT    NOT NULL,
                value        REAL    NOT NULL DEFAULT 100.0,
                last_updated TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(player_id, need_key)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS moodlets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id   INTEGER NOT NULL REFERENCES players(id),
                moodlet_key TEXT    NOT NULL,
                applied_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                expires_at  TEXT,
                is_negative INTEGER NOT NULL DEFAULT 0,
                UNIQUE(player_id, moodlet_key)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id   INTEGER NOT NULL REFERENCES players(id),
                skill_key   TEXT    NOT NULL,
                level       INTEGER NOT NULL DEFAULT 0,
                xp          REAL    NOT NULL DEFAULT 0.0,
                unlocked_at TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(player_id, skill_key)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS event_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id   INTEGER NOT NULL REFERENCES players(id),
                need_key    TEXT,
                action_text TEXT    NOT NULL,
                delta       REAL    NOT NULL DEFAULT 0.0,
                value_after REAL,
                timestamp   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.commit()
        print("   Database tables ready (SQLite)")


async def _init_postgres():
    import asyncpg
    url = get_db_url()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id            SERIAL PRIMARY KEY,
                avatar_uuid   TEXT    NOT NULL UNIQUE,
                display_name  TEXT    NOT NULL DEFAULT 'Unknown',
                token         TEXT    NOT NULL UNIQUE,
                registered_at TEXT    NOT NULL DEFAULT (now()::text),
                last_seen     TEXT    NOT NULL DEFAULT (now()::text),
                is_online     INTEGER NOT NULL DEFAULT 0,
                is_banned     INTEGER NOT NULL DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS needs (
                id           SERIAL PRIMARY KEY,
                player_id    INTEGER NOT NULL REFERENCES players(id),
                need_key     TEXT    NOT NULL,
                value        REAL    NOT NULL DEFAULT 100.0,
                last_updated TEXT    NOT NULL DEFAULT (now()::text),
                UNIQUE(player_id, need_key)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS moodlets (
                id          SERIAL PRIMARY KEY,
                player_id   INTEGER NOT NULL REFERENCES players(id),
                moodlet_key TEXT    NOT NULL,
                applied_at  TEXT    NOT NULL DEFAULT (now()::text),
                expires_at  TEXT,
                is_negative INTEGER NOT NULL DEFAULT 0,
                UNIQUE(player_id, moodlet_key)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                id          SERIAL PRIMARY KEY,
                player_id   INTEGER NOT NULL REFERENCES players(id),
                skill_key   TEXT    NOT NULL,
                level       INTEGER NOT NULL DEFAULT 0,
                xp          REAL    NOT NULL DEFAULT 0.0,
                unlocked_at TEXT    NOT NULL DEFAULT (now()::text),
                UNIQUE(player_id, skill_key)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS event_log (
                id          SERIAL PRIMARY KEY,
                player_id   INTEGER NOT NULL REFERENCES players(id),
                need_key    TEXT,
                action_text TEXT    NOT NULL,
                delta       REAL    NOT NULL DEFAULT 0.0,
                value_after REAL,
                timestamp   TEXT    NOT NULL DEFAULT (now()::text)
            )
        """)
        print("   Database tables ready (PostgreSQL)")
    finally:
        await conn.close()
