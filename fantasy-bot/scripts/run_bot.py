import os
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
from .writer import to_markdown, write_report, output_path

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


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
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = requests.post(OPENAI_CHAT_URL, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def local_week_window(tz_name: str):
    """Purely presentational week window label for the MD header."""
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=6, hours=23, minutes=59)
    return start.strftime("%d %b"), end.strftime("%d %b")


def resolve_week_for(kind: str) -> int:
    """Use Sleeper state to get current week; for recap use previous week."""
    st = get_state()
    week = st.get("week") or 1
    week = int(week)
    return week if kind == "preview" else max(1, week - 1)


def assemble_preview_prompt(league, week, cards, tz_name):
    sys = read_text("prompts/system_preview.txt")
    usr_tpl = read_text("prompts/user_preview.txt")
    start_date, end_date = local_week_window(tz_name)
    teams = sorted({c["home_name"] for c in cards} | {c["away_name"] for c in cards})
    match_lines = [
        f"- {c['home_name']} vs {c['away_name']} — proj {c['home_points']}–{c['away_points']}"
        for c in cards
    ]
    usr = render_template(
        usr_tpl,
        week=str(week),
        start_date=start_date,
        end_date=end_date,
        league_name=league.get("name", "Your League"),
        teams_overview=", ".join(teams),
        matchups_block="\n".join(match_lines),
    )
    return sys, usr, start_date, end_date


def assemble_recap_prompt(league, week, cards, tz_name):
    sys = read_text("prompts/system_recap.txt")
    usr_tpl = read_text("prompts/user_recap.txt")
    start_date, end_date = local_week_window(tz_name)
    results = []
    for c in cards:
        if c["home_points"] is None or c["away_points"] is None:
            continue
        results.append(
            f"- {c['home_name']} {c['home_points']} def. {c['away_name']} {c['away_points']}"
        )
    usr = render_template(
        usr_tpl,
        week=str(week),
        start_date=start_date,
        end_date=end_date,
        league_name=league.get("name", "Your League"),
        results_block="\n".join(results) or "(No finals found)",
        leaders_block="Top outputs by position not computed here (extend later).",
    )
    return sys, usr, start_date, end_date


def split_headline(text: str):
    """First non-empty line becomes the headline if short; else default."""
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    if not lines:
        return "League Update", text
    first = lines[0]
    if len(first) <= 80 and not first.lower().startswith(("1)", "- ")):
        return first.lstrip("# ").strip(), "\n".join(lines[1:]).strip()
    return "League Update", text


def main(kind: str):
    # Config & env
    cfg = load_config()
    tz_name = get_env("TIMEZONE", "Australia/Sydney")
    output_dir = get_env("OUTPUT_DIR", "reports")
    api_key = get_env("OPENAI_API_KEY")
    league_id = get_env("SLEEPER_LEAGUE_ID")

    if not league_id:
        raise SystemExit("Missing SLEEPER_LEAGUE_ID env.")

    # Optional time-gating (disabled in your cron workflows via DISABLE_TIMEGATE=1)
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

    # Data fetch
    week = resolve_week_for(kind)
    league = get_league(league_id)
    users = get_users(league_id)
    rosters = get_rosters(league_id)
    players_index = get_players_index()
    cards = build_matchup_cards(league_id, week, players_index, users, rosters)

    # Prompt assembly
    if kind == "preview":
        sys_msg, usr_msg, start_d, end_d = assemble_preview_prompt(league, week, cards, tz_name)
    else:
        sys_msg, usr_msg, start_d, end_d = assemble_recap_prompt(league, week, cards, tz_name)

    # LLM
    content = openai_chat(
        cfg["openai"]["model"],
        sys_msg,
        usr_msg,
        temperature=cfg["openai"]["temperature"],
        max_tokens=cfg["openai"]["max_tokens"],
        api_key=api_key,
    )
    headline, body = split_headline(content)
    md = to_markdown(kind, week, headline, body, start_d, end_d)

    # Idempotency: skip if file already exists (covers double UTC crons for DST)
    already = output_path(output_dir, kind, week)
    if os.path.exists(already) and os.path.getsize(already) > 0:
        print(f"{kind.title()} already exists for week {week} at {already}; skipping.")
        return

    # Write
    path = write_report(output_dir, kind, week, md)
    print(f"Wrote {path}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2 or sys.argv[1] not in ("preview", "recap"):
        print("Usage: python -m scripts.run_bot [preview|recap]")
        raise SystemExit(1)
    main(sys.argv[1])
