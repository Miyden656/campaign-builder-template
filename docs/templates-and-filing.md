# Master Templates & Filing Workflow

The whole point: **one canonical structure per thing**, so a place, person, faction, or arc looks the same no matter which tool you're in. Build these once and everything downstream — Lore, Tome, Foundry, Scry later — is just pouring the same shape into a different container. The fields below are built from how you already think (what / why / how; current state; last established), not a generic template.

The campaign builder's **canon ledger** (`bibles/<slug>-canon.md`) distills your answers into these shapes automatically, so the ledger drops cleanly into Lore later.

Copy any block, fill the blanks, done.

---

## The master templates

### LOCATION
```
Name:
Type:                         (city / village / landmark / region / building)
What it is:                   (one line — the essence)
Why it matters:               (its role in the story / why it exists)
How it connects:              (links to other places, factions, events)
Current state:                (what's true right now — update as it changes)
Who's here:                   (NPCs / factions present — link them)
Sensory hooks:                (3 quick details for vivid narration: sight, sound, smell)
Last established:             (what players last saw/learned + session tag, e.g. S07)
GM-only / secrets:
```

### NPC
```
Name:
Role:                         (one line)
What:                         (who they are at a glance)
Why:                          (why they exist / what they add to the story)
How:                          (how they operate — methods, what they're doing now)
Voice:                        (speech pattern + one sample line)
Drive:                        (what they want)
Ties:                         (relationships — link PCs, NPCs, factions)
Current state:                (where they are now / latest status)
Spotlight:                    (which PC could shine off them)
Stat block:                   (link to Foundry actor if combat-relevant)
GM-only / secrets:
```

### FACTION
```
Name:
Type:                         (order / guild / cult / nation / crew)
What:                         (what they are)
Why:                          (their goal — tie to the campaign's real-world spine)
How:                          (methods, resources, reach)
Key members:                  (link NPCs)
Allies / enemies:             (link)
Current state:                (their latest move)
Clock:                        (their escalating plan, step by step — this is your villain-plan workspace)
GM-only / secrets:
```

### ITEM / POWER  (magic with limits and cost)
```
Name:
What it does:
Limit / cost:                 (the price of using it — the heart of it)
Source / who can use it:      (bonded? tied to a person or place?)
Rarity / prevalence:
Narrative weight:             (why it matters to the story)
Complications:                (problems it creates, not just solves)
```

### ARC  (story layer)
```
Title:
Real-world spine:             (the issue at its core — your signature anchor)
Central conflict / villain goal:
Love thread:                  (the relationship woven in, even if not player-facing)
Stakes:                       (what's at risk)
Key beats:                    (open -> midpoint -> climax -> resolution = the destination)
Branch points:                (where player choices fork; note how each reroutes)
PC spotlights:                (one cool moment for each player this arc)
Locations & factions:         (link)
Clues seeded:                 (for mysteries — plant at least three per truth, fail-forward)
```

### SESSION  (Toolboard — your anti-scramble page)
```
Session # / date:
Goal:                         (one line — what should happen)
Opening hook:                 (how it starts)
At hand:                      (3-5 things you need ready: NPCs, places, stat links)
Possible scenes:              (2-3, flexible — not a script)
Player goals / branches ready:
Loose threads to maybe touch:
After — what changed:         (feeds your canon updates)
```

---

## Where each template lives (the same shape, four containers)

- **Lore (world truth):** LOCATION, NPC, FACTION, ITEM/POWER, and history entries. The template body *is* the Lore page. Turn every "connects / who's here / ties / key members" field into a real Lore link — that web is your continuity net.
- **Tome (story):** ARC and SESSION. Tome scenes tag the Lore pages they use, so a scene carries its canon. Put your ARC "branch points" into Tome's decision tracking.
- **Foundry (table):** the playable versions. A LOCATION becomes a Scene (map) plus a short Journal note; an NPC becomes an Actor (statblock, per the Foundry pack) plus a Journal note for voice/drive/ties; ITEM becomes an Item; ARC/SESSION live as Journal entries.
- **Scry (later, ~2027):** player-facing shares of selected Lore/Tome pages, with the GM-only fields withheld.

## The filing workflow (builder answer -> the right home)

1. The daily builder asks; you answer.
2. Sort the answer:
   - **A world fact** (a place, person, faction, item) -> a **Lore** page using the matching template.
   - **A story decision / beat / branch** -> **Tome** (arc or scene), logged in decision tracking.
   - **Something you'll need live at the table** -> **Foundry** (Actor for a combat NPC, Scene for a map, Journal for reference).
3. The builder's **canon ledger** is the bridge — it's already distilled into facts, so it drops cleanly into Lore pages.
4. After a session, your Loreify transcript -> update the "Current state / Last established" fields on the Lore pages you touched. That single habit is what keeps continuity from slipping.

## One naming convention everywhere
Same prefixes in Lore, Tome, and Foundry so the same name finds the same thing:
`LOC - Ravenhook` · `NPC - Mayor Castis` · `FAC - The Ashen Hand` · `ITEM - The Quiet Blade` · `ARC - The Drowned Deal` · sessions `S01`, `S02`...
One world = one Lore workspace; one campaign = one Tome project; one Foundry World per campaign.
