# scripts/constructors.py
import json, os, glob, collections

DATA_ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_STANDINGS = os.path.join(DATA_ROOT, "constructors_standings.json")

# Points per category (default 1). Adjust if you want a different scoring system.
POINTS = {
    "mnf_best_player": 1,
    "top_qb": 1,
    "top_rb": 1,
    "top_wr": 1,
    "top_te": 1,
    "top_dst": 1,
    "top_k": 1,
    "top_bench": 1,
    "largest_diff": 1,
}

# Position mapping helper (from Sleeper positions)
POS_QB = {"QB"}
POS_RB = {"RB"}
POS_WR = {"WR"}
POS_TE = {"TE"}
POS_K  = {"K"}
POS_DST = {"DEF", "DST"}  # we treat team defenses via D/ST slot

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def safe_get(obj, key, default=None):
    v = obj.get(key)
    return v if v is not None else default

def build_user_map(users):
    # user_id -> display name (fallback to team_name or id)
    m = {}
    for u in users:
        name = u.get("display_name") or u.get("metadata", {}).get("team_name") or u.get("user_id")
        m[u["user_id"]] = name
    return m

def build_roster_owner_map(rosters):
    # roster_id -> owner_id
    return {r["roster_id"]: r["owner_id"] for r in rosters}

def load_players_index(season_dir):
    """
    We try to resolve player positions and teams from a players index if present.
    Expect a file at data/players_nfl.json (optional).
    If missing, we’ll classify K and D/ST by slot; others remain unknown but still count for 'top bench' and MNF by team schedule.
    """
    fallback = os.path.join(DATA_ROOT, "players_nfl.json")
    if os.path.exists(fallback):
        try:
            return load_json(fallback)
        except Exception:
            pass
    return {}

def positions_for(player_id, players_idx):
    rec = players_idx.get(str(player_id))
    if not rec:
        return set()
    # Sleeper often has "position" plus "fantasy_positions"
    fps = rec.get("fantasy_positions") or []
    pos = rec.get("position")
    out = set(fps)
    if pos:
        out.add(pos)
    return {p for p in out if isinstance(p, str)}

def nfl_team_for(player_id, players_idx, starter_slot_maybe=None):
    # Used for MNF team filtering & DST lookup
    if starter_slot_maybe and isinstance(starter_slot_maybe, str) and starter_slot_maybe.isalpha() and len(starter_slot_maybe) in (2,3):
        # team D/ST recorded as team code in starters (e.g. "DET","DEN")
        return starter_slot_maybe
    rec = players_idx.get(str(player_id))
    if not rec:
        return None
    return rec.get("team")  # e.g. "KC","NYJ","LAR"

def find_week_files(season_dir):
    return sorted(glob.glob(os.path.join(season_dir, "week_*_matchups.json")))

def load_mnf_schedule(season_dir):
    """
    Optional file: data/{season}/mnf_schedule.json
    Example:
    {
      "1": ["PHI","GB"],  // Week 1 MNF teams by NFL code
      "2": ["DAL","NYG"]
    }
    """
    path = os.path.join(season_dir, "mnf_schedule.json")
    if os.path.exists(path):
        try:
            return load_json(path)
        except Exception:
            return {}
    return {}

