import os
import json
from datetime import datetime, timedelta
import pytz
import requests

from .utils import load_config, get_env, read_text, render_template
from .timegate import should_run
from .sleeper import (
    get_league, get_users, get_rosters, get_players_index,
    build_matchup_cards, resolve_week
)
from .writer import to_markdown, write_report

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

def openai_chat(model, system, user, temperature=0.6, max_tokens=2000):
    headers = {
        "Authorization": f"Bearer {get_env('OPENAI_API_KEY')}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role":"system", "content": system},
            {"role":"user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = requests.post(OPENAI_CHAT_URL, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

def local_week_window(tz_name: str, week: int):
    # purely presentational; rough Thur–Tue window around NFL week for display
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=6, hours=23, minutes=59)
    return start.strftime("%d %b"), end.strftime("%d %b")

def assemble_preview_prompt(cfg, league, week, cards, tz_name):
    sys = read_text("prompts/system_preview.txt")
    usr_tpl = read_text("prompts/user_preview.txt")

    start_date, end_date = local_week_window(tz_name, week)
    teams_overview = ", ".join(sorted({c['home_name'] for c in cards} | {c['away_name'] for c in cards}))

    lines = []
    for c in cards:
        lines.append(f"- {c['home_name']} vs {c['away_name']} — proj {c['home_points']}–{c['away_points']}")
    matchups_block = "\n".join(lines)

    usr = render_template(
        usr_tpl,
        week=str(week),
        start_date=start_date,
        end_date=end_date,
        league_name=league.get("name","Your League"),
        teams_overview=teams_overview,
        matchups_block=matchups_block
    )
    return sys, usr, start_date, end_date

def assemble_recap_prompt(cfg, league, week, cards, tz_name):
    sys = read_text("prompts/system_recap.txt")
    usr_tpl = read_text("prompts/user_recap.txt")

    start_date, end_date = local_week_window(tz_name, week)

    res_lines = []
    for c in cards:
        if c["home_points"] is None or c["away_points"] is None:
            continue
        res_lines.append(f"- {c['home_name']} {c['home_points']} def. {c['away_name']} {c['away_points']}")

    leaders_block = "Top outputs by position not computed here (can extend later)."

    usr = render_template(
        usr_tpl,
        week=str(week),
        start_date=start_date,
        end_date=end_date,
        league_name=league.get("name","Your League"),
        results_block="\n".join(res_lines) or "(No finals found)",
        leaders_block=leaders_block
    )
    return sys, usr, start_date, end_date

def main(kind: str):
    cfg = load_config()
    tz_name = get_env("TIMEZONE", "Australia/Sydney")

    # Time gate so a simple UTC cron can run hourly
    if os.getenv("DISABLE_TIMEGATE","").lower() not in ("1","true"):
        if not should_run(kind, tz_name):
            print(f"[{kind}] Outside run window for {tz_name}. Exiting cleanly.")
            return

    league_id = get_env("SLEEPER_LEAGUE_ID")
    season_hint = get_env("NFL_SEASON", None)

    week = resolve_week("current", season_hint)
    if kind == "recap":
        week = max(1, week - 1)

    league = get_league(league_id)
    users = get_users(league_id)
    rosters = get_rosters(league_id)
    players_index = get_players_index()

    cards = build_matchup_cards(league_id, week, players_index, users, rosters)

    if kind == "preview":
        sys, usr, start_d, end_d = assemble_preview_prompt(cfg, league, week, cards, tz_name)
    else:
        sys, usr, start_d, end_d = assemble_recap_prompt(cfg, league, week, cards, tz_name)

    content = openai_chat(
        cfg["openai"]["model"], sys, usr,
        temperature=cfg["openai"]["temperature"],
        max_tokens=cfg["openai"]["max_tokens"],
    )

    headline, body = split_headline(content)
    md = to_markdown(kind, week, headline, body, start_d, end_d)

    out_dir = get_env("OUTPUT_DIR", "reports")
    fpath = write_report(out_dir, kind, week, md)
    print(f"Wrote {fpath}")

def split_headline(text: str):
    # Expect "## Headline" already? Prompts ask model to supply a headline string.
    # Try first line as headline if short, else fallback.
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    if not lines:
        return "League Update", text
    first = lines[0]
    if len(first) <= 80 and not first.lower().startswith(("1)","- ")):
        body = "\n".join(lines[1:]).strip()
        return first.lstrip("# ").strip(), body
    return "League Update", text

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2 or sys.argv[1] not in ("preview","recap"):
        print("Usage: python -m scripts.run_bot [preview|recap]")
        sys.exit(1)
    main(sys.argv[1])
