import os
from datetime import datetime
from .utils import ensure_dir

def to_markdown(kind: str, week: int, headline: str, body: str, local_start: str, local_end: str):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"# {kind.title()} – Week {week}\n\n> Window: {local_start} – {local_end}\n> Generated: {stamp}\n\n## {headline}\n\n"
    return header + body.strip() + "\n"

def write_report(base_dir: str, kind: str, week: int, content: str):
    path = os.path.join(base_dir, f"{datetime.now().year}", f"week-{week:02d}")
    ensure_dir(path)
    fname = f"{kind}.md"  # preview.md / recap.md
    fpath = os.path.join(path, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)
    return fpath
