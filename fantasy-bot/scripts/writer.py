import os
from datetime import datetime

def to_markdown(kind: str, week: int, headline: str, body: str, local_start: str, local_end: str):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"# {kind.title()} – Week {week}\n\n> Window: {local_start} – {local_end}\n> Generated: {stamp}\n\n## {headline}\n\n"
    return header + body.strip() + "\n"

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def output_path(base_dir: str, kind: str, week: int):
    path = os.path.join(base_dir, f"{datetime.now().year}", f"week-{week:02d}")
    ensure_dir(path)
    return os.path.join(path, f"{kind}.md")

def write_report(base_dir: str, kind: str, week: int, content: str):
    fpath = output_path(base_dir, kind, week)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)
    return fpath
