# SL Phone HUD — Complete Backend Requirements
# Status: Design locked, ready to build
# Last updated: Session 1 complete, Session 2 starting
# ============================================================

# ============================================================
# WHAT'S ALREADY BUILT
# ============================================================

built_tables:
  - players           # avatar UUID, token, display name, online status
  - needs             # 7 needs per player, current value
  - event_log         # full history of every need change
  - moodlets          # active vibes with expiry timestamps (currently called moodlets in code)
  - skills            # 7 skills per player, level + XP

built_endpoints:
  - "POST /players/register"          # auto-register on HUD attach
  - "GET  /players/{id}"              # fetch player profile
  - "POST /actions/action"            # use an object, update needs
  - "GET  /actions/sync"              # sync all needs on HUD attach
  - "GET  /needs/"                    # all 7 needs for current player
  - "GET  /needs/{need_key}"          # single need + activity log
  - "GET  /needs/moodlets/active"     # active vibes
  - "GET  /health"                    # server health check

built_config_sections:
  - server              # host, port, decay interval, admin secret
  - database            # db path
  - needs               # 7 needs with decay rates, thresholds, emotes
  - objects             # interaction objects with gains and effects
  - moodlets            # vibe definitions (name, duration, modifiers)
  - skills              # 7 skills with XP thresholds and level unlocks
  - consequences        # zero-need penalties

built_services:
  - decay engine        # APScheduler ticking every 60s, online + offline rates
  - moodlet engine      # checks conditions after every action
  - auth service        # token generation + validation
  - purpose engine      # composite need calculation

built_infrastructure:
  - FastAPI app with CORS
  - SQLite locally, PostgreSQL on Render
  - Deployed at https://slhud.onrender.com
  - GitHub repo at github.com/Kiralette/slhud
  - Admin panel at /admin?secret=...

# ============================================================
# RENAME: moodlets → vibes
# ============================================================
# The moodlets table and all references should be renamed to
# vibes throughout the codebase. "Vibes" is the player-facing
# term. Update: table name, config section, all endpoints,
# all service references.

rename_tasks:
  - moodlets table → vibes
  - moodlets config section → vibes
  - GET /needs/moodlets/active → GET /needs/vibes/active
  - All service code references
  - Admin panel display

# ============================================================
# NEW CONFIG SECTIONS NEEDED
# ============================================================

