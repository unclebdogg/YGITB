"""Build data/<SEASON>/mnf_schedule.json — the teams playing on Monday night each week.

The Salt Shaker's "Best MNF Player" category reads this file. Without it, that point
goes unawarded every week (2026 had no file until this script was written).

Source: ESPN's public scoreboard API. A game counts as Monday night if its kickoff
falls on a Monday in US Eastern time — the UTC timestamp is Tuesday for most of them.

Run: SEASON=2026 python3 scripts/fetch_mnf_schedule.py
"""
import json, os, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEASON = os.getenv("SEASON", "2026")
WEEKS = int(os.getenv("WEEKS", "18"))
OUT = Path("data") / SEASON / "mnf_schedule.json"
API = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={s}&seasontype=2&week={w}"

def eastern(dt):
    # US Eastern is UTC-4 through the NFL regular season (DST ends early Nov);
    # UTC-5 after. Both keep a Monday-night kickoff on Monday, so -5 is safe.
    return dt.astimezone(timezone.utc) - timedelta(hours=5)

def main():
    sched = {}
    for wk in range(1, WEEKS + 1):
        with urllib.request.urlopen(API.format(s=SEASON, w=wk), timeout=30) as r:
            data = json.loads(r.read().decode())
        teams = []
        for ev in data.get("events", []):
            kickoff = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            if eastern(kickoff).weekday() != 0:  # 0 = Monday
                continue
            for c in ev.get("competitions", [{}])[0].get("competitors", []):
                abbr = c.get("team", {}).get("abbreviation")
                if abbr:
                    teams.append(abbr)
        if teams:
            sched[str(wk)] = teams
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(sched, indent=2) + "\n", encoding="utf-8")
    print(f"[mnf] wrote {OUT} — {len(sched)} weeks, {sum(len(v) for v in sched.values())} teams")

if __name__ == "__main__":
    main()
