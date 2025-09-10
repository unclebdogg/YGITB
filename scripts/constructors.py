#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Salt Shaker — Constructors Championship scorer (independent categories)
----------------------------------------------------------------------
- Each category is computed from the full data; NO removals across buckets.
- A player (and therefore the manager) can win multiple categories in a week,
  e.g., Top QB AND Best MNF Player.

Outputs:
  - data/<SEASON>/constructors_weekly.json
  - data/constructors_standings.json

Categories:
  - Best MNF Player (starters only)
  - Top QB (starters)
  - Top RB (starters)
  - Top WR (starters)
  - Top TE (starters)
  - Top D/ST (starters)
  - Top K (starters)
  - Top Bench (bench only)
  - Largest Winning Margin (team total, not player)

Config:
  - SEASON env var (default "2025")
  - Per-category points via env:
      PTS_MNF / PTS_QB / PTS_RB / PTS_WR / PTS_TE / PTS_DST / PTS_K / PTS_BENCH / PTS_DIFF
"""

import json
import os
from pathlib import Path
from collections import defaultdict

# ------------------ Config ------------------
SEASON = os.getenv("SEASON", "2025")

POINTS_CONFIG = {
    "mnf_best_player": int(os.getenv("PTS_MNF", "5")),
    "top_qb":          int(os.getenv("PTS_QB", "5")),
    "top_rb":          int(os.getenv("PTS_RB", "5")),
    "top_wr":          int(os.getenv("PTS_WR", "5")),
    "top_te":          int(os.getenv("PTS_TE", "5")),
    "top_dst":         int(os.getenv("PTS_DST", "5")),
    "top_k":           int(os.getenv("PTS_K", "5")),
    "top_bench":       int(os.getenv("PTS_BENCH", "5")),
    "largest_diff":    int(os.getenv("PTS_DIFF", "5")),
}

DATA_ROOT = Path("data")
SEASON_DIR = DATA_ROOT / SEASON
PLAYERS_INDEX_PATH = DATA_ROOT / "players_nfl.json"
MNF_PATH = SEASON_DIR / "mnf_schedule.json"
# --------------------------------------------

def load_json(p: Path, default=None):
    if not p.exists():
        return {} if default is None else default
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def list_week_files(season_dir: Path):
    return sorted(season_dir.glob("week_*_matchups.json"))

def week_from_fname(p: Path) -> int:
    # e.g. week_01_matchups.json -> 1
    stem = p.stem
    for tok in stem.split("_"):
        if tok.isdigit():
            return int(tok)
    return 0

def build_user_maps(season_dir: Path):
    users = load_json(season_dir / "users.json", default=[])
    rosters = load_json(season_dir / "rosters.json", default=[])
    users_map = {}
    for u in users:
        disp = u.get("display_name") or (u.get("metadata") or {}).get("team_name") or u.get("user_id")
        users_map[u["user_id"]] = disp
    roster_to_owner = {r["roster_id"]: r["owner_id"] for r in rosters}
    return users_map, roster_to_owner

def is_defense_code(pid) -> bool:
    # D/ST shows up as team code like "PHI", "NYJ", etc.
    return isinstance(pid, str) and pid.isalpha() and 2 <= len(pid) <= 3

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
    return [
        {"user_id": uid, "display_name": disp, "points": round(p, 2)}
        for uid, disp, p in entries
        if p == max_pts
    ]

def compute_weekly(season_dir: Path):
    """
    Returns:
      weekly_points_by_user: { "1": {user_id: int, ...}, ... }
      weekly_payloads: {
        "1": {
           "users": {user_id: display_name, ...},
           "winners": { cat_key: [ {user_id,display_name,points}, ... ], ... },
           "weekly_points": {user_id: int, ...}
        }, ...
      }
    """
    users_map, roster_to_owner = build_user_maps(season_dir)
    players_index = load_json(PLAYERS_INDEX_PATH, default={})
    mnf_schedule = load_json(MNF_PATH, default={})  # {"1":["PHI","DAL"], ...}

    def pos_of(pid):
        # Try to resolve via players index; handle defenses by team code
        if is_defense_code(pid):
            return "DEF"
        rec = players_index.get(str(pid))
        return (rec or {}).get("position")

    def nfl_team_of(pid):
        if is_defense_code(pid):
            return pid  # team defense
        rec = players_index.get(str(pid))
        return (rec or {}).get("team")

    weekly_points_by_user = {}
    weekly_payloads = {}

    for wf in list_week_files(season_dir):
        wk = week_from_fname(wf)
        matchups = load_json(wf, default=[])
        if not matchups:
            continue

        # roster_id -> {starters, players_points, total, matchup_id}
        by_roster = {}
        by_matchup = defaultdict(list)
        for m in matchups:
            rid = m.get("roster_id")
            if rid is None:
                continue
            starters = m.get("starters") or []
            pp = m.get("players_points") or {}
            pts_total = float(m.get("points") or 0.0)
            mid = m.get("matchup_id")
            by_roster[rid] = {
                "starters": starters,
                "players_points": pp,
                "points_total": pts_total,
                "matchup_id": mid,
            }
            if mid is not None:
                by_matchup[mid].append((rid, pts_total))

        # Category buckets (built independently from full data)
        top_qb, top_rb, top_wr, top_te, top_k, top_dst = [], [], [], [], [], []
        top_bench = []
        mnf_bucket = []
        mnf_teams = set(mnf_schedule.get(str(wk), []))

        # Build buckets — NO mutual exclusion
        for rid, info in by_roster.items():
            uid = roster_to_owner.get(rid)
            disp = users_map.get(uid, uid)
            starters = info["starters"]
            pp = info["players_points"]

            # Starters: attribute by position + MNF separately
            for pid in starters:
                pid_str = str(pid)
                pts = float(pp.get(pid_str, 0.0))
                pos = pos_of(pid)

                # Position buckets (independent of MNF)
                if is_defense_code(pid) or pos in ("DEF", "D/ST"):
                    top_dst.append((uid, disp, pts))
                elif pos == "QB":
                    top_qb.append((uid, disp, pts))
                elif pos == "RB":
                    top_rb.append((uid, disp, pts))
                elif pos == "WR":
                    top_wr.append((uid, disp, pts))
                elif pos == "TE":
                    top_te.append((uid, disp, pts))
                elif pos == "K":
                    top_k.append((uid, disp, pts))
                # Unknown positions are ignored for top-pos categories

                # MNF bucket (independent): any starter whose NFL team is in MNF teams
                nfl_tm = nfl_team_of(pid)
                if nfl_tm and nfl_tm in mnf_teams:
                    mnf_bucket.append((uid, disp, pts))

            # Bench category: any roster player that is NOT in starters
            starter_set = set(str(x) for x in starters)
            all_seen_ids = set(pp.keys())  # points dict contains both starters and bench IDs
            bench_ids = [pid for pid in all_seen_ids if pid not in starter_set]
            for bpid in bench_ids:
                bpts = float(pp.get(bpid, 0.0))
                top_bench.append((uid, disp, bpts))

        # Largest Winning Margin (team totals)
        largest_diff = []
        for mid, pairs in by_matchup.items():
            if len(pairs) < 2:
                continue
            pairs_sorted = sorted(pairs, key=lambda t: float(t[1]), reverse=True)
            (winner_rid, w_pts), (_, l_pts) = pairs_sorted[0], pairs_sorted[1]
            diff = float(w_pts) - float(l_pts)
            uid = roster_to_owner.get(winner_rid)
            disp = users_map.get(uid, uid)
            largest_diff.append((uid, disp, diff))

        # Winners (with ties allowed)
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

        # Sum weekly constructors points by user (each category independent)
        week_totals = defaultdict(int)
        for cat_key, wlist in winners.items():
            if not wlist:
                continue
            award = POINTS_CONFIG.get(cat_key, 0)
            for w in wlist:
                week_totals[w["user_id"]] += award

        weekly_points_by_user[str(wk)] = dict(week_totals)
        weekly_payloads[str(wk)] = {
            "users": users_map,
            "winners": winners,
            "weekly_points": dict(sorted(week_totals.items(), key=lambda kv: kv[1], reverse=True)),
        }

        # --- Optional sanity: audit that overlap is possible (no-op if not needed) ---
        # For example, if the single top scorer in mnf_bucket also tops a position,
        # both lists will include that manager. We do NOT alter either bucket.

    return weekly_points_by_user, weekly_payloads

def main():
    if not SEASON_DIR.exists():
        print(f"[constructors] Missing season dir: {SEASON_DIR}")
        write_json(DATA_ROOT / "constructors_standings.json", {
            "users": {},
            "standings_all_time": {},
            "points_config": POINTS_CONFIG,
            "season": SEASON,
        })
        return

    weekly_points_by_user, weekly_payloads = compute_weekly(SEASON_DIR)

    # Write weekly payloads
    weekly_out = SEASON_DIR / "constructors_weekly.json"
    write_json(weekly_out, weekly_payloads)

    # Build cumulative standings for this season
    cumulative = defaultdict(int)
    all_users = {}
    for wk, payload in weekly_payloads.items():
        all_users.update(payload.get("users", {}))
        for uid, pts in (payload.get("weekly_points") or {}).items():
            cumulative[uid] += int(pts)

    standings_out = {
        "users": all_users,
        "standings_all_time": dict(sorted(cumulative.items(), key=lambda kv: kv[1], reverse=True)),
        "points_config": POINTS_CONFIG,
        "season": SEASON,
    }
    write_json(DATA_ROOT / "constructors_standings.json", standings_out)

    print(f"[constructors] Wrote {weekly_out}")
    print(f"[constructors] Wrote {DATA_ROOT / 'constructors_standings.json'}")

if __name__ == "__main__":
    main()
