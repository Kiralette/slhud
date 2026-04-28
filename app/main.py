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
from app.routers import players, actions, needs
from app.admin import panel
from app.services.decay import run_decay_tick

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
