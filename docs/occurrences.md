# Life Occurrences Design Document
# SL Phone HUD — Dynamic Life Events System
# ============================================================
#
# PHILOSOPHY
# Occurrences are chapters, not traits. They happen TO your character.
# They have a beginning, a middle, and an end.
# Some you choose. Some choose you.
#
# RULES
# - Hard cap of 5 active occurrences at once
# - Player adds/removes freely via the phone's Life app
# - Duration is set by the player when adding (within allowed range)
# - Some occurrences have mechanical auto-progression (pregnancy trimesters)
# - Unexpected occurrences fire randomly from a server-side event engine
#   based on character state — the server can surprise you
# - Mental health occurrences are opt-in via a separate toggle in Settings
# - All occurrences generate vibes. Some generate Lumen changes.
# - Occurrences show on your profile card — visible to party HUD wearers
#
# ============================================================

# ============================================================
# OCCURRENCE CATEGORIES
# ============================================================
#
# 1. RELATIONSHIP & SOCIAL
# 2. CAREER & FINANCIAL
# 3. PHYSICAL HEALTH
# 4. LIFE TRANSITIONS
# 5. UNEXPECTED EVENTS (server-generated surprises)
# 6. MENTAL HEALTH (opt-in separately)
#
# ============================================================

# ============================================================
# 1. RELATIONSHIP & SOCIAL OCCURRENCES
# ============================================================

occurrence: new_relationship
  display_name: "In a New Relationship 💕"
  category: relationship
  player_adds: true
  duration_range: "open-ended — resolves when player removes"
  mechanical_effects:
    - Social decay 15% slower
    - Purpose passive gain +0.1/min while Social above 65
    - Lumen spend on nice meals counts as "date" — double Purpose gain
  vibes:
    - name: "Butterflies 🦋"
      trigger: First login of the day
      effect: Purpose +8, Fun decay paused 1 hr — morning happiness
      alignment: positive

    - name: "Thinking About Them 💭"
      trigger: Social below 50 while occurrence active
      effect: Fun −5, Purpose −3 — missing them
      alignment: negative

    - name: "Couple Goals ✨"
      trigger: Both partners logged in and in proximity (if partner also has occurrence)
      effect: Both get −10% all decay for session
      alignment: positive

    - name: "Argument 😤"
      trigger: Random (8% chance daily) — relationships aren't perfect
      effect: Social gains −20% for 2 hrs, Purpose −5
      alignment: negative

    - name: "Making Up 🌹"
      trigger: Fires 2–4 hrs after Argument vibe expires
      effect: Purpose +15, Social gains +20% for 2 hrs
      alignment: positive

occurrence: breakup
  display_name: "Going Through a Breakup 💔"
  category: relationship
  player_adds: true
  duration_range: "3–30 days (player sets)"
  mechanical_effects:
    - Purpose decays 20% faster
    - Fun gains −15%
    - Social decay faster when alone
  vibes:
    - name: "Not Okay 🌧️"
      trigger: First login of the day for first 3 days
      effect: Purpose −10 flat, Fun −8
      alignment: negative

    - name: "Cry Eating 🍜"
      trigger: Nice meal eaten with Purpose below 35
      effect: Hunger fully restored AND Purpose +8 — comfort food works
      alignment: positive

    - name: "Actually Getting Better 🌱"
      trigger: Day 5+ of occurrence + Social above 60
      effect: Purpose passive gain resumes normally — healing is happening
      alignment: positive

    - name: "Saw Something That Reminded Me 😞"
      trigger: Random (15% chance daily)
      effect: Purpose −6, Fun −5 flat
      alignment: negative

    - name: "Genuinely Fine 💅"
      trigger: Occurrence past day 10 + all needs above 60
      effect: Purpose +15 flat — turned a corner
      alignment: positive

occurrence: friendship_drama
  display_name: "Friendship Drama 😬"
  category: relationship
  player_adds: true
  duration_range: "1–14 days"
  mechanical_effects:
    - Social gains from group activities −15%
    - Charisma XP −5%
  vibes:
    - name: "Picking Sides 😶"
      trigger: In group of 3+ players
      effect: Social gains halved — uncomfortable group dynamics
      alignment: negative

    - name: "Venting Session 💬"
      trigger: 1-on-1 conversation for 10+ min
      effect: Purpose +8, occurrence duration −1 day — talking helps
      alignment: positive

    - name: "Petty 😒"
      trigger: Random (20% chance daily)
      effect: Charisma XP −8% today, Fun −3
      alignment: negative

    - name: "Squashed It 🤝"
      trigger: Social above 75 for 2 consecutive days
      effect: Occurrence resolves early, Purpose +10
      alignment: positive

