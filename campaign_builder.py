#!/usr/bin/env python3
"""
Campaign Builder — a daily, reply-driven TTRPG campaign planner for one GM.

Once a day (plus a manual trigger) it:

  1. Reads email replies over IMAP, pulls out just the answer, files it into the
     campaign's running bible (bibles/<slug>.md), and distills durable world
     facts into a queryable canon ledger (bibles/<slug>-canon.md).
  2. Figures out where the current themed SPRINT stands, and either continues it
     or wraps it with a short recap + an explicit transition to the next sprint.
  3. Asks the AI (Google Gemini free tier by default) for the next focused
     question(s) — grounded in the GM profile, the system flavor, and the canon
     so it never contradicts what's already established — and emails them in a
     clean, copy-paste-friendly format with examples tucked at the bottom.

It never drafts the creative core (the villain, the twist) — it scaffolds the
non-critical pieces and asks. A campaign only advances when the GM answers.

Standalone repo. Standard library only (no pip installs). All configuration
comes from environment variables; no credentials are ever printed.
"""

import email
import imaplib
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from email.header import decode_header, make_header
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid, parseaddr

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:  # pragma: no cover
    ZoneInfo = None

# --- Paths -----------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
CAMPAIGNS_PATH = os.path.join(HERE, "campaigns.txt")
STATE_PATH = os.path.join(HERE, "campaign_state.json")
BIBLES_DIR = os.path.join(HERE, "bibles")
FLAVOR_DIR = os.path.join(HERE, "flavor")        # per-campaign grounding
SYSTEMS_DIR = os.path.join(HERE, "systems")      # built-in system flavor
BACKPOCKET_DIR = os.path.join(HERE, "back-pocket")
GM_PROFILE_PATH = os.path.join(HERE, "gm_profile.md")

# --- Config (env) ----------------------------------------------------------


def _env(name, default=""):
    return os.environ.get(name, default)


def _env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _oneline(s):
    """Collapse newlines/tabs to a space and trim — secrets pasted with a stray
    line break must never sneak a newline into an email header (which is fatal)."""
    return re.sub(r"[\r\n\t]+", " ", s or "").strip()


# Email-header-bound values: never let a newline survive. The app password is
# stripped of ALL whitespace (Google shows it as "abcd efgh ..." — spaces out).
SENDER_EMAIL = _oneline(_env("SENDER_EMAIL"))
SENDER_APP_PASSWORD = re.sub(r"\s+", "", _env("SENDER_APP_PASSWORD"))
CAMPAIGN_RECIPIENT = _oneline(_env("CAMPAIGN_RECIPIENT")) or SENDER_EMAIL
SENDER_NAME = _oneline(_env("SENDER_NAME", "Campaign Builder")) or "Campaign Builder"

