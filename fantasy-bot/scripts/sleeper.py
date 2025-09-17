import requests
from typing import Any, Dict, List, Optional

BASE = "https://api.sleeper.app/v1"


# ----------------------------
# HTTP helpers
# ----------------------------
def _get(url: str) -> Any:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


# ----------------------------
# Public API wrappers
# ----------------------------
def get_state() -> Dict[str, Any]:
    """Sleeper global NFL state (season, week, etc.)."""
    return _get(f"{BASE}/state/nfl")


def get_players_index() -> Dict[str, Any]:
    """Large dictionary of players keyed by player_id (string)."""
    return _get(f"{BASE}/players/nfl")


def get_league(league_id: str) -> Dict[str, Any]:
    return _get(f"{BASE}/league/{league_id}")


def get_users(league_id: str) -> List[Dict[str, Any]]:
    return _get(f"{BASE}/league/{league_id}/users")


def get_rosters(league_id: str) -> List[Dict[str, Any]]:
    return _get(f"{BASE}/league/{league_id}/rosters")


def get_matchups(league_id: str, week: int) -> List[Dict[str, Any]]:
    return _get(f"{BASE}/league/{league_id}/matchups/{week}")


# ----------------------------
# Local utilities
# ----------------------------
def users_map(users: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Map user_id (string) -> user obj."""
    return {str(u.get("user_id")): u for u in users}


def rosters_map(rosters: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Map roster_id (int) -> roster obj."""
    res: Dict[int, Dict[str, Any]] = {}
    for r in rosters:
        res[int(r.get("roster_id"))] = r
    return res


def _record(roster: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return record dict with wins/losses/ties and a short text field."""
    st = (roster or {}).get("settings") or {}
    w, l, t = int(st.get("wins", 0)), int(st.get("losses", 0)), int(st.get("ties", 0))
    text = f"{w}-{l}" if t == 0 else f"{w}-{l}-{t}"
    return {"wins": w, "losses": l, "ties": t, "text": text}


def _team_display(roster: Optional[Dict[str, Any]], user: Optional[Dict[str, Any]]) -> str:
    """
    Prefer roster metadata team_name (what you see in the app).
    Fallback to user's display_name/username, then 'Roster {id}'.
    """
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
    """
    For previews (before games), Sleeper often populates 'projected_points'.
    For recaps (after games), 'points' will be present.
    """
    val = entry.get("points")
    if val is None:
        val = entry.get("projected_points")
    if val is None:
        return None
    try:
        return round(float(val), 2)
    except Exception:
        return None


# ----------------------------
# Primary data shaper for write-ups
# ----------------------------
def build_matchup_cards(
    league_id: str,
    week: int,
    players_index: Dict[str, Any],  # kept for future enrichment (starters, teams, etc.)
    users: List[Dict[str, Any]],
    rosters: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Groups Sleeper matchups by matchup_id and returns a normalized list:

    [
      {
        "home_name": str,            # roster metadata team name if set, else user display
        "away_name": str,
        "home_points": float|None,   # final or projected
        "away_points": float|None,
        "home_record": {wins,losses,ties,text},
        "away_record": {wins,losses,ties,text},
        # (room to add starters, top players, etc.)
      },
      ...
    ]
    """
    matchups = get_matchups(league_id, week)
    u_map = users_map(users)
    r_map = rosters_map(rosters)

    # group entries by matchup_id
    groups: Dict[int, List[Dict[str, Any]]] = {}
    for m in matchups:
        mid = m.get("matchup_id")
        if mid is None:
            # some leagues/entries can be stray; skip
            continue
        groups.setdefault(int(mid), []).append(m)

    cards: List[Dict[str, Any]] = []
    for mid, entries in groups.items():
        # Expect exactly two entries per matchup; skip odd/byes gracefully
        if len(entries) != 2:
            continue

        e1, e2 = entries[0], entries[1]
        r1 = r_map.get(int(e1.get("roster_id")))
        r2 = r_map.get(int(e2.get("roster_id")))
        u1 = u_map.get(str((r1 or {}).get("owner_id")))
        u2 = u_map.get(str((r2 or {}).get("owner_id")))

        cards.append(
            {
                "home_name": _team_display(r1, u1),
                "away_name": _team_display(r2, u2),
                "home_points": _points_or_projection(e1),
                "away_points": _points_or_projection(e2),
                "home_record": _record(r1),
                "away_record": _record(r2),
            }
        )

    return cards
