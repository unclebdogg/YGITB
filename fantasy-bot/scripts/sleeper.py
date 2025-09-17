import requests
from datetime import datetime
from .utils import get_env

BASE = "https://api.sleeper.app/v1"

def _get(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

def get_state():
    return _get(f"{BASE}/state/nfl")

def get_players_index():
    # Large payload; cache in Actions job only (fresh each run is ok)
    return _get(f"{BASE}/players/nfl")

def get_league(league_id):
    return _get(f"{BASE}/league/{league_id}")

def get_users(league_id):
    return _get(f"{BASE}/league/{league_id}/users")

def get_rosters(league_id):
    return _get(f"{BASE}/league/{league_id}/rosters")

def get_matchups(league_id, week):
    return _get(f"{BASE}/league/{league_id}/matchups/{week}")

def resolve_week(target: str = "current", season_hint=None):
    """
    Returns an int week. target in {"current","prev","next"}.
    Uses Sleeper state to figure week in-season, else you can pin season/weeks.
    """
    st = get_state()
    week = st.get("week")
    season = st.get("season")
    if season_hint:
        _ = season_hint  # not strictly used; Sleeper state is authoritative
    if week is None:
        # Offseason: default to 1 if preview; or last known week if recap.
        week = 1
    if target == "prev":
        return max(1, int(week) - 1)
    if target == "next":
        return int(week) + 1
    return int(week)

def users_map(users):
    return {u["user_id"]: u for u in users}

def rosters_map(rosters):
    res = {}
    for r in rosters:
        res[r["roster_id"]] = r
    return res

def display_name(user_obj):
    return user_obj.get("display_name") or user_obj.get("username") or "Unknown"

def build_matchup_cards(league_id, week, players_index, users, rosters):
    """
    Returns list of matchup dicts:
    {
      'home_name': 'Bevan',
      'away_name': 'Raylene',
      'home_points': 123.4 (final or projected),
      'away_points': 110.2,
      'home_players': [{'name':..., 'team':..., 'pos':..., 'points':...}, ...],
      ...
    }
    """
    # Sleeper groups matchups by matchup_id with roster_ids
    mjs = get_matchups(league_id, week)
    u_map = users_map(users)
    r_map = rosters_map(rosters)

    # Group by matchup_id
    match_groups = {}
    for m in mjs:
        mid = m.get("matchup_id")
        if mid is None:
            # some leagues may not have matchup_id for all records
            continue
        match_groups.setdefault(mid, []).append(m)

    cards = []
    for mid, entries in match_groups.items():
        if len(entries) != 2:
            # Handle bye or odd leagues gracefully
            continue

        e1, e2 = entries
        r1 = r_map.get(e1["roster_id"])
        r2 = r_map.get(e2["roster_id"])

        # Find owners
        u1 = u_map.get(str(r1.get("owner_id"))) if r1 else None
        u2 = u_map.get(str(r2.get("owner_id"))) if r2 else None
        n1 = display_name(u1) if u1 else f"Roster {e1['roster_id']}"
        n2 = display_name(u2) if u2 else f"Roster {e2['roster_id']}"

        def player_blob(player_id, pts_dict):
            p = players_index.get(str(player_id)) or {}
            return {
                "player_id": str(player_id),
                "name": p.get("full_name") or p.get("first_name") or "Unknown",
                "team": p.get("team"),
                "pos": p.get("position"),
                "points": pts_dict.get(str(player_id)) if pts_dict else None
            }

        # Points: for live/recap we have 'points'; for preview/projections, 'projected_points'
        home_points = e1.get("points") or e1.get("projected_points")
        away_points = e2.get("points") or e2.get("projected_points")

        # Players list optional (helps prompt add colour)
        home_players = [player_blob(pid, e1.get("players_points", {})) for pid in (e1.get("players") or [])]
        away_players = [player_blob(pid, e2.get("players_points", {})) for pid in (e2.get("players") or [])]

        cards.append({
            "home_name": n1,
            "away_name": n2,
            "home_points": round(home_points, 2) if home_points is not None else None,
            "away_points": round(away_points, 2) if away_points is not None else None,
            "home_players": home_players,
            "away_players": away_players
        })

    return cards