occurrence: new_friendship
  display_name: "New Friend Group 🌟"
  category: relationship
  player_adds: true
  duration_range: "open-ended"
  mechanical_effects:
    - Social gains from group activities +10%
    - Fun gains from events +10%
  vibes:
    - name: "Found My People 🥰"
      trigger: In group of 3+ HUD wearers at an event
      effect: Purpose +10, all decay −8% for session
      alignment: positive

    - name: "FOMO When I'm Not There 😩"
      trigger: Alone for 3+ hrs while occurrence active
      effect: Fun −8, Social decay faster
      alignment: negative

# ============================================================
# 2. CAREER & FINANCIAL OCCURRENCES
# ============================================================

occurrence: new_job
  display_name: "Just Started a New Job 📋"
  category: career
  player_adds: true
  duration_range: "7–30 days (settling-in period)"
  mechanical_effects:
    - Lumen earn rate −10% (still learning)
    - Energy decays 10% faster on work days
  vibes:
    - name: "First Day Energy ✨"
      trigger: First shift after adding occurrence
      effect: Purpose +12, Lumen penalty waived for first shift
      alignment: positive

    - name: "Imposter Syndrome 😰"
      trigger: Random (20% chance on any work day)
      effect: Lumen earn −15% today, Purpose −5
      alignment: negative

    - name: "Getting The Hang Of It 📈"
      trigger: Occurrence past day 7 + shift completed
      effect: Earn rate penalty reduced to −5%
      alignment: positive

    - name: "Actually Good At This 💪"
      trigger: Occurrence past day 14 + no Imposter Syndrome fired in 3 days
      effect: Occurrence resolves, earn rate fully restored + Purpose +10
      alignment: positive

occurrence: job_loss
  display_name: "Lost My Job 📦"
  category: career
  player_adds: true
  unexpected: true  # can also fire from server event engine
  duration_range: "open-ended — resolves when player starts new job"
  mechanical_effects:
    - No active job slot available (can still do odd jobs)
    - Lumen balance checked — if below 100, Broke vibe fires more easily
    - Purpose decays 12% faster
  vibes:
    - name: "What Do I Do Now 😶"
      trigger: First day of occurrence
      effect: Purpose −12 flat, all skill XP −5% today
      alignment: negative

    - name: "Unexpected Free Time 🌤️"
      trigger: Day 3+ + at least 1 odd job completed
      effect: Fun gains +10% — finding silver linings
      alignment: positive

    - name: "Actually Fine, I Hated That Job 😤"
      trigger: Random (25% chance after day 5)
      effect: Purpose +8 flat — relief sets in
      alignment: positive

    - name: "This Is Getting Stressful 😰"
      trigger: Day 10+ + Lumen balance below 150
      effect: Purpose −10, Fun decay faster — financial pressure mounting
      alignment: negative

    - name: "New Chapter 🚪"
      trigger: Starts a new job while this occurrence active
      effect: Occurrence resolves, Purpose +15, New Job occurrence auto-adds
      alignment: positive

occurrence: promotion
  display_name: "Just Got Promoted 🎉"
  category: career
  player_adds: false  # auto-fires when career tier increases
  duration_range: "3 days — the glow doesn't last forever"
  mechanical_effects:
    - Purpose passive gain doubled
    - Lumen earn rate +5% during occurrence
  vibes:
    - name: "On Top Of The World 🌟"
      trigger: Occurrence start
      effect: Purpose +20 flat, all needs decay −10% for 24 hrs
      alignment: positive

    - name: "Imposter Energy 😬"
      trigger: Day 2 of occurrence
      effect: Purpose −5 flat — the reality of new responsibilities
      alignment: negative

    - name: "Told Everyone 😄"
      trigger: In group of 2+ when occurrence active
      effect: Social +8 flat, nearby players get +3 Purpose — sharing good news
      alignment: positive

