# Campaign Builder

A daily, reply-driven planner that helps you build tabletop RPG campaigns as the
GM **a little each day** instead of one overwhelming marathon. Each day, for your
active campaign, you get **one email asking the next campaign-building
question(s)**. You **reply to lock in your answer.** The system files it, distills
the durable facts into a queryable world-canon, and asks the next sharper
question — moving through themed **sprints** so it always feels like it's going
somewhere.

It runs on **GitHub Actions** (free cloud automation) and the **free Gemini API
tier** — no server, nothing on your computer, **standard library only** (no
dependencies to rot). Built-in support for **D&D 5e**, the **Cosmere RPG**, and
**Avatar Legends**; any other system works via a flavor file.

---

## What makes it more than "a question a day"

- **Brainstorm from a blank page.** Start a campaign with *no* premise and it
  opens in a **brainstorm sprint** that pulls the core out of *you* — a
  real-world spine, a vibe, a rough premise, and a working title — through open,
  generative questions. It never hands you the idea (a few optional "sparks" sit
  at the very bottom only if you're stuck). Already have an idea? Give it a seed
  and it skips straight to building.
- **Themed sprints.** After the spark, it works one element at a time — premise &
  spine, the opening region, magic & limits, factions, the villain, key NPCs, the
  central conflict, player hooks, session one, then ongoing/deepen. Each email
  shows progress ("The villain · day 2 of up to 6 — Done: … | Now: … | Next: …"),
  and when a sprint is done you get a short recap built from *your own answers*
  and an explicit hand-off to the next one.
- **A world-canon ledger** (`bibles/<slug>-canon.md`). After each answer it
  distills the durable facts (places, NPCs, factions, magic rules, timeline) into
  a clean, phone-editable file, and **reads it before every question so it never
  contradicts what you've established.** This is the continuity "second brain" —
  and it drops straight into your Lore tool later.
- **`CANON: <thing>`** — reply that instead of an answer and you get back what the
  canon already knows about it (no advancing). Great for "wait, what did I say
  about this place three arcs ago?"
- **One-shot back-pocket mode.** Tag a line `[one-shot]` and it runs a compressed
  arc to a runnable session in a handful of days, then files a **ready-to-run
  summary** in `back-pocket/` so you build a reserve for short weeks.
- **It never writes your story.** It won't invent the villain's heart or the
  twist — it scaffolds structure and asks. It leans into your growth areas
  (villains, mystery/clue craft, branching choices, vivid narration) and teaches
  a technique with a google-able term when useful.
- **Clean, copy-paste-friendly email.** One-line context header, each question on
  its own line with space to type under it, examples tucked at the very bottom
  under a separator so they're a last resort.

---

## One-time setup (~15 min)

### 1. Get your own copy of the repo

You're starting from a **template**, so this is one click:

1. On the template repo's GitHub page, click the green **Use this template** →
   **Create a new repository**.
2. Name it (e.g. `campaign-builder`), set **Private**, and **Create repository**.

That's it — you now have your own copy with all the code. Everything below happens
in *your* repo. (You never touch the original template, and the owner never sees
your campaigns or secrets.)

### 2. Get a free Gemini API key

**https://aistudio.google.com/apikey** → sign in → **Create API key**. No credit
card. Copy it.

> Free-tier Gemini may use inputs to improve Google's models — fine for
> worldbuilding; just don't paste anything private.

### 3. Add the secrets

First, a 16-char Gmail **App Password** (the script signs in with this, not your
normal password):
1. Turn on 2-Step Verification: https://myaccount.google.com/security
2. Create an App Password: https://myaccount.google.com/apppasswords — name it
   `campaign-builder`, copy the 16 characters, **remove the spaces**.

Then in your repo: **Settings → Secrets and variables → Actions → New repository
secret** — add these five:

| Secret | What to put |
|---|---|
| `SENDER_EMAIL` | The Gmail that sends + is read for replies. |
| `SENDER_APP_PASSWORD` | The 16-char App Password from above (no spaces). |
| `CAMPAIGN_RECIPIENT` | Where questions go / who you reply as. **The simplest setup: make this the same as `SENDER_EMAIL`** (one inbox does both). |
| `GEMINI_API_KEY` | The key from step 2. |
| `SENDER_NAME` | The name the email is signed with (e.g. your first name). One line, no line break. |

### 4. IMAP (and optional tidiness)

Gmail leaves IMAP **on by default** now — nothing to flip. With the simple
single-account setup (`CAMPAIGN_RECIPIENT` = `SENDER_EMAIL`) and the default
`IMAP_FOLDER: INBOX`, **you don't need any filter** — questions and your replies
sit in your inbox and the script reads them there. Done.

**Optional tidiness:** every email the builder sends carries a hidden marker
(`#campaignbuilder` in the footer), and your replies quote it — so one filter can
organize everything:
- **Settings → Filters → Create a new filter** → *Has the words:* `#campaignbuilder`
  → **Apply label** (e.g. `Campaigns`). Add **Skip the Inbox** if you want it out
  of the way — but if you do, set `IMAP_FOLDER` in the workflow to that label so
  the script still finds it.
- Sort by *Subject:* the word `one-shot` (all one-shot mail) or a campaign's name.

> Using two separate accounts (a "bot" sender + your personal inbox)? Then put the
> `Campaigns`-label filter on the **sender** account (the one the script reads),
> set `IMAP_FOLDER` to that label, and reply from your personal account as normal.

### 5. Make it yours

- **`campaigns.txt`** — your campaigns, one per line: `system | working title |
  optional seed`. **Leave the seed off to brainstorm from scratch** (the default);
  add a one-line seed only when you already have an idea. The working title is
  just a stable handle for files/subject — your real campaign name gets
  brainstormed into the bible. One full campaign active at a time; use
  `[one-shot]` lines to stock the back-pocket.
- **`gm_profile.md`** — **fill this in first.** It's a blank template of your GM
  taste, growth goals, and boundaries, fed into *every* question — 15 minutes here
  is what makes the questions feel tailored to you instead of generic.
- **`flavor/<slug>.md`** — optional deep grounding for a specific campaign.

### 6. Test

**Actions** tab → **Daily campaign builder** → **Run workflow**. You should get a
first question. **Reply** to it, run the workflow again, and confirm the next
question builds on your answer and that `bibles/<slug>.md` + `bibles/<slug>-canon.md`
filled in.

### 7. Set up reliable delivery (cron-job.org) — important

This is the one non-obvious part. GitHub *has* a built-in scheduler, but it's
**unreliable** — scheduled runs are frequently hours late or skipped entirely,
especially on new repos. So instead of trusting it, a free external scheduler
**fires the workflow for you** by calling GitHub's API. Takes ~10 minutes, costs
nothing, and it's rock-solid.

The workflow **polls**: each run checks the mailbox, files any reply, and sends
the next question (under the daily cap). Your cron-job.org schedule sets the
*pace*:
- **Once a day** at your favorite hour → the classic one-question-a-day rhythm.
- **Every 30 minutes** (recommended; restrict to ~6:00–23:30) → on a free
  evening you can answer, get the next question back within ~30 minutes, and
  keep going — several rounds in one sitting. The daily cap (below) protects the
  slow burn. This uses ~1,100 of GitHub's 2,000 free monthly Actions minutes
  (each run bills as a rounded-up minute), so keep night hours off if you run
  other private-repo automations.

**A) Make a minimal GitHub token (~3 min):**
1. Go to **https://github.com/settings/personal-access-tokens/new** (fine-grained).
2. **Name:** `campaign-builder-trigger`. **Expiration:** 1 year (or "No expiration").
3. **Resource owner:** you. **Repository access:** *Only select repositories* →
   your `campaign-builder` repo.