new_config_sections:

  traits:
    # 28 traits across 6 categories
    # Each trait has: display_name, category (social/stress/love/self/drive/lifestyle/biology)
    # alignment (positive/negative/neutral), starting_lumen_bonus (negative traits only)
    # mechanical_effects (decay modifiers, XP modifiers, need floor overrides)
    # vibes list (4-5 vibes each with trigger conditions and effects)
    examples:
      - talkative, bookworm, creative_soul, overthinker, forgetful, curious
      - athletic, iron_stomach, slob, couch_potato, picky_eater, night_owl, morning_person
      - extrovert, empath, introvert, hot_headed, clingy, guarded, romantic
      - ambitious, resilient, lazy, impulsive, homebody
      - confident, self_aware, insecure, grieving, growing
      - cycle (auto-applied from biology profile)

  questionnaire:
    # Profile questions (Q1-Q5): name, pronouns, biology, age group, sexuality
    # Trait discovery questions (Q6-Q12): indirect, maps to trait scores
    # Each answer maps to trait bucket points
    # Top 3-5 traits above threshold are applied after submission

  careers:
    # 12 career paths, each with 3-5 tiers
    # Each tier: display_name, daily_pay (multiples of 50), skill_requirement,
    #            days_at_tier_required, location_required, skill_xp_grants, is_grey_area
    career_paths:
      - culinary_arts      # 5 tiers: Dishwasher → Head Chef
      - cafe_hospitality   # 5 tiers: Barista → Café Manager
      - marine_biology     # 5 tiers: Lab Assistant → Lead Scientist
      - medicine           # 5 tiers: Orderly → Attending Physician
      - visual_arts        # 5 tiers: Street Artist → Creative Director
      - music_career       # 5 tiers: Busker → Headlining Performer
      - content_creation   # 5 tiers: Micro-Influencer → Media Personality
      - fitness_sports     # 5 tiers: Gym Staff → Pro Athlete
      - law                # 5 tiers: Legal Clerk → Partner
      - corporate          # 5 tiers: Intern → Executive
      - transportation     # 5 tiers: Delivery Driver → Logistics Manager
      - retail             # 5 tiers: Stock Associate → Store Manager
      - cleaning           # 3 tiers: Cleaner → Facilities Manager
      # Grey area careers (no skill XP):
      - the_syndicate      # 5 tiers: Associate → Boss
      - underground_casino # 4 tiers: Card Dealer → Casino Owner
      - black_market       # 4 tiers: Street Vendor → Kingpin
      - underground_fixer  # 3 tiers: Street Fixer → The Cleaner

  odd_jobs:
    # Max 2 per day, reset midnight SLT
    # Each: display_name, pay (flat), min_duration_minutes, how_triggered
    - help_a_neighbor      # ✦40 flat, 15 min, player interaction
    - public_busking       # ✦35 flat, 15 min at zone
    - freelance_gig        # ✦55 flat, 30 min task
    - sell_crafted_item    # ✦25-70, craft time (future - crafting mod)

  economy:
    starting_lumens: 500
    lumen_topup_rates:
      - { lindens: 250, lumens: 50 }
      - { lindens: 500, lumens: 150 }
      - { lindens: 1000, lumens: 350 }
      - { lindens: 2500, lumens: 1000 }
    robbery:
      base_chance_daily: 0.005
      wealth_multiplier_divisor: 500
      max_multiplier: 4.0
      zone_modifiers:
        grey_area: 2.0
        home: 0.0
        event: 1.5
        working: 0.5
      stolen_percent_min: 0.15
      stolen_percent_max: 0.30
      stolen_min_lumens: 10
      stolen_max_lumens: 200

  shop_items:
    # All purchasable items with: display_name, category, lumen_cost,
    # need_effects (which needs it fills and how much), vibe_granted
    categories:
      - food_snacks
      - food_meals
      - drinks_free     # water always free
      - drinks_paid
      - hygiene         # all free
      - subscriptions   # Wavelength Premium, Gym membership etc.

  subscriptions:
    # Weekly recurring costs deducted Sunday midnight SLT
    - wavelength_premium  # ✦25/week, unlocks all radio stations
    - gym_membership      # ✦30/week, Fitness XP +15% all week
    - spotify_premium     # in-universe: "Wavelength Premium" (same thing)
    - instagram_blue      # in-universe: "Flare Verified" ✦20/week, +Social gains

  occurrences:
    # All occurrence types with: category, player_adds, unexpected (bool),
    # unexpected_chance, duration_range, mechanical_effects, vibes list
    categories:
      - relationship    # new_relationship, breakup, friendship_drama, new_friendship
      - career          # new_job, job_loss, promotion (auto), financial_windfall, robbery, financial_stress
      - physical_health # pregnancy (with trimester progression), new_parent, illness_mild, injury, chronic_condition
      - life_transition # moving, bereavement, new_home_city
      - unexpected      # server-generated random events
      - mental_health   # opt-in: depression_episode, anxiety_disorder, therapy, addiction_recovery

  calendar:
    # Standard holidays with dates, vibes generated, special effects
    # Fun holidays (hotdog day, teacher appreciation etc.)
    standard_holidays: 16 entries
    fun_holidays: 18 entries
    # Radio stations (stream URLs added when AzuraCast ready)
    wavelength_stations:
      - lumen_lofi
      - neon_pulse
      - the_groove
      - rise_fm
      - stillwater
      - the_cypher
      - velvet_hour
      - solstice
      - hardline
      - carnaval
      - greenhouse
      - player_fm

  achievements:
    # Achievement definitions: key, display_name, description (hint),
    # condition_type, condition_value, reward (Purpose bonus, badge etc.)
    examples:
      - still_standing          # survive 30 days
      - hotdog_hero             # wear hotdog costume on hotdog day
      - tax_season              # earn ✦10,000 lifetime
      - social_butterfly        # meet 20 unique players
      - honestly_doing_great    # all needs above 80 for a full week
      - burnout                 # hit Burnout vibe 3 times
      - verified                # reach 10,000 Flare followers

