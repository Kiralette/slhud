"""
SL Phone HUD — Backend Server
Entry point. Run with: python -m uvicorn app.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_config
from app.database import init_db
from app.routers import players, actions, needs, webapps, notifications, shop, career, social, flare, messages, calendar, cycle, occurrences, questionnaire
from app.admin import panel
from app.services.decay import run_decay_tick
from app.services.economy import rotate_weekly_specials, bill_subscriptions
from app.services.career import midnight_reset, auto_clockout_sweep
from app.services.flare import run_follower_engine, run_brand_deal_check
from app.services.ritual import (
    run_calendar_reminders, run_holiday_vibe_engine,
    run_cycle_prediction_update, run_pregnancy_progression, run_period_vibe_engine
)
from app.services.unexpected import run_unexpected_event_engine
from app.services.traits import run_trait_vibe_engine

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    print(f"\n✨ SL HUD backend starting up")
    print(f"   Needs loaded: {', '.join(cfg['needs'].keys())}")
    print(f"   Skills loaded: {', '.join(cfg['skills'].keys())}")
    print(f"   Decay interval: {cfg['server']['decay_interval_seconds']}s")
    await init_db()
    interval = cfg["server"]["decay_interval_seconds"]
    scheduler.add_job(run_decay_tick, "interval", seconds=interval, id="decay")
    scheduler.add_job(rotate_weekly_specials, "interval", seconds=60, id="specials_rotation")
    scheduler.add_job(bill_subscriptions, "interval", seconds=60, id="subscription_billing")
    scheduler.add_job(midnight_reset, "interval", seconds=60, id="midnight_reset")
    scheduler.add_job(auto_clockout_sweep, "interval", seconds=60, id="auto_clockout")
    scheduler.add_job(run_follower_engine, "interval", seconds=600, id="follower_engine")
    scheduler.add_job(run_brand_deal_check, "cron", day_of_week="sun", hour=0, minute=0, id="brand_deal_check")
    scheduler.add_job(run_calendar_reminders, "interval", seconds=1800, id="calendar_reminders")
    scheduler.add_job(run_holiday_vibe_engine, "cron", hour=0, minute=1, id="holiday_vibes")
    scheduler.add_job(run_cycle_prediction_update, "cron", hour=0, minute=2, id="cycle_prediction")
    scheduler.add_job(run_pregnancy_progression, "cron", hour=0, minute=3, id="pregnancy_progression")
    scheduler.add_job(run_period_vibe_engine, "cron", hour=0, minute=4, id="period_vibes")
    scheduler.add_job(run_unexpected_event_engine, "cron", hour=0, minute=5, id="unexpected_events")
    scheduler.add_job(run_trait_vibe_engine, "cron", hour=0, minute=10, id="trait_vibes")
    scheduler.start()
    print(f"   Decay engine started ✓ (every {interval}s)\n")
    yield
    scheduler.shutdown()
    print("\n👋 SL HUD backend shutting down")


app = FastAPI(
    title="SL Phone HUD API",
    description="Backend for the Second Life roleplay phone HUD system.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(players.router)
app.include_router(actions.router)
app.include_router(needs.router)
app.include_router(panel.router)
app.include_router(webapps.router)
app.include_router(notifications.router)
app.include_router(shop.router)
app.include_router(career.router)
app.include_router(social.router)
app.include_router(flare.router)
app.include_router(messages.router)
app.include_router(calendar.router)
app.include_router(cycle.router)
app.include_router(occurrences.router)
app.include_router(questionnaire.router)


@app.get("/", tags=["health"])
async def root():
    return {"status": "ok", "service": "SL HUD API", "version": "0.1.0"}


@app.get("/health", tags=["health"])
async def health():
    cfg = get_config()
    return {
        "status": "healthy",
        "needs_loaded": list(cfg["needs"].keys()),
        "skills_loaded": list(cfg["skills"].keys()),
        "decay_interval": cfg["server"]["decay_interval_seconds"],
        "decay_engine": "running" if scheduler.running else "stopped",
    }
