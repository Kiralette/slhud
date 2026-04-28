# Trait & Vibe Design Document
# SL Phone HUD — Character System
# XP bonuses capped at +5%. Each trait generates 4-5 vibes (mix of positive and negative).
# Vibes are temporary states. Traits are permanent personality shapers.

# ============================================================
# DESIGN PHILOSOPHY
# ============================================================
# - Traits shape HOW you experience the world, not HOW FAST you level
# - Every trait has both positive AND negative vibes regardless of alignment
# - Positive traits should occasionally backfire
# - Negative traits should occasionally produce something beautiful
# - No trait should feel mandatory or dominant
# - Vibes are surprising — players shouldn't always predict what fires

# ============================================================
# 🧠 MIND & PERSONALITY TRAITS
# ============================================================

trait: talkative
  alignment: positive
  description: Your character talks — a lot. They fill silences, strike up conversations easily, and rarely run out of things to say.
  mechanical_effects:
    - Social decay 10% slower (they naturally keep connections warm)
    - Charisma XP +5% (barely noticeable, just flavor)
  vibes:
    - name: "On A Roll 💬"
      alignment: positive
      trigger: Social above 75 + conversation with another player
      effect: Charisma XP doubled for next 30 min
      duration: 30 min

    - name: "Oversharing 😬"
      alignment: negative
      trigger: Social above 90 for 2+ hrs
      effect: Social gains halved — they've talked too much, people need space
      duration: 45 min

    - name: "Life of the Party 🎉"
      alignment: positive
      trigger: 3+ players nearby + Fun above 70
      effect: All nearby players get +5 Social, +3 Fun passively
      duration: While condition holds

    - name: "Can't Read the Room 🙄"
      alignment: negative
      trigger: Talking to another player whose Social is below 30
      effect: Target player gets -5 Social (they needed quiet), your Social -3
      duration: 20 min

    - name: "Magnetic ✨"
      alignment: positive
      trigger: Social above 80 + Purpose above 70
      effect: Odd job pay +15% — people want to work with them
      duration: Until either need drops below threshold

# ---

trait: bookworm
  alignment: positive
  description: Your character finds comfort and joy in reading, learning, and quiet intellectual pursuits.
  mechanical_effects:
    - Knowledge XP +5%
    - Fun gains from reading objects +10%
  vibes:
    - name: "Deep In It 📖"
      alignment: positive
      trigger: Using bookshelf/library for 10+ min
      effect: Social decay paused, Knowledge XP +10% for session
      duration: While reading

    - name: "Head In The Clouds ☁️"
      alignment: negative
      trigger: Knowledge above 80 + group of 2+ nearby
      effect: Social gains halved — too distracted to fully engage
      duration: 30 min

    - name: "Eureka! 💡"
      alignment: positive
      trigger: Skill level-up while Knowledge above 60
      effect: All skill XP +8% for 1 hour — one insight unlocks everything
      duration: 1 hr

    - name: "Restless Mind 🌀"
      alignment: negative
      trigger: No Knowledge XP earned in 24hrs
      effect: Fun decays 15% faster — boredom sets in without stimulation
      duration: Until Knowledge XP earned

    - name: "Hyperfocused 🧠"
      alignment: positive
      trigger: Fun above 75 + using any skill object
      effect: Skill XP +5%, Energy decay paused during session
      duration: While actively using skill object

# ---

trait: creative_soul
  alignment: positive
  description: Art, music, and making things — this is where they come alive.
  mechanical_effects:
    - Creativity XP +5%
    - Fun gains from creative objects +10%
  vibes:
    - name: "In The Zone 🎨"
      alignment: positive
      trigger: 15+ min using creative skill object
      effect: Purpose +8 flat, Creativity XP +5% for session
      duration: While creating

    - name: "Creative Block 😶"
      alignment: negative
      trigger: Failed to use any creative object for 48 hrs
      effect: Fun decay +20% — frustration builds without an outlet
      duration: Until creative object used

    - name: "Inspired 🌟"
      alignment: positive
      trigger: Attended an event or party (social creativity trigger)
      effect: Next creative session gives 2× Purpose gain
      duration: One session only

    - name: "Perfectionist Spiral 😤"
      alignment: negative
      trigger: Creativity XP earned but skill didn't level up
      effect: Fun −5 flat, slight Purpose dip — nothing feels good enough
      duration: 30 min

    - name: "Flow State 🌊"
      alignment: positive
      trigger: All needs above 60 simultaneously while using creative object
      effect: All XP from that session +5%, vibe feels incredible
      duration: While needs hold and creating

# ---

