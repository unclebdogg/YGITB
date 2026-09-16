#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import requests
from datetime import datetime, timedelta
import pytz

from .utils import load_config, get_env, read_text, render_template
from .timegate import should_run
from .sleeper import (
    get_state,
    get_league,
    get_users,
    get_rosters,
    get_players_index,
    build_matchup_cards,
)
from .writer import write_report, output_path

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


# ----------------------------
# LLM helpers
# ----------------------------
def openai_chat(model, system, user, temperature=0.6, max_tokens=2000, api_key=None):
    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY env.")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    # A single transient 5xx used to fail the whole weekly run and skip the week
    # (OpenAI returned 530 on 16 Sep). Retry a few times before giving up.
    last = None
    for attempt in range(1, 4):
        r = requests.post(OPENAI_CHAT_URL, headers=headers, json=payload, timeout=120)
        if r.status_code < 500:
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        last = f"{r.status_code} {r.text[:200]}"
        print(f"[llm] attempt {attempt}/3 failed: {last}")
        time.sleep(5 * attempt)
    raise SystemExit(f"OpenAI failed after 3 attempts: {last}")


def parse_json_or_die(text: str):
    try:
        return json.loads(text)
    except Exception:
        stripped = text.strip()
        # If the model added fences, try to strip them
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if "\n" in stripped:
                stripped = stripped.split("\n", 1)[1]
            try:
                return json.loads(stripped)
            except Exception:
                pass
        preview = stripped[:800]
        raise SystemExit(f"LLM did not return valid JSON.\n---\n{preview}\n---")


# ----------------------------
# Time / league helpers
# ----------------------------
def local_week_window(tz_name: str):
    """Return label window (Mon–Sun) for header only."""
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=6, hours=23, minutes=59)
    return start.strftime("%d %b"), end.strftime("%d %b")


def resolve_week_for(kind: str) -> int:
    """Use Sleeper state to get current week; for recap, use previous week."""
    st = get_state()
    week = int(st.get("week") or 1)
    return week if kind == "preview" else max(1, week - 1)


def resolve_season() -> str:
    """The NFL season these reports belong to — NFL_SEASON, else Sleeper state."""
    env = get_env("NFL_SEASON", "")
    if env:
        return str(env)
    return str(get_state().get("season") or datetime.now().year)


# ----------------------------
# Prompt assembly
# ----------------------------
def assemble_preview_prompt(league, week, cards, tz_name):
    """
    Structured preview: team names, records, projections.
    The system prompt enforces JSON; user prompt gives raw matchup lines.
    """
    sys = read_text("prompts/system_preview.txt")
    usr_tpl = read_text("prompts/user_preview.txt")
    start_date, end_date = local_week_window(tz_name)

    lines = []
    for c in cards:
        lines.append(
            f"- {c['home_name']} (rec {c['home_record']['text']}), proj {c['home_points']} "
            f"vs {c['away_name']} (rec {c['away_record']['text']}), proj {c['away_points']}"
        )

    usr = render_template(
        usr_tpl,
        week=str(week),
        start_date=start_date,
        end_date=end_date,
        league_name=league.get("name", "Your League"),
        matchups_block="\n".join(lines),
    )
    return sys, usr, start_date, end_date


def assemble_recap_prompt(league, week, cards, tz_name):
    """
    Structured recap: scoreline plus top 1–2 stars per team (from starters).
    """
    sys = read_text("prompts/system_recap.txt")
    usr_tpl = read_text("prompts/user_recap.txt")
    start_date, end_date = local_week_window(tz_name)

    def star_fmt(s):
        return f"{s['player']} ({s.get('nfl_team','?')} {s.get('pos','?')} – {s.get('points','?')} pts)"

    lines = []
    for c in cards:
        # score
        if c["home_points"] is not None and c["away_points"] is not None:
            score = (
                f"{c['home_name']} ({c['home_record']['text']}) {c['home_points']} "
                f"def. {c['away_name']} ({c['away_record']['text']}) {c['away_points']}"
            )
        else:
            score = (
                f"{c['home_name']} ({c['home_record']['text']}) vs "
                f"{c['away_name']} ({c['away_record']['text']}) (no final score)"
            )
        # stars
        home_stars = ", ".join(star_fmt(s) for s in (c.get("home_stars") or []))
        away_stars = ", ".join(star_fmt(s) for s in (c.get("away_stars") or []))
        stars_line = (
            f"  • Stars {c['home_name']}: {home_stars if home_stars else '—'} | "
            f"{c['away_name']}: {away_stars if away_stars else '—'}"
        )
        lines.append(f"- {score}\n{stars_line}")

    usr = render_template(
        usr_tpl,
        week=str(week),
        start_date=start_date,
        end_date=end_date,
        league_name=league.get("name", "Your League"),
        results_block="\n".join(lines) or "(No results found)",
    )
    return sys, usr, start_date, end_date


