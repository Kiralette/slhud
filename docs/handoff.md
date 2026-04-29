# SL Phone HUD — Master Session Handoff Document
# Give this to Claude at the start of every new session.
# Last updated: Session 3 complete
# ============================================================

# ============================================================
# PROJECT IDENTITY
# ============================================================

project: SL Phone HUD
description: >
  A Second Life roleplay phone HUD system — a slice-of-life sim tool
  inspired by The Sims 4. Players wear the HUD in SL, it tracks needs,
  skills, vibes, careers, economy, social features, and life occurrences.
  All apps are webapps served by FastAPI and displayed via llMediaOnFace
  on the HUD prim. No dark themes — aesthetic is minimal chic luxe.

owner: Kaitlyn Crenshaw (Kira / Madame Kira)
claude_name: Elara
repo: github.com/Kiralette/slhud
live_url: https://slhud.onrender.com
admin_panel: https://slhud.onrender.com/admin?secret=[secret]
local_dev: "cd D:\slhud_step1\slhud && python -m uvicorn app.main:app --reload"
stack: FastAPI + SQLite (local) / PostgreSQL (Render) + Jinja2 templates
python: 3.14 on Windows locally

# ============================================================
# SESSIONS COMPLETED
# ============================================================

session_1:
  summary: "Initial backend built — players, needs, decay engine, vibes engine, skills, auth, admin panel"
  key_decisions:
    - "7 needs: hunger, thirst, energy, fun, social, hygiene, purpose (composite)"
    - "7 skills: cooking, creativity, charisma, fitness, gaming, music, knowledge"
    - "Decay runs every 60s via APScheduler"
    - "SQLite locally, PostgreSQL on Render via asyncpg"
    - "Bearer token auth — token in URL for webapps"

session_2:
  summary: "Renamed moodlets→vibes, added 26 new DB tables, added economy/career/shop/wavelength config"
  key_decisions:
    - "moodlets renamed to vibes everywhere — table, config, endpoints"
    - "All 31 tables created (see table list below)"
    - "config.yaml now has: economy, shop_items, subscriptions, careers, wavelength sections"
    - "Currency is Lumens (✦) — starting balance ✦500"
    - "L$ rate: L$250 = ✦50"
    - "17 career paths with 3-5 tiers each, ~20% raise per tier"
    - "Max shift: 4 hours, pay deposited at clock-out"
    - "Heartbeat system: attachment pings every 60s, 2 missed = auto clock-out"
    - "Weekly specials: rotate Sunday midnight SLT"

session_3:
  summary: "Notification system built, Lumen Eats webapp built, aesthetic redesigned"
  key_decisions:
    - "Aesthetic: minimal chic luxe — warm ivory (#faf9f7), Cormorant Garamond headings, Jost body, muted gold (#9a7c4e)"
    - "NO dark themes, NO neon, NO gradients on backgrounds"
    - "Base template: app/templates/base.html — all apps extend this"
    - "Lumen Eats webapp: app/templates/apps/lumen_eats.html"
    - "Webapp router: app/routers/webapps.py"
    - "Notification service: app/services/notifications.py"
    - "Notification router: app/routers/notifications.py"
    - "Notifications have priority: low / normal / urgent"
    - "Decay engine fires notifications when needs cross warning/critical zones"
    - "HUD polls /notifications/unread-count every 60s for red dot data"
    - "HUD polls /notifications/urgent-toast every 60s for llOwnerSay messages"
    - "Beverages belong in Sip app — Lumen Eats is food only"
    - "Food items will eventually be real named foods (sushi, grapes etc)"

render_migration_needed:
  - "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'normal';"
  - "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS is_toasted INTEGER NOT NULL DEFAULT 0;"

# ============================================================
# ALL DATABASE TABLES (31 + weekly_specials = 32)
# ============================================================

tables_built:
  existing_from_session_1: [players, needs, event_log, vibes, skills]
  added_session_2:
    identity: [player_profiles, player_traits, player_settings]
    economy: [wallets, transactions, subscriptions]
    career: [employment, career_history, odd_job_log]
    social: [follows, proximity_log, message_threads, messages]
    feed: [posts, post_engagements, flare_stats]
    calendar: [calendar_events, cycle_log]
    occurrences: [player_occurrences, occurrence_vibe_log, vibe_log]
    achievements: [player_achievements, player_stats]
    system: [notifications, streaming_sessions, workout_plans]
  added_session_3: [weekly_specials]

