#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Retrofit team display names into Constructors JSON by querying Sleeper leagues.

Usage examples:
  python -m scripts.retrofit_team_names_from_sleeper --season 2025 --leagues 1260643183704932352,1238082932220891136
  python -m scripts.retrofit_team_names_from_sleeper --season 2025 --leagues 1260643183704932352 --dry-run

What it updates:
- data/<SEASON>/constructors_weekly.json
  * winners[*][*].team_name (set from mapping if user_id present)
  * users[user_id] -> team_name
  * teams -> full mapping {user_id: team_name}
- data/constructors_standings.json
  * users[user_id] -> team_name
  * teams -> full mapping {user_id: team_name}

Backups (.bak-YYYYmmddHHMMSS) are created before writing.
"""

import argparse, json, pathlib, sys
from datetime import datetime
from typing import Dict, List
import requests

DATA_ROOT = pathlib.Path("data")
SLEEPER_BASE = "https://api.sleeper.app/v1"


def _get(url: str):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_league_mapping(league_id: str) -> Dict[str, str]:
    """Return {user_id: team_display_name} for one league."""
    users = _get(f"{SLEEPER_BASE}/league/{league_id}/users")
    rosters = _get(f"{SLEEPER_BASE}/league/{league_id}/rosters")

    # Build user map
    u_map = {str(u.get("user_id")): u for u in users}

    def display_from_user(u: dict) -> str:
        if not u:
            return "Unknown Team"
        dn = (u.get("display_name") or "").strip()
        if dn:
            return dn
        un = (u.get("username") or "").strip()
        return un or "Unknown Team"

    mapping: Dict[str, str] = {}
    for r in rosters:
        uid = str(r.get("owner_id"))
        meta = r.get("metadata") or {}
        team_name = (meta.get("team_name") or "").strip()
        if team_name:
            mapping[uid] = team_name
        else:
            mapping[uid] = display_from_user(u_map.get(uid))

    return mapping


def merge_mappings(maps: List[Dict[str, str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in maps:
        out.update({k: v for k, v in m.items() if v and str(v).strip()})
    return out


def load_json(p: pathlib.Path):
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(p: pathlib.Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def backup_file(p: pathlib.Path) -> pathlib.Path:
    if not p.exists():
        return p
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    bak = p.with_suffix(p.suffix + f".bak-{stamp}")
    p.replace(bak)
    return bak


def apply_weekly(weekly: dict, mapping: Dict[str, str]) -> bool:
    changed = False
    for wk_str, payload in (weekly or {}).items():
        users_map = payload.get("users") or {}
        teams_map = payload.get("teams") or {}

        # update users map
        for uid, name in mapping.items():
            if users_map.get(uid) != name:
                users_map[uid] = name
                changed = True

        # winners: patch each item team_name using user_id
        winners = payload.get("winners") or {}
        for cat_items in winners.values():
            if not isinstance(cat_items, list):
                continue
            for w in cat_items:
                uid = str(w.get("user_id") or "").strip()
                if uid and uid in mapping and w.get("team_name") != mapping[uid]:
                    w["team_name"] = mapping[uid]
                    changed = True

        # write back
        payload["users"] = users_map
        # also store full teams mapping (helps renderers)
        new_teams = {**teams_map, **mapping}
        if new_teams != teams_map:
            payload["teams"] = new_teams
            changed = True
    return changed


def apply_standings(standings: dict, mapping: Dict[str, str]) -> bool:
    changed = False
    users_map = standings.get("users") or {}
    teams_map = standings.get("teams") or {}

    for uid, name in mapping.items():
        if users_map.get(uid) != name:
            users_map[uid] = name
            changed = True

    standings["users"] = users_map
    new_teams = {**teams_map, **mapping}
    if new_teams != teams_map:
        standings["teams"] = new_teams
        changed = True

    return changed


def main():
    ap = argparse.ArgumentParser(description="Retrofit team display names into constructors JSON using Sleeper leagues.")
    ap.add_argument("--season", required=True, help="Season string, e.g. 2025")
    ap.add_argument("--leagues", required=True, help="Comma-separated Sleeper league IDs")
    ap.add_argument("--dry-run", action="store_true", help="Print changes but do not write files")
    args = ap.parse_args()

    season = args.season
    league_ids = [s.strip() for s in args.leagues.split(",") if s.strip()]

    if not league_ids:
        print("No league IDs provided.", file=sys.stderr)
        sys.exit(1)

    # Build mapping from all leagues
    maps = []
    for lid in league_ids:
        try:
            m = fetch_league_mapping(lid)
            print(f"[OK] fetched {len(m)} team names from league {lid}")
            maps.append(m)
        except Exception as e:
            print(f"[WARN] failed to fetch league {lid}: {e}", file=sys.stderr)

    mapping = merge_mappings(maps)
    if not mapping:
        print("[ERR] No names fetched; aborting.", file=sys.stderr)
        sys.exit(1)

    weekly_path = DATA_ROOT / season / "constructors_weekly.json"
    standings_path = DATA_ROOT / "constructors_standings.json"
    weekly = load_json(weekly_path)
    standings = load_json(standings_path)

    changed_weekly = apply_weekly(weekly, mapping)
    changed_standings = apply_standings(standings, mapping)

    if args.dry_run:
        print(f"[DRY-RUN] weekly changed: {changed_weekly}, standings changed: {changed_standings}")
        # Small peek
        for wk in sorted(weekly.keys())[:1]:
            print(f"[SAMPLE] Week {wk} users -> {list((weekly[wk].get('users') or {}).items())[:5]}")
        print(f"[SAMPLE] Standings users -> {list((standings.get('users') or {}).items())[:5]}")
        return

    wrote_any = False
    if changed_weekly:
        bak = backup_file(weekly_path)
        if bak != weekly_path:
            print(f"[BACKUP] {weekly_path} -> {bak}")
        write_json(weekly_path, weekly)
        print(f"[WRITE]  {weekly_path}")
        wrote_any = True

    if changed_standings:
        bak = backup_file(standings_path)
        if bak != standings_path:
            print(f"[BACKUP] {standings_path} -> {bak}")
        write_json(standings_path, standings)
        print(f"[WRITE]  {standings_path}")
        wrote_any = True

    if not wrote_any:
        print("[OK] No changes required; mapping already reflected.")


if __name__ == "__main__":
    main()
