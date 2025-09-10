#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Salt Shaker — Constructors Championship scorer
----------------------------------------------
Outputs:
  - data/<SEASON>/constructors_weekly.json
  - data/constructors_standings.json

Weekly categories (independent; same manager can win multiple):
  - Best MNF Player (starters)
  - Top QB / RB / WR / TE / K / D/ST (starters)
  - Top Bench (bench only)
  - Largest Winning Margin (team totals)

Scoring:
  - Default 1 point per category per week (env overridable)
  - Default TIE_MODE = 'single' (one winner per category/week)
    * tie-break: by points desc, then player_name asc, then user_id asc
  - Set TIE_MODE='allow' to award full points to all tied winners

Env:
  - SEASON (default "2025")
  - PTS_MNF, PTS_QB, PTS_RB, PTS_WR, PTS_TE, PTS_DST, PTS_K, PTS_BENCH, PTS_DIFF
  - TIE_MODE ('single' | 'allow')
"""

import json
import os
from pathlib import Path
from collections import defaultdict

# ---------- Config ----------
SEASON = os.getenv("SEASON", "2025")
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
TIE_MODE = os.getenv("TIE_MODE", "single").lower()  # 'single' or 'allow'

DATA_ROOT = Path("data")
SEASON_DIR = DATA_ROOT / SEASON
PLAYERS_INDEX_PATH = DATA_ROOT / "players_nfl.json"
MNF_PATH = SEASON_DIR / "mnf_schedule.json"
# ----------------------------

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

def week_from_name(p: Path) -> int:
    stem = p.stem  # week_01_matchups
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
    # D/ST encoded as team code like "PHI","NYJ"
    return isinstance(pid, str) and pid.isalpha() and 2 <= len(pid) <= 3

def get_player_info(players_index, pid):
    """Return (player_id, full_name, position, team). Handles D/ST codes."""
    if is_defense_code(pid):
        return (str(pid), f"{pid} D/ST", "D/ST", str(pid))
    rec = players_index.get(str(pid)) or {}
    name = rec.get("full_name") or f"{rec.get('first_name','')} {rec.get('last_name','')}".strip() or str(pid)
    pos = rec.get("position") or ""
    team = rec.get("team") or ""
    return (str(pid), name, pos, team)

def settle_winners(bucket, users_map):
    """
    bucket entries must be tuples:
      (user_id, display_name, points, player_id, player_name, position, team)
    - ignore entries with points <= 0
    - dedupe by (user_id, player_id) keeping highest points
    - return either all tied max (TIE_MODE='allow') or single winner (TIE_MODE='single')
    """
    best_by_key = {}
    for (uid, disp, pts, pid, pname, pos, team) in bucket:
        if pts is None or float(pts) <= 0:
            continue
        uid = str(uid)
        disp = disp or users_map.get(uid, uid)
        pid = str(pid)
        pts = float(pts)
        key = (uid, pid)
        cur = best_by_key.get(key)
        if cur is None or pts > cur[2]:
            best_by_key[key] = (uid, disp, pts, pid, pname, pos, team)

    entries = list(best_by_key.values())
    if not entries:
        return []

    # sort for deterministic tie-breaking
    entries.sort(key=lambda e: (-e[2], (e[4] or ""), e[0]))  # pts desc, player_name asc, user_id asc
    max_pts = entries[0][2]
    if TIE_MODE == "allow":
        winners = [e for e in entries if e[2] == max_pts]
    else:
        winners = [entries[0]]

    out = [
        {
            "user_id": uid,
            "display_name": disp,
            "points": round(pts, 2),
            "player_id": pid,
            "player_name": pname,
            "position": pos,
            "team": team,
        }
        for (uid, disp, pts, pid, pname, pos, team) in winners
    ]
    return out

def compute_weekly(season_dir: Path):
    users_map, roster_to_owner = build_user_maps(season_dir)
    players_index = load_json(PLAYERS_INDEX_PATH, default={})
    mnf_schedule = load_json(MNF_PATH, default={})

    weekly_points_by_user = {}
    weekly_payloads = {}

    for wf in list_week_files(season_dir):
        wk = week_from_name(wf)
        matchups = load_json(wf, default=[])
        if not matchups:
            continue

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

        # Buckets
        top_qb, top_rb, top_wr, top_te, top_k, top_dst = [], [], [], [], [], []
        top_bench = []
        mnf_bucket = []
        mnf_teams = set(mnf_schedule.get(str(wk), []))

        for rid, info in by_roster.items():
            uid = roster_to_owner.get(rid)
            disp = users_map.get(uid, uid)
            starters = info["starters"]
            pp = info["players_points"]

            for pid in starters:
                pid_str = str(pid)
                pts = float(pp.get(pid_str, 0.0))
                (player_id, pname, pos, team) = get_player_info(players_index, pid)

                if pts > 0:
                    if pos == "QB":
                        top_qb.append((uid, disp, pts, player_id, pname, pos, team))
                    elif pos == "RB":
                        top_rb.append((uid, disp, pts, player_id, pname, pos, team))
                    elif pos == "WR":
                        top_wr.append((uid, disp, pts, player_id, pname, pos, team))
                    elif pos == "TE":
                        top_te.append((uid, disp, pts, player_id, pname, pos, team))
                    elif pos == "K":
                        top_k.append((uid, disp, pts, player_id, pname, pos, team))
                    elif pos in ("D/ST", "DEF") or is_defense_code(pid):
                        top_dst.append((uid, disp, pts, player_id, pname, "D/ST", team))

                # MNF independent
                if team and team in mnf_teams and pts > 0:
                    mnf_bucket.append((uid, disp, pts, player_id, pname, pos or ("D/ST" if is_defense_code(pid) else ""), team))

            # bench
            starter_set = set(str(x) for x in starters)
            for bpid, bpts in pp.items():
                if bpid in starter_set:
                    continue
                bpts_val = float(bpts or 0.0)
                if bpts_val <= 0:
                    continue
                (player_id, pname, pos, team) = get_player_info(players_index, bpid)
                top_bench.append((uid, disp, bpts_val, player_id, pname, pos, team))

        # Largest diff
        largest_diff = []
        for mid, pairs in by_matchup.items():
            if len(pairs) < 2:
                continue
            pairs_sorted = sorted(pairs, key=lambda t: float(t[1]), reverse=True)
            (winner_rid, w_pts), (_, l_pts) = pairs_sorted[0], pairs_sorted[1]
            diff = float(w_pts) - float(l_pts)
            if diff > 0:
                uid = roster_to_owner.get(winner_rid)
                disp = users_map.get(uid, uid)
                # No player entity; keep shape with blanks
                largest_diff.append((uid, disp, diff, "", "", "", ""))

        winners = {
            "mnf_best_player": settle_winners(mnf_bucket, users_map),
            "top_qb":          settle_winners(top_qb, users_map),
            "top_rb":          settle_winners(top_rb, users_map),
            "top_wr":          settle_winners(top_wr, users_map),
            "top_te":          settle_winners(top_te, users_map),
            "top_dst":         settle_winners(top_dst, users_map),
            "top_k":           settle_winners(top_k, users_map),
            "top_bench":       settle_winners(top_bench, users_map),
            "largest_diff":    settle_winners(largest_diff, users_map),
        }

        # Weekly points
        week_totals = defaultdict(int)
        for cat_key, wlist in winners.items():
            if not wlist:
                continue
            award = POINTS_CONFIG.get(cat_key, 0)
            if TIE_MODE == "allow":
                for w in wlist:
                    week_totals[w["user_id"]] += award
            else:
                # single winner already selected
                week_totals[wlist[0]["user_id"]] += award

        weekly_points_by_user[str(wk)] = dict(week_totals)
        weekly_payloads[str(wk)] = {
            "users": users_map,
            "winners": winners,
            "weekly_points": dict(sorted(week_totals.items(), key=lambda kv: kv[1], reverse=True)),
        }

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

    weekly_points, weekly_payloads = compute_weekly(SEASON_DIR)

    # Write weekly payloads
    weekly_out = SEASON_DIR / "constructors_weekly.json"
    write_json(weekly_out, weekly_payloads)

    # Cumulative standings for this season
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
        "tie_mode": TIE_MODE,
    }
    write_json(DATA_ROOT / "constructors_standings.json", standings_out)

    print(f"[constructors] Wrote {weekly_out}")
    print(f"[constructors] Wrote {DATA_ROOT / 'constructors_standings.json'}")

if __name__ == "__main__":
    main()