4. **Permissions → Repository → Actions:** set to **Read and write**. Leave
   everything else at **No access**. Generate, and **copy the token**.

**B) Create the cron-job.org job (~7 min):**
1. Sign up free at **https://cron-job.org**, verify email, log in. Set your
   account **timezone** (so it handles Daylight Saving for you).
2. **Create cronjob:**
   - **URL:** `https://api.github.com/repos/<you>/campaign-builder/actions/workflows/campaign.yml/dispatches`
     (replace `<you>` with your GitHub username)
   - **Schedule:** every 30 minutes with hours ~6–23 enabled (or once a day at
     the hour you want your question — see the pacing note above).
3. In the job's **Advanced / Headers & body**:
   - **Request method:** `POST`
   - **Headers:**
     - `Authorization` → `Bearer YOUR_TOKEN` *(the word Bearer, one space, the token — no `+`)*
     - `Accept` → `application/vnd.github+json`
     - `Content-Type` → `application/json`
     - `User-Agent` → `campaign-builder`
   - **Request body:** `{"ref":"main"}`
4. **Save**, then use the **Test run** button. A **`204 No Content`** response =
   success (GitHub returns 204 on a good trigger). Check your **Actions** tab for a
   fresh `workflow_dispatch` run appearing — that's it working.

> Tip: turn on cron-job.org's failure notifications so you're emailed if the
> trigger ever breaks (e.g. the token expires in a year).

---

## Day to day

- **Answer** by replying under each question. With 30-minute polling you can
  answer again when the next one arrives and keep going — or stop anytime; it
  waits and never nags.
- **The slow-burn cap:** at most `MAX_ROUNDS_PER_DAY` (default 12) questions per
  day across all campaigns, resetting at local midnight — a one-line env edit in
  `campaign.yml`. Busy days need no special handling: the system only sends
  after you reply, so a day you don't answer is a day with no mail. (An optional
  `LIGHT_DAYS` knob can hard-pin chosen weekdays to 1 question; it ships off.)