# ============================================================
# APP LIST — 18 APPS TOTAL
# ============================================================
# All apps are webapps at /app/{name}?token=...
# Token stays in URL for all links/forms (SL browser has no cookies)
# All apps extend base.html (minimal chic luxe aesthetic)

apps:
  pulse:
    name: "Pulse"
    url: "/app/pulse"
    type: "Home widget"
    shows: "All 7 needs + wallet balance. Active vibes as pills. Tap any bar to open that app."

  lumen_eats:
    name: "Lumen Eats"
    url: "/app/lumen-eats"
    type: "Hunger need + food ordering"
    tabs: [Order, Market, Activity]
    order_tab: "Weekly specials (rotates Sunday) + always-available base items. Buy → Lumens deducted → need effect applied. Delivery system TBD (CasperVend or custom giver)."
    market_tab: "Nearby in-world food vendors detected by zone objects"
    activity_tab: "Last 20 hunger log entries"
    notes: "Food only — no beverages. Items will become real named foods (sushi, grapes etc)"
    status: "UI built — buy endpoint not yet wired"

  sip:
    name: "Sip"
    url: "/app/sip"
    type: "Thirst need + drink ordering"
    notes: "ALL beverages live here — water (free), coffee, juice, energy drink, specialty drinks. Same structure as Lumen Eats."
    status: "Not built yet"

  recharge:
    name: "Recharge"
    url: "/app/recharge"
    type: "Energy need + sleep schedule"
    tabs: [Energy, Sleep, Nearby]
    notes: "Sleep schedule tab: set bedtime/wake time SLT, streak counter. Nearby rest objects tab."
    status: "Not built yet"

  thrill:
    name: "Thrill"
    url: "/app/thrill"
    type: "Fun need + what's on"
    tabs: [Fun, "What's On", Nearby]
    notes: "What's On: today's public events, Wavelength shortcut, nearby entertainment objects, random fun button."
    status: "Not built yet"

  aura:
    name: "Aura"
    url: "/app/aura"
    type: "Social need + nearby players"
    tabs: [Social, "Who's Around"]
    notes: "Who's Around: nearby HUD wearers, their public vibes, check-in button, DM shortcut."
    status: "Not built yet"

  glow:
    name: "Glow"
    url: "/app/glow"
    type: "Hygiene need + facilities"
    tabs: [Hygiene, Facilities]
    notes: "All hygiene is free. Facilities tab shows nearby shower/bath objects."
    status: "Not built yet"

  luminary:
    name: "Luminary"
    url: "/app/luminary"
    type: "Purpose need + reflection"
    tabs: [Purpose, Reflection]
    notes: "Reflection tab: weekly wellbeing chart, what's helping/hurting, active occurrences affecting Purpose."
    status: "Not built yet"

  vault:
    name: "Vault"
    url: "/app/vault"
    type: "Wallet — Lumens balance + transactions"
    tabs: [Balance, History, "Top Up"]
    notes: "Balance + weekly earned vs spent. Full transaction history filterable by type. Top-up links to L$ purchase."
    status: "Not built yet"

  grind:
    name: "Grind"
    url: "/app/grind"
    type: "Career — jobs + clock-in"
    tabs: [Career, "Odd Jobs", History]
    notes: "Current job + tier. Clock-in/out button with live timer. Days to promotion. Odd job slots (2/day). Apply for new jobs."
    status: "Not built yet"

  ritual:
    name: "Ritual"
    url: "/app/ritual"
    type: "Calendar + cycle tracking"
    tabs: [Calendar, Community, Cycle]
    notes: "Monthly grid view. Period prediction shading. Holiday dots. Cycle log tab gated by biology profile."
    status: "Not built yet"

  flare:
    name: "Flare"
    url: "/app/flare"
    type: "Feed + social (combined — replaces old Orbit)"
    tabs: [Feed, Post, Profile, Discover]
    notes: >
      Feed: posts from mutuals + NPC engagement.
      Followers are NPC count (not real players).
      Real players = Mutuals (shown separately).
      Brand deals tied to follower milestones: 500→✦30/wk, 1k→✦60/wk, 5k→✦120/wk, 10k→✦200/wk, 50k→✦400/wk.
      Post quality scales with Creativity + Charisma skill.
      Anyone can post — Content Creation career unlocks monetization.
    status: "Not built yet"

  canvas:
    name: "Canvas"
    url: "/app/canvas"
    type: "Everything about me"
    tabs: [Profile, Stats, Traits, Vibes, Occurrences, Legacy, Notifications, Settings]
    notes: >
      Profile: character card, bio, pronouns, days alive.
      Stats: lifetime counters — meals eaten, XP earned, players met, shifts worked etc.
      Traits: all active traits shown as flavor only — NO mechanical details shown to player.
      Vibes: active vibes + full history (replaces old Spark app).
      Occurrences: life events add/remove (replaces old Chapter app).
      Legacy: achievements (replaces old Legacy app).
      Notifications: full history filterable by app (replaces old Signal app).
      Settings: theme/case color, privacy, notification toggles, mental health opt-in, questionnaire link.
    status: "Not built yet"

  ping:
    name: "Ping"
    url: "/app/ping"
    type: "DMs between players"
    notes: "Message threads with mutuals. Send a vibe shortcut. Typing indicator. Messages stored server-side — not SL chat."
    status: "Not built yet"

  haul:
    name: "Haul"
    url: "/app/haul"
    type: "Shop — general items + subscriptions"
    tabs: ["Weekly Specials", "Always Available", Subscriptions]
    notes: "Weekly specials rotate Sunday midnight SLT — auto from pool, admin can override/pin. Non-food items here."
    status: "Not built yet"

  wavelength:
    name: "Wavelength"
    url: "/app/wavelength"
    type: "Music streaming + radio"
    notes: >
      Station picker — 12 stations, 4 free, 8 premium (✦25/week).
      Uses llMediaOnFace to play AzuraCast stream URLs on HUD prim — player hears music IRL.
      NOT llSetParcelMusicURL (that's parcel-wide — wrong).
      Stream URLs left empty in config — Madame Kira will add AzuraCast URLs when ready.
      Gameplay effects (XP bonuses, vibes) tracked server-side by session.
    stations: [lumen_lofi, neon_pulse, the_groove, rise_fm, stillwater, the_cypher, velvet_hour, solstice, hardline, carnaval, greenhouse, player_fm]
    status: "Not built yet"

  guide:
    name: "Guide"
    url: "/app/guide"
    type: "Browser / Help"
    notes: "Home links to FAQ, patch notes, how-to guides, career guide, trait guide. Static pages served by FastAPI."
    status: "Not built yet"

  skill_apps:
    names: "Craft (cooking) · Flow (creativity) · Charm (charisma) · Stride (fitness) · Play (gaming) · Strings (music) · Pages (knowledge)"
    url: "/app/skill/{skill_key}"
    type: "7 skill apps — one URL pattern"
    notes: "Level, XP bar, XP to next, recent log, level unlock descriptions. Stride also has workout plan builder."
    status: "Not built yet"

# ============================================================
# NOTIFICATION MAP — every app's messages
# ============================================================

notifications:
  lumen_eats:
    - ["Getting hungry 🍞", "Hunger is running low — time to eat.", normal]
    - ["Starving 🚨", "Hunger is critical — XP is reduced until you eat.", urgent]
    - ["New weekly specials are here! 🌟", "Check Lumen Eats for this week's menu.", normal]
    - ["Order placed ✓", "{item} — ✦{amount} spent.", low]

  sip:
    - ["Getting thirsty 💧", "Thirst is running low.", normal]
    - ["Critically dehydrated 🚨", "XP is reduced until you drink something.", urgent]

  recharge:
    - ["Running low on energy ⚡", "Consider resting soon.", normal]
    - ["Exhausted 🚨", "Skill actions are blocked until you rest.", urgent]
    - ["It's your bedtime 🌙", "You set a sleep reminder for this time.", normal]
    - ["Well Rested bonus active ✨", "All decay slowed for 2 hours.", low]

  thrill:
    - ["Getting bored 🎉", "Fun is running low.", normal]
    - ["Very bored 🚨", "Boredom is affecting your XP gains.", urgent]
    - ["{event_name} starts in 1 hour!", "Don't forget — you RSVPd.", normal]

  aura:
    - ["Feeling isolated 🫂", "Social is running low.", normal]
    - ["Isolated 🚨", "Social isolation is affecting your XP gains.", urgent]
    - ["{avatar_name} is nearby! 👋", "A fellow HUD wearer just entered range.", low]
    - ["{avatar_name} checked in on you 💙", "", low]

  glow:
    - ["Could use a shower 🛁", "Hygiene is running low.", normal]
    - ["Very unhygienic 🚨", "Hygiene is critical — Social gains are reduced.", urgent]

  luminary:
    - ["Feeling a bit lost 🕯️", "Purpose is running low.", normal]
    - ["Lost 🚨", "Purpose is critical — XP is heavily reduced.", urgent]

  vault:
    - ["Broke 💸", "Lumen balance is very low.", normal]
    - ["✦{amount} deposited 💼", "Shift complete — {job_title}.", normal]
    - ["Lumens topped up 🎉", "✦{amount} added to your wallet.", low]
    - ["You were robbed 😱", "✦{amount} stolen. Check your balance.", urgent]
    - ["Subscription renewed 📅", "{subscription} — ✦{amount} deducted.", low]
    - ["Subscription cancelled ⚠️", "{subscription} — insufficient funds.", normal]

  grind:
    - ["30 minutes left in your shift ⏱️", "Auto clock-out in 30 minutes.", normal]
    - ["Shift complete! ✦{amount} deposited 💰", "{hours} hours worked as {title}.", normal]
    - ["Auto clocked out 📴", "Attachment removed or heartbeat lost.", normal]
    - ["Promotion available! 🎉", "You're ready to become {next_title}.", normal]
    - ["Burnout 🏳️", "You've been overworking. Forced rest day.", urgent]
    - ["Odd job slots reset 🔄", "2 odd job slots available today.", low]
    - ["Let go 📦", "You were let go due to extended absence.", normal]

  ritual:
    - ["{event_name} is tomorrow!", "You have an event coming up.", normal]
    - ["{avatar_name}'s birthday is next week 🎂", "", low]
    - ["Period predicted in 2 days 🌙", "Based on your cycle history.", normal]
    - ["It's {holiday_name} today 🎉", "", low]
    - ["New community event: {name} 📅", "Created by {creator}.", low]

  flare:
    - ["{avatar_name} followed you on Flare 👀", "", low]
    - ["{avatar_name} liked your post ❤️", "", low]
    - ["{avatar_name} commented on your post 💬", "{preview}", low]
    - ["You hit {count} followers! 🌟", "", normal]
    - ["New brand deal offer 💼", "{brand} wants to work with you.", normal]
    - ["Brand deal payout 💸", "✦{amount} deposited from {brand}.", low]
    - ["Your post is trending this week 🔥", "", normal]
    - ["Viral Moment! ✨", "Your post blew up.", normal]

  canvas:
    - ["New vibe: {vibe_name} 💫", "{vibe_description}", low]
    - ["Achievement unlocked: {name} 🏆", "", normal]
    - ["Unexpected event 🌊", "{description}", normal]
    - ["Entering {trimester} 🤰", "Pregnancy is progressing.", normal]
    - ["Traits editable in {days} days 🔓", "Your 14-day cooldown is almost up.", low]

  ping:
    - ["{avatar_name}: {message_preview} 💬", "", normal]
    - ["{avatar_name} sent you a vibe 💫", "", low]

  haul:
    - ["This week's specials are live! 🛍️", "New items available in Haul and Lumen Eats.", normal]
    - ["{subscription} renews tomorrow 📅", "✦{amount} will be deducted.", normal]
    - ["Purchase confirmed 🛒", "{item} added to inventory.", low]

  wavelength:
    - ["New station available 🎵", "{station_name} is now in Wavelength.", low]
    - ["Premium active 🎶", "All 12 stations unlocked.", low]

  skill_apps:
    - ["Level up! {skill} is now Level {level} 📈", "{unlock_description}", normal]
    - ["New ability unlocked ✨", "{description}", low]
    - ["Workout reminder 💪", "You planned today as a gym day.", normal]

# ============================================================
# ECONOMY DETAILS
# ============================================================

economy:
  currency: "Lumens (✦)"
  starting_balance: 500
  linden_rate: "L$250 = ✦50"
  topup_tiers:
    - "L$250 → ✦50"
    - "L$500 → ✦150"
    - "L$1000 → ✦350"
    - "L$2500 → ✦1000"

  robbery:
    formula: "base 0.5%/day × min(balance/500, 4.0) × zone_modifier"
    zone_modifiers: {grey_area: 2.0, home: 0.0, event: 1.5, working: 0.5}
    amount_stolen: "15-30% of balance, min ✦10, max ✦200"

  shop_items_free: [water]
  shop_items_food: [basic_snack ✦5, basic_meal ✦15, good_meal ✦25, nice_meal ✦35]
  shop_items_drinks_in_sip: [coffee ✦8, juice ✦6, energy_drink ✦10, specialty_drink ✦15]
  subscriptions:
    - "wavelength_premium: ✦25/week — all stations, 2× Music XP"
    - "gym_membership: ✦30/week — Fitness XP +15%"
    - "flare_verified: ✦20/week — Social gains +10%, verified badge"

  weekly_specials:
    rotation: "Sunday midnight SLT"
    pool: "~20 items in config, 4-6 picked randomly"
    admin_override: "Admin panel can pin specific items"

  odd_jobs:
    daily_limit: 2
    reset: "Midnight SLT"
    jobs:
      - "help_a_neighbor: ✦40, 15 min interaction"
      - "public_busking: ✦35, 15 min at zone"
      - "freelance_gig: ✦55, 30 min task"

# ============================================================
# CAREER SYSTEM
# ============================================================

career_mechanics:
  shift_max_hours: 4
  warning_at: "3.5 hours (30 min before auto clock-out)"
  auto_clock_out: "4 hours OR 2 missed heartbeat pings"
  heartbeat_interval: "60 seconds"
  pay_deposited: "At clock-out — proportional if early"
  reset: "Midnight SLT — hours_today resets"
  promotion_requires: "Skill level AND minimum days at current tier"
  grey_area_careers: "No skill XP, higher base pay, future raid risk"

career_paths:
  legal:
    - culinary_arts      # Dishwasher → Head Chef (✦50→✦110)
    - cafe_hospitality   # Barista → Café Manager (✦60→✦120)
    - marine_biology     # Lab Assistant → Lead Scientist (✦55→✦115)
    - medicine           # Orderly → Attending Physician (✦55→✦115)
    - visual_arts        # Street Artist → Creative Director (✦50→✦110)
    - music_career       # Busker → Headlining Performer (✦50→✦110)
    - content_creation   # Micro-Influencer → Media Personality (✦50→✦110)
    - fitness_sports     # Gym Staff → Pro Athlete (✦50→✦110)
    - law                # Legal Clerk → Partner (✦55→✦115)
    - corporate          # Intern → Executive (✦50→✦110)
    - transportation     # Delivery Driver → Logistics Manager (✦50→✦110)
    - retail             # Stock Associate → Store Manager (✦50→✦110)
    - cleaning           # Cleaner → Facilities Manager (✦50→✦75, 3 tiers)
  grey_area:
    - the_syndicate      # Associate → Boss (✦75→✦160)
    - underground_casino # Card Dealer → Casino Owner (✦75→✦130)
    - black_market       # Street Vendor → Kingpin (✦75→✦130)
    - underground_fixer  # Street Fixer → The Cleaner (✦75→✦110, 3 tiers)

# ============================================================
# TRAIT SYSTEM
# ============================================================

traits:
  count: 28
  max_per_player: 5
  negative_traits_give: "✦50 starting bonus each, max ✦100"
  xp_bonus_cap: "+5% — flavor only, not competitive"
  mechanics_hidden: true  # Player never sees XP bonuses in trait picker
  vibes_per_trait: "4-5, mix of positive and negative regardless of trait alignment"
  edit_cooldown: "14 days"

  questionnaire:
    type: "Chat-style web form — typing animation, pill answers"
    url: "/app/questionnaire?token=..."
    path_choice: "Player picks: Discover (questionnaire) OR Build (pick list)"
    profile_questions: [name, pronouns, biology_agab, gender_expression, age_group, sexuality]
    trait_questions: 7
    result: "Top 3-5 traits applied silently after 'Getting to know you...' screen"

  categories: [mind_personality, body_physical, social_emotional, work_drive, self_wellbeing, biology_auto]

  positive_traits: [talkative, bookworm, creative_soul, athletic, iron_stomach, extrovert, empath, ambitious, resilient, confident, self_aware, growing]
  negative_traits: [overthinker, forgetful, slob, couch_potato, picky_eater, introvert, hot_headed, clingy, lazy, impulsive, insecure, grieving]
  neutral_traits: [curious, night_owl, morning_person, guarded, romantic, homebody]
  auto_biology: [cycle]

# ============================================================
# VIBE SYSTEM
# ============================================================

vibes:
  renamed_from: moodlets
  table: vibes
  config_key: vibes
  endpoint: "/needs/vibes/active"
  per_trait: "4-5 vibes each — see docs/traits_and_vibes.md"
  universal_vibes:
    positive: [well_rested, fed_happy, buzzing, in_my_element, glowing_up, main_character_energy]
    negative: [running_on_empty, not_okay, stinky, broke, payday_fatigue]

# ============================================================
# LIFE OCCURRENCES
# ============================================================

occurrences:
  max_active: 5
  mental_health: "opt-in only via Settings toggle"
  unexpected_events: "server-generated — robbery, windfall, illness, job loss"
  categories: [relationship, career_financial, physical_health, life_transition, unexpected, mental_health]
  pregnancy: "auto-progresses through 3 trimesters over 42 real days (14 days each)"
  cycle_tracking: "Flo-style — player logs start/duration, server predicts future windows"
  full_details: "see docs/occurrences.md"

# ============================================================
# TECHNICAL DETAILS
# ============================================================

tech:
  webapp_auth: "Token in URL — ?token=... — no cookies (SL browser limitation)"
  hud_communication: "LSL heartbeat broadcast every 60s on private channel, server builds proximity map"
  proximity_range: "20m (llSensor)"
  zone_detection: "Scripted zone objects broadcast zone type every 30s on private channel"
  music: "llMediaOnFace renders AzuraCast stream URL — NOT llSetParcelMusicURL (parcel-wide)"
  item_delivery: "Deferred — apply need effect for now, CasperVend/custom giver later"

  render_migrations_needed_after_session_3:
    - "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'normal';"
    - "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS is_toasted INTEGER NOT NULL DEFAULT 0;"

# ============================================================
# BUILD ORDER — REMAINING SESSIONS
# ============================================================

session_4_todo:
  priority: NEXT
  tasks:
    - "POST /shop/buy — deduct Lumens, apply need effect, create transaction, push notification"
    - "GET /wallet — balance + transaction history for Vault webapp"
    - "POST /wallet/topup — credit Lumens (called by L$ vendor webhook)"
    - "GET /shop/items — full catalog for Haul webapp"
    - "Weekly specials rotation background job (Sunday midnight SLT)"
    - "Subscription billing background job (Sunday midnight SLT)"
    - "Build Vault webapp (app/templates/apps/vault.html)"
    - "Build Sip webapp with drink ordering"
    - "Wire Lumen Eats buy button to /shop/buy"

session_5_todo:
  tasks:
    - "POST /career/apply — check requirements, create employment row"
    - "POST /career/clockin — record start time"
    - "POST /career/clockout — calculate hours, deposit pay, push notification"
    - "POST /career/heartbeat — update last_heartbeat_at, auto clock-out if missed 2"
    - "POST /career/promote — check tier requirements, advance if eligible"
    - "GET /career — current job data for Grind webapp"
    - "POST /career/odd-jobs/complete — log odd job, deposit pay"
    - "Midnight reset job (hours_today, odd job counter)"
    - "Build Grind webapp"

session_6_todo:
  tasks:
    - "POST /social/follow + DELETE /social/follow"
    - "POST /social/proximity — heartbeat proximity update"
    - "GET /social/nearby — nearby HUD wearers"
    - "POST /flare/post — create post, calculate quality tier, update flare_stats"
    - "GET /flare/feed — posts from follows"
    - "POST /flare/like + /flare/comment"
    - "Flare follower engine (every 10 min background job)"
    - "Brand deal weekly check (Sunday midnight)"
    - "Build Flare webapp"
    - "Build Ping (messages) webapp"
    - "GET/POST /messages endpoints"

session_7_todo:
  tasks:
    - "Calendar CRUD endpoints"
    - "Cycle log endpoints (POST /cycle/log, GET /cycle/history)"
    - "Cycle prediction calculation"
    - "Occurrence add/remove/update endpoints"
    - "Unexpected event engine (daily per-player roll)"
    - "Holiday vibe engine (daily midnight job)"
    - "Calendar reminder job (every 30 min)"
    - "Build Ritual webapp"
    - "Build Occurrences in Canvas"

session_8_todo:
  tasks:
    - "Chat-style questionnaire webapp (/app/questionnaire)"
    - "Trait scoring logic (answers → trait points → top 3-5 applied)"
    - "Trait effects wired into decay engine (night_owl XP timing, homebody decay etc)"
    - "Trait-generated vibe triggers wired into vibe engine"
    - "Build Canvas webapp (all 8 tabs)"

session_9_todo:
  tasks:
    - "Achievement checker service (triggered after every action)"
    - "Achievement definitions in config"
    - "Build remaining need webapps: Recharge, Thrill, Aura, Glow, Luminary"
    - "Build Haul webapp"
    - "Build Wavelength webapp"
    - "Build all 7 skill webapps (one template, dynamic)"
    - "Build Pulse home widget"
    - "Build Guide (help/FAQ) webapp"
    - "Admin panel expansions"

session_10_todo:
  tasks:
    - "Full integration testing"
    - "Performance review (slow endpoints)"
    - "LSL HUD scripts begin:"
    - "  - Phone frame prim setup"
    - "  - App icon grid with llMediaOnFace per app"
    - "  - Heartbeat broadcast script"
    - "  - Proximity detection script"
    - "  - Wavelength media player integration"
    - "  - Red dot notification overlay logic"
    - "  - Questionnaire link from Settings"

# ============================================================
# FILES TO READ AT SESSION START
# ============================================================
# When starting a new session, clone repo and read these first:

files_to_read_first:
  - "config.yaml — all config sections"
  - "app/database.py — all table definitions"
  - "app/main.py — router registration"
  - "app/services/decay.py — decay + notification triggers"
  - "app/routers/webapps.py — webapp router pattern"
  - "app/templates/base.html — shared aesthetic"
  - "docs/handoff.md — this file"

# Then read the specific router/service for whatever session we're building.

# ============================================================
# CYCLE & PREGNANCY SYSTEM — DETAILED MECHANICS
# ============================================================

cycle_tracking:
  who_gets_it: "Players who answered Female or Intersex on biology_agab profile question"
  opt_in: "Not optional — flows from biology answer. Non-binary can choose yes/no."
  where: "Ritual app → Cycle tab"
  table: cycle_log

  how_player_logs:
    start: "Tap 'I started today' → pick duration slider (3-8 days) → server records cycle_start_slt"
    end: "Tap 'I finished today' → server records cycle_end_slt, calculates cycle_length_days"
    spotting: "Tap 'Spotting / light' → logged but marked lighter for prediction accuracy"
    skip: "Tap 'Skip this cycle' → marks that month manually, doesn't skew average"

  prediction:
    requires: "2+ logged cycles before predictions start"
    formula: "avg_cycle_length = average of all logged cycle_length_days"
    next_start: "last_cycle_start + avg_cycle_length"
    variance: "±3 days shown as lighter shading on calendar"
    accuracy: "improves with each logged cycle"
    display: "Pink shading on Ritual calendar grid — dark for confirmed, light for predicted window"

  period_occurrence:
    auto_fires: "When cycle_start_slt is logged by player"
    duration: "Set by player (3-8 days)"
    mechanical_effects:
      - "Fun decays 15% faster during window"
      - "Social gains -10% during window"
      - "Hunger cravings — nice meals give bonus Hunger restore"
    vibes_during_window:
      - ["PMS 🌙", "Period window active — Fun drains faster.", negative, auto]
      - ["Irritable 😤", "Random 50% chance per day during window — Social interactions give -5 instead of gains for 30 min.", negative, random]
      - ["Craving Something 🍫", "Nice meal gives 2× Hunger restore today.", neutral, random]
    vibes_after_window:
      - ["Glowing ✨", "3 days after period ends — Purpose +10, Social gains +15%, 48 hrs.", positive, auto]
      - ["Actually Invincible 💪", "First day after period — all decay -10%, 24 hrs.", positive, auto]

  calendar_notifications:
    - ["Bracing Myself 😬", "Period predicted in 2 days — Fun -5, mild Energy drain.", normal]
    - ["Period started 🌙", "Logged and tracked. Take care of yourself.", low]
    - ["Period predicted in 2 days 🌙", "Based on your cycle history.", normal]

  calendar_display:
    confirmed_period: "Dark pink days on grid"
    predicted_window: "Light pink shading ±3 days"
    post_cycle_glow: "Small gold dot 3 days after end"
    never_visible_to: "Other players — always private"

pregnancy:
  who_can_add: "Players with female_agab or intersex biology profile answer"
  how_added: "Player adds manually via Canvas → Occurrences → Add Occurrence → Pregnancy"
  occurrence_key: "pregnancy"
  total_duration: "42 real days (14 days per trimester)"
  auto_progression: "Server background job checks daily — advances trimester at day 14 and day 28"
  table: player_occurrences (sub_stage column tracks trimester_1/2/3)
  early_end: "Player can remove occurrence anytime — no mechanic, just narrative removal. No judgment."

  trimester_1:
    days: "1-14"
    display: "First Trimester 🤰"
    mechanical_effects:
      - "Hunger decays 20% faster"
      - "Energy decays 15% faster"
    vibes:
      - ["Morning Sickness 🤢", "40% daily chance — Hunger gains halved for 2 hrs, Fun -8.", negative, random]
      - ["Glowing ✨", "Triggers if all needs above 65 — Purpose +10, Social +5.", positive, conditional]
      - ["So Tired 😴", "Triggers if Energy below 50 — Energy decay 2×, rest gives less.", negative, conditional]
      - ["Telling People 💕", "Triggers in group of 2+ after day 7 — Purpose +12, nearby players +5 Purpose.", positive, conditional]

  trimester_2:
    days: "15-28"
    display: "Second Trimester 🤰"
    mechanical_effects:
      - "Hunger decays 25% faster"
      - "Energy normalizes slightly"
      - "Hygiene decays slightly faster"
    vibes:
      - ["Nesting 🏠", "Triggers in home zone 2+ hrs — Purpose +8, all decay -10%.", positive, conditional]
      - ["Uncomfortable 😮‍💨", "25% daily chance — Energy -5, Fun -5.", negative, random]
      - ["Feeling Movements 🥺", "20% daily chance — Purpose +15 flat.", positive, random]

  trimester_3:
    days: "29-42"
    display: "Third Trimester 🤰"
    mechanical_effects:
      - "Hunger decays 30% faster"
      - "Energy decays 20% faster"
      - "Location-required jobs pay 15% less"
    vibes:
      - ["Ready Now Please 😩", "Triggers day 10+ of T3 — Fun -10%, Purpose fluctuates.", negative, conditional]
      - ["Nesting Hard 🏠", "Triggers in home zone — all decay -15%, Purpose +5/hr passive.", positive, conditional]
      - ["Almost There 🌟", "Triggers day 13 of T3 — Purpose +20 flat.", positive, auto]

  resolution:
    at_day_42: "Pregnancy occurrence resolves automatically"
    then: "New Parent occurrence auto-added"
    notifications:
      - ["Entering Second Trimester 🤰", "Your pregnancy is progressing.", normal]
      - ["Entering Third Trimester 🤰", "Almost there.", normal]
      - ["Pregnancy complete 🌟", "New chapter beginning.", normal]

new_parent:
  occurrence_key: "new_parent"
  auto_added_from: "pregnancy resolution OR player adds manually"
  duration: "Open-ended or player sets up to 90 days"
  mechanical_effects:
    - "Energy decays 25% faster (sleep deprivation)"
    - "Purpose passive gain doubled (meaning is high)"
    - "Social decay slower (nesting with family)"
  vibes:
    - ["Sleep Deprived 😵", "Energy below 60 — all XP -5%, Energy harder to restore.", negative, conditional]
    - ["Worth It 🥺", "Energy below 40 but Purpose above 75 — Purpose +10 flat.", positive, conditional]
    - ["First Smile 🌟", "20% daily chance first 30 days — Purpose +20 flat.", positive, random]
    - ["Touched Out 😶", "Social above 80 — Social gains halved, need personal space.", negative, conditional]
    - ["Village 🫂", "Another player completes odd job for them — Energy +15 flat, Purpose +8.", positive, event]

background_jobs_needed_for_cycle_pregnancy:
  cycle_prediction_update:
    schedule: "Daily midnight SLT"
    does: "Recalculates avg_cycle_length and next_predicted_start for all players with 2+ cycles"

  pregnancy_progression:
    schedule: "Daily midnight SLT"
    does: "Checks all active pregnancy occurrences, advances sub_stage at day 14 and 28, resolves at day 42, auto-adds new_parent"

  period_vibe_engine:
    schedule: "Daily midnight SLT"
    does: "For players in active period window, rolls random vibes (Irritable 50%, Craving 30%), fires post-cycle vibes on day 3 after end"

  calendar_reminders:
    schedule: "Every 30 minutes SLT"
    does: "Checks upcoming events (24hr), birthdays (7-day), period predictions (2-day), fires notifications"