trait: overthinker
  alignment: negative
  description: Their brain never fully switches off. They analyze, catastrophize, and second-guess — exhaustingly.
  mechanical_effects:
    - Fun decays 15% faster (idle mind is a restless one)
    - Social gains halved when 2+ needs in Struggling zone
  vibes:
    - name: "Spiraling 😰"
      alignment: negative
      trigger: 2+ needs below 35
      effect: Social gains −40%, Fun drains faster
      duration: Until needs recover

    - name: "Hyperfocused 🧠"
      alignment: positive
      trigger: Fun above 70 while using any skill object
      effect: Skill XP +5% — anxiety channeled into productivity
      duration: While Fun holds

    - name: "Actually That Was Perfect 🥲"
      alignment: positive
      trigger: Successfully completes a shift without clocking out early
      effect: Purpose +10 flat — relief and pride hit together
      duration: Instant

    - name: "3am Brain 🌑"
      alignment: negative
      trigger: Logged in between midnight–4am SLT with Energy below 50
      effect: Fun decay 2×, Sleep doesn't fully restore Energy
      duration: Until Energy above 70

    - name: "Surprisingly Okay 😌"
      alignment: positive
      trigger: Social above 75 after previously having Spiraling vibe
      effect: Purpose +12 flat, Fun decay normal for 2 hrs — the relief is real
      duration: 2 hrs

# ---

trait: forgetful
  alignment: negative
  description: They mean well but can never quite hold onto things — tasks slip, names blur, routines fall apart.
  mechanical_effects:
    - Knowledge XP −5%
    - 8% random chance any timed action gives no XP (forgot to focus)
  vibes:
    - name: "Scattered 🌀"
      alignment: negative
      trigger: 2+ skill objects used in same session with no rest
      effect: Random skill gets 0 XP that session instead of the active one
      duration: Session

    - name: "Happy Accident 🍀"
      alignment: positive
      trigger: Triggered randomly (10% chance) on any action
      effect: That action gives double XP — stumbled into something great
      duration: Single action

    - name: "Wait What Was I Doing 😶"
      alignment: negative
      trigger: Same object used 3 days in a row
      effect: That object gives no XP today — autopilot kicked in
      duration: One day

    - name: "Fresh Eyes ✨"
      alignment: positive
      trigger: Returns to an object after 5+ days away
      effect: That session gives +8% XP — like rediscovering it
      duration: One session

    - name: "Oops 🙈"
      alignment: negative
      trigger: Clocks in for work then misses heartbeat (distracted)
      effect: Auto clock-out fires early, partial pay only
      duration: Instant

# ---

trait: curious
  alignment: neutral
  description: Always looking for something new. Routines bore them. Discovery is the whole point.
  mechanical_effects:
    - First use of any new object type gives bonus Fun
  vibes:
    - name: "New Obsession ✨"
      alignment: positive
      trigger: First time using any object type ever
      effect: 2× Fun and XP for that full session
      duration: First session only

    - name: "Already Over It 😑"
      alignment: negative
      trigger: Same object used 4 days in a row
      effect: That object gives −15% XP — boredom is real
      duration: Until a different object used

    - name: "Rabbit Hole 🕳️"
      alignment: positive
      trigger: Switching between 3+ different objects in one session
      effect: Knowledge XP +5% — connecting dots across different things
      duration: Session

    - name: "FOMO 😩"
      alignment: negative
      trigger: Another player uses an object type they've never tried
      effect: Fun −3 flat — restlessness kicks in
      duration: 20 min

    - name: "That's Actually Interesting 🤔"
      alignment: positive
      trigger: Knowledge skill levels up
      effect: Purpose +8 flat — the satisfaction of learning something real
      duration: Instant

# ============================================================
# 💪 BODY & PHYSICAL TRAITS
# ============================================================

trait: athletic
  alignment: positive
  description: Physical activity is natural to them. They push harder and recover faster.
  mechanical_effects:
    - Energy decays 8% slower
    - Fitness XP +5%
  vibes:
    - name: "Endorphin Rush 🏃"
      alignment: positive
      trigger: Gym session 10+ min
      effect: Energy decay paused 1 hr, Fun +5 flat
      duration: 1 hr

    - name: "Rest Day Guilt 😬"
      alignment: negative
      trigger: No physical activity for 48 hrs
      effect: Energy decays 10% faster, mild Purpose dip
      duration: Until gym/physical activity

    - name: "In The Body 💪"
      alignment: positive
      trigger: Energy above 80 + gym session
      effect: Fitness XP +5% for session, feels great
      duration: Session

    - name: "Overtraining 🥵"
      alignment: negative
      trigger: Gym used 3 sessions in one day
      effect: Energy decay 2× for rest of day, Fitness XP halved
      duration: Until midnight SLT reset

    - name: "Natural High 🌤️"
      alignment: positive
      trigger: Fitness skill levels up
      effect: All needs decay −5% for 2 hrs — the body just works better
      duration: 2 hrs

# ---

