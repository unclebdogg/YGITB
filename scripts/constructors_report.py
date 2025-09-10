#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Salt Shaker — Constructors Markdown Report
------------------------------------------
Reads:
  - data/<SEASON>/constructors_weekly.json
  - data/constructors_standings.json
Outputs:
  - reports/<SEASON>/constructors_week_{NN}.md
"""

import json, os, pathlib
from datetime import datetime

DATA_ROOT = pathlib.Path("data")
REPORT_ROOT = pathlib.Path("reports")
SEASON = os.getenv("SEASON", "2025")

WEEKLY_FILE = DATA_ROOT / SEASON / "constructors_weekly.json"
STANDINGS_FILE = DATA_ROOT / "constructors_standings.json"
REPORT_DIR = REPORT_ROOT / SEASON
REPORT_DIR.mkdir(parents=True, exist_ok=True)

CAT_LABELS = {
    "mnf_best_player": "Best MNF Player",
    "top_qb": "Top QB",
    "top_rb": "Top RB",
    "top_wr": "Top WR",
    "top_te": "Top TE",
    "top_dst": "Top D/ST",
    "top_k": "Top K",
    "top_bench": "Top Bench",
    "largest_diff": "Largest Winning Margin",
}

def load_json(p):
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def latest_week_key(weekly_dict):
    # keys are "1","2",... (strings); return highest as "NN"
    if not weekly_dict:
        return None
    ks = sorted(int(k) for k in weekly_dict.keys())
    return str(ks[-1])

def md_table(headers, rows):
    out = []
    out.append("| " + " | ".join(headers) + " |")
    out.append("|" + "|".join("---" for _ in headers) + "|")
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)

def main():
    weekly = load_json(WEEKLY_FILE)  # {"01": {...}, "02": {...}, ...} or {"1": {...}}
    standings = load_json(STANDINGS_FILE)

    wk = latest_week_key(weekly)
    if not wk:
        out = REPORT_DIR / "constructors_week__no_data.md"
        with open(out, "w", encoding="utf-8") as f:
            f.write("# Salt Shaker Constructors — No data yet\n")
        print(f"Wrote {out}")
        return

    payload = weekly[wk]
    winners = payload.get("winners", {})
    week_points = payload.get("weekly_points", {})
    users_map = payload.get("users", {})

    # Weekly Category Winners table
    winners_rows = []
    for key in [
        "mnf_best_player","top_qb","top_rb","top_wr","top_te","top_dst","top_k","top_bench","largest_diff"
    ]:
        label = CAT_LABELS.get(key, key)
        items = winners.get(key, [])
        if not items:
            winners_rows.append([label, "—", "—", "—", "—", "—"])
            continue
        # Multiple winners allowed (ties). One row per winner.
        for w in items:
            manager = w.get("display_name", w.get("user_id",""))
            player  = w.get("player_name") or ("—" if key=="largest_diff" else "")
            pos     = w.get("position") or ("—" if key=="largest_diff" else "")
            team    = w.get("team") or ("—" if key=="largest_diff" else "")
            pts     = w.get("points", "")
            winners_rows.append([label, manager, player, pos, team, pts])
    winners_section = md_table(
        ["Category", "Manager", "Player", "Pos", "Team", "Pts"],
        winners_rows
    )

    # Weekly scoreboard (latest week)
    wp_rows = sorted(
        [ (users_map.get(uid, uid), pts) for uid, pts in week_points.items() ],
        key=lambda x: x[1], reverse=True
    )
    weekly_rows = []
    for i, (name, pts) in enumerate(wp_rows, start=1):
        weekly_rows.append([i, name, pts])
    weekly_section = md_table(["Rank","Manager","Points"], weekly_rows)

    # Build week-by-week wide table from ALL weeks present
    all_week_keys = sorted(int(k) for k in weekly.keys())
    managers = set()
    for k in weekly.keys():
        managers.update((weekly[k].get("weekly_points") or {}).keys())
    managers = sorted(managers, key=lambda uid: users_map.get(uid, uid))

    wide_headers = ["Manager"] + [f"Wk {wk}" for wk in all_week_keys] + ["Total"]
    wide_rows = []
    for uid in managers:
        name = users_map.get(uid, uid)
        row_vals = []
        total = 0
        for wk_i in all_week_keys:
            wkp = weekly[str(wk_i)].get("weekly_points") or {}
            pts = int(wkp.get(uid, 0))
            total += pts
            row_vals.append(pts)
        wide_rows.append([name] + row_vals + [total])
    week_by_week_section = md_table(wide_headers, wide_rows)

    # Cumulative standings
    all_users = standings.get("users", {})
    totals = standings.get("standings_all_time", {})
    cum_rows = sorted(
        [(all_users.get(uid, uid), pts) for uid, pts in totals.items()],
        key=lambda x: x[1],
        reverse=True
    )
    cum_tbl_rows = []
    for i, (name, pts) in enumerate(cum_rows, start=1):
        cum_tbl_rows.append([i, name, pts])
    cumulative_section = md_table(["Rank","Manager","Points"], cum_tbl_rows)

    # Points config line
    cfg = standings.get("points_config", {})
    cfg_str = ", ".join(f"{k}:{v}" for k,v in cfg.items()) if cfg else ""

    # Compose MD
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    md = []
    md.append(f"# Salt Shaker Constructors — Week {wk}")
    md.append(f"_Generated: {ts}_\n")
    md.append("## Weekly Category Winners")
    md.append(winners_section)
    md.append("\n## Weekly Scoreboard")
    md.append(weekly_section)
    md.append("\n## Week-by-Week Scoreboard")
    md.append(week_by_week_section)
    md.append("\n## Constructors Standings (Cumulative)")
    md.append(cumulative_section)
    if cfg_str:
        md.append(f"\n_Scoring config:_ {cfg_str}")

    out_path = REPORT_DIR / f"constructors_week_{wk}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md).rstrip() + "\n")
    print(f"Wrote {out_path}")

if __name__ == "__main__":
    main()
