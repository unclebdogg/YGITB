import os
from datetime import datetime

def to_markdown(kind: str, week: int, headline: str, body: str, local_start: str, local_end: str):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"# {kind.title()} – Week {week}\n\n> Window: {local_start} – {local_end}\n> Generated: {stamp}\n\n## {headline}\n\n"
    return header + body.strip() + "\n"

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def output_path(base_dir: str, kind: str, week: int, season: str):
    # Season, NOT calendar year. January runs belong to the PREVIOUS NFL season:
    # using datetime.now().year filed the 2025 playoff recaps under 2026/week-01..03,
    # and the idempotency check then skipped the real week 1 of 2026 as "already exists".
    path = os.path.join(base_dir, str(season), f"week-{week:02d}")
    ensure_dir(path)
    return os.path.join(path, f"{kind}.md")

def write_report(base_dir: str, kind: str, week: int, content: str, season: str):
    fpath = output_path(base_dir, kind, week, season)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)
    return fpath