occurrence: financial_windfall
  display_name: "Unexpected Money 💸"
  category: financial
  player_adds: true
  unexpected: true  # also fires from server event engine
  duration_range: "instant — resolves immediately after Lumen grant"
  unexpected_triggers:
    - "Inheritance from distant relative"
    - "Found money"
    - "Won a small prize"
    - "Overpaid and refunded"
  mechanical_effects:
    - Instant Lumen grant: ✦50–200 (randomized by server on unexpected fire)
    - If player-added: player specifies flavor text, server grants ✦50 flat
  vibes:
    - name: "Treat Yourself 🛍️"
      trigger: Windfall received
      effect: Next Lumen purchase costs 20% less — spend it while it's fresh
      duration: 2 hrs after receiving
      alignment: positive

    - name: "Should Probably Save This 😬"
      trigger: Windfall received when already above ✦500
      effect: Purpose +3 — the relief of abundance
      alignment: positive

occurrence: robbery
  display_name: "Got Robbed 😱"
  category: financial
  player_adds: true
  unexpected: true  # primary source — server fires this randomly
  unexpected_chance: "3% per day if player is in a grey-area zone"
  duration_range: "instant effect + 3-day aftermath occurrence"
  mechanical_effects:
    - Instant Lumen loss: 20–40% of current balance
    - During 3-day aftermath: Hygiene decays faster (stress), Social gains −10%
  vibes:
    - name: "Shaken 😰"
      trigger: Immediately after robbery
      effect: Purpose −15 flat, Fun decay 2× for 24 hrs
      alignment: negative

    - name: "Telling Everyone 😤"
      trigger: 1-on-1 conversation within 6 hrs of robbery
      effect: Social +8 flat — venting helps, the other player gets +5 Purpose for listening
      alignment: positive

    - name: "Won't Happen Again 😤"
      trigger: Day 3 of aftermath
      effect: Purpose +8 — resolve formed, occurrence ends
      alignment: positive

    - name: "Still Jumpy 😬"
      trigger: Random (30% chance during 3-day aftermath)
      effect: Energy −5, Fun −5 — hypervigilance
      alignment: negative

occurrence: financial_stress
  display_name: "Financially Stressed 💸"
  category: financial
  player_adds: true
  unexpected: true  # auto-fires if Lumen balance below 50 for 3+ days
  duration_range: "auto-resolves when Lumen balance above 200"
  mechanical_effects:
    - Can only use free need objects (water, rest, basic hygiene)
    - Purpose decays 10% faster
    - Odd job daily limit increased to 3 (desperation bonus)
  vibes:
    - name: "Broke 💸"
      trigger: Occurrence start
      effect: Fun gains −20%, Purpose −8 flat
      alignment: negative

    - name: "Resourceful 🔧"
      trigger: Day 2+ + both odd jobs completed
      effect: Purpose +6 — making it work
      alignment: positive

    - name: "Small Win 🎯"
      trigger: Lumen balance increases by 50+ in one day
      effect: Purpose +10, Fun +5 — momentum
      alignment: positive

    - name: "Asking For Help 🤝"
      trigger: Another player completes an odd job nearby
      effect: +8 Social, Purpose +5 — community catches you
      alignment: positive

# ============================================================
# 3. PHYSICAL HEALTH OCCURRENCES
# ============================================================