# ============================================================
# NEW DATABASE TABLES NEEDED (26 total)
# ============================================================

new_tables:

  # --- IDENTITY & PROFILE ---
  player_profiles:
    columns: [player_id FK, bio, pronouns, age_group, sexuality,
              biology_agab, gender_expression, questionnaire_completed_at,
              questionnaire_last_edited_at, is_mental_health_opted_in]
    notes: "Extended profile info beyond the players table"

  player_traits:
    columns: [player_id FK, trait_key, applied_at, source (questionnaire/picked)]
    notes: "Max 5 traits per player"

  player_settings:
    columns: [player_id FK, notification_prefs JSON, privacy_prefs JSON,
              theme_case_color, theme_wallpaper_uuid, is_muted,
              timezone_offset_hours]
    notes: "All HUD customization preferences"

  # --- ECONOMY ---
  wallets:
    columns: [player_id FK, balance REAL, total_earned REAL, total_spent REAL,
              last_updated]
    notes: "One row per player. Balance in Lumens."

  transactions:
    columns: [player_id FK, amount REAL, type (wage/purchase/topup/robbery/gift),
              description, related_id, timestamp]
    notes: "Full Lumen movement history. Never deleted."

  subscriptions:
    columns: [player_id FK, subscription_key, started_at, next_billing_at,
              is_active, cancelled_at]
    notes: "Active recurring weekly purchases"

  # --- CAREER & JOBS ---
  employment:
    columns: [player_id FK, career_path_key, tier_level, job_title,
              clocked_in_at, last_heartbeat_at, is_clocked_in,
              hours_today, days_at_tier, total_days_worked]
    notes: "Current job state. One row per player."

  career_history:
    columns: [player_id FK, career_path_key, tier_level, job_title,
              started_at, ended_at, total_shifts, total_earned]
    notes: "Historical record of all jobs held"

  odd_job_log:
    columns: [player_id FK, odd_job_key, completed_at, amount_earned]
    notes: "Tracks daily odd job count (max 2/day)"

  # --- SOCIAL & MESSAGING ---
  follows:
    columns: [follower_id FK, following_id FK, followed_at]
    notes: "Player-to-player follow relationships. Mutuals = mutual follows."

  proximity_log:
    columns: [player_id FK, nearby_player_id FK, first_seen_at,
              last_seen_at, session_count, last_zone]
    notes: "Social graph built from HUD heartbeat proximity data"

  messages:
    columns: [thread_id FK, sender_id FK, content, sent_at, is_read]
    notes: "DM content between players"

  message_threads:
    columns: [id, player_a_id FK, player_b_id FK, last_message_at,
              unread_count_a, unread_count_b]
    notes: "One thread per player pair"

  # --- FEED (FLARE) ---
  posts:
    columns: [player_id FK, content_text, category (food/fitness/creative/life/achievement/event),
              quality_tier (0-3), follower_count_at_post, npc_likes, npc_comments,
              is_brand_deal_post, brand_deal_id, created_at, expires_at]
    notes: "Posts live 48 hrs. Quality tier affects NPC engagement."

  post_engagements:
    columns: [post_id FK, player_id FK, type (like/comment), content, created_at]
    notes: "Real player engagement (mutuals). Separate from NPC engagement."

  flare_stats:
    columns: [player_id FK, follower_count INT, weekly_post_count,
              active_brand_deal_key, brand_deal_started_at, brand_deal_posts_this_week,
              last_post_at, post_streak_days]
    notes: "Flare-specific stats. follower_count is the NPC metric."

  # --- CALENDAR ---
  calendar_events:
    columns: [player_id FK, title, event_type (personal/birthday/community/occurrence_milestone),
              event_date_slt, end_date_slt, is_recurring, recurrence_rule,
              is_public, color_key, generates_vibe_key, rsvp_count, notes]
    notes: "All player-created calendar events"

  cycle_log:
    columns: [player_id FK, cycle_start_slt, cycle_end_slt, period_duration_days,
              cycle_length_days, avg_cycle_length, next_predicted_start,
              is_manual_override, logged_at]
    notes: "Period tracking. Always private."

  # --- OCCURRENCES ---
  player_occurrences:
    columns: [player_id FK, occurrence_key, started_at, ends_at,
              sub_stage (trimester_1/2/3 etc.), is_unexpected,
              is_dismissed, is_resolved, metadata JSON]
    notes: "Max 5 active at once. Mental health requires opt-in flag."

  occurrence_vibe_log:
    columns: [player_id FK, occurrence_key, vibe_key, fired_at]
    notes: "Prevents same vibe firing twice in short window per occurrence"

  vibe_log:
    columns: [player_id FK, vibe_key, trigger_source, fired_at, expired_at]
    notes: "Full history of all vibes ever fired. Powers Achievements."

  # --- ACHIEVEMENTS & STATS ---
  player_achievements:
    columns: [player_id FK, achievement_key, unlocked_at, is_notified]
    notes: "Earned achievements. Checker runs after every action."

  player_stats:
    columns: [player_id FK, days_alive INT, total_lumens_earned REAL,
              total_meals_eaten INT, total_skill_xp_earned REAL,
              total_players_met INT, total_vibes_fired INT,
              total_posts_made INT, lifetime_followers_gained INT,
              total_shifts_worked INT, last_updated]
    notes: "Lifetime counters. Updated incrementally, never recalculated."

  # --- NOTIFICATIONS ---
  notifications:
    columns: [player_id FK, app_source, title, body, is_read,
              action_url, created_at]
    notes: "All HUD notifications. Filterable by app_source."

  # --- STREAMING ---
  streaming_sessions:
    columns: [player_id FK, station_key, started_at, ended_at,
              duration_minutes, xp_earned, is_premium]
    notes: "Tracks active and completed Wavelength sessions"

  # --- FITNESS ---
  workout_plans:
    columns: [player_id FK, target_days JSON, reminder_time_slt,
              created_at, is_active]
    notes: "Player-set weekly fitness schedule for Stride app reminders"