# ----------------------------
# Markdown renderers
# ----------------------------
def md_preview_from_json(week: int, data: dict, local_start: str, local_end: str) -> str:
    parts = []
    parts.append(f"# Preview – Week {week}\n\n> Window: {local_start} – {local_end}\n")
    parts.append(f"## {data.get('headline','League Preview')}\n")
    sl = data.get("storylines") or []
    if sl:
        parts.append("**Key Storylines**")
        for s in sl:
            parts.append(f"- {s}")
        parts.append("")
    for m in data.get("matchups", []):
        h, a = m.get("home", {}), m.get("away", {})
        title = f"### {h.get('name','?')} ({h.get('record','-')}) vs {a.get('name','?')} ({a.get('record','-')})"
        sub = f"_Projections:_ {h.get('proj','?')} – {a.get('proj','?')}"
        parts.append(title)
        parts.append(sub)
        if m.get("angle"):
            parts.append(f"**Angle:** {m['angle']}")
        if m.get("capsule"):
            parts.append(m["capsule"])
        parts.append("")
    if data.get("kicker"):
        parts.append(f"> {data['kicker']}")
    parts.append("")
    return "\n".join(parts)


def md_recap_from_json(week: int, data: dict, local_start: str, local_end: str) -> str:
    POS_ICON = {
        "QB": "🧠",
        "RB": "🏃",
        "WR": "🎯",
        "TE": "🧲",
        "K": "🎯",
        "DEF": "🛡️",
        "DST": "🛡️",
        "FLEX": "🔁",
    }
    STAR = "⭐"
    TROPHY = "🏆"

    parts = []
    parts.append(f"# Recap – Week {week}\n\n> Window: {local_start} – {local_end}\n")
    parts.append(f"## {data.get('headline','League Recap')}\n")

    # Moments
    mm = data.get("moments") or []
    if mm:
        parts.append("**Moments That Mattered**")
        for s in mm:
            parts.append(f"- {s}")
        parts.append("")

    # Games
    for g in data.get("games", []):
        h, a = g.get("home", {}), g.get("away", {})
        r = g.get("result", {})
        title = (
            f"### {h.get('name','?')} ({h.get('record','-')}) "
            f"{r.get('home','?')} – {r.get('away','?')} "
            f"{a.get('name','?')} ({a.get('record','-')})"
        )
        parts.append(title)

        # Star performers
        stars = g.get("stars") or []
        if stars:
            star_bits = []
            for s in stars:
                icon = POS_ICON.get((s.get("pos") or "").upper(), STAR)
                star_bits.append(
                    f"{icon} {s.get('player','?')} "
                    f"({s.get('nfl_team','?')} {s.get('pos','?')} – {s.get('points','?')} pts)"
                )
            parts.append("**Star Performers:** " + ", ".join(star_bits))

        # Capsule
        if g.get("capsule"):
            parts.append(g["capsule"])

        parts.append("")

    # Pulse
    pulse = data.get("pulse") or []
    if pulse:
        parts.append("**Power Pulse**")
        for i, s in enumerate(pulse, start=1):
            lead = TROPHY if i == 1 else "•"
            parts.append(f"- {lead} {s}")
        parts.append("")

    return "\n".join(parts)


# ----------------------------
# Main
# ----------------------------
def main(kind: str):
    # Config & env
    cfg = load_config()
    tz_name = get_env("TIMEZONE", "Australia/Sydney")
    output_dir = get_env("OUTPUT_DIR", "reports")
    api_key = get_env("OPENAI_API_KEY")
    league_id = get_env("SLEEPER_LEAGUE_ID")
    if not league_id:
        raise SystemExit("Missing SLEEPER_LEAGUE_ID env.")

    # Optional timegate (disabled in cron via DISABLE_TIMEGATE=1)
    if os.getenv("DISABLE_TIMEGATE", "").lower() not in ("1", "true"):
        gate_ok = should_run(
            kind,
            tz_name,
            preview_day=get_env("PREVIEW_DAY", "Thursday"),
            preview_hour=int(get_env("PREVIEW_HOUR", 9, int)),
            recap_day=get_env("RECAP_DAY", "Wednesday"),
            recap_hour=int(get_env("RECAP_HOUR", 9, int)),
        )
        if not gate_ok:
            print(f"[{kind}] Outside run window for {tz_name}. Exiting cleanly.")
            return

    # Sleeper data
    week = resolve_week_for(kind)
    season = resolve_season()

    # Idempotency BEFORE the paid LLM call (this used to generate the report, then
    # throw it away — a wasted OpenAI call on every duplicate cron).
    already = output_path(output_dir, kind, week, season)
    if os.path.exists(already) and os.path.getsize(already) > 0:
        print(f"{kind.title()} already exists for {season} week {week} at {already}; skipping.")
        return

    league = get_league(league_id)
    users = get_users(league_id)
    rosters = get_rosters(league_id)
    players_index = get_players_index()
    cards = build_matchup_cards(league_id, week, players_index, users, rosters)

    # Prompts
    if kind == "preview":
        sys_msg, usr_msg, start_d, end_d = assemble_preview_prompt(league, week, cards, tz_name)
    else:
        sys_msg, usr_msg, start_d, end_d = assemble_recap_prompt(league, week, cards, tz_name)

    # LLM → JSON
    content = openai_chat(
        cfg["openai"]["model"],
        sys_msg,
        usr_msg,
        temperature=cfg["openai"]["temperature"],
        max_tokens=cfg["openai"]["max_tokens"],
        api_key=api_key,
    )
    data = parse_json_or_die(content)

    # Render Markdown
    if kind == "preview":
        md = md_preview_from_json(week, data, start_d, end_d)
    else:
        md = md_recap_from_json(week, data, start_d, end_d)

    # Write
    path = write_report(output_dir, kind, week, md, season)
    print(f"Wrote {path}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2 or sys.argv[1] not in ("preview", "recap"):
        print("Usage: python -m scripts.run_bot [preview|recap]")
        raise SystemExit(1)

    main(sys.argv[1])
