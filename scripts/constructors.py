#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Salt Shaker — Constructors Championship scorer
----------------------------------------------
Reads Sleeper exports from data/<SEASON>/ and produces:
  - data/<SEASON>/constructors_weekly.json
  - data/constructors_standings.json

Categories (weekly):
  - Best MNF Player
  - Top QB
  - Top RB
  - Top WR
  - Top TE
  - Top D/ST
  - Top K
  - Top Bench
  - Largest Winning Margin

Each category awards points to the winner(s) (ties split fully; i.e., all tied winners get full points).
You can adjust point values via env or the POINTS_CONFIG dict below.

Resilience:
  - Handles missing files/weeks gracefully
  - Robust winners_from() accepts dicts, 3-tuples, or 2-tuples
  - Never crashes on empty buckets

Author: Jakebot
"""

import json
import os
from pathlib import Path
from collections import defaultdict

# ---------- Config ----------
SEASON = os.getenv("SEASON", "2025")

# Per-category points (can be overridden by env; else defaults below)
POINTS_CONFIG = {
    "mnf_best_player": int(os.getenv("PTS_MNF", "1")),
    "top_qb":          int(os.getenv("PTS_QB", "1")),
    "top_rb":          int(os.getenv("PTS_RB", "1")),
    "top_wr":          int(os.getenv("PTS_WR", "1")),
    "top_te":          int(os.getenv("PTS_TE", "1")),
    "top_dst":         int(os.getenv("PTS_DST", "1")),
    "top_k":           int(os.getenv("PTS_K", "1")),
    "top_bench":       int(os.getenv("PTS_BENCH", "1")),
    "largest_diff":    int(os.getenv("PTS_DIFF", "1")),
}

DATA_ROOT = Path("data")
SEASON_DIR = DATA_ROOT / SEASON
PLAYERS_INDEX_PATH = DATA_ROOT / "players_nfl.json"  # optional (only used for team codes if needed)
MNF_PATH = SEASON_DIR / "mnf_schedule.json"

# ----------------------------

def load_json(p: Path, default=None):
    if not p.exists():
        return {} if default is None else default
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def list_week_files(season_dir: Path):
    return sorted(season_dir.glob("week_*_matchups.json"))

def week_from_name(p: Path) -> int:
    # "week_01_matchups.json" -> 1
    stem = p.stem  # week_01_matchups
    parts = stem.split("_")
    for tok in parts:
        if tok.isdigit():
            return int(tok)
    return 0

def build_user_maps(season_dir: Path):
    users = load_json(season_dir / "users.json", default=[])
    rosters = load_json(season_dir / "rosters.json", default=[])
    # user_id -> display_name (fallback to metadata.team_name or user_id)
    users_map = {}
    for u in users:
        disp = u.get("display_name") or (u.get("metadata") or {}).get("team_name") or u.get("user_id")
        users_map[u["user_id"]] = disp
    # roster_id -> owner_id -> display_name
    roster_to_owner = {r["roster_id"]: r["owner_id"] for r in rosters}
    return users_map, roster_to_owner

def winners_from(bucket, users_map=None):
    """
    Accept entries shaped as:
      - dicts:    {"user_id":..., "display_name":..., "points":...}
      - 3-tuples: (user_id, display_name, points)
      - 2-tuples: (user_id, points)  -> display_name inferred from users_map
    Returns: [{"user_id","display_name","points"}, ...] (ties allowed)
    """
    users_map = users_map or {}
    entries = []

    for item in bucket or []:
        uid = disp = None
        pts = 0.0

        if isinstance(item, dict):
            uid  = item.get("user_id")
            disp = item.get("display_name") or users_map.get(uid, uid)
            pts  = float(item.get("points") or 0)
        elif isinstance(item, (list, tuple)):
            if len(item) == 3:
                uid, disp, pts = item
                disp = disp or users_map.get(uid, uid)
                pts = float(pts or 0)
            elif len(item) == 2:
                uid, pts = item
                disp = users_map.get(uid, uid)
                pts = float(pts or 0)
            else:
                continue
        else:
            continue

        if uid is None:
            continue
        entries.append((uid, disp, pts))

    if not entries:
        return []

    max_pts = max(p for _, _, p in entries)
    winners = [
        {"user_id": uid, "display_name": disp, "points": round(p, 2)}
        for uid, disp, p in entries
        if p == max_pts
    ]
    return winners

def add_points(standings, winners, category_key):
    pts_award = POINTS_CONFIG.get(category_key, 0)
    for w in winners:
        uid = w["user_id"]
        standings[uid] += pts_award

def is_defense_id(pid: str) -> bool:
    # Starters can include defense as a team code like "PHI", "NYJ", etc. Sleeper uses alpha for D/ST.
    return isinstance(pid, str) and pid.isalpha() and 2 <= len(pid) <= 3

def compute_week_constructors(season_dir: Path):
    """
    For each available week file, compute all categories and return:
    weekly_points_by_user[week] = {user_id: total_points_this_week}
    weekly_winners[week] = {category: [winner dicts], users: {user_id: display_name}}
    """
    users_map, roster_to_owner = build_user_maps(season_dir)
    mnf_schedule = load_json(MNF_PATH, default={})  # {"1": ["MIN","CHI"], ...}
    weekly_points = {}
    weekly_winners = {}

    week_files = list_week_files(season_dir)
    if not week_files:
        return weekly_points, weekly_winners

    for wf in week_files:
        wk = week_from_name(wf)
        matchups = load_json(wf, default=[])
        if not matchups:
            continue

        # Build per-roster aggregates
        # For each roster_id: starters list, players_points dict, total points, matchup_id
        by_roster = {}
        by_matchup = defaultdict(list)  # matchup_id -> list[(roster_id, points)]
        for m in matchups:
            rid = m.get("roster_id")
            if rid is None:
                continue
            starters = m.get("starters", []) or []
            players_points = m.get("players_points", {}) or {}
            points = float(m.get("points") or 0.0)
            mid = m.get("matchup_id")
            by_roster[rid] = {
                "starters": starters,
                "players_points": players_points,
                "points": points,
                "matchup_id": mid
            }
            if mid is not None:
                by_matchup[mid].append((rid, points))

        # ---------------------
        # Build buckets by category
        # ---------------------

        # Helpers to attribute (user_id -> display_name) from roster_id
        def owner_uid(rid):
            return roster_to_owner.get(rid)

        def owner_disp(rid):
            uid = owner_uid(rid)
            return users_map.get(uid, uid)

        # Position resolution for starters:
        # We don't have positions on IDs here, so we infer by typical Sleeper usage:
        # - K: player ids that map to K in players_points? (We only have points, not position)
        # Instead, we use a heuristic:
        #   For D/ST: alpha team codes in starters (PHI, NYJ, etc.)
        #   For K: Kicker IDs are numeric and appear in starters but not in common offensive positions.
        # Realistically, the most reliable way is to use the "players" index to map id->position.
        players_index = load_json(PLAYERS_INDEX_PATH, default={})

        def pid_pos(pid):
            # team defense
            if is_defense_id(pid):
                return "DEF"
            rec = players_index.get(str(pid))
            if not rec:
                return None
            return rec.get("position")

        # --- Top position categories (starters only) ---
        top_qb, top_rb, top_wr, top_te, top_k, top_dst = [], [], [], [], [], []
        # --- Top bench category ---
        top_bench = []
        # --- Best MNF Player (starters only) ---
        mnf_bucket = []
        mnf_teams = set(mnf_schedule.get(str(wk), []))

        # Iterate rosters to populate buckets
        for rid, info in by_roster.items():
            uid = owner_uid(rid)
            disp = owner_disp(rid)
            starters = info["starters"]
            pp = info["players_points"]

            # Starters by POS
            for pid in starters:
                pts = float(pp.get(str(pid), 0.0))
                pos = pid_pos(pid)
                # D/ST
                if is_defense_id(pid) or pos == "DEF" or pos == "D/ST":
                    top_dst.append((uid, disp, pts))
                    # MNF D/ST if in MNF teams
                    if pid in mnf_teams:
                        mnf_bucket.append((uid, disp, pts))
                    continue

                if pos == "QB":
                    top_qb.append((uid, disp, pts))
                elif pos == "RB":
                    top_rb.append((uid, disp, pts))
                elif pos == "WR":
                    top_wr.append((uid, disp, pts))
                elif pos == "TE":
                    top_te.append((uid, disp, pts))
                elif pos == "K":
                    top_k.append((uid, disp, pts))
                else:
                    # If we can’t resolve position (missing index), ignore for top-pos buckets
                    pass

                # MNF best player: any starter whose real NFL team is in the MNF list
                # We can attempt to resolve NFL team via players_index
                rec = players_index.get(str(pid))
                nfl_team = (rec or {}).get("team")
                if nfl_team and nfl_team in mnf_teams:
                    mnf_bucket.append((uid, disp, pts))
                # Also if team code starter equals an MNF defense (handled above)

            # Bench: any player in players list that is NOT in starters
            all_players = set(info["players_points"].keys())  # all IDs seen for that roster this week
            starter_ids = set(str(x) for x in starters)
            bench_ids = [pid for pid in all_players if pid not in starter_ids]
            for bpid in bench_ids:
                bpts = float(pp.get(str(bpid), 0.0))
                top_bench.append((uid, disp, bpts))

        # Largest Winning Margin (from matchup totals)
        largest_diff = []
        for mid, pairs in by_matchup.items():
            if len(pairs) < 2:
                continue
            # pick winner & diff
            pairs_sorted = sorted(pairs, key=lambda t: float(t[1]), reverse=True)
            (winner_rid, winner_pts), (_, loser_pts) = pairs_sorted[0], pairs_sorted[1]
            diff = float(winner_pts) - float(loser_pts)
            largest_diff.append((owner_uid(winner_rid), owner_disp(winner_rid), diff))

        # Winners per category (robust to empty buckets)
        winners = {
            "mnf_best_player": winners_from(mnf_bucket, users_map),
            "top_qb":          winners_from(top_qb, users_map),
            "top_rb":          winners_from(top_rb, users_map),
            "top_wr":          winners_from(top_wr, users_map),
            "top_te":          winners_from(top_te, users_map),
            "top_dst":         winners_from(top_dst, users_map),
            "top_k":           winners_from(top_k, users_map),
            "top_bench":       winners_from(top_bench, users_map),
            "largest_diff":    winners_from(largest_diff, users_map),
        }

        # Accumulate weekly constructors points by user
        week_totals = defaultdict(int)
        for cat_key, wlist in winners.items():
            if not wlist:
                continue
            pts_award = POINTS_CONFIG.get(cat_key, 0)
            for w in wlist:
                week_totals[w["user_id"]] += pts_award

        # Persist weekly winners & points (plus user display map for that week)
        weekly_winners[str(wk)] = {
            "users": users_map,
            "winners": winners,
            "weekly_points": dict(sorted(week_totals.items(), key=lambda kv: kv[1], reverse=True)),
        }
        weekly_points[str(wk)] = dict(week_totals)

    return weekly_points, weekly_winners

def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def main():
    if not SEASON_DIR.exists():
        print(f"[constructors] Season dir not found: {SEASON_DIR}")
        # Still write empty outputs so workflow doesn't fail
        write_json(DATA_ROOT / "constructors_standings.json", {
            "users": {},
            "standings_all_time": {},
            "points_config": POINTS_CONFIG,
        })
        return

    # Compute weekly winners/points per week
    weekly_points, weekly_winners = compute_week_constructors(SEASON_DIR)

    # Write per-season weekly winners file
    weekly_out = SEASON_DIR / "constructors_weekly.json"
    write_json(weekly_out, weekly_winners)

    # Build cumulative standings across available weeks (this season only by default)
    cumulative = defaultdict(int)
    all_users = {}
    for wk, payload in weekly_winners.items():
        users_map = payload.get("users", {})
        all_users.update(users_map)
        wk_points = payload.get("weekly_points", {})
        for uid, pts in wk_points.items():
            cumulative[uid] += int(pts)

    standings_out = {
        "users": all_users,
        "standings_all_time": dict(sorted(cumulative.items(), key=lambda kv: kv[1], reverse=True)),
        "points_config": POINTS_CONFIG,
        "season": SEASON,
    }
    write_json(DATA_ROOT / "constructors_standings.json", standings_out)

    print(f"[constructors] Wrote: {weekly_out}")
    print(f"[constructors] Wrote: {DATA_ROOT / 'constructors_standings.json'}")

if __name__ == "__main__":
    main()