# ============================================================
# NEW ENDPOINTS NEEDED (grouped by feature area)
# ============================================================

new_endpoints:

  profile:
    - "POST /profile/setup"              # submit questionnaire (new player)
    - "GET  /profile/me"                 # full profile for current player
    - "PUT  /profile/me"                 # update bio, pronouns etc.
    - "GET  /profile/{player_id}"        # public profile (limited fields)
    - "GET  /profile/traits"             # current player's traits
    - "POST /profile/traits/pick"        # pick-your-own traits path
    - "PUT  /profile/settings"           # update HUD settings/preferences

  economy:
    - "GET  /wallet"                     # current balance + transaction history
    - "POST /wallet/topup"               # add Lumens (L$ purchase webhook)
    - "POST /shop/buy"                   # purchase item from Haul, deducts Lumens
    - "GET  /shop/items"                 # full shop catalog
    - "GET  /subscriptions"              # active subscriptions
    - "POST /subscriptions/subscribe"    # start a subscription
    - "DELETE /subscriptions/{key}"      # cancel subscription

  career:
    - "GET  /career"                     # current job info
    - "POST /career/apply"               # apply for a job (checks requirements)
    - "POST /career/clockin"             # clock in for shift
    - "POST /career/clockout"            # clock out (calc pay, deposit)
    - "POST /career/heartbeat"           # attachment heartbeat ping (every 60s)
    - "POST /career/promote"             # check + apply promotion if eligible
    - "GET  /career/odd-jobs"            # available odd jobs today
    - "POST /career/odd-jobs/complete"   # complete an odd job

  social:
    - "POST /social/follow/{player_id}"    # follow a player
    - "DELETE /social/follow/{player_id}"  # unfollow
    - "GET  /social/followers"             # my followers list
    - "GET  /social/following"             # who I follow
    - "GET  /social/nearby"                # nearby HUD wearers (from proximity data)
    - "POST /social/proximity"             # heartbeat proximity update from HUD

  messages:
    - "GET  /messages"                     # all threads
    - "GET  /messages/{thread_id}"         # message history for thread
    - "POST /messages/send"                # send a DM
    - "PUT  /messages/{thread_id}/read"    # mark thread as read
    - "POST /messages/send-vibe"           # send a vibe notification to player

  flare:
    - "POST /flare/post"                   # create a post
    - "GET  /flare/feed"                   # feed of posts from follows
    - "POST /flare/like/{post_id}"         # like a post
    - "POST /flare/comment/{post_id}"      # comment on a post
    - "GET  /flare/stats"                  # follower count, streak, brand deal
    - "GET  /flare/brand-deals"            # available brand deal offers
    - "POST /flare/brand-deals/accept"     # accept a brand deal

  calendar:
    - "GET  /calendar"                     # all events for current player
    - "POST /calendar/events"              # create event
    - "PUT  /calendar/events/{id}"         # edit event
    - "DELETE /calendar/events/{id}"       # delete event
    - "GET  /calendar/community"           # public events from followed players
    - "POST /calendar/rsvp/{event_id}"     # RSVP to a public event
    - "GET  /calendar/holidays"            # pre-loaded holidays for current month
    - "POST /cycle/log"                    # log cycle start/end
    - "GET  /cycle/history"                # cycle log + prediction

  occurrences:
    - "GET  /occurrences"                  # active occurrences
    - "POST /occurrences/add"              # add an occurrence
    - "PUT  /occurrences/{id}"             # update (duration, sub-stage)
    - "DELETE /occurrences/{id}"           # resolve/remove occurrence
    - "GET  /occurrences/unexpected"       # unexpected events inbox

  achievements:
    - "GET  /achievements"                 # all earned + locked achievements
    - "GET  /stats"                        # lifetime stats

  streaming:
    - "POST /streaming/start"              # start a streaming session
    - "POST /streaming/stop"               # end session, calc XP
    - "GET  /streaming/stations"           # station list from config

  notifications:
    - "GET  /notifications"                # all notifications
    - "PUT  /notifications/read"           # mark all read
    - "DELETE /notifications"              # clear history