- **Start a new campaign from any email:** reply
  `NEW CAMPAIGN: <system> | <name> | <optional seed>` (system required; include
  `[one-shot]` in the seed for a one-shot). It spins up a fresh, fully isolated
  brainstorm without touching the campaign you replied from.
- **Look something up:** reply `CANON: <a place, person, or faction>` and it tells
  you what your world bible already knows about it.
- **Get the next question now:** Actions → Run workflow.
- **Pause / start / one-shot:** edit `campaigns.txt` (`#` pauses; `[one-shot]`
  tags a one-shot).
- **Read your world:** `bibles/<slug>.md` (full Q&A) and `bibles/<slug>-canon.md`
  (distilled facts). Finished one-shots: `back-pocket/<slug>.md`.

**How replies route (campaigns never mix):** every outbound email carries a
hidden routing token in its footer (e.g. `[cb:storm-coast#14]`). Your reply
quotes it, so answers land in the right campaign even if you edit the subject or
write a fresh email — include `[cb:<slug>]` anywhere to force a campaign. If a
message can't be routed confidently, the system emails back asking which
campaign you meant instead of guessing.

Slug = the name lowercased with non-letters turned to hyphens ("Storm Coast" →
`storm-coast`).

---

## Swapping the AI provider

Single swap point in `.github/workflows/campaign.yml`:

```yaml
AI_PROVIDER: gemini            # gemini | anthropic | openai
AI_MODEL: gemini-2.5-flash
```

Change those two and add that provider's key secret (`ANTHROPIC_API_KEY` or
`OPENAI_API_KEY`) to upgrade quality later — no code changes.

---

## Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `CAMPAIGN_RECIPIENT` | — (secret) | Where questions go / whose replies to read |
| `GEMINI_API_KEY` | — (secret) | Free Gemini key |
| `AI_PROVIDER` / `AI_MODEL` | `gemini` / `gemini-2.5-flash` | The AI swap point |
| `IMAP_FOLDER` | `INBOX` | Mailbox/label the script reads (default works for a single-account setup; use a label if you archive) |
| `RESEND_AFTER_DAYS` | `0` | Resend a question once after N silent days (0 = off) |
| `MAX_ROUNDS_PER_DAY` | `12` | Global cap on question rounds per day (all campaigns); resets at local midnight |
| `LIGHT_DAYS` | *(empty — off)* | Optional: weekdays where the cap is pinned to 1 (comma list, e.g. `wed,sun`) |
| `TIMEZONE` | `America/Chicago` | For dating entries |

Email/SMTP vars (`SENDER_EMAIL`, `SENDER_APP_PASSWORD`, `SMTP_*`, `USE_SSL`,
`SENDER_NAME`) are the same ones the writing emailer uses.

---

## Files

| Path | What it is |
|---|---|
| `campaign_builder.py` | The engine (stdlib only). |
| `campaigns.txt` | Your campaigns. Edit this. |
| `campaign_state.json` | Per-campaign status + sprint tracking (auto). |
| `gm_profile.md` | Your global GM taste + boundaries. |
| `systems/*.md` | Built-in system flavor (D&D 5e, Cosmere, Avatar Legends). |
| `flavor/<slug>.md` | Optional per-campaign grounding you write. |
| `bibles/<slug>.md` | The running Q&A transcript. |
| `bibles/<slug>-canon.md` | The distilled, queryable world canon. |
| `back-pocket/<slug>.md` | Finished, ready-to-run one-shots. |
| `docs/templates-and-filing.md` | The master templates the canon distills toward. |
| `.github/workflows/campaign.yml` | The job that runs the builder + saves state back. Fired daily by cron-job.org (see step 7). |

---

## Troubleshooting

- **Red X, "missing required env vars":** a secret isn't set (usually
  `GEMINI_API_KEY` or `CAMPAIGN_RECIPIENT`).
- **No email, run green:** check spam, mark "not spam"; confirm `CAMPAIGN_RECIPIENT`.
- **Reply not picked up:** make sure you *replied* (kept the `[Name]` subject) and
  ran the workflow again. Matching uses threading + the subject tag.
- **"reply ingest failed" in the log:** it still sends questions; it just skipped
  reading mail this run (transient IMAP hiccup or wrong `IMAP_FOLDER`). Catches up
  next run.
- **No question arrives at the scheduled time:** check your cron-job.org job ran
  (its execution history) and that its last response was `204`. If a token expired,
  regenerate it (step 7A) and update the `Authorization` header. Daylight Saving is
  handled automatically by cron-job.org's timezone — nothing to flip.
- **Two questions in one evening (rare):** only happens if you reply within a few
  minutes of getting a question and the trigger fires again right after. Harmless.
