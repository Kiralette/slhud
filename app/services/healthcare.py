"""
Healthcare service — daily scheduled jobs.

  run_medication_reminders()     — daily: notify players whose medications expire soon
  run_appointment_reminders()    — daily: remind players of upcoming appointments
  run_insurance_billing()        — weekly: deduct insurance premiums from wallet
  run_missed_appointment_check() — daily: mark past scheduled appointments as missed
"""

from datetime import date, timedelta

from app.database import is_postgres
from app.services.notifications import push_notification


# ── Medication Reminders ──────────────────────────────────────────────────────

async def run_medication_reminders(db=None):
    """
    Daily: check all active medications with an end_date approaching.
    Notify players whose medication runs out within their refill_reminder_days window.
    """
    if db is None:
        return

    today = date.today()

    if is_postgres():
        rows = await db.fetch(
            """SELECT m.*, p.display_name
               FROM healthcare_medications m
               JOIN players p ON p.id = m.player_id
               WHERE m.is_active = 1 AND m.end_date IS NOT NULL""")
    else:
        async with db.execute(
            """SELECT m.*, p.display_name
               FROM healthcare_medications m
               JOIN players p ON p.id = m.player_id
               WHERE m.is_active = 1 AND m.end_date IS NOT NULL"""
        ) as cur:
            rows = await cur.fetchall()

    for row in rows:
        try:
            end   = date.fromisoformat(row["end_date"][:10])
            remind_days = int(row["refill_reminder_days"] or 7)
            remind_date = end - timedelta(days=remind_days)

            if today == remind_date:
                await push_notification(
                    player_id=row["player_id"],
                    app_source="healthcare",
                    title=f"Medication running low 💊",
                    body=f"{row['name']} runs out on {row['end_date'][:10]}. Schedule a refill consultation in MyChart.",
                    priority="normal",
                    db=db)

            # Auto-deactivate expired medications
            if today > end:
                if is_postgres():
                    await db.execute(
                        "UPDATE healthcare_medications SET is_active = 0 WHERE id = $1",
                        row["id"])
                else:
                    await db.execute(
                        "UPDATE healthcare_medications SET is_active = 0 WHERE id = ?",
                        (row["id"],))
        except Exception:
            pass

    if not is_postgres():
        await db.commit()


# ── Appointment Reminders ─────────────────────────────────────────────────────

async def run_appointment_reminders(db=None):
    """
    Daily: remind players of appointments scheduled for tomorrow.
    """
    if db is None:
        return

    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    if is_postgres():
        rows = await db.fetch(
            """SELECT a.*, p.display_name
               FROM healthcare_appointments a
               JOIN players p ON p.id = a.player_id
               WHERE a.status = 'scheduled' AND a.scheduled_date = $1""",
            tomorrow)
    else:
        async with db.execute(
            """SELECT a.*, p.display_name
               FROM healthcare_appointments a
               JOIN players p ON p.id = a.player_id
               WHERE a.status = 'scheduled' AND a.scheduled_date = ?""",
            (tomorrow,)
        ) as cur:
            rows = await cur.fetchall()

    for row in rows:
        time_str = f" at {row['scheduled_time']}" if row.get("scheduled_time") else ""
        await push_notification(
            player_id=row["player_id"],
            app_source="healthcare",
            title=f"Appointment tomorrow 🏥",
            body=f"{row['specialty']} with {row['doctor_name']}{time_str}. Open MyChart to prepare.",
            priority="normal",
            db=db)


# ── Missed Appointment Check ──────────────────────────────────────────────────

async def run_missed_appointment_check(db=None):
    """
    Daily: mark any scheduled appointments whose date has passed as 'missed'.
    """
    if db is None:
        return

    yesterday = (date.today() - timedelta(days=1)).isoformat()

    if is_postgres():
        rows = await db.fetch(
            """SELECT id, player_id, specialty, doctor_name
               FROM healthcare_appointments
               WHERE status = 'scheduled' AND scheduled_date <= $1""",
            yesterday)
    else:
        async with db.execute(
            """SELECT id, player_id, specialty, doctor_name
               FROM healthcare_appointments
               WHERE status = 'scheduled' AND scheduled_date <= ?""",
            (yesterday,)
        ) as cur:
            rows = await cur.fetchall()

    for row in rows:
        if is_postgres():
            await db.execute(
                "UPDATE healthcare_appointments SET status = 'missed' WHERE id = $1",
                row["id"])
        else:
            await db.execute(
                "UPDATE healthcare_appointments SET status = 'missed' WHERE id = ?",
                (row["id"],))

        await push_notification(
            player_id=row["player_id"],
            app_source="healthcare",
            title=f"Missed appointment 📋",
            body=f"Your {row['specialty']} with {row['doctor_name']} was missed. Reschedule in MyChart.",
            priority="low",
            db=db)

    if not is_postgres():
        await db.commit()