def compute_week_constructors(season_dir):
    users = load_json(os.path.join(season_dir, "users.json"))
    rosters = load_json(os.path.join(season_dir, "rosters.json"))
    user_map = build_user_map(users)
    roster_owner = build_roster_owner_map(rosters)
    players_idx = load_players_index(season_dir)
    mnf_sched = load_mnf_schedule(season_dir)

    weekly_winners = {}  # week -> {category: [team_names]}
    weekly_points  = {}  # week -> {team_name: total_points_that_week}

    for mf in find_week_files(season_dir):
        week = os.path.basename(mf).split("_")[1]  # "01"
        matchups = load_json(mf)

        # buckets
        top_by_pos = {"QB": [], "RB": [], "WR": [], "TE": [], "DST": [], "K": []}  # list of tuples (team_name, player_id, points)
        top_bench  = []  # (team_name, player_id, points)
        team_points = collections.defaultdict(float)  # team -> points
        largest_diff = []  # (team_name, margin)

        # group by matchup_id to find margins
        by_id = collections.defaultdict(list)
        for m in matchups:
            by_id[m["matchup_id"]].append(m)

        # Traverse every lineup entry to populate buckets
        for m in matchups:
            rid = m["roster_id"]
            owner = roster_owner.get(rid)
            team_name = user_map.get(owner, str(owner))
            points_map = m.get("players_points", {}) or {}
            starters = m.get("starters", []) or []
            all_players = m.get("players", []) or []

            # record team total (for margin)
            team_points[team_name] += m.get("points", 0.0)

            # starters: figure out positions/DST/K via players_idx and slot clues
            for pid, ppts in points_map.items():
                # identify if this id was starter or bench
                is_starter = pid in starters
                # derive position
                pos_set = positions_for(pid, players_idx)
                # detect D/ST from starters list slot token (team code) when applicable
                maybe_dst_team = None
                for s in starters:
                    if s.isalpha() and len(s) in (2,3):
                        maybe_dst_team = s
                # crude D/ST check: if pid not resolvable but slot is team code, we’ll capture from the slot later

                # Drop into position buckets only if this player actually exists in roster players list
                # (Sleeper includes all on roster, but we'll trust players_points)
                # Top bench logic
                if not is_starter:
                    top_bench.append((team_name, pid, ppts))

                # Position buckets (if we know the position)
                if pos_set & POS_QB:
                    top_by_pos["QB"].append((team_name, pid, ppts))
                if pos_set & POS_RB:
                    top_by_pos["RB"].append((team_name, pid, ppts))
                if pos_set & POS_WR:
                    top_by_pos["WR"].append((team_name, pid, ppts))
                if pos_set & POS_TE:
                    top_by_pos["TE"].append((team_name, pid, ppts))
                if pos_set & POS_K:
                    top_by_pos["K"].append((team_name, pid, ppts))

            # D/ST from starters list: starters includes e.g. "DET"
            for s in starters:
                if isinstance(s, str) and s.isalpha() and len(s) in (2,3):
                    # find a synthetic key for points: Sleeper puts team D/ST points under key equal to team code in players_points
                    ppts = points_map.get(s, 0.0)
                    top_by_pos["DST"].append((team_name, f"{s}_DST", ppts))

        # Largest margin per matchup
        for mid, entries in by_id.items():
            if not entries:
                continue
            pts = [(user_map.get(roster_owner.get(e["roster_id"])), e.get("points", 0.0)) for e in entries]
            if len(pts) >= 2:
                sorted_ = sorted(pts, key=lambda x: x[1], reverse=True)
                margin = sorted_[0][1] - sorted_[1][1]
                largest_diff.append((sorted_[0][0], margin))

        # MNF best player
        mnf_winners = []
        if week.lstrip("0") in mnf_sched:
            mnf_teams = set(mnf_sched[week.lstrip("0")])  # ["PHI","GB"]
            # scan all players across matchups, pick highest among those whose NFL team in mnf_teams
            best_mnf = None  # (team_name, pid, ppts)
            for m in matchups:
                rid = m["roster_id"]
                owner = roster_owner.get(rid)
                team_name = user_map.get(owner, str(owner))
                starters = m.get("starters", []) or []
                points_map = m.get("players_points", {}) or {}

                # include starters & bench
                involved_ids = set(points_map.keys())
                # plus D/ST via slot code
                for s in starters:
                    if isinstance(s, str) and s.isalpha() and len(s) in (2,3):
                        # D/ST points keyed by team code
                        if s in points_map:
                            # treat as a "player" with team code s
                            pid = f"{s}_DST"
                            ppts = points_map[s]
                            # D/ST "team" is s
                            nfl_team = s
                            if nfl_team in mnf_teams:
                                if (best_mnf is None) or (ppts > best_mnf[2]):
                                    best_mnf = (team_name, pid, ppts)
                # real player ids
                for pid, ppts in points_map.items():
                    nfl_team = nfl_team_for(pid, players_idx)
                    if nfl_team in mnf_teams:
                        if (best_mnf is None) or (ppts > best_mnf[2]):
                            best_mnf = (team_name, pid, ppts)

            if best_mnf:
                mnf_winners = [best_mnf[0]]

        # Helper to choose winners per bucket
        def winners_from(bucket):
            if not bucket:
                return []
            # bucket is list[(team_name, pid, pts)]
            max_pts = max(p for _, _, p in bucket)
            return sorted({team for (team, _, p) in bucket if p == max_pts})

        winners = {
            "mnf_best_player": mnf_winners,                               # may be []
            "top_qb": winners_from(top_by_pos["QB"]),
            "top_rb": winners_from(top_by_pos["RB"]),
            "top_wr": winners_from(top_by_pos["WR"]),
            "top_te": winners_from(top_by_pos["TE"]),
            "top_dst": winners_from(top_by_pos["DST"]),
            "top_k": winners_from(top_by_pos["K"]),
            "top_bench": winners_from(top_bench),
            "largest_diff": winners_from(largest_diff),
        }
        weekly_winners[week] = winners

        # Assign points
        tally = collections.Counter()
        for cat, teams in winners.items():
            for t in teams:
                tally[t] += POINTS.get(cat, 1)
        weekly_points[week] = dict(tally)

        # Persist weekly details in season dir
        with open(os.path.join(season_dir, "constructors_weekly.json"), "w", encoding="utf-8") as f:
            json.dump(weekly_winners, f, indent=2, ensure_ascii=False)

    return weekly_points

def main():
    # Build standings across all seasons you have locally
    standings_all = collections.Counter()
    per_season_points = {}

    for season_dir in sorted([d for d in glob.glob(os.path.join(DATA_ROOT, "*")) if os.path.isdir(d)]):
        # require base files
        if not (os.path.exists(os.path.join(season_dir, "users.json")) and os.path.exists(os.path.join(season_dir, "rosters.json"))):
            continue
        weekly_points = compute_week_constructors(season_dir)
        per_season_points[os.path.basename(season_dir)] = weekly_points
        # cumulate
        for wk, pts_map in weekly_points.items():
            for team, pts in pts_map.items():
                standings_all[team] += pts

    out = {
        "per_season_weekly_points": per_season_points,
        "standings_all_time": dict(standings_all),
        "points_config": POINTS,
        "notes": "Ties award full points to all tied teams. MNF requires data/{season}/mnf_schedule.json."
    }
    with open(OUT_STANDINGS, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()

