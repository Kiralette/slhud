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
            CREATE TABLE IF NOT EXISTS vibes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id   INTEGER NOT NULL REFERENCES players(id),
                vibe_key TEXT    NOT NULL,
                applied_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                expires_at  TEXT,
                is_negative INTEGER NOT NULL DEFAULT 0,
                UNIQUE(player_id, vibe_key)
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

        # --- IDENTITY & PROFILE ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS player_profiles (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id                   INTEGER NOT NULL UNIQUE REFERENCES players(id),
                bio                         TEXT    DEFAULT '',
                pronouns                    TEXT    DEFAULT '',
                age_group                   TEXT    DEFAULT '',
                sexuality                   TEXT    DEFAULT '',
                biology_agab                TEXT    DEFAULT '',
                gender_expression           TEXT    DEFAULT '',
                questionnaire_completed_at  TEXT,
                questionnaire_last_edited_at TEXT,
                zodiac                      TEXT,
                is_mental_health_opted_in   INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS player_traits (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id  INTEGER NOT NULL REFERENCES players(id),
                trait_key  TEXT    NOT NULL,
                applied_at TEXT    NOT NULL DEFAULT (datetime('now')),
                source     TEXT    NOT NULL DEFAULT 'questionnaire',
                UNIQUE(player_id, trait_key)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS player_settings (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id             INTEGER NOT NULL UNIQUE REFERENCES players(id),
                notification_prefs    TEXT    NOT NULL DEFAULT '{}',
                privacy_prefs         TEXT    NOT NULL DEFAULT '{}',
                theme_case_color      TEXT    NOT NULL DEFAULT '#7f77dd',
                theme_wallpaper_uuid  TEXT    DEFAULT NULL,
                is_muted              INTEGER NOT NULL DEFAULT 0,
                timezone_offset_hours REAL    NOT NULL DEFAULT 0.0,
                bedtime_slt           TEXT    DEFAULT NULL,
                sleep_streak_days     INTEGER NOT NULL DEFAULT 0
            )
        """)
        # --- ECONOMY ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id     INTEGER NOT NULL UNIQUE REFERENCES players(id),
                balance       REAL    NOT NULL DEFAULT 500.0,
                total_earned  REAL    NOT NULL DEFAULT 0.0,
                total_spent   REAL    NOT NULL DEFAULT 0.0,
                last_updated  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id   INTEGER NOT NULL REFERENCES players(id),
                amount      REAL    NOT NULL,
                type        TEXT    NOT NULL,
                description TEXT    NOT NULL DEFAULT '',
                related_id  INTEGER DEFAULT NULL,
                timestamp   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id         INTEGER NOT NULL REFERENCES players(id),
                subscription_key  TEXT    NOT NULL,
                started_at        TEXT    NOT NULL DEFAULT (datetime('now')),
                next_billing_at   TEXT,
                is_active         INTEGER NOT NULL DEFAULT 1,
                cancelled_at      TEXT    DEFAULT NULL,
                UNIQUE(player_id, subscription_key)
            )
        """)
        # --- CAREER & JOBS ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS employment (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id         INTEGER NOT NULL UNIQUE REFERENCES players(id),
                career_path_key   TEXT    DEFAULT NULL,
                tier_level        INTEGER NOT NULL DEFAULT 0,
                job_title         TEXT    DEFAULT NULL,
                clocked_in_at     TEXT    DEFAULT NULL,
                last_heartbeat_at TEXT    DEFAULT NULL,
                is_clocked_in     INTEGER NOT NULL DEFAULT 0,
                hours_today       REAL    NOT NULL DEFAULT 0.0,
                days_at_tier      INTEGER NOT NULL DEFAULT 0,
                total_days_worked INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS career_history (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id        INTEGER NOT NULL REFERENCES players(id),
                career_path_key  TEXT    NOT NULL,
                tier_level       INTEGER NOT NULL,
                job_title        TEXT    NOT NULL,
                started_at       TEXT    NOT NULL DEFAULT (datetime('now')),
                ended_at         TEXT    DEFAULT NULL,
                total_shifts     INTEGER NOT NULL DEFAULT 0,
                total_earned     REAL    NOT NULL DEFAULT 0.0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS odd_job_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id     INTEGER NOT NULL REFERENCES players(id),
                odd_job_key   TEXT    NOT NULL,
                completed_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                amount_earned REAL    NOT NULL DEFAULT 0.0
            )
        """)
        # --- SOCIAL & MESSAGING ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS follows (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                follower_id   INTEGER NOT NULL REFERENCES players(id),
                following_id  INTEGER NOT NULL REFERENCES players(id),
                followed_at   TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(follower_id, following_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS proximity_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id        INTEGER NOT NULL REFERENCES players(id),
                nearby_player_id INTEGER NOT NULL REFERENCES players(id),
                first_seen_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                last_seen_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                session_count    INTEGER NOT NULL DEFAULT 1,
                last_zone        TEXT    DEFAULT NULL,
                UNIQUE(player_id, nearby_player_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_threads (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                player_a_id      INTEGER NOT NULL REFERENCES players(id),
                player_b_id      INTEGER NOT NULL REFERENCES players(id),
                last_message_at  TEXT    DEFAULT NULL,
                unread_count_a   INTEGER NOT NULL DEFAULT 0,
                unread_count_b   INTEGER NOT NULL DEFAULT 0,
                UNIQUE(player_a_id, player_b_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id  INTEGER NOT NULL REFERENCES message_threads(id),
                sender_id  INTEGER NOT NULL REFERENCES players(id),
                content    TEXT    NOT NULL,
                sent_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                is_read    INTEGER NOT NULL DEFAULT 0
            )
        """)
        # --- FLARE (FEED) ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id              INTEGER NOT NULL REFERENCES players(id),
                content_text           TEXT    NOT NULL DEFAULT '',
                category               TEXT    NOT NULL DEFAULT 'life',
                quality_tier           INTEGER NOT NULL DEFAULT 0,
                follower_count_at_post INTEGER NOT NULL DEFAULT 0,
                npc_likes              INTEGER NOT NULL DEFAULT 0,
                npc_comments           INTEGER NOT NULL DEFAULT 0,
                is_brand_deal_post     INTEGER NOT NULL DEFAULT 0,
                brand_deal_id          INTEGER DEFAULT NULL,
                created_at             TEXT    NOT NULL DEFAULT (datetime('now')),
                expires_at             TEXT    DEFAULT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS post_engagements (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id    INTEGER NOT NULL REFERENCES posts(id),
                player_id  INTEGER NOT NULL REFERENCES players(id),
                type       TEXT    NOT NULL DEFAULT 'like',
                content    TEXT    DEFAULT NULL,
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS flare_stats (
                id                         INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id                  INTEGER NOT NULL UNIQUE REFERENCES players(id),
                follower_count             INTEGER NOT NULL DEFAULT 0,
                weekly_post_count          INTEGER NOT NULL DEFAULT 0,
                active_brand_deal_key      TEXT    DEFAULT NULL,
                brand_deal_started_at      TEXT    DEFAULT NULL,
                brand_deal_posts_this_week INTEGER NOT NULL DEFAULT 0,
                last_post_at               TEXT    DEFAULT NULL,
                post_streak_days           INTEGER NOT NULL DEFAULT 0
            )
        """)
        # --- CALENDAR ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id          INTEGER NOT NULL REFERENCES players(id),
                title              TEXT    NOT NULL,
                event_type         TEXT    NOT NULL DEFAULT 'personal',
                event_date_slt     TEXT    NOT NULL,
                end_date_slt       TEXT    DEFAULT NULL,
                is_recurring       INTEGER NOT NULL DEFAULT 0,
                recurrence_rule    TEXT    DEFAULT NULL,
                is_public          INTEGER NOT NULL DEFAULT 0,
                visibility         TEXT    NOT NULL DEFAULT 'private',
                color_key          TEXT    NOT NULL DEFAULT 'purple',
                generates_vibe_key TEXT    DEFAULT NULL,
                rsvp_count         INTEGER NOT NULL DEFAULT 0,
                notes              TEXT    DEFAULT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cycle_log (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id            INTEGER NOT NULL REFERENCES players(id),
                cycle_start_slt      TEXT    NOT NULL,
                cycle_end_slt        TEXT    DEFAULT NULL,
                period_duration_days INTEGER DEFAULT NULL,
                cycle_length_days    INTEGER DEFAULT NULL,
                avg_cycle_length     REAL    DEFAULT NULL,
                next_predicted_start TEXT    DEFAULT NULL,
                is_manual_override   INTEGER NOT NULL DEFAULT 0,
                logged_at            TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # --- OCCURRENCES ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS player_occurrences (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id      INTEGER NOT NULL REFERENCES players(id),
                occurrence_key TEXT    NOT NULL,
                started_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                ends_at        TEXT    DEFAULT NULL,
                sub_stage      TEXT    DEFAULT NULL,
                is_unexpected  INTEGER NOT NULL DEFAULT 0,
                is_dismissed   INTEGER NOT NULL DEFAULT 0,
                is_resolved    INTEGER NOT NULL DEFAULT 0,
                metadata       TEXT    NOT NULL DEFAULT '{}'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS occurrence_vibe_log (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id      INTEGER NOT NULL REFERENCES players(id),
                occurrence_key TEXT    NOT NULL,
                vibe_key       TEXT    NOT NULL,
                fired_at       TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vibe_log (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id      INTEGER NOT NULL REFERENCES players(id),
                vibe_key       TEXT    NOT NULL,
                trigger_source TEXT    DEFAULT NULL,
                fired_at       TEXT    NOT NULL DEFAULT (datetime('now')),
                expired_at     TEXT    DEFAULT NULL
            )
        """)
        # --- ACHIEVEMENTS & STATS ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS horoscope_cache (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sign        TEXT    NOT NULL,
                date        TEXT    NOT NULL,
                horoscope   TEXT    NOT NULL,
                fetched_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(sign, date)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS player_achievements (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id       INTEGER NOT NULL REFERENCES players(id),
                achievement_key TEXT    NOT NULL,
                unlocked_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                is_notified     INTEGER NOT NULL DEFAULT 0,
                UNIQUE(player_id, achievement_key)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS player_stats (
                id                        INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id                 INTEGER NOT NULL UNIQUE REFERENCES players(id),
                days_alive                INTEGER NOT NULL DEFAULT 0,
                total_lumens_earned       REAL    NOT NULL DEFAULT 0.0,
                total_meals_eaten         INTEGER NOT NULL DEFAULT 0,
                total_skill_xp_earned     REAL    NOT NULL DEFAULT 0.0,
                total_players_met         INTEGER NOT NULL DEFAULT 0,
                total_vibes_fired         INTEGER NOT NULL DEFAULT 0,
                total_posts_made          INTEGER NOT NULL DEFAULT 0,
                lifetime_followers_gained INTEGER NOT NULL DEFAULT 0,
                total_shifts_worked       INTEGER NOT NULL DEFAULT 0,
                last_updated              TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # --- NOTIFICATIONS ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id    INTEGER NOT NULL REFERENCES players(id),
                app_source   TEXT    NOT NULL DEFAULT 'system',
                title        TEXT    NOT NULL,
                body         TEXT    NOT NULL DEFAULT '',
                priority     TEXT    NOT NULL DEFAULT 'normal',
                is_read      INTEGER NOT NULL DEFAULT 0,
                is_toasted   INTEGER NOT NULL DEFAULT 0,
                action_url   TEXT    DEFAULT NULL,
                created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # --- STREAMING ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS streaming_sessions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id        INTEGER NOT NULL REFERENCES players(id),
                station_key      TEXT    NOT NULL,
                started_at       TEXT    NOT NULL DEFAULT (datetime('now')),
                ended_at         TEXT    DEFAULT NULL,
                duration_minutes REAL    NOT NULL DEFAULT 0.0,
                xp_earned        REAL    NOT NULL DEFAULT 0.0,
                is_premium       INTEGER NOT NULL DEFAULT 0
            )
        """)
        # --- FITNESS ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS workout_plans (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id         INTEGER NOT NULL UNIQUE REFERENCES players(id),
                target_days       TEXT    NOT NULL DEFAULT '[]',
                reminder_time_slt TEXT    DEFAULT NULL,
                created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
                is_active         INTEGER NOT NULL DEFAULT 1
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS weekly_specials (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                item_key             TEXT    NOT NULL,
                special_price        REAL    NOT NULL,
                display_name_override TEXT   DEFAULT NULL,
                available_from       TEXT    NOT NULL,
                available_until      TEXT    NOT NULL,
                is_pinned            INTEGER NOT NULL DEFAULT 0,
                created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
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
            CREATE TABLE IF NOT EXISTS vibes (
                id          SERIAL PRIMARY KEY,
                player_id   INTEGER NOT NULL REFERENCES players(id),
                vibe_key TEXT    NOT NULL,
                applied_at  TEXT    NOT NULL DEFAULT (now()::text),
                expires_at  TEXT,
                is_negative INTEGER NOT NULL DEFAULT 0,
                UNIQUE(player_id, vibe_key)
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

        # --- IDENTITY & PROFILE ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS player_profiles (
                id                          SERIAL PRIMARY KEY,
                player_id                   INTEGER NOT NULL UNIQUE REFERENCES players(id),
                bio                         TEXT    DEFAULT \'\',
                pronouns                    TEXT    DEFAULT \'\',
                age_group                   TEXT    DEFAULT \'\',
                sexuality                   TEXT    DEFAULT \'\',
                biology_agab                TEXT    DEFAULT \'\',
                gender_expression           TEXT    DEFAULT \'\',
                questionnaire_completed_at  TEXT,
                questionnaire_last_edited_at TEXT,
                zodiac                      TEXT,
                is_mental_health_opted_in   INTEGER NOT NULL DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS player_traits (
                id         SERIAL PRIMARY KEY,
                player_id  INTEGER NOT NULL REFERENCES players(id),
                trait_key  TEXT    NOT NULL,
                applied_at TEXT    NOT NULL DEFAULT (now()::text),
                source     TEXT    NOT NULL DEFAULT \'questionnaire\',
                UNIQUE(player_id, trait_key)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS player_settings (
                id                    SERIAL PRIMARY KEY,
                player_id             INTEGER NOT NULL UNIQUE REFERENCES players(id),
                notification_prefs    TEXT    NOT NULL DEFAULT \'{}\',
                privacy_prefs         TEXT    NOT NULL DEFAULT \'{}\',
                theme_case_color      TEXT    NOT NULL DEFAULT \'#7f77dd\',
                theme_wallpaper_uuid  TEXT    DEFAULT NULL,
                is_muted              INTEGER NOT NULL DEFAULT 0,
                timezone_offset_hours REAL    NOT NULL DEFAULT 0.0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                id            SERIAL PRIMARY KEY,
                player_id     INTEGER NOT NULL UNIQUE REFERENCES players(id),
                balance       REAL    NOT NULL DEFAULT 500.0,
                total_earned  REAL    NOT NULL DEFAULT 0.0,
                total_spent   REAL    NOT NULL DEFAULT 0.0,
                last_updated  TEXT    NOT NULL DEFAULT (now()::text)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id          SERIAL PRIMARY KEY,
                player_id   INTEGER NOT NULL REFERENCES players(id),
                amount      REAL    NOT NULL,
                type        TEXT    NOT NULL,
                description TEXT    NOT NULL DEFAULT \'\',
                related_id  INTEGER DEFAULT NULL,
                timestamp   TEXT    NOT NULL DEFAULT (now()::text)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id                SERIAL PRIMARY KEY,
                player_id         INTEGER NOT NULL REFERENCES players(id),
                subscription_key  TEXT    NOT NULL,
                started_at        TEXT    NOT NULL DEFAULT (now()::text),
                next_billing_at   TEXT,
                is_active         INTEGER NOT NULL DEFAULT 1,
                cancelled_at      TEXT    DEFAULT NULL,
                UNIQUE(player_id, subscription_key)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS employment (
                id                SERIAL PRIMARY KEY,
                player_id         INTEGER NOT NULL UNIQUE REFERENCES players(id),
                career_path_key   TEXT    DEFAULT NULL,
                tier_level        INTEGER NOT NULL DEFAULT 0,
                job_title         TEXT    DEFAULT NULL,
                clocked_in_at     TEXT    DEFAULT NULL,
                last_heartbeat_at TEXT    DEFAULT NULL,
                is_clocked_in     INTEGER NOT NULL DEFAULT 0,
                hours_today       REAL    NOT NULL DEFAULT 0.0,
                days_at_tier      INTEGER NOT NULL DEFAULT 0,
                total_days_worked INTEGER NOT NULL DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS career_history (
                id               SERIAL PRIMARY KEY,
                player_id        INTEGER NOT NULL REFERENCES players(id),
                career_path_key  TEXT    NOT NULL,
                tier_level       INTEGER NOT NULL,
                job_title        TEXT    NOT NULL,
                started_at       TEXT    NOT NULL DEFAULT (now()::text),
                ended_at         TEXT    DEFAULT NULL,
                total_shifts     INTEGER NOT NULL DEFAULT 0,
                total_earned     REAL    NOT NULL DEFAULT 0.0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS odd_job_log (
                id            SERIAL PRIMARY KEY,
                player_id     INTEGER NOT NULL REFERENCES players(id),
                odd_job_key   TEXT    NOT NULL,
                completed_at  TEXT    NOT NULL DEFAULT (now()::text),
                amount_earned REAL    NOT NULL DEFAULT 0.0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS follows (
                id            SERIAL PRIMARY KEY,
                follower_id   INTEGER NOT NULL REFERENCES players(id),
                following_id  INTEGER NOT NULL REFERENCES players(id),
                followed_at   TEXT    NOT NULL DEFAULT (now()::text),
                UNIQUE(follower_id, following_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS proximity_log (
                id               SERIAL PRIMARY KEY,
                player_id        INTEGER NOT NULL REFERENCES players(id),
                nearby_player_id INTEGER NOT NULL REFERENCES players(id),
                first_seen_at    TEXT    NOT NULL DEFAULT (now()::text),
                last_seen_at     TEXT    NOT NULL DEFAULT (now()::text),
                session_count    INTEGER NOT NULL DEFAULT 1,
                last_zone        TEXT    DEFAULT NULL,
                UNIQUE(player_id, nearby_player_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS message_threads (
                id               SERIAL PRIMARY KEY,
                player_a_id      INTEGER NOT NULL REFERENCES players(id),
                player_b_id      INTEGER NOT NULL REFERENCES players(id),
                last_message_at  TEXT    DEFAULT NULL,
                unread_count_a   INTEGER NOT NULL DEFAULT 0,
                unread_count_b   INTEGER NOT NULL DEFAULT 0,
                UNIQUE(player_a_id, player_b_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         SERIAL PRIMARY KEY,
                thread_id  INTEGER NOT NULL REFERENCES message_threads(id),
                sender_id  INTEGER NOT NULL REFERENCES players(id),
                content    TEXT    NOT NULL,
                sent_at    TEXT    NOT NULL DEFAULT (now()::text),
                is_read    INTEGER NOT NULL DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id                     SERIAL PRIMARY KEY,
                player_id              INTEGER NOT NULL REFERENCES players(id),
                content_text           TEXT    NOT NULL DEFAULT \'\',
                category               TEXT    NOT NULL DEFAULT \'life\',
                quality_tier           INTEGER NOT NULL DEFAULT 0,
                follower_count_at_post INTEGER NOT NULL DEFAULT 0,
                npc_likes              INTEGER NOT NULL DEFAULT 0,
                npc_comments           INTEGER NOT NULL DEFAULT 0,
                is_brand_deal_post     INTEGER NOT NULL DEFAULT 0,
                brand_deal_id          INTEGER DEFAULT NULL,
                created_at             TEXT    NOT NULL DEFAULT (now()::text),
                expires_at             TEXT    DEFAULT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS post_engagements (
                id         SERIAL PRIMARY KEY,
                post_id    INTEGER NOT NULL REFERENCES posts(id),
                player_id  INTEGER NOT NULL REFERENCES players(id),
                type       TEXT    NOT NULL DEFAULT \'like\',
                content    TEXT    DEFAULT NULL,
                created_at TEXT    NOT NULL DEFAULT (now()::text)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS flare_stats (
                id                         SERIAL PRIMARY KEY,
                player_id                  INTEGER NOT NULL UNIQUE REFERENCES players(id),
                follower_count             INTEGER NOT NULL DEFAULT 0,
                weekly_post_count          INTEGER NOT NULL DEFAULT 0,
                active_brand_deal_key      TEXT    DEFAULT NULL,
                brand_deal_started_at      TEXT    DEFAULT NULL,
                brand_deal_posts_this_week INTEGER NOT NULL DEFAULT 0,
                last_post_at               TEXT    DEFAULT NULL,
                post_streak_days           INTEGER NOT NULL DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id                 SERIAL PRIMARY KEY,
                player_id          INTEGER NOT NULL REFERENCES players(id),
                title              TEXT    NOT NULL,
                event_type         TEXT    NOT NULL DEFAULT \'personal\',
                event_date_slt     TEXT    NOT NULL,
                end_date_slt       TEXT    DEFAULT NULL,
                is_recurring       INTEGER NOT NULL DEFAULT 0,
                recurrence_rule    TEXT    DEFAULT NULL,
                is_public          INTEGER NOT NULL DEFAULT 0,
                visibility         TEXT    NOT NULL DEFAULT \'private\',
                color_key          TEXT    NOT NULL DEFAULT \'purple\',
                generates_vibe_key TEXT    DEFAULT NULL,
                rsvp_count         INTEGER NOT NULL DEFAULT 0,
                notes              TEXT    DEFAULT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cycle_log (
                id                   SERIAL PRIMARY KEY,
                player_id            INTEGER NOT NULL REFERENCES players(id),
                cycle_start_slt      TEXT    NOT NULL,
                cycle_end_slt        TEXT    DEFAULT NULL,
                period_duration_days INTEGER DEFAULT NULL,
                cycle_length_days    INTEGER DEFAULT NULL,
                avg_cycle_length     REAL    DEFAULT NULL,
                next_predicted_start TEXT    DEFAULT NULL,
                is_manual_override   INTEGER NOT NULL DEFAULT 0,
                logged_at            TEXT    NOT NULL DEFAULT (now()::text)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS player_occurrences (
                id             SERIAL PRIMARY KEY,
                player_id      INTEGER NOT NULL REFERENCES players(id),
                occurrence_key TEXT    NOT NULL,
                started_at     TEXT    NOT NULL DEFAULT (now()::text),
                ends_at        TEXT    DEFAULT NULL,
                sub_stage      TEXT    DEFAULT NULL,
                is_unexpected  INTEGER NOT NULL DEFAULT 0,
                is_dismissed   INTEGER NOT NULL DEFAULT 0,
                is_resolved    INTEGER NOT NULL DEFAULT 0,
                metadata       TEXT    NOT NULL DEFAULT \'{}\'
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS occurrence_vibe_log (
                id             SERIAL PRIMARY KEY,
                player_id      INTEGER NOT NULL REFERENCES players(id),
                occurrence_key TEXT    NOT NULL,
                vibe_key       TEXT    NOT NULL,
                fired_at       TEXT    NOT NULL DEFAULT (now()::text)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS vibe_log (
                id             SERIAL PRIMARY KEY,
                player_id      INTEGER NOT NULL REFERENCES players(id),
                vibe_key       TEXT    NOT NULL,
                trigger_source TEXT    DEFAULT NULL,
                fired_at       TEXT    NOT NULL DEFAULT (now()::text),
                expired_at     TEXT    DEFAULT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS horoscope_cache (
                id          SERIAL PRIMARY KEY,
                sign        TEXT    NOT NULL,
                date        TEXT    NOT NULL,
                horoscope   TEXT    NOT NULL,
                fetched_at  TEXT    NOT NULL DEFAULT now()::text,
                UNIQUE(sign, date)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS player_achievements (
                id              SERIAL PRIMARY KEY,
                player_id       INTEGER NOT NULL REFERENCES players(id),
                achievement_key TEXT    NOT NULL,
                unlocked_at     TEXT    NOT NULL DEFAULT (now()::text),
                is_notified     INTEGER NOT NULL DEFAULT 0,
                UNIQUE(player_id, achievement_key)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS player_stats (
                id                        SERIAL PRIMARY KEY,
                player_id                 INTEGER NOT NULL UNIQUE REFERENCES players(id),
                days_alive                INTEGER NOT NULL DEFAULT 0,
                total_lumens_earned       REAL    NOT NULL DEFAULT 0.0,
                total_meals_eaten         INTEGER NOT NULL DEFAULT 0,
                total_skill_xp_earned     REAL    NOT NULL DEFAULT 0.0,
                total_players_met         INTEGER NOT NULL DEFAULT 0,
                total_vibes_fired         INTEGER NOT NULL DEFAULT 0,
                total_posts_made          INTEGER NOT NULL DEFAULT 0,
                lifetime_followers_gained INTEGER NOT NULL DEFAULT 0,
                total_shifts_worked       INTEGER NOT NULL DEFAULT 0,
                last_updated              TEXT    NOT NULL DEFAULT (now()::text)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id         SERIAL PRIMARY KEY,
                player_id  INTEGER NOT NULL REFERENCES players(id),
                app_source TEXT    NOT NULL DEFAULT \'system\',
                title      TEXT    NOT NULL,
                body       TEXT    NOT NULL DEFAULT \'\',
                is_read    INTEGER NOT NULL DEFAULT 0,
                action_url TEXT    DEFAULT NULL,
                created_at TEXT    NOT NULL DEFAULT (now()::text)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS streaming_sessions (
                id               SERIAL PRIMARY KEY,
                player_id        INTEGER NOT NULL REFERENCES players(id),
                station_key      TEXT    NOT NULL,
                started_at       TEXT    NOT NULL DEFAULT (now()::text),
                ended_at         TEXT    DEFAULT NULL,
                duration_minutes REAL    NOT NULL DEFAULT 0.0,
                xp_earned        REAL    NOT NULL DEFAULT 0.0,
                is_premium       INTEGER NOT NULL DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workout_plans (
                id                SERIAL PRIMARY KEY,
                player_id         INTEGER NOT NULL UNIQUE REFERENCES players(id),
                target_days       TEXT    NOT NULL DEFAULT \'[]\',
                reminder_time_slt TEXT    DEFAULT NULL,
                created_at        TEXT    NOT NULL DEFAULT (now()::text),
                is_active         INTEGER NOT NULL DEFAULT 1
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS weekly_specials (
                id                   SERIAL PRIMARY KEY,
                item_key             TEXT    NOT NULL,
                special_price        REAL    NOT NULL,
                display_name_override TEXT   DEFAULT NULL,
                available_from       TEXT    NOT NULL,
                available_until      TEXT    NOT NULL,
                is_pinned            INTEGER NOT NULL DEFAULT 0,
                created_at           TEXT    NOT NULL DEFAULT (now()::text)
            )
        """)

        print("   Database tables ready (PostgreSQL)")
    finally:
        await conn.close()
