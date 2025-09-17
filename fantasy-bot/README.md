# Fantasy Preview & Recap Bot

Generates:
- **Preview** (Thurs AU local): `reports/YYYY/week-XX/preview.md`
- **Recap** (Wed AU local): `reports/YYYY/week-XX/recap.md`

## Setup

1. **Create repo** and copy this project in.
2. **Add GitHub Secrets** (Repo → Settings → Secrets → Actions):
   - `OPENAI_API_KEY`
   - `SLEEPER_LEAGUE_ID` (find in your league’s URL)
   - (optional) `NFL_SEASON` (if you want to pin)
   - (optional) `REPO_COMMIT_AUTHOR_NAME`, `REPO_COMMIT_AUTHOR_EMAIL`
3. The workflow runs **hourly** (UTC). The script **time-gates** to:
   - Preview: **Thursday 09:00** Australia/Sydney
   - Recap: **Wednesday 09:00** Australia/Sydney
   (DST-safe since gating is done in local tz.)

## Manual run

Actions → “Fantasy Preview & Recap” → **Run workflow** → choose `preview` or `recap`.

## Customising prompts

Edit files under `/prompts`. The placeholders are simple `{{var}}` replacements.
