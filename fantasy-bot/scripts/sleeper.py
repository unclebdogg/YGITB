import requests
from typing import Any, Dict, List, Optional

BASE = "https://api.sleeper.app/v1"


def _get(url: str) -> Any:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def get_state() -> Dict[str, Any]:
    return _get(f"{BASE}/state/nfl")


def get_players_index() -> Dict[str, Any]:
    # Big dict keyed by player_id -> { full_name, position, team, ... }
    return _get(f"{BASE}/players/nfl")


def get_league(league_id: str) -> Dict[str, Any]:
    return _get(f"{BASE}/league/{league_id}")


def get_users(league_id: str) -> List[Dict[str, Any]]:
    return _get(f"{BASE}/league/{league_id}/users")


def get_rosters(league_id: str) -> List[Dict[str, Any]]:
    return _get(f"{BASE}/league/{league_id}/rosters")


def get_matchups(league_id: str, week: int) -> List[Dict[str, Any]]:
    return _get(f"{BASE}/league/{league_id}/matchups/{week}")


def users_map(users: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(u.get("user_id")): u for u in users}


def rosters_map(rosters: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    res: Dict[int, Dict[str, Any]] = {}
    for r in rosters:
        res[int(r.get("roster_id"))] = r
    return res


def _record(roster: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    st = (roster or {}).get("settings") or {}
    w, l, t = int(st.get("wins", 0)), int(st.get("losses", 0)), int(st.get("ties", 0))
    text = f"{w}-{l}" if t == 0 else f"{w}-{l}-{t}"
    return {"wins": w, "losses": l, "ties": t, "text": text}


def _team_display(roster: Optional[Dict[str, Any]], user: Optional[Dict[str, Any]]) -> str:
    if roster:
        meta = roster.get("metadata") or {}
        team_name = meta.get("team_name")
        if team_name and str(team_name).strip():
            return str(team_name).strip()
    if user:
        dn = user.get("display_name")
        if dn and str(dn).strip():
            return str(dn).strip()
        un = user.get("username")
        if un and str(un).strip():
            return str(un).strip()
    if roster and roster.get("roster_id") is not None:
        return f"Roster {roster.get('roster_id')}"
    return "Unknown Team"


def _points_or_projection(entry: Dict[str, Any]) -> Optional[float]:
    val = entry.get("points")
    if val is None:
        val = entry.get("projected_points")
    if val is None:
        return None
    try:
        return round(float(val), 2)
    except Exception:
        return None


def _top_starters(entry: Dict[str, Any], players_index: Dict[str, Any], top_n: int = 2):
    """
    Return top N starters by fantasy points with (name,pos,nfl_team,points).
    Uses entry['starters'] and entry['players_points'] from Sleeper matchups.
    """
    starters = entry.get("starters") or []  # list of player_ids in starting slots
    ppoints = entry.get("players_points") or {}  # player_id -> pts
    scored = []
    for pid in starters:
        pts = ppoints.get(pid)
        if pts is None:
            continue
        info = players_index.get(pid) or {}
        name = info.get("full_name") or info.get("first_name") or pid
        pos = info.get("position") or "FLEX"
        nfl = info.get("team") or "FA"
        try:
            scored.append({
                "player": str(name),
                "pos": str(pos),
                "nfl_team": str(nfl),
                "points": round(float(pts), 2)
            })
        except Exception:
            continue
    scored.sort(key=lambda x: x["points"], reverse=True)
    return scored[:top_n]


def build_matchup_cards(
    league_id: str,
    week: int,
    players_index: Dict[str, Any],
    users: List[Dict[str, Any]],
    rosters: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    matchups = get_matchups(league_id, week)
    u_map = users_map(users)
    r_map = rosters_map(rosters)

    groups: Dict[int, List[Dict[str, Any]]] = {}
    for m in matchups:
        mid = m.get("matchup_id")
        if mid is None:
            continue
        groups.setdefault(int(mid), []).append(m)

    cards: List[Dict[str, Any]] = []
    for mid, entries in groups.items():
        if len(entries) != 2:
            continue

        e1, e2 = entries[0], entries[1]
        r1 = r_map.get(int(e1.get("roster_id")))
        r2 = r_map.get(int(e2.get("roster_id")))
        u1 = u_map.get(str((r1 or {}).get("owner_id")))
        u2 = u_map.get(str((r2 or {}).get("owner_id")))

        cards.append({
            "home_name": _team_display(r1, u1),
            "away_name": _team_display(r2, u2),
            "home_points": _points_or_projection(e1),
            "away_points": _points_or_projection(e2),
            "home_record": _record(r1),
            "away_record": _record(r2),
            "home_stars": _top_starters(e1, players_index, top_n=2),
            "away_stars": _top_starters(e2, players_index, top_n=2),
        })

    return cards
