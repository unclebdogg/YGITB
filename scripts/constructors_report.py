#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Salt Shaker — Constructors Markdown Reports (all weeks)
-------------------------------------------------------
Reads:
  - data/<SEASON>/constructors_weekly.json
  - data/constructors_standings.json
Writes:
  - reports/<SEASON>/constructors_week_{NN}.md for every week present
  - reports/<SEASON>/index.md (season index with links)
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

def md_table(headers, rows):
    out = []
    out.append("| " + " | ".join(headers) + " |")
    out.append("|" + "|".join("---" for _ in headers) + "|")
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)

def week_keys_sorted(weekly_dict):
    if not weekly_dict:
        return []
    return sorted(int(k) for k in weekly_dict.keys())

def render_week_md(wk_key_str, weekly, standings):
    wk = int(wk_key_str)
    payload = weekly[wk_key_str]
    winners = payload.get("winners", {})
    users_map = payload.get("users", {})
    week_points = payload.get("weekly_points", {})

    # Weekly winners table
    winners_rows = []
    for key in ["mnf_best_player","top_qb","top_rb","top_wr","top_te","top_dst","top_k","top_bench","largest_diff"]:
        label = CAT_LABELS.get(key, key)
        items = winners.get(key, [])
        if not items:
            winners_rows.append([label, "—", "—", "—", "—", "—"])
            continue
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

    # Weekly scoreboard for this specific week
    wp_rows = sorted(
        [ (users_map.get(uid, uid), pts) for uid, pts in week_points.items() ],
        key=lambda x: x[1], reverse=True
    )
    weekly_rows = [[i, name, pts] for i, (name, pts) in enumerate(wp_rows, start=1)]
    weekly_section = md_table(["Rank","Manager","Points"], weekly_rows)

    # Week-by-week scoreboard (from week 1 -> current week)
    all_weeks = [wk_i for wk_i in week_keys_sorted(weekly) if wk_i <= wk]
    managers = set()
    for k in all_weeks:
        managers.update((weekly[str(k)].get("weekly_points") or {}).keys())
    managers = sorted(managers, key=lambda uid: users_map.get(uid, uid))

    wide_headers = ["Manager"] + [f"Wk {k}" for k in all_weeks] + ["Total"]
    wide_rows = []
    for uid in managers:
        name = users_map.get(uid, uid)
        row_vals, total = [], 0
        for k in all_weeks:
            pts = int((weekly[str(k)].get("weekly_points") or {}).get(uid, 0))
            total += pts
            row_vals.append(pts)
        wide_rows.append([name] + row_vals + [total])
    week_by_week_section = md_table(wide_headers, wide_rows)

    # Cumulative standings (full season so far)
    all_users = standings.get("users", {})
    totals = standings.get("standings_all_time", {})
    cum_rows = sorted(
        [(all_users.get(uid, uid), pts) for uid, pts in totals.items()],
        key=lambda x: x[1],
        reverse=True
    )
    cum_tbl_rows = [[i, name, pts] for i, (name, pts) in enumerate(cum_rows, start=1)]
    cumulative_section = md_table(["Rank","Manager","Points"], cum_tbl_rows)

    cfg = standings.get("points_config", {})
    cfg_str = ", ".join(f"{k}:{v}" for k,v in cfg.items()) if cfg else ""
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    md = []
    md.append(f"# Salt Shaker Constructors — Week {wk_key_str}")
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

    out_path = REPORT_DIR / f"constructors_week_{int(wk_key_str):02d}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md).rstrip() + "\n")
    return out_path

def main():
    weekly = load_json(WEEKLY_FILE)
    standings = load_json(STANDINGS_FILE)

    ks = week_keys_sorted(weekly)
    if not ks:
        out = REPORT_DIR / "constructors_week__no_data.md"
        with open(out, "w", encoding="utf-8") as f:
            f.write("# Salt Shaker Constructors — No data yet\n")
        print(f"Wrote {out}")
        return

    written = []
    for k in ks:
        p = render_week_md(str(k), weekly, standings)
        written.append(p)

    # Season index
    lines = ["# Salt Shaker Constructors — Season Index\n"]
    for k in ks:
        fn = f"constructors_week_{k:02d}.md"
        lines.append(f"- [Week {k}]({fn})")
    index_path = REPORT_DIR / "index.md"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    for p in written:
        print(f"Wrote {p}")
    print(f"Wrote {index_path}")

if __name__ == "__main__":
    main()