occurrence: pregnancy
  display_name: "Pregnant 🤰"
  category: physical_health
  player_adds: true
  requires_biology: "female_agab or intersex"  # biology profile check
  duration_range: "auto-progresses through 3 trimesters over 42 real days"
  # Each trimester = 14 real days
  sub_stages:
    trimester_1:
      display: "First Trimester 🤰"
      mechanical_effects:
        - Hunger decays 20% faster (eating for two)
        - Energy decays 15% faster (exhaustion)
        - Nausea vibe possible
      vibes:
        - name: "Morning Sickness 🤢"
          trigger: Random (40% chance daily in T1)
          effect: Hunger gains halved for 2 hrs, Fun −8
          alignment: negative
        - name: "Glowing ✨"
          trigger: All needs above 65 in T1
          effect: Purpose +10, Social +5 — the good days
          alignment: positive
        - name: "So Tired 😴"
          trigger: Energy below 50 in T1
          effect: Energy decay 2×, Nap gives less restore
          alignment: negative
        - name: "Telling People 💕"
          trigger: In group of 2+ after day 7 of T1
          effect: Purpose +12, nearby players get +5 Purpose
          alignment: positive

    trimester_2:
      display: "Second Trimester 🤰"
      mechanical_effects:
        - Hunger decays 25% faster
        - Energy normalizes
        - Hygiene decays slightly faster
      vibes:
        - name: "Nesting 🏠"
          trigger: In home zone for 2+ hrs
          effect: Purpose +8, all decay −10% — the urge to prepare
          alignment: positive
        - name: "Uncomfortable 😮‍💨"
          trigger: Random (25% chance daily)
          effect: Energy −5, Fun −5
          alignment: negative
        - name: "Feeling Movements 🥺"
          trigger: Random (20% chance daily in T2)
          effect: Purpose +15 flat — overwhelming
          alignment: positive

    trimester_3:
      display: "Third Trimester 🤰"
      mechanical_effects:
        - Hunger decays 30% faster
        - Energy decays 20% faster
        - Movement restricted (location-based jobs pay 20% less — harder to work)
      vibes:
        - name: "Ready Now Please 😩"
          trigger: Day 10+ of T3
          effect: Fun −10%, Purpose fluctuates wildly
          alignment: negative
        - name: "Nesting Hard 🏠"
          trigger: In home zone in T3
          effect: All decay −15%, Purpose +5/hr passive
          alignment: positive
        - name: "Almost There 🌟"
          trigger: Day 13 of T3
          effect: Purpose +20 flat — anticipation
          alignment: positive

  resolution:
    - After T3 completes (day 42): occurrence resolves
    - New Parent occurrence auto-adds
    - Pregnancy occurrence can be ended early by player (miscarriage/loss — handled sensitively, no mechanics, just narrative removal)

occurrence: new_parent
  display_name: "New Parent 👶"
  category: physical_health
  player_adds: true
  auto_adds_from: pregnancy
  duration_range: "open-ended or 90 days if player sets a limit"
  mechanical_effects:
    - Energy decays 25% faster (sleep deprivation)
    - Purpose passive gain doubled (meaning is high)
    - Social decay slower (nesting with family)
  vibes:
    - name: "Sleep Deprived 😵"
      trigger: Energy below 60
      effect: All XP −5%, Energy harder to restore
      alignment: negative
    - name: "Worth It 🥺"
      trigger: Energy below 40 but Purpose above 75
      effect: Purpose +10 flat — exhausted but fulfilled
      alignment: positive
    - name: "First Smile 🌟"
      trigger: Random (daily, 20% chance) in first 30 days
      effect: Purpose +20 flat — the moments that make it real
      alignment: positive
    - name: "Touched Out 😶"
      trigger: Social above 80 (everyone wants to see the baby)
      effect: Social gains halved — need personal space
      alignment: negative
    - name: "Village 🫂"
      trigger: Another player completes odd job for them
      effect: Energy +15 flat, Purpose +8 — it takes a village
      alignment: positive

occurrence: illness_mild
  display_name: "Under The Weather 🤧"
  category: physical_health
  player_adds: true
  unexpected: true  # server can fire randomly (2% chance if Energy was below 20 for 24hrs)
  duration_range: "2–7 days (player sets)"
  mechanical_effects:
    - Energy decays 20% faster
    - Hunger decays 15% faster (body needs fuel to heal)
    - All skill XP −8%
  vibes:
    - name: "Just Want To Rest 😴"
      trigger: Occurrence start
      effect: Purpose −5, rest restores 20% more Energy — body knows what it needs
      alignment: negative
    - name: "Soup Helps 🍜"
      trigger: Any meal eaten
      effect: Hunger gain +20%, small Purpose boost — comfort
      alignment: positive
    - name: "Pushing Through 💪"
      trigger: Completes a work shift while ill
      effect: Purpose +10, ✦5 bonus — showed up anyway
      alignment: positive
    - name: "Getting Worse 🤒"
      trigger: Energy hits critical while ill
      effect: Duration extended by 1 day, all XP halved
      alignment: negative
    - name: "Finally Better 🌤️"
      trigger: Occurrence end
      effect: Purpose +8, Energy decay normal — the relief of wellness
      alignment: positive

