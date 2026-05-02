# job-tracker

Polls ~190 companies + curated job lists every 30 minutes via GitHub Actions, filters for new-grad inference / MLSys / SWE / GPU roles in the US that are sponsorship-friendly, and posts hits to a Discord channel. State is persisted in `jobs.db` (committed back to the repo). React ✅ on a Discord post to mark a job applied.

Coverage spans frontier AI labs, inference infra, GPU clouds, hardware/accelerators, vector DBs, dev tools, robotics, autonomous, biotech-AI, big-tech SaaS, fintech, security, crypto/Web3, climate/industrial, defense, and YC startups — across 7 source types (Greenhouse, Ashby, Lever, Workday, Workable, SmartRecruiters, plus curated GitHub lists like SimplifyJobs/New-Grad-Positions and vanshb03/New-Grad-2026).

Spec lives in [`SPEC.md`](SPEC.md). Internal workflow rules live in [`CLAUDE.md`](CLAUDE.md).

## Stack

- Python 3.11+
- `httpx[http2]` — async fetching
- `pydantic` v2 — config validation only
- `pyyaml` — config parsing
- stdlib `sqlite3`, `re`, `dataclasses`, `logging`, `argparse`

No Celery, no Redis, no SQLAlchemy, no Discord library. Three deps total.

## Layout

```
src/
  main.py              # entry: fetch → filter → notify → save
  sync_reactions.py    # entry: scan ✅ reactions → mark applied
  models.py            # Job dataclass, ATS enum, CompanyEntry
  config.py            # pydantic load+validate companies.yaml
  state.py             # SQLite wrapper
  discord.py           # bot REST: post embeds + read reactions
  utils.py             # html_strip + US location constants
  fetchers/            # greenhouse, ashby, lever, workday
  filters/             # role, seniority, location, sponsorship, pipeline
companies.yaml         # editable list of companies + filter tweaks
.github/workflows/poll.yml
jobs.db                # SQLite, committed
```

## One-time setup

1. Discord side:
   - Create a server (or pick one) with a `#jobs` channel.
   - https://discord.com/developers/applications → New Application → **Bot** tab → Reset Token, save it.
   - **OAuth2 → URL Generator**: scopes = `bot`; permissions = `View Channels`, `Send Messages`, `Embed Links`, `Read Message History`, `Add Reactions`. Open the generated URL to invite the bot.
   - In Discord, enable Developer Mode (Settings → Advanced) → right-click `#jobs` → Copy Channel ID.
2. GitHub side:
   - Push this repo (public is fine — Actions runs are unlimited and the data is non-sensitive).
   - **Settings → Secrets and variables → Actions** → add `DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID`.
   - **Settings → Actions → General → Workflow permissions** → "Read and write permissions".
3. Bootstrap:
   - **Actions** tab → **poll** workflow → **Run workflow** → set `bootstrap = true`.
   - Confirm `jobs.db` got committed and **zero** Discord messages were sent.
   - Wait for the next scheduled run (≤ 30 min). Real new postings now ping `#jobs`.

If you skip the bootstrap step you'll get 200+ pings on first run. Don't.

## Running locally

```bash
pip install -r requirements.txt

# See what would be notified — no DB writes, no Discord posts:
python -m src.main --dry-run

# Populate jobs.db with all currently-open jobs marked notified=1:
python -m src.main --bootstrap

# Real cycle:
DISCORD_BOT_TOKEN=... DISCORD_CHANNEL_ID=... python -m src.main
DISCORD_BOT_TOKEN=... DISCORD_CHANNEL_ID=... python -m src.sync_reactions

# Inspect:
sqlite3 jobs.db "SELECT company, title, location FROM seen ORDER BY first_seen DESC LIMIT 20;"
sqlite3 jobs.db "SELECT * FROM run_log ORDER BY run_id DESC LIMIT 5;"
```

## Editing the company list

Open [`companies.yaml`](companies.yaml). Each entry needs `name`, `ats`, and the fields that ATS requires (`token` for greenhouse/ashby/lever/workable; `tenant`+`site`+optional `subdomain` for workday).

**Verify before committing.** ATS tokens drift; assume any guessed token is wrong until you've hit the API directly. Patterns to test:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://boards-api.greenhouse.io/v1/boards/<token>/jobs
curl -s -o /dev/null -w "%{http_code}\n" https://api.ashbyhq.com/posting-api/job-board/<token>
curl -s -o /dev/null -w "%{http_code}\n" "https://api.lever.co/v0/postings/<token>?mode=json"
curl -s -o /dev/null -w "%{http_code}\n" https://apply.workable.com/api/v1/widget/accounts/<token>
```

For Workday, the URL pattern in your browser bar tells you all three fields:
`https://<tenant>.wd<N>.myworkdayjobs.com/<site>/...`. Default subdomain is `wd1`; override with `subdomain: wd5` if needed (NVIDIA is wd5, for example).

## Filter tuning

All filters live in `src/filters/`. Regexes are tested against hand-crafted cases — if you change them, drop into Python and verify against the existing examples first. The sponsorship filter logs every rejection at `INFO` so you can spot-check false positives in week 1.

## Troubleshooting

- **Workflow runs but no commit happens**: check `Settings → Actions → General → Workflow permissions` is set to "Read and write permissions". Without that, the `git push` silently no-ops.
- **All Discord posts fail**: regenerate the bot token, re-invite the bot to the server with the right permissions, update the secret.
- **A company always returns 0 jobs**: hit the ATS endpoint directly (see "Editing the company list"). The most common cause is a stale token.
- **Workday tenant 422s**: try `subdomain: wd5` or `wd103`. Workday tenant subdomains are not consistent.

## Known v1 limitations

- **Workable + GitHub-list jobs have no description.** Both Workable's widget API and the curated GitHub README tables expose title + location but not the body. Sponsorship filter passes empty descriptions, so these jobs skip the sponsorship gate. Title-fallback location filter is what catches non-US roles. SimplifyJobs's 🇺🇸 (US-citizen-only) and 🛂 (no-sponsorship) emoji flags ARE respected at the title-filter stage.
- **Cross-source dedupe is by `(company, title)` lowercase match.** A direct ATS hit on Anthropic's "Software Engineer, Inference" and a SimplifyJobs row for the same role get collapsed to one entry, preferring the ATS one (it has a description for sponsorship filtering). Slight title variations slip past dedupe — minor noise.
- **Per-tenant Workday discovery is manual.** When a `<tenant>.wd<N>.myworkdayjobs.com/<site>` URL isn't predictable, the bootstrap surfaces a 404 in the logs and the company is silently skipped. The TODO block at the bottom of `companies.yaml` lists known Workday-hosted companies that need their `tenant`+`site`+`subdomain` filled in by hand (visit each careers page; the URL bar shows the values once you click into a job).

## What's parked (v2+)

iCIMS / SmartRecruiters / JobVite adapters (more company coverage); LLM-based role scoring; custom Google/Meta/Apple-careers scrapers; Discord slash commands (`/mute`, `/search`); web dashboard; multi-user support.
