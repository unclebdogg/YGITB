# scripts/aggregate_stats.py
import json, os, glob, collections

DATA_ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_SUMMARY = os.path.join(DATA_ROOT, "summary.json")

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def build_user_map(users):
    m = {}
    for u in users:
        name = u.get("display_name") or u.get("metadata", {}).get("team_name") or u.get("user_id")
        m[u["user_id"]] = name
    return m

def build_roster_owner(rosters):
    m = {}
    for r in rosters:
        m[r["roster_id"]] = r["owner_id"]
    return m

def summarize_season(season_dir):
    users = load_json(os.path.join(season_dir, "users.json"))
    rosters = load_json(os.path.join(season_dir, "rosters.json"))
    user_map = build_user_map(users)
    roster_owner = build_roster_owner(rosters)

    head_to_head = collections.defaultdict(lambda: collections.Counter())
    team_points = collections.Counter()
    weekly_highs = []

    for mf in sorted(glob.glob(os.path.join(season_dir, "week_*_matchups.json"))):
        week = os.path.basename(mf).split("_")[1]
        matchups = load_json(mf)

        # group by matchup_id
        by_id = collections.defaultdict(list)
        for m in matchups:
            by_id[m["matchup_id"]].append(m)

        for mid, entries in by_id.items():
            if not entries:
                continue
            pts = {e["roster_id"]: e.get("points", 0) for e in entries}

            # add team points
            for rid, p in pts.items():
                owner_id = roster_owner.get(rid)
                team = user_map.get(owner_id, str(owner_id))
                team_points[team] += p

            # winner/runner-up for H2H-ish tally
            sorted_teams = sorted(pts.items(), key=lambda kv: kv[1], reverse=True)
            if len(sorted_teams) >= 2:
                (rid_w, _), (rid_l, _) = sorted_teams[0], sorted_teams[1]
                A = user_map.get(roster_owner.get(rid_w))
                B = user_map.get(roster_owner.get(rid_l))
                if A and B:
                    head_to_head[A][B] += 1

            # weekly high (top scorer that week)
            rid_top, p_top = sorted_teams[0]
            team_top = user_map.get(roster_owner.get(rid_top))
            if team_top is not None:
                weekly_highs.append({
                    "season": os.path.basename(season_dir),
                    "week": week,
                    "team": team_top,
                    "points": p_top,
                })

    return {
        "head_to_head": {k: dict(v) for k, v in head_to_head.items()},
        "team_points": dict(team_points),
        "weekly_highs": weekly_highs,
    }

def main():
    seasons = [d for d in glob.glob(os.path.join(DATA_ROOT, "*")) if os.path.isdir(d)]
    grand_h2h = collections.defaultdict(lambda: collections.Counter())
    grand_points = collections.Counter()
    grand_week_highs = []
    per_season = {}

    for sd in sorted(seasons):
        # require base files
        if not (os.path.exists(os.path.join(sd, "users.json")) and os.path.exists(os.path.join(sd, "rosters.json"))):
            continue
        s = summarize_season(sd)
        per_season[os.path.basename(sd)] = s

        # aggregate all-time
        for a, vs in s["head_to_head"].items():
            for b, cnt in vs.items():
                grand_h2h[a][b] += cnt
        for t, pts in s["team_points"].items():
            grand_points[t] += pts
        grand_week_highs.extend(s["weekly_highs"])

    out = {
        "per_season": per_season,
        "all_time": {
            "head_to_head": {k: dict(v) for k, v in grand_h2h.items()},
            "team_points": dict(grand_points),
            "weekly_highs": sorted(grand_week_highs, key=lambda x: (-x["points"])),
        }
    }
    os.makedirs(DATA_ROOT, exist_ok=True)
    with open(OUT_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()

