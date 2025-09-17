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
    start_date, end_date = local_week_window(tz_name_
