# ...
from .writer import to_markdown, write_report, output_path
# ...
md = to_markdown(kind, week, headline, body, start_d, end_d)

already = output_path(output_dir, kind, week)
if os.path.exists(already) and os.path.getsize(already) > 0:
    print(f"{kind.title()} already exists for week {week} at {already}; skipping.")
    return

path = write_report(output_dir, kind, week, md)
print(f"Wrote {path}")
