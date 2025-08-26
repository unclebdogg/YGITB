# scripts/sleeper_history.py
import json, os, time, urllib.request

# ---------- CONFIG ----------
LEAGUE_ID = "1260643183704932352"   # e.g. "1260643183704932352"
SEASON_MAX_WEEKS = 17               # adjust to your league length
OUTDIR = os.path.join(os.path.dirname(__file__), "..", "data")
SLEEP_SEC = 0.25                    # be polite to the API
# ----------------------------

def get(url: str):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read().decode())

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)
    return path

def crawl_league(league_id: str):
    """Follow previous_league_id to gather all seasons for this league family."""
    ids = []
    cur = league_id
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        league = get(f"https://api.sleeper.app/v1/league/{cur}")
        ids.append(cur)
        cur = league.get("previous_league_id")
        time.sleep(SLEEP_SEC)
    return ids  # newest -> oldest

def write_json(path, obj):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def main():
    leagues = crawl_league(LEAGUE_ID)  # newest -> oldest
    for lid in leagues:
        league = get(f"https://api.sleeper.app/v1/league/1260643183704932352")
        season = league.get("season")
        season_dir = ensure_dir(os.path.join(OUTDIR, season))

        # Base metadata
        write_json(os.path.join(season_dir, "league.json"), league)
        users = get(f"https://api.sleeper.app/v1/league/1260643183704932352/users")
        write_json(os.path.join(season_dir, "users.json"), users)
        rosters = get(f"https://api.sleeper.app/v1/league/1260643183704932352/rosters")
        write_json(os.path.join(season_dir, "rosters.json"), rosters)
        time.sleep(SLEEP_SEC)

        # Week-by-week matchups
        for wk in range(1, SEASON_MAX_WEEKS + 1):
            try:
                matchups = get(f"https://api.sleeper.app/v1/league/1260643183704932352/matchups/{wk}")
                write_json(os.path.join(season_dir, f"week_{wk:02d}_matchups.json"), matchups)
                time.sleep(SLEEP_SEC)
            except Exception:
                # Some seasons/weeks may not exist; skip quietly
                pass

if __name__ == "__main__":
    main()