# ============================================================
# NEW BACKGROUND JOBS (APScheduler additions)
# ============================================================

new_background_jobs:
  - name: "subscription_billing"
    schedule: "Every Sunday midnight SLT (Pacific)"
    does: "Deducts weekly subscription costs from wallets. Cancels if insufficient funds."

  - name: "cycle_prediction_update"
    schedule: "Daily at midnight SLT"
    does: "Recalculates next predicted period start for all players with 2+ cycles logged."

  - name: "calendar_reminders"
    schedule: "Every 30 minutes"
    does: "Checks for upcoming events (24hr, birthday 7-day, period 2-day) and queues notifications."

  - name: "holiday_vibe_engine"
    schedule: "Daily at midnight SLT"
    does: "Checks if today is a holiday/fun-day and applies relevant vibes to all active players."

  - name: "flare_follower_engine"
    schedule: "Every 10 minutes"
    does: "Processes post engagement, calculates follower gains, checks brand deal requirements."

  - name: "achievement_checker"
    schedule: "Runs after every action (triggered, not scheduled)"
    does: "Checks all achievement conditions against player_stats after any state change."

  - name: "unexpected_event_engine"
    schedule: "Daily per-player roll at a random time"
    does: "Rolls for robbery, illness, windfall, job loss based on player state."

  - name: "brand_deal_weekly_check"
    schedule: "Every Sunday midnight SLT"
    does: "Checks brand deal post requirements. Pays out or pauses deals. Generates new offers."

  - name: "midnight_reset"
    schedule: "Daily midnight SLT"
    does: "Resets: odd_job count, hours_today on employment, clears expired vibes."

