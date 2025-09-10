#!/usr/bin/env python3
# scripts/constructors_report.py
import json, os, pathlib, sys
from datetime import datetime

DATA_ROOT = pathlib.Path("data")
SEASON    = os.getenv("SEASON", "2025")
SEASON_DIR = DATA_ROOT / SEASON
WEEKLY_FILE = SEASON_DIR / "constructors_weekly.json"
STANDINGS_FILE = DATA_ROOT / "constructors_standings.json"
REPORT_DIR = pathlib.Path("reports") / SEASON
REPORT_DIR.mkdir(parents=True, exist_ok=True)

def load_json(p):
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def latest_week(weekly: dict) -> str | None:
    if not weekly:
        return None
    # keys are "01","02",...
    ks = sorted((int(k) for k in weekly.keys()))
    return f"{ks[-1]:02d}" if ks else None

def winner_line(category: str, arr: list[dict], users: dict) -> str:
    if not arr:
        return f"- **{category}**: —"
    names = []
    for w in arr:
        # winner objects can have user_id + display_name
        uid = w.get("user_id") or ""
        disp = w.get("display_name") or users.get(uid, uid) or uid
        names.append(disp)
    return f"- **{category}**: " + ", ".join(names)

def table_rank(rows, title="Standings", top_n=10):
    if not rows:
        return f"\n### {title}\n_No data yet._\n"
    lines = [f"\n### {title}\n", "| Rank | Manager | Points |", "|---:|---|---:|"]
    for i, (name, pts) in enumerate(rows[:top_n], start=1):
        lines.append(f"| {i} | {name} | {pts} |")
    return "\n".join(lines) + "\n"

def main():
    weekly = load_json(WEEKLY_FILE)
    standings = load_json(STANDINGS_FILE)

    wk = latest_week(weekly)
    if not wk:
        out = REPORT_DIR / "constructors_week__no_data.md"
        with open(out, "w", encoding="utf-8") as f:
            f.write("# Salt Shaker Constructors — No data yet\n")
        print(f"Wrote {out}")
        return

    week_payload = weekly.get(wk, {})
    winners = week_payload.get("winners", {})
    week_users = week_payload.get("users", {})  # {user_id: display_name}

    # Build standings rows from global file (user_id keyed)
    all_users = standings.get("users", {})
    totals = standings.get("standings_all_time", {})
    rows = sorted(
        [(all_users.get(uid, uid), pts) for uid, pts in totals.items()],
        key=lambda x: x[1],
        reverse=True
    )

    # Nicely ordered categories
    cat_order = [
        ("mnf_best_player", "Best MNF Player"),
        ("top_qb", "Top QB"),
        ("top_rb", "Top RB"),
        ("top_wr", "Top WR"),
        ("top_te", "Top TE"),
        ("top_dst", "Top D/ST"),
        ("top_k", "Top K"),
        ("top_bench", "Top Bench"),
        ("largest_diff", "Largest Winning Margin"),
    ]

    # Compose report
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append(f"# Salt Shaker Constructors — Week {wk}")
    lines.append(f"_Generated: {ts}_\n")

    lines.append("## Weekly Category Winners")
    for key, label in cat_order:
        lines.append(winner_line(label, winners.get(key, []), {**all_users, **week_users}))
    lines.append("")

    # Weekly points table (only those who scored this week)
    weekly_points = week_payload.get("weekly_points", {})
    weekly_rows = sorted(
        [ (week_users.get(uid, all_users.get(uid, uid)), pts) for uid, pts in weekly_points.items() ],
        key=lambda x: x[1],
        reverse=True
    )
    lines.append(table_rank(weekly_rows, title=f"Week {wk} Points"))

    # All-time/cumulative standings
    lines.append(table_rank(rows, title="Constructors Standings (Cumulative)", top_n=20))

    # Helpful footer
    points_cfg = standings.get("points_config", {})
    if points_cfg:
        cfg_str = ", ".join(f"{k}:{v}" for k,v in points_cfg.items())
        lines.append(f"_Scoring config:_ {cfg_str}\n")

    out_path = REPORT_DIR / f"constructors_week_{wk}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    print(f"Wrote {out_path}")

if __name__ == "__main__":
    main()
