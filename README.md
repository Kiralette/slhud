# SL Phone HUD — Backend

Python backend for the Second Life roleplay phone HUD system.
Tracks player needs, runs offline decay, manages moodlets and skills.

## Quickstart

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and configure environment
cp .env.example .env
# Edit .env — set ADMIN_SECRET to something long and random

# 4. Run the server
uvicorn app.main:app --reload
```

Server starts at http://localhost:8000
API docs at http://localhost:8000/docs

## Project structure

```
slhud/
├── config.yaml          ← All game values (needs, decay, moodlets, skills)
├── requirements.txt
├── .env.example
├── app/
│   ├── main.py          ← FastAPI entry point
│   ├── config.py        ← Hot-reloading config loader
│   ├── models/          ← Pydantic request/response models      [step 2]
│   ├── routers/         ← API endpoint definitions              [step 3-5]
│   ├── services/        ← Business logic (decay, moodlets, etc) [step 6-7]
│   └── admin/           ← Admin web panel                       [step 8]
├── data/
│   └── hud.db           ← SQLite database (auto-created)        [step 2]
└── tests/                                                        [ongoing]
```

## Build steps

- [x] Step 1 — Scaffold + config.yaml
- [ ] Step 2 — Database schema + init_db.py
- [ ] Step 3 — FastAPI skeleton + auth
- [ ] Step 4 — Core endpoints (register, action, sync)
- [ ] Step 5 — Needs endpoints
- [ ] Step 6 — Decay engine (APScheduler)
- [ ] Step 7 — Moodlet engine
- [ ] Step 8 — Admin panel