# ============================================================
# AMENDED EXISTING SYSTEMS
# ============================================================

amendments:

  decay_engine:
    - "Add trait modifier lookup before applying decay rates"
    - "Night Owl / Morning Person traits modify XP rates by SLT hour"
    - "Homebody trait modifies decay rates when player is in home zone"
    - "Subscription bonuses (gym membership) apply to Fitness XP"

  vibe_engine:
    - "Add trait-based vibe triggers (Overthinker → Spiraling etc.)"
    - "Add occurrence-based vibe triggers"
    - "Add calendar-based vibe triggers (period, holidays, birthdays)"
    - "Add proximity-based vibe triggers (Extrovert On One, Introvert People'd Out)"
    - "Prevent duplicate vibe firing within cooldown window (occurrence_vibe_log)"

  action_processor:
    - "Check wallet balance before allowing paid shop purchases"
    - "Apply subscription bonuses to XP calculations"
    - "Trigger achievement checker after every successful action"
    - "Update player_stats incrementally on relevant actions"
    - "Check brand deal post categories and credit toward active deal"

  admin_panel:
    - "Add player wallet view and manual adjustment"
    - "Add occurrence management (add/remove for any player)"
    - "Add trait override (admin can set traits directly)"
    - "Add global event broadcast (fires holiday vibe for all players)"
    - "Add Flare follower override"

# ============================================================
# BUILD ORDER RECOMMENDATION
# ============================================================

build_order:
  session_2:
    - "1. Rename moodlets → vibes throughout codebase"
    - "2. Add new config sections: careers, economy, traits (structure only)"
    - "3. Add new DB tables: wallets, transactions, employment, player_profiles, player_traits, player_settings"
    - "4. Update init_db() for all new tables"
    - "5. Economy endpoints: wallet, shop/buy, topup"
    - "6. Career endpoints: apply, clockin, clockout, heartbeat"

  session_3:
    - "1. Questionnaire web page (chat-style, served by FastAPI)"
    - "2. Trait scoring and assignment logic"
    - "3. Trait effect integration into decay + vibe engines"
    - "4. Profile endpoints"

  session_4:
    - "1. Social endpoints: follow, proximity, nearby"
    - "2. Messages endpoints"
    - "3. Flare endpoints + follower engine"
    - "4. Streaming endpoints"

  session_5:
    - "1. Calendar endpoints + holiday engine"
    - "2. Cycle tracking endpoints"
    - "3. Occurrence endpoints + unexpected event engine"
    - "4. Calendar-based vibes"

  session_6:
    - "1. Achievements system + achievement checker"
    - "2. Notifications endpoints"
    - "3. Background job additions"
    - "4. Admin panel expansions"
    - "5. Full integration testing"

  lsl_hud_build:  # After backend complete
    - "7 Need app screens (Pulse widget + individual apps)"
    - "7 Skill app screens"
    - "Career clock-in HUD"
    - "Heartbeat broadcast system"
    - "Proximity detection"
    - "Phone frame with case/wallpaper customization"
    - "Wavelength web player integration"
    - "Questionnaire link from Settings"