SMTP_SERVER = _env("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = _env_int("SMTP_PORT", 465)
SMTP_USE_SSL = _env_bool("USE_SSL", True)

IMAP_SERVER = _env("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT = _env_int("IMAP_PORT", 993)
IMAP_FOLDER = _env("IMAP_FOLDER", "INBOX")

TIMEZONE = _env("TIMEZONE", "America/Chicago")
RESEND_AFTER_DAYS = _env_int("RESEND_AFTER_DAYS", 0)

# Slow-burn guard: a GLOBAL cap on question rounds per day (across all
# campaigns), resetting at local midnight in TIMEZONE. On "light days" the cap
# is pinned to 1 standard question regardless. Both are one-line env edits.
MAX_ROUNDS_PER_DAY = _env_int("MAX_ROUNDS_PER_DAY", 12)
LIGHT_DAYS = {d.strip().lower()[:3] for d in
              _env("LIGHT_DAYS", "wed,sun").split(",") if d.strip()}

AI_PROVIDER = _env("AI_PROVIDER", "gemini").strip().lower()
AI_MODEL = _env("AI_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = _env("GEMINI_API_KEY")
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
OPENAI_API_KEY = _env("OPENAI_API_KEY")

# Leading [Name] tag in a subject (handles "Re: " prefixes).
SUBJECT_TAG_RE = re.compile(r"^\s*(?:re:\s*)*\[(?P<name>[^\]]+)\]", re.I)

# A stable marker stamped on every outgoing email's footer. Lets one Gmail
# filter catch ALL campaign mail (and replies, which quote it) regardless of
# campaign — the basis of the "Campaigns" archive label the builder reads.
STABLE_TAG = "#campaignbuilder"

# Machine-readable routing token stamped next to STABLE_TAG, e.g.
# [cb:ember-isles#14]. A reply quotes it, so the system can route the answer to
# the right campaign even if the subject was edited or threading headers are
# missing. Parsed from the RAW body (quotes included) — token beats threading.
TOKEN_RE = re.compile(r"\[cb:(?P<slug>[a-z0-9-]+)(?:#(?P<turn>\d+))?\]", re.I)

# Reply command that spins up a brand-new campaign from inside any email:
#   NEW CAMPAIGN: <system> | <name> | <optional seed>
# The system part is REQUIRED (no guessing); a malformed command gets a help
# email back instead of silently doing the wrong thing.
NEWCMD_RE = re.compile(r"^\s*new\s+campaign\s*:\s*(?P<rest>.+)$", re.I | re.S)


# --- Sprints ---------------------------------------------------------------
# Themed multi-day sprints so the GM feels forward motion. `cap` is the soft
# max days before a sprint is force-completed so nothing drags. The AI can also
# judge a sprint done sooner. `terminal` sprints produce an artifact and finish.

CAMPAIGN_SPRINTS = [
    {"key": "spark", "label": "Brainstorm the spark", "cap": 5,
     "focus": "discovering the campaign's core FROM the GM, not for him — start "
              "from what's actually on his mind (a real-world tension or theme he "
              "keeps circling, an image, a feeling he wants at the table) and pull "
              "out a rough premise, a grounded spine, and a working title through "
              "open, generative questions. Help him converge toward ONE direction "
              "he's excited about; never hand him the premise or the twist"},
    {"key": "premise", "label": "Premise & spine", "cap": 4,
     "focus": "the core premise and a grounded real-world thematic spine; tone, "
              "scope and rough length if not yet clear"},
    {"key": "region", "label": "The opening region", "cap": 4,
     "focus": "where play begins — the local region/locale the party starts in, "
              "its feel and a few vivid sensory hooks"},
    {"key": "powers", "label": "Magic, powers & limits", "cap": 4,
     "focus": "the forces in play and, crucially, their hard limits and costs; "
              "how common magic is in this world"},
    {"key": "factions", "label": "Factions & forces", "cap": 5,
     "focus": "the powers in conflict, what each wants, and how they pressure "
              "the world"},
    {"key": "villain", "label": "The villain", "cap": 6,
     "focus": "the central antagonist and their concrete, escalating plan (a "
              "growth area — scaffold structure, never invent the heart of it)"},
    {"key": "npcs", "label": "Key NPCs", "cap": 5,
     "focus": "allies, the central figure, and key NPCs — each with a reason to "
              "exist (what/why/how), drives, and what they hide"},
    {"key": "conflict", "label": "Central conflict & stakes", "cap": 4,
     "focus": "the spine of the campaign, the stakes, and the clock"},
    {"key": "hooks", "label": "Player hooks & branches", "cap": 4,
     "focus": "hooks tying each PC to the stakes, session-zero seeds, and real "
              "branch points that still cohere (a growth area)"},
    {"key": "session_one", "label": "Session one", "cap": 3,
     "focus": "the opening scene/encounter and how it grabs the table fast"},
    {"key": "ongoing", "label": "Ongoing & deepen", "cap": 999,
     "focus": "flesh out thin areas indefinitely — more NPCs, locations, "
              "encounters, mysteries, side threads, and consequences"},
]

ONESHOT_SPRINTS = [
    {"key": "concept", "label": "Concept & tone", "cap": 2,
     "focus": "the one-shot's concept and a clearly locked tone"},
    {"key": "ensemble", "label": "The ensemble / pregens", "cap": 2,
     "focus": "the pregen ensemble — powers and weaknesses as plot engines, with "
              "real heart"},
    {"key": "cold_open", "label": "The hook & cold open", "cap": 2,
     "focus": "a strong cold open that drops the table straight into it"},
    {"key": "conflict", "label": "The central chaos", "cap": 2,
     "focus": "the central conflict/chaos driving the session"},
    {"key": "setpieces", "label": "Set-pieces", "cap": 3,
     "focus": "two or three memorable set-pieces"},
    {"key": "twist", "label": "The twist / payoff", "cap": 2,
     "focus": "the twist and the payoff (scaffold structure, don't invent its "
              "heart)"},
    {"key": "ready", "label": "Ready to run", "cap": 1, "terminal": True,
     "focus": "compile everything into a ready-to-run summary"},
]


def sprint_list(ctype):
    return ONESHOT_SPRINTS if ctype == "one-shot" else CAMPAIGN_SPRINTS


def find_sprint(ctype, key):
    for s in sprint_list(ctype):
        if s["key"] == key:
            return s
    return sprint_list(ctype)[0]


def next_sprint(ctype, key):
    lst = sprint_list(ctype)
    for i, s in enumerate(lst):
        if s["key"] == key:
            return lst[i + 1] if i + 1 < len(lst) else None
    return None


def progress_marker(campaign, cstate):
    ctype = cstate.get("type", "campaign")
    done = [find_sprint(ctype, k)["label"] for k in cstate.get("completed_sprints", [])]
    now = find_sprint(ctype, cstate.get("current_sprint")).get("label", "")
    nxt = next_sprint(ctype, cstate.get("current_sprint"))
    nxt_label = nxt["label"] if nxt else ("(complete)" if ctype == "one-shot" else "(keep deepening)")
    done_str = ", ".join(done) if done else "—"
    return f"Done: {done_str} | Now: {now} | Next: {nxt_label}"


# --- Small helpers ---------------------------------------------------------


def today_in_tz():
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
        except Exception:
            pass
    return date.today().isoformat()


def days_since(date_str, today_str):
    if not date_str:
        return 10 ** 6
    try:
        return (date.fromisoformat(today_str) - date.fromisoformat(date_str)).days
    except ValueError:
        return 10 ** 6


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return s or "campaign"


# --- Daily round cap (the slow-burn guard) ----------------------------------


def weekday_key(today_str):
    """3-letter weekday key ('mon'..'sun') for an ISO date string."""
    try:
        return date.fromisoformat(today_str).strftime("%a").lower()[:3]
    except ValueError:
        return ""


def cap_for(today_str):
    """Today's global question-round cap: 1 on light days, else the env cap."""
    if weekday_key(today_str) in LIGHT_DAYS:
        return 1
    return max(MAX_ROUNDS_PER_DAY, 0)


def rounds_left(state, today_str):
    """Remaining question rounds today (global, all campaigns). Resets the
    counter at the first call past local midnight."""
    if state.get("rounds_date") != today_str:
        state["rounds_date"] = today_str
        state["rounds_today"] = 0
    return cap_for(today_str) - state.get("rounds_today", 0)


def count_round(state, today_str):
    if state.get("rounds_date") != today_str:
        state["rounds_date"] = today_str
        state["rounds_today"] = 0
    state["rounds_today"] = state.get("rounds_today", 0) + 1


def bible_path(slug):
    return os.path.join(BIBLES_DIR, slug + ".md")


def canon_path(slug):
    return os.path.join(BIBLES_DIR, slug + "-canon.md")


def flavor_path(slug):
    return os.path.join(FLAVOR_DIR, slug + ".md")


def backpocket_path(slug):
    return os.path.join(BACKPOCKET_DIR, slug + ".md")


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (FileNotFoundError, OSError):
        return ""


def append_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


# --- System flavor ---------------------------------------------------------

SYSTEM_ALIASES = [
    (re.compile(r"\b(d\s*&\s*d|dnd|d20|dungeons|5e|5th)\b", re.I), "dnd-5e"),
    (re.compile(r"cosmere|stormlight|mistborn|roshar|scadrial", re.I), "cosmere-rpg"),
    (re.compile(r"avatar|legends|bending|korra|aang", re.I), "avatar-legends"),
]


def system_flavor(system_name):
    """Return built-in flavor text for a system, or '' if none matches."""
    for pattern, key in SYSTEM_ALIASES:
        if pattern.search(system_name or ""):
            return read_text(os.path.join(SYSTEMS_DIR, key + ".md"))
    return ""


# --- campaigns.txt ---------------------------------------------------------

ONESHOT_TOKEN_RE = re.compile(r"\[\s*one[\s\-]?shot\s*\]", re.I)


def parse_campaigns(path):
    """Parse campaigns.txt into [{system, name, slug, seed, type}].

    Format: `system | name | optional seed`. A `[one-shot]` token anywhere on
    the line (or a 4th `one-shot` field) marks it a one-shot. `#` comments /
    pauses a line."""
    campaigns = []
    seen = set()
    for raw in read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        ctype = "one-shot" if ONESHOT_TOKEN_RE.search(line) else "campaign"
        line = ONESHOT_TOKEN_RE.sub("", line).strip()
        parts = [p.strip() for p in line.split("|")]
        system = parts[0] if len(parts) > 0 else ""
        name = parts[1] if len(parts) > 1 else ""
        seed = parts[2] if len(parts) > 2 else ""
        if len(parts) > 3 and parts[3].lower() in ("one-shot", "oneshot", "one shot"):
            ctype = "one-shot"
        if not name:
            name, system = system, ""
        if not name:
            continue
        slug = slugify(name)
        if slug in seen:
            continue
        seen.add(slug)
        campaigns.append({"system": system, "name": name, "slug": slug,
                          "seed": seed, "type": ctype})
    return campaigns


# --- State -----------------------------------------------------------------


def default_state():
    return {"campaigns": {}, "processed_uids": {}, "sent_message_ids": [],
            "last_run_date": None,
            # Global slow-burn counter: question rounds sent today (all
            # campaigns combined). Resets when rounds_date != today.
            "rounds_date": None, "rounds_today": 0}


def default_campaign(system, name, ctype="campaign"):
    first = sprint_list(ctype)[0]["key"]
    return {
        "system": system,
        "name": name,
        "type": ctype,
        "status": "new",                 # new | awaiting_reply | ready | complete
        "questions_asked": 0,
        "current_sprint": first,
        "sprint_day": 0,
        "completed_sprints": [],
        "last_questions": [],
        "last_message_id": "",
        "awaiting_since": None,
        "flagged_empty": False,
        "resend_count": 0,
        # Set at ingest time, consumed at send time (persisted — with the daily
        # cap, the send can happen on a later run than the ingest):
        "pending_sprint_complete": False,
        "pending_recap": "",
        "pending_canon_query": "",
    }


def load_state(path):
    base = default_state()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        return base
    if not isinstance(data, dict):
        return base
    data.setdefault("campaigns", {})
    if not isinstance(data["campaigns"], dict):
        data["campaigns"] = {}
    data.setdefault("processed_uids", {})
    if not isinstance(data["processed_uids"], dict):
        data["processed_uids"] = {}
    data.setdefault("sent_message_ids", [])
    if not isinstance(data["sent_message_ids"], list):
        data["sent_message_ids"] = []
    data.setdefault("last_run_date", None)
    data.setdefault("rounds_date", None)
    if not isinstance(data.get("rounds_today"), int):
        data["rounds_today"] = 0
    for slug, c in list(data["campaigns"].items()):
        if not isinstance(c, dict):
            data["campaigns"][slug] = default_campaign("", slug)
            continue
        ref = default_campaign(c.get("system", ""), c.get("name", slug),
                               c.get("type", "campaign"))
        for k, v in ref.items():
            c.setdefault(k, v)
    return data


def save_state(path, state):
    # The pending_* flags ARE persisted: with the daily cap, an ingested answer
    # can wait until tomorrow before its next question goes out, and the sprint
    # assessment (complete? recap?) must survive across runs until it's used.
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# --- Email reply parsing ---------------------------------------------------

_REPLY_HEADERS = re.compile(
    r"^\s*(on .+wrote:|-+\s*original message\s*-+|from:\s|sent from my|"
    r"get outlook for|________+)", re.I)


def _decode_header(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def strip_html(html):
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return (text.replace("&nbsp;", " ").replace("&amp;", "&")
            .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            .replace("&#39;", "'"))


def get_plain_body(msg):
    plain = html = None
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            disp = str(part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except (LookupError, TypeError):
                text = payload.decode("utf-8", errors="replace")
            if part.get_content_type() == "text/plain" and plain is None:
                plain = text
            elif part.get_content_type() == "text/html" and html is None:
                html = text
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            charset = msg.get_content_charset() or "utf-8"
            try:
                plain = payload.decode(charset, errors="replace")
            except (LookupError, TypeError):
                plain = payload.decode("utf-8", errors="replace")
    if plain is not None:
        return plain
    if html is not None:
        return strip_html(html)
    return ""


def extract_reply(body):
    """Strip quoted original + signature, returning just the new reply."""
    if not body:
        return ""
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    kept = []
    for line in body.split("\n"):
        s = line.strip()
        if _REPLY_HEADERS.match(s):
            break
        if s == "--" or line.rstrip() == "-- ":
            break
        if s.startswith(">"):
            break
        kept.append(line)
    answer = re.sub(r"\n{3,}", "\n\n", "\n".join(kept).strip())
    return answer


# --- AI calls --------------------------------------------------------------


class AIError(Exception):
    pass


def _http_post_json(url, payload, headers, timeout=90):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _call_gemini(system, user, json_mode):
    if not GEMINI_API_KEY:
        raise AIError("GEMINI_API_KEY is not set.")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{AI_MODEL}:generateContent?key={GEMINI_API_KEY}")
    # Generous ceiling: Gemini 2.5's internal "thinking" tokens count against
    # this budget, and long bibles make it think harder — a low cap truncates
    # the JSON and we fall back to a generic question.
    gen = {"temperature": 0.9, "maxOutputTokens": 16384}
    if json_mode:
        gen["responseMimeType"] = "application/json"
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": gen,
    }
    out = _http_post_json(url, payload, {"Content-Type": "application/json"})
    try:
        return out["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError):
        raise AIError(f"Unexpected Gemini response: {json.dumps(out)[:300]}")


def _call_anthropic(system, user, json_mode):
    if not ANTHROPIC_API_KEY:
        raise AIError("ANTHROPIC_API_KEY is not set.")
    payload = {"model": AI_MODEL, "max_tokens": 4096, "temperature": 0.9,
               "system": system, "messages": [{"role": "user", "content": user}]}
    headers = {"Content-Type": "application/json", "x-api-key": ANTHROPIC_API_KEY,
               "anthropic-version": "2023-06-01"}
    out = _http_post_json("https://api.anthropic.com/v1/messages", payload, headers)
    try:
        return out["content"][0]["text"].strip()
    except (KeyError, IndexError, TypeError):
        raise AIError(f"Unexpected Anthropic response: {json.dumps(out)[:300]}")


def _call_openai(system, user, json_mode):
    if not OPENAI_API_KEY:
        raise AIError("OPENAI_API_KEY is not set.")
    payload = {"model": AI_MODEL, "temperature": 0.9, "max_tokens": 4096,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}]}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {OPENAI_API_KEY}"}
    out = _http_post_json("https://api.openai.com/v1/chat/completions", payload, headers)
    try:
        return out["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise AIError(f"Unexpected OpenAI response: {json.dumps(out)[:300]}")


_PROVIDERS = {"gemini": _call_gemini, "anthropic": _call_anthropic,
              "openai": _call_openai}


def call_ai(system, user, json_mode=False, retries=4):
    fn = _PROVIDERS.get(AI_PROVIDER)
    if fn is None:
        raise AIError(f"Unknown AI_PROVIDER '{AI_PROVIDER}'.")
    delay, last = 2.0, None
    for attempt in range(retries):
        try:
            return fn(system, user, json_mode)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                print(f"AI {exc.code}; backing off {delay:.0f}s "
                      f"({attempt + 1}/{retries})")
                time.sleep(delay); delay *= 2; continue
            raise AIError(f"HTTP {exc.code} from {AI_PROVIDER}.")
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(delay); delay *= 2; continue
            raise AIError(f"Network error: {exc.__class__.__name__}")
    raise AIError(f"AI call failed: {last}")


def _loads_lenient(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j != -1 and j > i:
            return json.loads(text[i:j + 1])
        raise


def call_ai_json(system, user, attempts=2):
    """JSON-mode AI call with a retry when the response comes back garbled or
    truncated (long bibles occasionally produce unparseable output). Network/
    HTTP retries live inside call_ai; this guards the parse step."""
    last = None
    for i in range(attempts):
        try:
            return _loads_lenient(call_ai(system, user, json_mode=True))
        except (json.JSONDecodeError, ValueError) as exc:
            last = exc
            print(f"AI JSON unparseable (attempt {i + 1}/{attempts}); retrying.")
    raise AIError(f"AI returned unparseable JSON after {attempts} attempts: "
                  f"{last.__class__.__name__}")


# --- Prompt building -------------------------------------------------------

STANDING = (
    "You are an expert tabletop RPG Game Master and a campaign-design "
    "interviewer helping ONE GM build a game a little each day. Core rules of "
    "how you work:\n"
    "- Ask, don't write. You ask focused questions; you NEVER draft the "
    "campaign's creative core (the villain's heart, the central twist). You may "
    "scaffold non-critical structure and offer optional example directions.\n"
    "- Honor the GM PROFILE in tone, themes, and pace. Default to a question "
    "that STRETCHES him, but keep it answerable in a few minutes on a busy day "
    "(time is his scarcest resource).\n"
    "- Anchor campaigns on a grounded real-world thematic spine, and assume a "
    "love thread is woven into every arc even if not player-facing.\n"
    "- Lean into his growth areas: villains & their plans, mystery/clue plotting "
    "(re-introduce gently with craft, never as a gotcha), branching player "
    "choices, and vivid narration. When a question teaches a technique, give a "
    "one-line description plus a term he can google.\n"
    "- Stay consistent with the WORLD CANON below; build on it, never "
    "contradict it.\n"
    "- Default tone heroic PG-13 with grounded, earned moral weight."
)


def _context_block(campaign, cstate):
    bits = [STANDING, ""]
    profile = read_text(GM_PROFILE_PATH)
    if profile.strip():
        bits.append("=== GM PROFILE ===\n" + profile.strip())
    flavor = system_flavor(campaign["system"])
    if flavor.strip():
        bits.append("=== SYSTEM FLAVOR: " + (campaign["system"] or "system")
                    + " ===\n" + flavor.strip())
    custom = read_text(flavor_path(campaign["slug"]))
    if custom.strip():
        bits.append("=== CAMPAIGN-SPECIFIC NOTES (source of truth) ===\n"
                    + custom.strip())
    canon = read_text(canon_path(campaign["slug"]))
    if canon.strip():
        bits.append("=== WORLD CANON (established — do not contradict) ===\n"
                    + canon.strip())
    return "\n\n".join(bits)


def build_question_prompt(campaign, cstate, sprint, transcript, is_first):
    system = _context_block(campaign, cstate)
    ctype = cstate.get("type", "campaign")
    kind = "one-shot" if ctype == "one-shot" else "campaign"
    seed = (f"Seed: {campaign['seed']}\n" if campaign.get("seed") else "")
    is_brainstorm = sprint.get("key") == "spark"
    if is_first and is_brainstorm:
        intro = (
            f"This is a brand-new {kind} and he is starting from a BLANK PAGE — "
            "no premise yet. You are in brainstorm mode. Open warmly and "
            "generatively: draw the spark out of HIM. A great first question "
            "invites him to surface what's actually pulling at him right now (a "
            "real-world tension or theme, an image, a feeling he wants the table "
            "to have), or to toss out a few rough sparks you can grow together. "
            "Do NOT propose a premise; pull it from him. Any example directions "
            "go only in 'examples' as an unstuck aid he can ignore.\n")
    elif is_first:
        intro = f"This is a brand-new {kind} — nothing decided yet.\n"
    else:
        intro = f"Continuing the {kind}. Build on the most recent answer.\n"
    body = (
        f"CAMPAIGN: {campaign['name']} ({campaign['system'] or 'system TBD'})  "
        f"[{kind}]\n{seed}"
        f"CURRENT SPRINT: {sprint['label']} — focus on {sprint['focus']}.\n\n"
        f"{intro}"
    )
    if transcript.strip():
        body += ("Bible so far (every question + his answers):\n-----\n"
                 + transcript.strip() + "\n-----\n\n")
    body += (
        "Ask the next question for THIS sprint. Usually one question; at most "
        "two if they're tightly linked. Concrete, answerable in a few "
        "sentences, building on the latest answer and the canon.\n\n"
        "ALWAYS include 2-3 entries in 'examples': vivid, concrete springboards "
        "specific to THIS exact question and to what he has ALREADY established "
        "(use names/facts from the bible and canon). They are the spark that "
        "gets him going, so include them every single email — but keep them "
        "FRESH and PROGRESSIVE: never reuse or rephrase earlier examples, and let "
        "them advance as the build advances. They sit at the very bottom as "
        "things to react to, remix, or ignore; the question itself is the real, "
        "progressive ask.\n\n"
        "Return ONLY JSON with this shape:\n"
        "{\n"
        '  "questions": ["the question", "optional second question"],\n'
        '  "teaches": {"description": "one line on the technique", "term": '
        '"google-able term"}   (or null if not teaching anything),\n'
        '  "examples": ["2-3 fresh springboards specific to THIS question + the '
        'established canon", "..."]\n'
        "}"
    )
    return system, body


def build_assessment_prompt(campaign, cstate, sprint, latest_answer, transcript):
    system = _context_block(campaign, cstate)
    body = (
        f"CAMPAIGN: {campaign['name']}. CURRENT SPRINT: {sprint['label']} "
        f"(day {cstate['sprint_day']} of up to {sprint['cap']}; focus: "
        f"{sprint['focus']}).\n\n"
        "The GM just answered the latest question. His answer:\n-----\n"
        f"{latest_answer.strip()}\n-----\n\n"
        "Full bible so far for context:\n-----\n"
        f"{transcript.strip()}\n-----\n\n"
        "Do two jobs:\n"
        "1) CANON: extract the DURABLE world facts stated in HIS answer "
        "(locations, NPCs, factions, items/powers and their limits, magic "
        "rules, timeline, arc decisions). Distill only what he actually said — "
        "never invent. Each fact: a category from [LOCATION, NPC, FACTION, "
        "ITEM/POWER, MAGIC, TIMELINE, ARC, OTHER], a short name, and ONE tight "
        "line (<= 25 words). Capture the most important facts — up to about 15; "
        "consolidate rather than listing every minor detail. Keep the whole JSON "
        "compact.\n"
        "2) SPRINT STATUS: decide whether this sprint's element is now fleshed "
        "out enough to move on. If yes, write a 1-2 sentence recap built from "
        "HIS answers (not new invention).\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "canon": [{"category": "NPC", "name": "...", "fact": "..."}],\n'
        '  "sprint_complete": true/false,\n'
        '  "recap": "short recap from his answers (only if complete, else empty)"'
        "\n}"
    )
    return system, body


def build_canon_query_prompt(campaign, cstate, query):
    system = _context_block(campaign, cstate)
    body = (
        f"The GM is asking what the WORLD CANON above already knows about: "
        f"\"{query}\".\n\n"
        "Answer ONLY from the established canon and campaign notes above. If the "
        "canon is silent or thin on it, say so plainly and suggest what to nail "
        "down. Be concise and concrete. Plain prose, no preamble."
    )
    return system, body


def build_backpocket_prompt(campaign, cstate, transcript):
    system = _context_block(campaign, cstate)
    body = (
        f"The one-shot \"{campaign['name']}\" is built. Using ONLY what the GM "
        "decided in the bible below, compile a clean, ready-to-run one-shot "
        "summary he can pick up cold on a short week. Use his content; don't "
        "invent new core elements. Include, as plain-text sections: Concept & "
        "tone; The ensemble (pregens, with powers/weaknesses as plot engines); "
        "Cold open; Central conflict; Set-pieces (2-3); The twist/payoff; and a "
        "short 'How to run it' note (pacing, the locked tone). Keep it tight and "
        "scannable.\n\nBible:\n-----\n" + transcript.strip() + "\n-----"
    )
    return system, body


# --- Canon ledger ----------------------------------------------------------


def update_canon(slug, name, entries, today, sprint_label):
    """Append distilled facts to the canon ledger. Creates it if needed."""
    entries = [e for e in (entries or [])
               if isinstance(e, dict) and (e.get("fact") or e.get("name"))]
    if not entries:
        return
    if not os.path.exists(canon_path(slug)):
        append_text(canon_path(slug),
                    f"# World Canon — {name}\n\n"
                    "Facts distilled from your answers. The builder reads this "
                    "before every question so it never contradicts what's here. "
                    "Human-editable — fix or expand anything.\n")
    lines = [f"\n## {today} · after {sprint_label}\n"]
    for e in entries:
        cat = str(e.get("category", "OTHER")).strip().upper() or "OTHER"
        nm = str(e.get("name", "")).strip()
        fact = str(e.get("fact", "")).strip()
        head = f"**{nm}**: " if nm else ""
        lines.append(f"- [{cat}] {head}{fact}")
    append_text(canon_path(slug), "\n".join(lines) + "\n")


# --- SMTP ------------------------------------------------------------------


def send_email(to_addr, subject, body, message_id=None, in_reply_to=None,
               token=None):
    footer = STABLE_TAG + (f" [cb:{token}]" if token else "")
    body = body.rstrip() + "\n\n" + footer + "\n"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((SENDER_NAME, SENDER_EMAIL))
    msg["To"] = to_addr
    msg["Reply-To"] = SENDER_EMAIL
    if message_id:
        msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=60) as s:
            s.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            s.sendmail(SENDER_EMAIL, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=60) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            s.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            s.sendmail(SENDER_EMAIL, [to_addr], msg.as_string())


def _track_sent(state, message_id):
    state["sent_message_ids"].append(message_id)
    if len(state["sent_message_ids"]) > 500:
        state["sent_message_ids"] = state["sent_message_ids"][-500:]


# --- Email composition (the hard format spec) ------------------------------


def compose_question_email(campaign, cstate, sprint, qjson, recap_block):
    ctype = cstate.get("type", "campaign")
    day = cstate["sprint_day"]
    cap = sprint["cap"]
    cap_note = f" of up to {cap}" if cap < 100 else ""
    lines = [f"{campaign['name']} — {sprint['label']} · day {day}{cap_note}",
             f"Progress — {progress_marker(campaign, cstate)}", ""]

    if recap_block:
        lines.append(recap_block.strip())
        lines.append("")

    questions = qjson.get("questions") or []
    if isinstance(questions, str):
        questions = [questions]
    questions = [q.strip() for q in questions if str(q).strip()][:2]
    for i, q in enumerate(questions, 1):
        prefix = f"{i}) " if len(questions) > 1 else ""
        lines.append(prefix + q)
        lines.append("")          # blank line to type the answer under
        lines.append("")

    teaches = qjson.get("teaches")
    if isinstance(teaches, dict) and (teaches.get("description") or teaches.get("term")):
        desc = str(teaches.get("description", "")).strip()
        term = str(teaches.get("term", "")).strip()
        tip = "Technique: " + desc
        if term:
            tip += f"  (look up: {term})"
        lines.append(tip)
        lines.append("")

    examples = qjson.get("examples") or []
    if isinstance(examples, str):
        examples = [examples]
    examples = [e.strip() for e in examples if str(e).strip()][:3]
    if examples:
        lines.append("--- Examples (only if you're stuck) ---")
        for e in examples:
            lines.append(f"- {e}")
        lines.append("")

    lines.append("———")
    lines.append("Reply with your answer under each question. Tip: reply "
                 "`CANON: <thing>` and I'll tell you what the world bible "
                 "already knows. Or start something new: reply "
                 "`NEW CAMPAIGN: <system> | <name>` for a fresh brainstorm "
                 "(this campaign is untouched). No rush — nothing moves until "
                 "you answer.")
    return "\n".join(lines), questions


def fallback_question(sprint):
    return {"questions": [f"Let's work on {sprint['label'].lower()}: "
                          f"what's your next decision about {sprint['focus']}?"],
            "teaches": None, "examples": []}


# --- IMAP ingest -----------------------------------------------------------


def imap_connect():
    imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    imap.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
    return imap


def _search_uids(imap):
    try:
        typ, data = imap.uid("search", None, "ALL")
        if typ == "OK":
            return data[0].split()
    except imaplib.IMAP4.error:
        pass
    return []


def handle_new_campaign_command(rest, state, campaigns_by_slug):
    """Process `NEW CAMPAIGN: <system> | <name> | <seed>` from any reply.

    Creates an isolated campaign: its own line in campaigns.txt, its own state
    entry, and (via the normal advance path) its own bible + canon files. The
    campaign the command arrived from is never touched. Returns a short log
    string; sends a help/confirmation email as appropriate."""
    first_line = rest.strip().splitlines()[0] if rest.strip() else ""
    parts = [p.strip() for p in first_line.split("|")]
    system = parts[0] if len(parts) > 0 else ""
    name = parts[1] if len(parts) > 1 else ""
    seed = parts[2] if len(parts) > 2 else ""

    if not system or not name:
        send_email(
            CAMPAIGN_RECIPIENT,
            "[Campaign Builder] NEW CAMPAIGN needs a system and a name",
            "Almost! The format is:\n\n"
            "  NEW CAMPAIGN: <system> | <name> | <optional seed>\n\n"
            "The system is required so nothing gets assumed. Examples:\n"
            "  NEW CAMPAIGN: D&D 5e | Embergard\n"
            "  NEW CAMPAIGN: Cosmere RPG | Ashfall | [one-shot] a heist during "
            "a highstorm\n\n"
            "Reply to any campaign email with a corrected command (on its own, "
            "as the whole reply).")
        return "malformed NEW CAMPAIGN command — sent format help"

    slug = slugify(name)
    if slug in state["campaigns"] or slug in campaigns_by_slug:
        send_email(
            CAMPAIGN_RECIPIENT,
            f"[Campaign Builder] '{name}' already exists",
            f"A campaign with the name '{name}' (slug '{slug}') already exists, "
            "so nothing was created. Pick a different name and send the command "
            "again.")
        return f"NEW CAMPAIGN '{slug}' already exists — sent notice"

    ctype = "one-shot" if ONESHOT_TOKEN_RE.search(first_line) else "campaign"
    line = f"{system} | {name}" + (f" | {seed}" if seed else "")
    append_text(CAMPAIGNS_PATH, "\n" + line + "\n")
    state["campaigns"][slug] = default_campaign(system, name, ctype)
    return f"created new {ctype} '{slug}' from email command"


def send_which_campaign_email(state, campaigns_by_slug):
    """We got a reply we couldn't confidently route — ask, never guess."""
    active = [(slug, c) for slug, c in state["campaigns"].items()
              if c.get("status") != "complete" and slug in campaigns_by_slug]
    lines = ["I got a reply but couldn't tell which campaign it belongs to, so "
             "I didn't file it anywhere (campaigns never mix).", "",
             "To send it again, either reply directly to that campaign's latest "
             "question email, or include its routing tag anywhere in your "
             "reply:", ""]
    for slug, c in active:
        waiting = " (waiting on you)" if c.get("status") == "awaiting_reply" else ""
        lines.append(f"  - {c.get('name', slug)}  ->  [cb:{slug}]{waiting}")
    if not active:
        lines.append("  (no active campaigns)")
    send_email(CAMPAIGN_RECIPIENT,
               "[Campaign Builder] Which campaign is this for?",
               "\n".join(lines))


def ingest_replies(imap, state, campaigns_by_slug, today):
    """Read new mail and route each message to the right campaign.

    Routing priority (campaigns must never mix):
      1. the [cb:slug] token quoted from our footer — survives edited subjects
         and fresh (unthreaded) emails;
      2. threading headers against the last question's Message-ID;
      3. the [Name] subject tag.
    A confident match files the answer (or CANON query). `NEW CAMPAIGN: ...`
    spins up an isolated new campaign. Anything else gets a "which campaign?"
    email rather than a guess."""
    awaiting = {slug: c for slug, c in state["campaigns"].items()
                if c.get("status") == "awaiting_reply" and slug in campaigns_by_slug}
    by_msgid = {c["last_message_id"]: slug for slug, c in awaiting.items()
                if c.get("last_message_id")}

    typ, _ = imap.select(IMAP_FOLDER, readonly=True)
    if typ != "OK":
        print(f"WARN: could not select IMAP folder '{IMAP_FOLDER}'; skipping ingest.")
        return

    processed = set(state["processed_uids"].get(IMAP_FOLDER, []))
    sent_ids = set(state.get("sent_message_ids", []))
    recipient_addr = parseaddr(CAMPAIGN_RECIPIENT)[1].lower()

    for uid in _search_uids(imap):
        uid_s = uid.decode() if isinstance(uid, bytes) else str(uid)
        if uid_s in processed:
            continue
        typ, msg_data = imap.uid("fetch", uid, "(RFC822)")
        if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
            continue
        msg = email.message_from_bytes(msg_data[0][1])

        msg_id = (msg.get("Message-ID") or "").strip()
        if msg_id and msg_id in sent_ids:
            processed.add(uid_s)
            continue

        # Only the owner's replies count.
        from_addr = parseaddr(msg.get("From", ""))[1].lower()
        if recipient_addr and from_addr and from_addr != recipient_addr:
            processed.add(uid_s)
            continue

        raw = get_plain_body(msg)
        answer = extract_reply(raw)
        flagged = False
        if not answer.strip():
            answer, flagged = raw.strip(), True

        # NEW CAMPAIGN command — handled before routing; it can arrive from
        # inside ANY email (or a fresh one) and never touches its host campaign.
        m = NEWCMD_RE.match(answer.strip())
        if m and not flagged:
            print(handle_new_campaign_command(m.group("rest"), state,
                                              campaigns_by_slug))
            processed.add(uid_s)
            continue

        subject = _decode_header(msg.get("Subject", ""))
        refs = (msg.get("In-Reply-To", "") + " " + msg.get("References", ""))
        looks_reply = bool(msg.get("In-Reply-To")) or subject.lower().startswith("re:")

        # 1) Routing token (from the quoted footer) beats everything.
        slug = None
        tm = TOKEN_RE.search(raw)
        if tm:
            tok_slug = tm.group("slug").lower()
            if tok_slug in awaiting:
                slug = tok_slug
            elif tok_slug in state["campaigns"]:
                # A reply to a campaign that isn't waiting (stale/duplicate).
                processed.add(uid_s)
                print(f"Skipped stale reply tokened for '{tok_slug}' "
                      "(not awaiting).")
                continue
        # 2) Threading headers.
        if slug is None:
            for mid, cand in by_msgid.items():
                if mid and mid in refs:
                    slug = cand
                    break
        # 3) Subject tag.
        if slug is None:
            sm = SUBJECT_TAG_RE.match(subject)
            if sm and looks_reply:
                tag_slug = slugify(sm.group("name"))
                if tag_slug in awaiting:
                    slug = tag_slug
        if slug is None:
            # Looks like one of ours (it's in the label and from the owner) but
            # we can't place it confidently: ask, never guess.
            if looks_reply or STABLE_TAG in raw:
                send_which_campaign_email(state, campaigns_by_slug)
                print("Unroutable reply — asked which campaign it belongs to.")
            processed.add(uid_s)
            continue

        cstate = state["campaigns"][slug]
        campaign = campaigns_by_slug[slug]

        # CANON query command — don't advance; flag a lookup reply.
        m = re.match(r"\s*canon\s*:\s*(?P<q>.+)", answer, re.I | re.S)
        if m and not flagged:
            cstate["pending_canon_query"] = m.group("q").strip()
            processed.add(uid_s)
            print(f"Canon query for '{slug}': {cstate['pending_canon_query'][:60]}")
            continue

        # Normal answer: file it, distill canon, assess the sprint.
        append_text(bible_path(slug), f"\n**Answer — {today}:**\n\n{answer}\n")
        sprint = find_sprint(cstate.get("type", "campaign"), cstate["current_sprint"])
        try:
            system, user = build_assessment_prompt(
                campaign, cstate, sprint, answer, read_text(bible_path(slug)))
            res = call_ai_json(system, user)
            update_canon(slug, campaign["name"], res.get("canon"), today,
                         sprint["label"])
            cstate["pending_sprint_complete"] = bool(res.get("sprint_complete"))
            cstate["pending_recap"] = str(res.get("recap", "")).strip()
        except (AIError, ValueError, KeyError) as exc:
            print(f"WARN: assessment failed for '{slug}' ({exc.__class__.__name__}); "
                  f"continuing without canon update.")
            cstate["pending_sprint_complete"] = False
            cstate["pending_recap"] = ""

        cstate["status"] = "ready"
        cstate["flagged_empty"] = flagged
        cstate["awaiting_since"] = None
        cstate["resend_count"] = 0
        by_msgid = {mid: s for mid, s in by_msgid.items() if s != slug}
        awaiting.pop(slug, None)
        processed.add(uid_s)
        print(f"Ingested answer for '{slug}'"
              + (" (empty extraction — stored raw, flagged)" if flagged else ""))

    state["processed_uids"][IMAP_FOLDER] = sorted(processed)


# --- Advancing -------------------------------------------------------------


def _send_question(campaign, cstate, state, sprint, today, recap_block, is_first):
    """Generate + send the next question(s) for a sprint. Mutates state."""
    transcript = read_text(bible_path(campaign["slug"])) if not is_first else ""
    try:
        system, user = build_question_prompt(
            campaign, cstate, sprint, transcript, is_first)
        qjson = call_ai_json(system, user)
        if not (qjson.get("questions")):
            qjson = fallback_question(sprint)
    except (AIError, ValueError, KeyError) as exc:
        print(f"WARN: question gen failed for '{campaign['slug']}' "
              f"({exc.__class__.__name__}); using fallback.")
        qjson = fallback_question(sprint)

    if not os.path.exists(bible_path(campaign["slug"])):
        header = (f"# Campaign Bible — {campaign['name']}\n\n"
                  f"- **System:** {campaign['system'] or 'TBD'}\n"
                  f"- **Type:** {cstate.get('type', 'campaign')}\n"
                  f"- **Started:** {today}\n")
        if campaign.get("seed"):
            header += f"- **Seed:** {campaign['seed']}\n"
        append_text(bible_path(campaign["slug"]), header + "\n---\n")

    body, questions = compose_question_email(
        campaign, cstate, sprint, qjson, recap_block)
    qtext = "\n".join(f"- {q}" for q in questions)
    append_text(bible_path(campaign["slug"]),
                f"\n## {sprint['label']} · day {cstate['sprint_day']} — {today}\n\n"
                f"{qtext}\n")

    message_id = make_msgid(domain=(SENDER_EMAIL.split("@")[-1] or "campaign.local"))
    type_tag = "one-shot: " if cstate.get("type") == "one-shot" else ""
    subject = (f"[{campaign['name']}] {type_tag}{sprint['label']} - "
               f"day {cstate['sprint_day']}")
    # Fresh standalone email (no In-Reply-To), carrying the routing token.
    send_email(CAMPAIGN_RECIPIENT, subject, body, message_id=message_id,
               token=f"{campaign['slug']}#{cstate['questions_asked'] + 1}")

    cstate["status"] = "awaiting_reply"
    cstate["questions_asked"] += 1
    cstate["last_questions"] = questions
    cstate["last_message_id"] = message_id
    cstate["awaiting_since"] = today
    cstate["flagged_empty"] = False
    cstate["resend_count"] = 0
    _track_sent(state, message_id)
    print(f"Sent '{campaign['slug']}' — {sprint['label']} day {cstate['sprint_day']}.")


def finish_oneshot(campaign, cstate, state, today):
    """Compile the one-shot into the back-pocket library and mark it complete."""
    transcript = read_text(bible_path(campaign["slug"]))
    try:
        system, user = build_backpocket_prompt(campaign, cstate, transcript)
        summary = call_ai(system, user)
    except AIError as exc:
        print(f"WARN: back-pocket summary failed for '{campaign['slug']}' ({exc}); "
              f"leaving one-shot ready to retry next run.")
        return False
    append_text(backpocket_path(campaign["slug"]),
                f"# {campaign['name']} — ready-to-run one-shot\n\n"
                f"*System: {campaign['system'] or 'TBD'} · filed {today}*\n\n"
                + summary.strip() + "\n")
    body = (f"{campaign['name']} — ready to run.\n\n"
            "Your one-shot is built and filed in "
            f"back-pocket/{campaign['slug']}.md for a short week. Here it is:\n\n"
            "———\n\n" + summary.strip())
    message_id = make_msgid(domain=(SENDER_EMAIL.split("@")[-1] or "campaign.local"))
    send_email(CAMPAIGN_RECIPIENT, f"[{campaign['name']}] one-shot: Ready to run", body,
               message_id=message_id, token=campaign["slug"])
    _track_sent(state, message_id)
    cstate["status"] = "complete"
    cstate["completed_sprints"] = [s["key"] for s in ONESHOT_SPRINTS]
    print(f"One-shot '{campaign['slug']}' complete — filed to back-pocket.")
    return True


def advance_campaign(campaign, state, today):
    slug = campaign["slug"]
    cstate = state["campaigns"].setdefault(
        slug, default_campaign(campaign["system"], campaign["name"], campaign["type"]))
    cstate["system"] = campaign["system"]
    cstate["name"] = campaign["name"]
    ctype = cstate.get("type", "campaign")

    bible_exists = os.path.exists(bible_path(slug))
    is_first = cstate["questions_asked"] == 0 or not bible_exists

    if is_first:
        # Full campaigns with no seed begin in brainstorm mode (the "spark"
        # sprint); a provided seed means he already has an idea, so skip straight
        # to building it. One-shots use their own first sprint.
        if ctype == "campaign":
            start_key = "premise" if campaign.get("seed") else "spark"
        else:
            start_key = sprint_list(ctype)[0]["key"]
        cstate["current_sprint"] = start_key
        cstate["sprint_day"] = 1
        cstate["completed_sprints"] = []
        sprint = find_sprint(ctype, start_key)
        _send_question(campaign, cstate, state, sprint, today, "", is_first=True)
        return

    sprint = find_sprint(ctype, cstate["current_sprint"])
    complete = cstate.get("pending_sprint_complete") or cstate["sprint_day"] >= sprint["cap"]

    if not complete:
        cstate["sprint_day"] += 1
        _send_question(campaign, cstate, state, sprint, today, "", is_first=False)
        return

    # Sprint wraps: recap + transition to the next sprint.
    recap = cstate.get("pending_recap", "").strip()
    nxt = next_sprint(ctype, cstate["current_sprint"])

    if cstate["current_sprint"] not in cstate["completed_sprints"]:
        cstate["completed_sprints"].append(cstate["current_sprint"])

    if nxt is None:
        # End of the line. One-shots are done after their last content sprint;
        # campaigns stay in "ongoing/deepen" forever.
        if ctype == "campaign":
            cstate["sprint_day"] += 1
            _send_question(campaign, cstate, state, sprint, today, "", is_first=False)
        else:
            finish_oneshot(campaign, cstate, state, today)
        return

    if nxt.get("terminal"):
        # One-shot's final step: compile, file, finish.
        cstate["current_sprint"] = nxt["key"]
        cstate["sprint_day"] = 1
        finish_oneshot(campaign, cstate, state, today)
        return

    cstate["current_sprint"] = nxt["key"]
    cstate["sprint_day"] = 1
    done_label = sprint["label"]
    recap_block = f"{done_label} — locked in."
    if recap:
        recap_block += " " + recap
    recap_block += f"\nNext up: {nxt['label']}."
    _send_question(campaign, cstate, state, nxt, today, recap_block, is_first=False)


def answer_canon_query(campaign, cstate, state, today):
    query = cstate.get("pending_canon_query", "").strip()
    if not query:
        return
    try:
        system, user = build_canon_query_prompt(campaign, cstate, query)
        answer = call_ai(system, user)
    except AIError as exc:
        answer = (f"(Couldn't reach the AI to look that up right now: {exc}. "
                  "Try again next run.)")
    body = (f"{campaign['name']} — canon lookup\n\n"
            f"You asked: {query}\n\n———\n\n{answer.strip()}\n\n———\n"
            "Your open question is still waiting — reply to the previous "
            "question email to answer it.")
    message_id = make_msgid(domain=(SENDER_EMAIL.split("@")[-1] or "campaign.local"))
    send_email(CAMPAIGN_RECIPIENT,
               f"[{campaign['name']}] Canon: {query[:40]}", body,
               message_id=message_id, token=campaign["slug"])
    _track_sent(state, message_id)
    cstate["pending_canon_query"] = ""
    print(f"Answered canon query for '{campaign['slug']}'.")


# --- Main ------------------------------------------------------------------


def main():
    missing = [n for n, v in (("SENDER_EMAIL", SENDER_EMAIL),
                              ("SENDER_APP_PASSWORD", SENDER_APP_PASSWORD),
                              ("CAMPAIGN_RECIPIENT", CAMPAIGN_RECIPIENT)) if not v]
    if AI_PROVIDER == "gemini" and not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if missing:
        # Not configured yet (e.g. a fresh copy of the repo, or a secret typo).
        # Exit GREEN, not red — a blank template / mid-setup repo shouldn't spam
        # the owner with failure emails every night. The log says what's missing.
        print("Secrets not configured yet — missing: " + ", ".join(missing)
              + ". Add them in Settings > Secrets and variables > Actions, then "
              "run again. Skipping this run.")
        return 0

    today = today_in_tz()
    state = load_state(STATE_PATH)
    campaigns = parse_campaigns(CAMPAIGNS_PATH)
    if not campaigns:
        print("No active campaigns; nothing to do.")
        state["last_run_date"] = today
        save_state(STATE_PATH, state)
        return 0
    by_slug = {c["slug"]: c for c in campaigns}

    # 1) Ingest replies. Always scan: NEW CAMPAIGN commands can arrive even
    #    when nothing is awaiting a reply.
    try:
        imap = imap_connect()
        try:
            ingest_replies(imap, state, by_slug, today)
        finally:
            try:
                imap.logout()
            except Exception:
                pass
    except Exception as exc:
        print(f"WARN: reply ingest failed ({exc.__class__.__name__}: {exc}); "
              "continuing.")

    # A NEW CAMPAIGN command may have appended to campaigns.txt — reload so the
    # new campaign gets its kickoff question this same run (cap permitting).
    campaigns = parse_campaigns(CAMPAIGNS_PATH)
    by_slug = {c["slug"]: c for c in campaigns}

    # 2) Act on each campaign, under the global daily round cap.
    sent_any = False
    for campaign in campaigns:
        slug = campaign["slug"]
        cstate = state["campaigns"].get(slug)
        try:
            if cstate and cstate.get("status") == "complete":
                print(f"'{slug}' is complete; skipping.")
                continue
            if cstate and cstate.get("pending_canon_query"):
                # Canon lookups are free — they don't count against the cap.
                answer_canon_query(campaign, cstate, state, today)
                sent_any = True
                continue
            is_new = (cstate is None or cstate.get("questions_asked", 0) == 0
                      or not os.path.exists(bible_path(slug)))
            if is_new or (cstate and cstate.get("status") == "ready"):
                if rounds_left(state, today) <= 0:
                    print(f"Daily cap reached ({cap_for(today)} round(s) on "
                          f"{weekday_key(today)}); '{slug}' will advance "
                          "after local midnight.")
                    continue
                advance_campaign(campaign, state, today)
                count_round(state, today)
                sent_any = True
            elif cstate and cstate.get("status") == "awaiting_reply":
                if (RESEND_AFTER_DAYS > 0 and cstate.get("resend_count", 0) < 1
                        and days_since(cstate.get("awaiting_since"), today)
                        >= RESEND_AFTER_DAYS):
                    _resend(campaign, cstate, today)
                    sent_any = True
                else:
                    print(f"'{slug}' awaiting a reply; leaving it alone.")
        except AIError as exc:
            print(f"WARN: skipping '{slug}' — AI error: {exc}")
        except Exception as exc:
            print(f"WARN: skipping '{slug}' — {exc.__class__.__name__}: {exc}")

    state["last_run_date"] = today
    save_state(STATE_PATH, state)
    if not sent_any:
        print("Nothing to send this run.")
    return 0


def _resend(campaign, cstate, today):
    qs = cstate.get("last_questions") or []
    body = ("Still waiting on this whenever you're ready:\n\n"
            + "\n\n".join(qs) + "\n\n———\nReply to lock it in. Only nudge.")
    # Fresh standalone email; the token routes any reply to it correctly.
    send_email(CAMPAIGN_RECIPIENT,
               f"[{campaign['name']}] reminder", body,
               token=campaign["slug"])
    cstate["resend_count"] = cstate.get("resend_count", 0) + 1
    print(f"Resent reminder for '{campaign['slug']}'.")


if __name__ == "__main__":
    sys.exit(main())