trait: iron_stomach
  alignment: positive
  description: They'll eat anything, anywhere, anytime. Their relationship with food is uncomplicated.
  mechanical_effects:
    - Hunger decays 8% slower
    - Basic meals give same Hunger gain as good meals
  vibes:
    - name: "Satisfied 😌"
      alignment: positive
      trigger: Hunger above 85
      effect: All decay −5% — contentment makes everything easier
      duration: While Hunger above 85

    - name: "Overate 🤢"
      alignment: negative
      trigger: Ate two meals within 30 min
      effect: Energy −8 flat, movement feels slow. No skill XP for 30 min
      duration: 30 min

    - name: "Comfort Eating 🍜"
      alignment: positive
      trigger: Hunger below 30 + eating any meal
      effect: Purpose +6 flat — food is genuinely comforting to them
      duration: Instant

    - name: "Bottomless Pit 😅"
      alignment: negative
      trigger: Hunger drops to critical despite eating recently
      effect: Hunger decays 15% faster for rest of day — body needs more
      duration: Until midnight SLT

    - name: "That Hit Different 🙌"
      alignment: positive
      trigger: Nice restaurant meal when all other needs above 60
      effect: Fed & Happy vibe extended by 1 hr, Purpose +5
      duration: Extended vibe

# ---

trait: slob
  alignment: negative
  description: Hygiene is... not a priority. The mess doesn't bother them. Other people might disagree.
  mechanical_effects:
    - Hygiene decays 35% faster
    - Stinky vibe triggers at 30 instead of 20
  vibes:
    - name: "Funky 🧦"
      alignment: negative
      trigger: Hygiene below 40
      effect: Social gains reduced 20%, visible on nearby players' party HUD
      duration: Until Hygiene above 50

    - name: "Actually Feel Human 🛁"
      alignment: positive
      trigger: Shower or bath taken when Hygiene was below 25
      effect: Purpose +12 flat — the contrast hits hard
      duration: Instant

    - name: "Couldn't Care Less 😎"
      alignment: positive
      trigger: Hygiene below 30 but Social above 65
      effect: Confidence boost — immune to social penalties from Hygiene for 1 hr
      duration: 1 hr

    - name: "Even They Noticed 😳"
      alignment: negative
      trigger: Hygiene hits zero
      effect: Forced emote fires, Social −15 flat, can't gain Social until showered
      duration: Until hygiene above 40

    - name: "Surprisingly Fresh 🌸"
      alignment: positive
      trigger: Takes a bath (5+ min) voluntarily
      effect: Glowing Up vibe fires, Social gains +20% for 2 hrs — the effort shows
      duration: 2 hrs

# ---

trait: couch_potato
  alignment: negative
  description: Exercise is genuinely not their thing. Rest is their natural state.
  mechanical_effects:
    - Fitness XP −5%
    - Energy decays 10% faster during physical activity
  vibes:
    - name: "Heavy Legs 😮‍💨"
      alignment: negative
      trigger: Gym session attempted with Energy below 50
      effect: Energy drains faster during session instead of restoring
      duration: Session

    - name: "Surprisingly Refreshed 😯"
      alignment: positive
      trigger: Completes full gym session despite being Couch Potato
      effect: Purpose +10 flat — genuine surprise at themselves
      duration: Instant

    - name: "This Is Fine 🛋️"
      alignment: positive
      trigger: Energy above 80 from resting (not gym)
      effect: All decay −8% — they're in their element doing nothing
      duration: While Energy above 80 from rest

    - name: "Ugh Fine 😒"
      alignment: negative
      trigger: Another player invites to gym (shared activity)
      effect: Fun −5 flat, Energy −3 before even starting
      duration: 20 min

    - name: "Wait I Kind Of Like This 😳"
      alignment: positive
      trigger: Fitness skill reaches level 2 (despite everything)
      effect: Gym sessions restore Energy normally from now on — body adapted
      duration: Permanent unlock

# ---

