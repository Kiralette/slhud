"""
Horoscope service.

Fetches daily horoscopes from a free API, caches in DB per sign per day.
Falls back to hardcoded readings if the API is unavailable.
"""

import httpx
from datetime import date
from app.database import is_postgres, get_db_path, get_db_url

ZODIAC_META = {
    "aries":       ("♈", "#FF6B6B"),
    "taurus":      ("♉", "#9B7653"),
    "gemini":      ("♊", "#F7C59F"),
    "cancer":      ("♋", "#A8D8EA"),
    "leo":         ("♌", "#F9A825"),
    "virgo":       ("♍", "#7CB9A8"),
    "libra":       ("♎", "#C9B1BD"),
    "scorpio":     ("♏", "#6B3FA0"),
    "sagittarius": ("♐", "#E07B39"),
    "capricorn":   ("♑", "#708090"),
    "aquarius":    ("♒", "#5BC8F5"),
    "pisces":      ("♓", "#7FCDCD"),
}

# Fallback readings if API is down (3 per sign, rotates daily)
FALLBACK = {
    "aries":       ["Bold moves pay off today. Trust your instincts.", "Your energy is infectious right now.", "A moment of stillness reveals what the rush was hiding."],
    "taurus":      ["Comfort is earned today. Take the slow route.", "Something you've been building is about to be seen.", "Your patience is your superpower today."],
    "gemini":      ["Two ideas collide into something unexpectedly good.", "Say the thing you've been drafting. The timing is fine.", "Let one thought land before chasing the next."],
    "cancer":      ["Home feels like the answer today. Trust that.", "Someone needs your care more than they're letting on.", "Your intuition is a signal, not a spiral."],
    "leo":         ["You don't need the spotlight — but it finds you anyway.", "Your generosity lands differently right now.", "Quiet confidence is more powerful than a performance today."],
    "virgo":       ["Details you've been tracking quietly start to connect.", "Perfection is a starting point, not a destination.", "Your precision is a gift — so is knowing when to stop."],
    "libra":       ["Balance feels elusive, which means you're close.", "Someone wants your honest take. Give it gently.", "Beauty is in the small things today."],
    "scorpio":     ["What's hidden is becoming clear. Sit with it.", "Your intensity draws the right people closer.", "Trust is built in the silences, not just the words."],
    "sagittarius": ["Wander, even just in thought. Distance gives clarity.", "Something you dismissed as small turns out to matter.", "Your optimism is your navigation system today."],
    "capricorn":   ["The long game is paying dividends.", "Rest is part of the strategy, not a detour from it.", "Someone respects you more than they've said."],
    "aquarius":    ["Your unusual take turns out to be exactly right.", "Connection doesn't have to be conventional to be real.", "A system you've been watching has a flaw — you know the fix."],
    "pisces":      ["Dreams are data today. Pay attention.", "Empathy is your strength — include yourself in it.", "The fog clears around something you've been waiting to understand."],
}


def _fallback(sign: str, today: str) -> str:
    import hashlib
    seed = int(hashlib.md5(f"{sign}{today}".encode()).hexdigest(), 16)
    options = FALLBACK.get(sign, ["Today is yours to shape."])
    return options[seed % len(options)]


async def _fetch_from_api(sign: str) -> str | None:
    """Try to fetch from horoscope-app-api.vercel.app."""
    try:
        url = f"https://horoscope-app-api.vercel.app/api/v1/get-horoscope/daily?sign={sign}&day=today"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                # Response: {"data": {"date": "...", "horoscope_data": "..."}}
                horoscope_text = (
                    data.get("data", {}).get("horoscope_data") or
                    data.get("horoscope") or
                    data.get("description") or
                    data.get("text")
                )
                if horoscope_text and len(horoscope_text) > 10:
                    return horoscope_text.strip()
    except Exception:
        pass
    return None


async def get_horoscope(sign: str) -> dict:
    """
    Get today's horoscope for a zodiac sign.
    Checks DB cache first, fetches from API if not cached, falls back to hardcoded.
    """
    if not sign or sign not in ZODIAC_META:
        return None

    today = date.today().isoformat()
    symbol, color = ZODIAC_META[sign]

    # Check cache
    cached = await _get_cached(sign, today)
    if cached:
        return _build_result(sign, cached, today, symbol, color)

    # Fetch from API
    api_text = await _fetch_from_api(sign)
    text = api_text or _fallback(sign, today)

    # Store in cache
    await _store_cache(sign, today, text)

    return _build_result(sign, text, today, symbol, color)


def _build_result(sign, text, today, symbol, color):
    return {
        "zodiac": sign.title(),
        "symbol": symbol,
        "color": color,
        "text": text,
        "date": today,
        "source": "api" if len(text) > 80 else "generated",
    }


async def _get_cached(sign: str, today: str) -> str | None:
    if is_postgres():
        import asyncpg
        conn = await asyncpg.connect(get_db_url())
        try:
            row = await conn.fetchrow(
                "SELECT horoscope FROM horoscope_cache WHERE sign = $1 AND date = $2",
                sign, today)
            return row["horoscope"] if row else None
        finally:
            await conn.close()
    else:
        import aiosqlite
        async with aiosqlite.connect(get_db_path()) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT horoscope FROM horoscope_cache WHERE sign = ? AND date = ?",
                (sign, today)
            ) as cur:
                row = await cur.fetchone()
            return row["horoscope"] if row else None


async def _store_cache(sign: str, today: str, text: str) -> None:
    if is_postgres():
        import asyncpg
        conn = await asyncpg.connect(get_db_url())
        try:
            await conn.execute(
                """INSERT INTO horoscope_cache (sign, date, horoscope)
                   VALUES ($1, $2, $3) ON CONFLICT (sign, date) DO NOTHING""",
                sign, today, text)
        finally:
            await conn.close()
    else:
        import aiosqlite
        async with aiosqlite.connect(get_db_path()) as db:
            await db.execute(
                "INSERT OR IGNORE INTO horoscope_cache (sign, date, horoscope) VALUES (?, ?, ?)",
                (sign, today, text))
            await db.commit()