# ── Insurance Premium Billing ─────────────────────────────────────────────────

async def run_insurance_billing(db=None):
    """
    Weekly (Sundays): deduct insurance premium from wallet for private plan holders.
    Luminos Public and Uninsured have no premium.
    """
    if db is None:
        return

    WEEKLY_PREMIUMS = {
        "clarity_basic":    6,    # ~25/mo ÷ 4
        "clarity_plus":     15,   # ~60/mo ÷ 4
        "luminos_prestige": 30,   # ~120/mo ÷ 4
    }

    if is_postgres():
        rows = await db.fetch(
            """SELECT hp.player_id, hp.insurance_plan
               FROM healthcare_profiles hp
               WHERE hp.insurance_plan IN ('clarity_basic','clarity_plus','luminos_prestige')""")
    else:
        async with db.execute(
            """SELECT hp.player_id, hp.insurance_plan
               FROM healthcare_profiles hp
               WHERE hp.insurance_plan IN ('clarity_basic','clarity_plus','luminos_prestige')"""
        ) as cur:
            rows = await cur.fetchall()

    from app.routers.healthcare import INSURANCE_PLANS

    for row in rows:
        premium = WEEKLY_PREMIUMS.get(row["insurance_plan"], 0)
        if premium <= 0:
            continue

        plan_name = INSURANCE_PLANS.get(row["insurance_plan"], {}).get("name", row["insurance_plan"])

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        if is_postgres():
            await db.execute(
                """UPDATE wallets SET balance = GREATEST(0, balance - $1),
                   total_spent = total_spent + $2, last_updated = $3
                   WHERE player_id = $4""",
                premium, premium, now, row["player_id"])
            await db.execute(
                """INSERT INTO transactions (player_id, amount, type, description, timestamp)
                   VALUES ($1, $2, 'purchase', $3, $4)""",
                row["player_id"], -premium, f"Insurance premium: {plan_name}", now)
        else:
            await db.execute(
                """UPDATE wallets SET balance = MAX(0, balance - ?),
                   total_spent = total_spent + ?, last_updated = ?
                   WHERE player_id = ?""",
                (premium, premium, now, row["player_id"]))
            await db.execute(
                """INSERT INTO transactions (player_id, amount, type, description, timestamp)
                   VALUES (?, ?, 'purchase', ?, ?)""",
                (row["player_id"], -premium, f"Insurance premium: {plan_name}", now))

        await push_notification(
            player_id=row["player_id"],
            app_source="healthcare",
            title=f"Insurance premium deducted 💳",
            body=f"✦{premium} deducted for {plan_name} weekly premium.",
            priority="low",
            db=db)

    if not is_postgres():
        await db.commit()


# ── Vaccination Due Reminders ─────────────────────────────────────────────────

async def run_vaccination_reminders(db=None):
    """
    Daily: remind players of vaccinations due within the next 7 days.
    """
    if db is None:
        return

    today    = date.today()
    in_7days = (today + timedelta(days=7)).isoformat()

    if is_postgres():
        rows = await db.fetch(
            """SELECT * FROM healthcare_vaccinations
               WHERE next_due_date IS NOT NULL
               AND next_due_date >= $1 AND next_due_date <= $2""",
            today.isoformat(), in_7days)
    else:
        async with db.execute(
            """SELECT * FROM healthcare_vaccinations
               WHERE next_due_date IS NOT NULL
               AND next_due_date >= ? AND next_due_date <= ?""",
            (today.isoformat(), in_7days)
        ) as cur:
            rows = await cur.fetchall()

    for row in rows:
        await push_notification(
            player_id=row["player_id"],
            app_source="healthcare",
            title=f"Vaccination due soon 💉",
            body=f"{row['vaccine_name']} is due by {row['next_due_date']}. Schedule in MyChart.",
            priority="low",
            db=db)