occurrence: injury
  display_name: "Recovering From Injury 🩹"
  category: physical_health
  player_adds: true
  duration_range: "7–30 days (player sets)"
  mechanical_effects:
    - Fitness XP −30% (can't train properly)
    - Energy decays 15% faster
    - Location-based jobs pay 15% less (slower, less effective)
  vibes:
    - name: "Can't Do What I Normally Do 😞"
      trigger: Gym session attempted
      effect: Session gives no Fitness XP, Energy drains faster
      alignment: negative
    - name: "Finding Other Ways 📚"
      trigger: Non-physical skill object used
      effect: That skill XP +5% — redirected energy
      alignment: positive
    - name: "Cabin Fever 😤"
      trigger: Day 7+ + no gym for 5 days
      effect: Fun decay faster, slight Purpose dip
      alignment: negative
    - name: "Finally Healed 💪"
      trigger: Occurrence end
      effect: Purpose +10, first gym session after gives double Fitness XP
      alignment: positive

occurrence: chronic_condition
  display_name: "Managing a Chronic Condition ♾️"
  category: physical_health
  player_adds: true
  duration_range: "open-ended — part of life"
  mechanical_effects:
    - One need (player chooses which) decays 15% faster permanently
    - Energy has a lower effective ceiling (max 85 instead of 100)
  vibes:
    - name: "Flare Up 😮‍💨"
      trigger: Random (15% chance daily)
      effect: Chosen need decays 2× today, Energy −10 flat
      alignment: negative
    - name: "Good Day 🌤️"
      trigger: Random (20% chance daily) — good days exist
      effect: All decay normal today, the chosen need behaves itself
      alignment: positive
    - name: "Managing It 💊"
      trigger: Chosen need kept above 50 for 7 consecutive days
      effect: Purpose +10 flat — the discipline of self-management
      alignment: positive
    - name: "Explaining Myself 😔"
      trigger: Social interaction when Energy below 40
      effect: Social gains −10% — exhausting to explain
      alignment: negative

# ============================================================
# 4. LIFE TRANSITIONS
# ============================================================

occurrence: moving
  display_name: "Moving / Settling Into New Place 📦"
  category: life_transition
  player_adds: true
  duration_range: "3–14 days"
  mechanical_effects:
    - Homebody trait bonus paused (home zone feels foreign)
    - Hygiene decays slightly faster (chaos of moving)
    - Purpose fluctuates
  vibes:
    - name: "Everything In Boxes 📦"
      trigger: Occurrence start
      effect: Fun decay faster, Purpose −5
      alignment: negative
    - name: "Fresh Start ✨"
      trigger: Day 3+ + all needs above 55
      effect: Purpose +12, occurrence resolves early
      alignment: positive
    - name: "This Is Mine 🏠"
      trigger: First time resting in new home zone
      effect: Purpose +10, Homebody bonus resumes
      alignment: positive

occurrence: bereavement
  display_name: "Grieving a Loss 🕯️"
  category: life_transition
  player_adds: true
  duration_range: "7–60 days (player sets)"
  mechanical_effects:
    - Purpose decays 20% faster
    - Fun gains −20%
    - Social needed more than usual for Purpose stability
  vibes:
    - name: "Grief Wave 🌊"
      trigger: Random (30% chance daily for first 14 days)
      effect: Purpose −12 flat, Fun −10
      alignment: negative
    - name: "They Would Have Liked This 🌷"
      trigger: Fun above 65 while occurrence active
      effect: Purpose +10 flat — permission to enjoy things
      alignment: positive
    - name: "Telling Stories 🕯️"
      trigger: 1-on-1 conversation for 15+ min
      effect: Purpose +12, grief wave less likely today
      alignment: positive
    - name: "Just A Normal Day 🌤️"
      trigger: All needs above 60 for full day
      effect: Purpose +8 — the ordinary feels like a gift
      alignment: positive
    - name: "Still Here 💙"
      trigger: Occurrence past day 30
      effect: Grief waves become less frequent, Purpose floor rises
      alignment: positive

occurrence: new_home_city
  display_name: "New In Town 🗺️"
  category: life_transition
  player_adds: true
  duration_range: "14–30 days"
  mechanical_effects:
    - Social gains from new players +20% (everyone is new, more open)
    - Social decay faster (no established connections yet)
  vibes:
    - name: "Don't Know Anyone 😶"
      trigger: Alone for 2+ hrs in first week
      effect: Social decay 2×, Fun −8
      alignment: negative
    - name: "Made A Friend 🌟"
      trigger: First 5 interactions with a new player
      effect: Purpose +10, that player gets Familiar relationship bonus
      alignment: positive
    - name: "Actually Love It Here 🏙️"
      trigger: Day 10+ + Social above 65
      effect: Occurrence resolves early, Purpose +15
      alignment: positive

# ============================================================
# 5. UNEXPECTED EVENTS (server-generated)
# ============================================================
# These fire automatically from the server event engine.
# Players can dismiss them from the Life app but not prevent them.
# Some fire based on conditions. Some are purely random.

unexpected_event: found_money
  display_name: "Found Some Money 💵"
  trigger_condition: "random 1% daily chance"
  effect: "✦15–30 added to wallet instantly"
  vibe:
    - name: "Lucky Day 🍀"
      effect: Next purchase 15% cheaper, Purpose +5
      duration: 2 hrs

unexpected_event: inheritance
  display_name: "Inheritance From Distant Relative 📜"
  trigger_condition: "random 0.5% daily chance — rare"
  effect: "✦100–300 added to wallet"
  vibe:
    - name: "Didn't Even Know Them 😶"
      effect: Purpose fluctuates — complicated feelings about unexpected money
      duration: 24 hrs
    - name: "Treat Yourself 🛍️"
      effect: Next big purchase gives bonus Purpose
      duration: 48 hrs

unexpected_event: spontaneous_job_loss
  display_name: "Unexpectedly Let Go 📦"
  trigger_condition: "2% daily chance if player hasn't worked in 5+ days (neglect)"
  effect: "Current job removed, Job Loss occurrence added"
  note: "Flavor: 'You were let go due to extended absence.'"

unexpected_event: robbery
  display_name: "Robbed 😱"
  trigger_condition: "3% daily chance if player is in grey-area zone"
  effect: "20–40% of Lumen balance removed, Robbery occurrence added"

unexpected_event: surprise_gift
  display_name: "Someone Left You Something 🎁"
  trigger_condition: "fires when a Connector-trait player completes odd job near you"
  effect: "✦10–20 added, Purpose +8"
  vibe:
    - name: "People Are Good 🌷"
      effect: Social gains +10% for 4 hrs
      duration: 4 hrs

unexpected_event: viral_moment
  display_name: "Went Viral 📱"
  trigger_condition: "Content Creator career tier 2+ + random 5% weekly chance"
  effect: "✦50 bonus, Influencer occurrence added for 3 days"
  vibe:
    - name: "15 Minutes 🌟"
      effect: Lumen earn rate +20% for 3 days, Social gains +15%
      duration: 3 days

unexpected_event: illness_exposure
  display_name: "Came Down With Something 🤧"
  trigger_condition: "2% daily chance if Energy was below 20 for 24+ hrs"
  effect: "Mild Illness occurrence auto-added for 3 days"

unexpected_event: lucky_find
  display_name: "Found Something Useful 🎲"
  trigger_condition: "random 2% daily chance"
  effect: "Random: free meal, hygiene item, or skill session granted"
  vibe:
    - name: "Right Place Right Time 🍀"
      effect: Purpose +5, Fun +5
      duration: Instant

# ============================================================
# 6. MENTAL HEALTH OCCURRENCES (opt-in only)
# ============================================================
# Requires player to enable Mental Health Occurrences in Settings.
# These are handled with care — they enrich RP but never punish.
# All have clear paths toward feeling better.
# Negative effects are real but never trap the player permanently.

occurrence: depression_episode
  display_name: "Going Through A Hard Time 🌧️"
  category: mental_health
  opt_in_required: true
  player_adds: true
  duration_range: "7–30 days (player sets)"
  mechanical_effects:
    - Purpose decays 15% faster
    - Fun gains −20%
    - Getting out of bed is harder — Energy ceiling 85
    - BUT: small wins feel bigger (Purpose gains from completing things doubled)
  vibes:
    - name: "Heavy 😶"
      trigger: First login of day
      effect: Purpose −5, Fun decay faster
      alignment: negative
    - name: "Couldn't Do It Today 😔"
      trigger: Logged in but no actions taken for 30+ min
      effect: Purpose −3 — the stillness
      alignment: negative
    - name: "Did The Thing 🌱"
      trigger: Any skill object used or odd job completed
      effect: Purpose +10 flat — the small wins matter more
      alignment: positive
    - name: "Good Hour 🌤️"
      trigger: Fun above 65 while occurrence active
      effect: Purpose +8 flat — the unexpected windows of okay-ness
      alignment: positive
    - name: "Getting Help 💙"
      trigger: Therapy occurrence active simultaneously
      effect: Depression episode duration capped at 14 days, vibes less severe
      alignment: positive
    - name: "Turned A Corner 🌅"
      trigger: Day 14+ + Fun above 60 for 3 consecutive days
      effect: Occurrence resolves early if player chooses
      alignment: positive

occurrence: anxiety_disorder
  display_name: "High Anxiety 😰"
  category: mental_health
  opt_in_required: true
  player_adds: true
  duration_range: "open-ended or timed (player chooses)"
  mechanical_effects:
    - Overthinking vibe triggers more easily (lower threshold)
    - Social gains −10% in groups (on edge)
    - BUT: when calm (all needs above 65), XP gains +5%
  vibes:
    - name: "On Edge 😬"
      trigger: Any 2 needs in warning zone
      effect: Social gains −20%, Fun decay faster
      alignment: negative
    - name: "Panic Moment 😰"
      trigger: Random (10% daily chance)
      effect: Energy −8 flat, Fun −10, Social −5 — it hits suddenly
      alignment: negative
    - name: "Breathing Through It 🧘"
      trigger: Energy above 70 after Panic Moment
      effect: Panic Moment clears, Purpose +5 — managed it
      alignment: positive
    - name: "Calm Day 🌿"
      trigger: All needs above 65 for full login session
      effect: XP +5%, Purpose passive gain doubled — the good days feel earned
      alignment: positive
    - name: "Therapy Helping 💙"
      trigger: Therapy occurrence active
      effect: Panic Moment chance reduced to 5%, On Edge threshold raises
      alignment: positive

occurrence: therapy
  display_name: "In Therapy 🛋️"
  category: mental_health
  opt_in_required: true
  player_adds: true
  duration_range: "open-ended"
  mechanical_effects:
    - Purpose floor raised to 25 (always something to hold onto)
    - Negative vibes expire 15% faster
    - All mental health occurrences less severe while active
    - Costs ✦20/week (therapy isn't free)
  vibes:
    - name: "Processing 🌀"
      trigger: Once per week, random day
      effect: Purpose −5 then +15 — the session was hard but helpful
      alignment: neutral
    - name: "Breakthrough 💡"
      trigger: Random (10% weekly chance)
      effect: Purpose +20 flat, one active negative vibe clears
      alignment: positive
    - name: "Resistance 😶"
      trigger: Random (15% weekly chance)
      effect: Purpose −5 — some weeks are just hard
      alignment: negative
    - name: "Tools Working 🔧"
      trigger: Successfully navigates a Panic Moment or Spiraling vibe
      effect: Purpose +8, therapy XP tracked (future skill?)
      alignment: positive

occurrence: addiction_recovery
  display_name: "In Recovery 🌱"
  category: mental_health
  opt_in_required: true
  player_adds: true
  duration_range: "open-ended — this is a life chapter"
  mechanical_effects:
    - Purpose passive gain +0.1/min (sobriety builds meaning)
    - Coffee/stimulant items give no Buzzing vibe (careful with substances)
    - BUT: community interactions give +50% Social gain
  vibes:
    - name: "One Day At A Time 🕯️"
      trigger: Each day occurrence is active
      effect: Purpose +3 flat — the accumulation
      alignment: positive
    - name: "Craving 😶"
      trigger: Random (15% daily chance)
      effect: Fun −8, Purpose −5 — the pull
      alignment: negative
    - name: "Called My Sponsor 📞"
      trigger: 1-on-1 conversation when Craving active
      effect: Craving clears, Social +8, Purpose +10
      alignment: positive
    - name: "X Days Clean 🌟"
      trigger: Every 7 days the occurrence is active
      effect: Purpose +12 flat — the milestone
      alignment: positive
    - name: "Community 🫂"
      trigger: In group of 2+ HUD wearers
      effect: Social gains +15%, Purpose passive gain higher
      alignment: positive

# ============================================================
# OCCURRENCE STRUCTURE IN DATABASE
# ============================================================

# Table: player_occurrences
# player_id       INTEGER FK
# occurrence_key  TEXT
# started_at      TEXT datetime
# ends_at         TEXT datetime (null = open-ended)
# sub_stage       TEXT (for pregnancy trimesters etc)
# is_unexpected   BOOLEAN (true if server-generated)
# is_dismissed    BOOLEAN (player acknowledged)
# metadata        TEXT JSON (any extra data — e.g. robbery amount)

# Table: occurrence_vibe_log
# player_id       INTEGER FK
# occurrence_key  TEXT
# vibe_key        TEXT
# fired_at        TEXT datetime
# (prevents same vibe firing multiple times in short window)