trait: picky_eater
  alignment: negative
  description: They have opinions about food and they're not shy about them.
  mechanical_effects:
    - Basic meals restore 25% less Hunger
    - Hunger decays 8% faster
  vibes:
    - name: "Not Hungry 🙄"
      alignment: negative
      trigger: Only basic meals available (no good/nice options nearby)
      effect: Hunger warnings come earlier, mood slightly sour
      duration: Until better food found

    - name: "Finally Something Good 😩"
      alignment: positive
      trigger: Nice meal eaten after Hunger was below 30
      effect: Purpose +10 flat, Fed & Happy vibe extended 1 hr
      duration: Extended

    - name: "I Guess This Is Fine 😐"
      alignment: neutral
      trigger: Basic meal eaten when Hunger critical
      effect: Hunger restored normally just this once — survival instinct
      duration: Instant

    - name: "Honestly Obsessed 🤤"
      alignment: positive
      trigger: Same nice meal object used 3 days in a row
      effect: That specific meal gives +10% extra Hunger — they found their thing
      duration: Permanent for that object

    - name: "This Is Inedible 🤮"
      alignment: negative
      trigger: Ate basic meal with Hunger above 50 (wasn't even hungry enough)
      effect: Fun −5, mild Purpose dip — why did they do that
      duration: 20 min

# ---

trait: night_owl
  alignment: neutral
  description: They come alive when the world goes quiet. Mornings are enemies.
  mechanical_effects:
    - All XP +5% between 9pm–3am SLT
    - Energy decay slightly faster before noon SLT
  vibes:
    - name: "Second Wind 🌙"
      alignment: positive
      trigger: Still active after midnight SLT with Energy above 40
      effect: All XP +5%, Fun decay paused until 3am SLT
      duration: Until 3am SLT or Energy below 40

    - name: "Morning Is A Crime ☠️"
      alignment: negative
      trigger: Logged in before 9am SLT
      effect: All XP −5%, Energy decays faster until noon
      duration: Until noon SLT

    - name: "The City Never Sleeps 🏙️"
      alignment: positive
      trigger: Working a job shift between 10pm–2am SLT
      effect: Lumen earn rate +8% — peak performance hours
      duration: During late shift

    - name: "Couldn't Sleep 😵"
      alignment: negative
      trigger: Energy hits critical between midnight and 6am SLT
      effect: Energy restoration from rest halved — the bed just doesn't help
      duration: Until 6am SLT reset

    - name: "Golden Hour 🌅"
      alignment: positive
      trigger: Still awake at 5am SLT with Fun above 60
      effect: Purpose +10 flat — something poetic about being up this late
      duration: Instant

# ---

trait: morning_person
  alignment: neutral
  description: Early starts feel natural. The quiet of the morning is genuinely their favorite time.
  mechanical_effects:
    - All XP +5% between 6am–12pm SLT
    - Energy decay slightly faster after 8pm SLT
  vibes:
    - name: "Early Bird ☀️"
      alignment: positive
      trigger: Active before 9am SLT with Energy above 60
      effect: All XP +5%, first action of the day gives double Fun
      duration: Until noon SLT

    - name: "Fading Fast 🌒"
      alignment: negative
      trigger: Still active after 9pm SLT
      effect: Energy decays 15% faster, XP −5%
      duration: Until logged off or midnight

    - name: "Perfect Morning 🌤️"
      alignment: positive
      trigger: All needs above 65 before noon SLT
      effect: Main Character Energy vibe has 30% chance to fire
      duration: Instant roll

    - name: "Everyone Else Is Wasting The Day 😤"
      alignment: negative
      trigger: Social below 40 before noon SLT (nobody's online)
      effect: Fun decays faster — morning is only good with purpose
      duration: Until Social recovers

    - name: "Got A Head Start 📋"
      alignment: positive
      trigger: Completes an odd job before noon SLT
      effect: Second odd job slot unlocks for today — early bird bonus
      duration: Today only

# ============================================================
# ❤️ SOCIAL & EMOTIONAL TRAITS
# ============================================================

trait: extrovert
  alignment: positive
  description: People give them energy. Groups are comfortable. Silence feels wrong.
  mechanical_effects:
    - Social never decays while in a group of 2+
    - Social gains +10% in groups
  vibes:
    - name: "On One 🔥"
      alignment: positive
      trigger: 3+ players nearby + Social above 75
      effect: Spreads +4 Social to all nearby players passively
      duration: While players nearby

    - name: "Why Is Nobody Here 😩"
      alignment: negative
      trigger: Alone for 2+ hrs
      effect: Fun decays 20% faster, Purpose slowly dips
      duration: Until another player nearby

    - name: "Center Of Gravity 🌟"
      alignment: positive
      trigger: Social above 85 at an event
      effect: Event gives +50% Social gains to all attendees
      duration: While at event with high Social

    - name: "Drained By The Wrong People 😶"
      alignment: negative
      trigger: Social interaction with a player who has Stinky or Not Okay vibe
      effect: Their Social gain is halved — bad energy is contagious
      duration: 30 min

    - name: "In Your Element 🎯"
      alignment: positive
      trigger: Social above 90
      effect: Charisma XP +5%, all needs decay −5%
      duration: While Social above 90

# ---

trait: empath
  alignment: positive
  description: They feel what others feel. This is both their gift and their burden.
  mechanical_effects:
    - Helping other players gives +5 Purpose automatically
  vibes:
    - name: "Heart Full 🥰"
      alignment: positive
      trigger: Completed odd job involving another player
      effect: Purpose +12 flat, Social +8 flat
      duration: Instant

    - name: "Taking On Too Much 😔"
      alignment: negative
      trigger: 2+ nearby players have negative vibes active
      effect: Fun −8 flat, Purpose dips — absorbs others' bad energy
      duration: Until negative-vibe players leave proximity

    - name: "You Need This More Than Me 🤲"
      alignment: positive
      trigger: Shares a food/drink item with another player (if scripted sharing exists)
      effect: Their Hunger gain is given to the other player instead — feels purposeful
      duration: Instant

    - name: "Compassion Fatigue 🕯️"
      alignment: negative
      trigger: Helped 3+ players in one day
      effect: Social gains halved for rest of day — emotionally spent
      duration: Until midnight SLT

    - name: "Contagious Joy 🌈"
      alignment: positive
      trigger: Purpose above 80 in a group
      effect: All nearby players get +5 Purpose passively
      duration: While Purpose above 80 and in group

# ---

trait: introvert
  alignment: negative
  description: People are a lot. They need quiet to feel okay.
  mechanical_effects:
    - Energy decays 15% faster in groups of 3+
    - Social gains halved in groups of 3+
  vibes:
    - name: "People'd Out 🔋"
      alignment: negative
      trigger: In group of 3+ for 30+ min
      effect: Energy decay 2×, needs quiet time to recover
      duration: Until alone 15+ min

    - name: "Recharging 🌿"
      alignment: positive
      trigger: Alone for 30+ min with Energy above 40
      effect: All decay −15%, Purpose rises passively
      duration: While alone

    - name: "Actually Having Fun 😮"
      alignment: positive
      trigger: In group of exactly 2 (one-on-one) with Social above 60
      effect: Social gains normal (not halved), Fun +5
      duration: While in 1-on-1

    - name: "Please Stop Talking To Me 😶"
      alignment: negative
      trigger: Talkative-trait player initiates conversation while Energy below 40
      effect: Social gives −5 instead of positive gain
      duration: 20 min

    - name: "Deep Conversation 🌌"
      alignment: positive
      trigger: 1-on-1 conversation for 15+ min
      effect: Purpose +10, Social fully restored — the right kind of people
      duration: Instant

# ---

trait: hot_headed
  alignment: negative
  description: Patience is short. Temper is close to the surface. It burns bright and burns fast.
  mechanical_effects:
    - Social interactions give −5 when Energy below 40
    - Fitness XP +5% (anger is fuel)
  vibes:
    - name: "Irritable 😤"
      alignment: negative
      trigger: Energy below 40
      effect: Social interactions give negative gains instead of positive
      duration: Until Energy above 50

    - name: "Fired Up 💥"
      alignment: positive
      trigger: Irritable vibe active + gym session
      effect: Fitness XP +5%, Energy restores faster — channeled it well
      duration: Session

    - name: "Actually Really Sorry 🥺"
      alignment: positive
      trigger: Irritable vibe expires naturally
      effect: Social +8 flat — the guilt makes them reach out
      duration: Instant

    - name: "Wrong Day Wrong Person 😠"
      alignment: negative
      trigger: Clingy-trait player nearby while Irritable active
      effect: Both players lose −8 Social — the friction is real
      duration: 30 min

    - name: "That Felt Good 😤→😌"
      alignment: positive
      trigger: Fitness session while Irritable, Energy goes above 60
      effect: Irritable vibe clears, Purpose +6 flat
      duration: Instant clear

# ---

trait: clingy
  alignment: negative
  description: Alone feels wrong. The need for connection is constant, sometimes overwhelming.
  mechanical_effects:
    - Social decays 25% faster when alone
    - Purpose drops −5 every hour without player interaction
  vibes:
    - name: "Lonely 💔"
      alignment: negative
      trigger: Social below 45
      effect: Purpose drains faster, Fun −10% — the absence is loud
      duration: Until Social above 55

    - name: "You're Here 🥺"
      alignment: positive
      trigger: Another player initiates conversation when Lonely vibe active
      effect: Social +15 flat, Purpose +8 — the relief is overwhelming
      duration: Instant

    - name: "Too Much Too Fast 😬"
      alignment: negative
      trigger: Social above 90 — they overfilled
      effect: Social gains temporarily reversed — pushing people away
      duration: 30 min

    - name: "Finally 🫂"
      alignment: positive
      trigger: Social goes from below 30 to above 70 in one session
      effect: Purpose +15 flat — the swing feels enormous
      duration: Instant

    - name: "Please Don't Go 🌧️"
      alignment: negative
      trigger: Player they were interacting with logs off
      effect: Social −8 flat, Lonely vibe more likely to fire next hour
      duration: 1 hr sensitivity window

# ---

trait: guarded
  alignment: neutral
  description: Trust is earned slowly. Walls are up by default. This protects them — mostly.
  mechanical_effects:
    - Social gains 15% slower (takes longer to warm up)
    - Immune to Lonely vibe permanently
  vibes:
    - name: "Walls Up 🧱"
      alignment: neutral
      trigger: New player nearby (first interaction ever)
      effect: Social gain from that player halved until 3+ interactions logged
      duration: Until familiarity built

    - name: "Actually Trust You 🤝"
      alignment: positive
      trigger: 5+ interactions logged with same player
      effect: Social gains from that player +20% — the wall came down
      duration: Permanent with that player

    - name: "Too Comfortable 😬"
      alignment: negative
      trigger: Social above 85 (rare for them)
      effect: Vulnerability hangover — Social decays faster next 2 hrs
      duration: 2 hrs

    - name: "You Surprised Me 🌷"
      alignment: positive
      trigger: Another player completes an odd job for them
      effect: Purpose +10, that player gets permanently easier Social gains
      duration: Permanent unlock for that relationship

    - name: "Don't Push It 😶"
      alignment: negative
      trigger: Clingy-trait player nearby repeatedly
      effect: Social gains from that player permanently reduced
      duration: Permanent for that pairing

# ---

trait: romantic
  alignment: neutral
  description: Feelings run deep. Connection is everything. This is beautiful and sometimes painful.
  mechanical_effects:
    - One-on-one Social gains +20%
    - Social decays 10% faster when alone
  vibes:
    - name: "Lovesick 💌"
      alignment: positive
      trigger: One-on-one Social above 80
      effect: Purpose +10, Fun decay paused 2 hrs — they're floating
      duration: 2 hrs

    - name: "Lonely 💔"
      alignment: negative
      trigger: Social below 35 for 3+ hrs
      effect: Purpose drains faster, Fun −15% — the absence is physical
      duration: Until Social above 50

    - name: "That Wasn't Nothing 🌹"
      alignment: positive
      trigger: First interaction with a new player
      effect: Purpose +5 flat — possibility is exciting
      duration: Instant

    - name: "Reading Into It 😰"
      alignment: negative
      trigger: Social drops after a period of being high
      effect: Fun −8 flat, slight Purpose dip — catastrophizing
      duration: 45 min

    - name: "This Is Enough 🕯️"
      alignment: positive
      trigger: Social above 75 + Purpose above 75 simultaneously
      effect: All decay −8%, everything just feels right
      duration: While both hold

# ============================================================
# ⚡ WORK & DRIVE TRAITS
# ============================================================

trait: ambitious
  alignment: positive
  description: Always chasing the next thing. Rest feels like falling behind.
  mechanical_effects:
    - Lumen earn rate +8% while clocked in
    - Promotion requires 1 fewer day at each tier
  vibes:
    - name: "Grind Mode 💼"
      alignment: positive
      trigger: Clocked in with Energy above 60
      effect: Skill XP +5% during shift, feels sharp
      duration: While clocked in and Energy above 60

    - name: "Burnout 🏳️"
      alignment: negative
      trigger: Worked max hours 3 days in a row
      effect: Energy decay 2×, Lumen earn −10% for 24 hrs — forced rest
      duration: 24 hrs

    - name: "The Promotion Is Mine 🏆"
      alignment: positive
      trigger: Promoted to next career tier
      effect: Purpose +20 flat — this one hit different
      duration: Instant

    - name: "Is This Even Worth It 😮‍💨"
      alignment: negative
      trigger: Burnout fires within same week as previous Burnout
      effect: Purpose −15 flat, Lumen earn −15% for 48 hrs
      duration: 48 hrs

    - name: "Just One More Thing 📋"
      alignment: positive
      trigger: Completes both an odd job and a full shift in one day
      effect: ✦10 bonus, Purpose +5 — they squeezed the day
      duration: Instant

# ---

trait: resilient
  alignment: positive
  description: They bend but don't break. Hard things make them harder.
  mechanical_effects:
    - Negative vibes expire 30% faster
    - Purpose never drops below 20 naturally
  vibes:
    - name: "Bouncing Back 💪"
      alignment: positive
      trigger: Any negative vibe expires
      effect: Purpose +5 flat — every recovery is a small win
      duration: Instant

    - name: "Numb 😶"
      alignment: negative
      trigger: 3+ negative vibes fired in same day
      effect: Positive vibes give 50% reduced effect — the armor also blocks the good
      duration: Until midnight reset

    - name: "Been Through Worse 🪨"
      alignment: positive
      trigger: Any need hits zero
      effect: Recovery rate for that need doubled — they know how to bounce back
      duration: Until need above 50

    - name: "Tired Of Being Strong 😔"
      alignment: negative
      trigger: Purpose below 30 despite Resilient trait protection
      effect: Social gains −20%, Fun −10% — even they have a limit
      duration: Until Purpose above 40

    - name: "Actually Fine 🌤️"
      alignment: positive
      trigger: Worked through a full shift while any need was critical
      effect: Purpose +15 flat, ✦5 bonus pay — showed up anyway
      duration: Instant

# ---

trait: lazy
  alignment: negative
  description: Everything takes more effort than it should. Rest is the default.
  mechanical_effects:
    - All skill XP −5%
    - Lumen earn rate −8% while clocked in
    - Energy decays 12% slower (conserves it well by doing nothing)
  vibes:
    - name: "Can't Be Bothered 😴"
      alignment: negative
      trigger: Any skill object used for less than 5 min then abandoned
      effect: That object gives no XP for rest of day
      duration: Until midnight

    - name: "Accidentally Productive 😯"
      alignment: positive
      trigger: Completes full 4-hr shift despite Lazy trait
      effect: Purpose +15 flat, ✦5 bonus — surprised everyone including themselves
      duration: Instant

    - name: "This Is Actually Fine 🛋️"
      alignment: positive
      trigger: Energy above 85 (well rested from doing nothing)
      effect: First skill session of day gives normal XP (penalty waived)
      duration: First session

    - name: "Not Getting Paid Enough For This 😒"
      alignment: negative
      trigger: Clocked in at location-required job
      effect: Lumen earn rate −5% additional — resentment
      duration: Shift

    - name: "Fine I'll Do It 😤"
      alignment: positive
      trigger: Reaches career tier 2 despite Lazy trait (takes longer, happens)
      effect: Promotion purpose bonus doubled — the effort was real
      duration: Instant

# ---

trait: impulsive
  alignment: negative
  description: Decisions are made quickly and reconsidered never.
  mechanical_effects:
    - 12% chance any purchase costs double
    - Odd job outcomes occasionally randomized
  vibes:
    - name: "On A Whim 🎲"
      alignment: neutral
      trigger: Randomly (12% chance on any action)
      effect: That action gives either 2× or 0× result — coin flip
      duration: Single action

    - name: "That Worked Out 😅"
      alignment: positive
      trigger: On A Whim rolls positive
      effect: Purpose +6 flat — the chaos paid off
      duration: Instant

    - name: "Why Did I Do That 🤦"
      alignment: negative
      trigger: On A Whim rolls negative on a purchase
      effect: ✦ lost, Fun −5 flat
      duration: Instant

    - name: "Spontaneous Joy ✨"
      alignment: positive
      trigger: Tries a new object with no planning
      effect: 2× Fun for that session — the novelty is real
      duration: Session

    - name: "Buyer's Remorse 😞"
      alignment: negative
      trigger: Purchased premium item (nice meal, subscription) when broke
      effect: Purpose −5, Fun −5 — that was a mistake
      duration: 1 hr

# ---

trait: homebody
  alignment: neutral
  description: Home is where they function. The world outside takes something from them.
  mechanical_effects:
    - All decay −12% in home/residential zone
    - Rest restores 15% more Energy at home
  vibes:
    - name: "Cozy 🏠"
      alignment: positive
      trigger: All needs above 55 while in home zone
      effect: Purpose gains +10%, feels genuinely peaceful
      duration: While in home zone with good needs

    - name: "Out Of Place 😶"
      alignment: negative
      trigger: In a public/commercial zone for 2+ hrs
      effect: Energy decays 10% faster, slight Fun drain
      duration: While in non-home zone after 2 hrs

    - name: "Actually Needed This 🌿"
      alignment: positive
      trigger: Attends an event after 3+ days of staying home
      effect: Social +10 flat, Fun +8 flat — the contrast helps
      duration: Instant on arrival

    - name: "Overwhelmed 😵"
      alignment: negative
      trigger: In crowded zone (3+ players) outside home
      effect: Energy −5 flat, slight anxiety — too much
      duration: 30 min

    - name: "My Space 🕯️"
      alignment: positive
      trigger: Skill used at home object (if home has skill objects)
      effect: That skill XP +5% — the comfort translates
      duration: Session

# ============================================================
# 🪞 SELF & WELLBEING TRAITS
# ============================================================

trait: confident
  alignment: positive
  description: They know who they are. That certainty is magnetic.
  mechanical_effects:
    - Immune to Insecure and Not Feeling It vibes permanently
    - Social gains never reduced by low Hygiene
    - Charisma XP +5%
  vibes:
    - name: "That Girl / That Guy 💅"
      alignment: positive
      trigger: All needs above 70
      effect: Purpose passive gain doubled, Charisma XP +5%
      duration: While all needs above 70

    - name: "Overconfident 😬"
      alignment: negative
      trigger: Social above 95 (rarely happens but can)
      effect: Social interactions start giving diminishing returns
      duration: While Social above 95

    - name: "You Got This 🌟"
      alignment: positive
      trigger: Career promotion achieved
      effect: Purpose +15 flat, all needs decay −8% for 4 hrs
      duration: 4 hrs

    - name: "Actually Vulnerable 🥺"
      alignment: negative
      trigger: Purpose drops below 35 (rare but hits differently)
      effect: Confident trait provides no protection — some hits land
      duration: Until Purpose above 45

    - name: "Unbothered 😌"
      alignment: positive
      trigger: Negative vibe from another player's trait affects them
      effect: Effect reduced by 50% — it just doesn't stick
      duration: Per incident

# ---

trait: self_aware
  alignment: positive
  description: They notice things — about themselves, about the room, about what's coming.
  mechanical_effects:
    - Need warnings trigger at 35% not 20%
    - Active vibes show exact time remaining on HUD
  vibes:
    - name: "Grounded 🪨"
      alignment: positive
      trigger: Consistently (no need below 35 for 48 hrs)
      effect: Purpose passive gain rate slightly increased
      duration: While streak holds

    - name: "Seeing It Coming 😬"
      alignment: negative
      trigger: Earlier warning triggers (35% threshold)
      effect: Anxiety about the approaching need kicks in — Fun −3 flat
      duration: Until need restored

    - name: "Actually Okay 😌"
      alignment: positive
      trigger: Need that triggered warning gets restored before critical
      effect: Purpose +5 flat — they caught it in time
      duration: Instant

    - name: "Too In Their Head 🌀"
      alignment: negative
      trigger: 3+ needs in warning zone simultaneously
      effect: Overwhelmed — Fun decay 2× while managing all of them
      duration: Until 2+ needs restored

    - name: "Reading The Room 🔍"
      alignment: positive
      trigger: Nearby player has a negative vibe they don't know about
      effect: Self-aware player is notified on HUD — can choose to help
      duration: Notification only

# ---

trait: insecure
  alignment: negative
  description: The inner critic is loud. Comparison is automatic. Some days are harder than others.
  mechanical_effects:
    - Purpose decays 15% faster when Hygiene below 50 or Social below 40
    - Comparing Myself vibe triggers when nearby player has positive vibe
  vibes:
    - name: "Not Feeling It 🪞"
      alignment: negative
      trigger: Hygiene below 45 OR Social below 40
      effect: Purpose decay faster, Social gains −15%
      duration: Until both needs recover

    - name: "Comparing Myself 👁️"
      alignment: negative
      trigger: Nearby player activates a positive vibe
      effect: Purpose −5 flat, Fun −3 flat
      duration: 30 min

    - name: "Actually Really Proud 🥺"
      alignment: positive
      trigger: Skill levels up
      effect: Purpose +15 flat — the self-doubt makes wins hit harder
      duration: Instant

    - name: "Seen 🌷"
      alignment: positive
      trigger: Another player completes a social action directed at them
      effect: Purpose +12 flat, Not Feeling It vibe clears immediately
      duration: Instant clear

    - name: "Bad Day 🌧️"
      alignment: negative
      trigger: 2+ negative vibes active simultaneously
      effect: Purpose floor drops to 15 for this session
      duration: Until negative vibes clear

# ---

trait: grieving
  alignment: negative
  description: Something was lost. It shapes everything quietly. Connection is the only thing that helps.
  mechanical_effects:
    - Purpose decays 12% faster
    - Fun gains −8%
  vibes:
    - name: "Heavy Heart 🖤"
      alignment: negative
      trigger: Alone for 1+ hr
      effect: Purpose drains faster, Fun −10%
      duration: Until Social interaction

    - name: "You Helped 🌷"
      alignment: positive
      trigger: Social interaction when Heavy Heart active
      effect: Purpose +15 flat, Heavy Heart clears — connection is the medicine
      duration: Instant clear

    - name: "Something Beautiful 🕯️"
      alignment: positive
      trigger: Attended event or party
      effect: Purpose +12 flat, Fun gains normal (penalty waived) for session
      duration: Event session

    - name: "Not Today 😶"
      alignment: negative
      trigger: Fun below 25
      effect: All skill XP halved — can't focus
      duration: Until Fun above 35

    - name: "Actually Laughed 🌤️"
      alignment: positive
      trigger: Fun above 75 (rare but beautiful)
      effect: Purpose +20 flat — the surprise of joy after loss
      duration: Instant

# ---

trait: growing
  alignment: neutral
  description: A work in progress. Deliberately. The journey is the point.
  mechanical_effects:
    - All skill XP +5%
    - Purpose doubled from every skill level-up
  vibes:
    - name: "Working On It 🌱"
      alignment: positive
      trigger: Used 2+ different skill objects in one day
      effect: Purpose +5 flat — the variety feels intentional
      duration: Instant

    - name: "Off Track 😔"
      alignment: negative
      trigger: No skill XP earned for 48 hrs
      effect: Purpose decays slightly faster — they feel the stagnation
      duration: Until skill XP earned

    - name: "Getting Better 📈"
      alignment: positive
      trigger: Same skill used 3 days in a row
      effect: Consistency bonus — that skill XP +5% today
      duration: Today

    - name: "Compared To Who I Was 🪞"
      alignment: positive
      trigger: Skill reaches a new max level milestone (5, 8, 10)
      effect: Purpose +20 flat — genuine reflection moment
      duration: Instant

    - name: "Setback 😮‍💨"
      alignment: negative
      trigger: Skill XP lost or reset (if that mechanic exists)
      effect: Purpose −10 flat, Fun decay 15% faster for 24 hrs
      duration: 24 hrs

# ============================================================
# 🌙 BIOLOGY (auto-applied, not chosen)
# ============================================================

trait: cycle
  alignment: neutral
  description: Auto-applied based on biology profile answer. 28-day server-side timer with ±3 day variance.
  mechanical_effects:
    - Active window: 3-5 days per cycle
    - Fun decays 15% faster during window
    - Social gains −10% during window
  vibes:
    - name: "PMS 🌙"
      alignment: negative
      trigger: Cycle window begins
      effect: Fun decay +15%, random Irritable vibe possible, Hungry more often
      duration: 3-5 days

    - name: "Irritable 😤"
      alignment: negative
      trigger: Randomly within PMS window (50% chance per day)
      effect: Social interactions give −5 instead of gains for 30 min
      duration: 30 min

    - name: "Craving Something 🍫"
      alignment: neutral
      trigger: Hunger drops during PMS window
      effect: Nice meal gives 2× Hunger restore — specific craving satisfied
      duration: Single meal

    - name: "Glowing ✨"
      alignment: positive
      trigger: 3 days after cycle window closes
      effect: Purpose +10, Social gains +15%, skin literally glowing — the after
      duration: 48 hrs

    - name: "Actually Invincible 💪"
      alignment: positive
      trigger: First day after PMS window
      effect: All decay −10%, Energy feels high — contrast effect
      duration: 24 hrs
