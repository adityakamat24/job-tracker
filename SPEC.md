# Job Tracker — Planning Spec

A personal job-monitoring system that polls ~50 companies' ATS endpoints every 30 minutes, filters for new-grad inference / MLSys / SWE / GPU roles in the US that are sponsorship-friendly, and posts new hits to a Discord channel. State is persisted in a SQLite file committed back to the repo. ✅ reactions on Discord mark a job as "applied" in the DB. Built to run entirely on GitHub Actions, no servers.

---

## 0. Goals & Non-goals

**Goals**
- Catch new postings within ~30 min of going live.
- Zero noise: every Discord ping should be a role I actually want to consider.
- Zero infra to babysit: GitHub Actions only, no VPS, no serverless workers, no Docker.
- DB state recoverable and inspectable (SQLite, committed to repo).
- Easy to add/remove companies (single YAML edit).

**Non-goals**
- Not a multi-user product.
- No web UI.
- No LLM-based matching or scoring (v1 is rule-based; can add later).
- Not trying to scrape Workday-hard-mode targets like Google careers / Meta careers in v1; those get custom adapters later.
- No applying to jobs automatically. Just notification + tracking.

---

## 1. Architecture

```
            ┌─────────────────┐
            │ GitHub Actions  │
            │  cron */30m     │
            └────────┬────────┘
                     │
                     ▼
            ┌─────────────────┐
            │   main.py       │  one entry point, <500 LOC
            └────────┬────────┘
                     │
        ┌────────────┼────────────┬─────────────┐
        ▼            ▼            ▼             ▼
   greenhouse.py  ashby.py    lever.py     workday.py
        │            │            │             │
        └────────────┴────┬───────┴─────────────┘
                          ▼
                  normalize → Job dataclass
                          │
                          ▼
                   filters.py
            (role / location / seniority / sponsorship)
                          │
                          ▼
                     state.py
              (SQLite: seen, applied, message_map)
                          │
                          ▼
                    discord.py
            (post via bot REST, batched per company)
                          │
                          ▼
            commit jobs.db back to repo
```

A separate cron job (same workflow, different step) runs `sync_reactions.py` to scan recent channel messages for ✅ reactions and mark applied jobs. Same cycle, runs after the fetch step.

---

## 2. Stack

- **Python 3.11+**
- `httpx[http2]` — async fetching, all ATS calls run concurrently via `asyncio.gather`
- `pydantic` v2 — config validation only
- `pyyaml` — config file parsing
- stdlib `sqlite3` — no ORM
- stdlib `re`, `dataclasses`, `logging`, `argparse`

No Celery, no Redis, no SQLAlchemy, no Discord library (I just hit the REST API directly with httpx). Total deps: 3.

---

## 3. Repo Layout

```
job-tracker/
├── .github/
│   └── workflows/
│       └── poll.yml                # cron + commit-back
├── src/
│   ├── __init__.py
│   ├── main.py                     # entry point: fetch → filter → notify → save
│   ├── sync_reactions.py           # entry point: read channel reactions → mark applied
│   ├── models.py                   # Job dataclass, NormalizedLocation, etc.
│   ├── config.py                   # load + validate companies.yaml
│   ├── fetchers/
│   │   ├── __init__.py
│   │   ├── base.py                 # abstract Fetcher class
│   │   ├── greenhouse.py
│   │   ├── ashby.py
│   │   ├── lever.py
│   │   └── workday.py
│   ├── filters/
│   │   ├── __init__.py
│   │   ├── role.py                 # title regex
│   │   ├── location.py             # US-only
│   │   ├── seniority.py            # new-grad
│   │   └── sponsorship.py          # description scan
│   ├── state.py                    # SQLite wrapper
│   └── discord.py                  # bot REST: post + read reactions
├── companies.yaml                  # the editable list
├── jobs.db                         # SQLite, committed
├── requirements.txt
├── README.md
└── SPEC.md                         # this file
```

---

## 4. Data Model

### `models.py`

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class ATS(str, Enum):
    GREENHOUSE = "greenhouse"
    ASHBY = "ashby"
    LEVER = "lever"
    WORKDAY = "workday"

@dataclass
class Job:
    id: str                       # namespaced: f"{ats}:{company_slug}:{native_id}"
    company: str                  # display name, e.g. "Anthropic"
    ats: ATS
    title: str
    location: str                 # raw string from API
    url: str                      # apply URL
    description: str = ""         # full text, for sponsorship scan
    posted_at: datetime | None = None
    departments: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)  # original payload, for debugging

    def short(self) -> str:
        return f"[{self.company}] {self.title} — {self.location}"
```

### SQLite schema (`state.py`)

```sql
CREATE TABLE IF NOT EXISTS seen (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    url TEXT NOT NULL,
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    closed_at TIMESTAMP,                     -- set when no longer in fetch results
    notified BOOLEAN DEFAULT 0,
    discord_message_id TEXT,                 -- for reaction lookup
    applied BOOLEAN DEFAULT 0,
    applied_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_seen_company ON seen(company);
CREATE INDEX IF NOT EXISTS idx_seen_first_seen ON seen(first_seen);
CREATE INDEX IF NOT EXISTS idx_seen_message_id ON seen(discord_message_id);

CREATE TABLE IF NOT EXISTS run_log (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    jobs_fetched INTEGER,
    jobs_new INTEGER,
    jobs_notified INTEGER,
    errors TEXT
);
```

ID namespacing matters: two companies on different ATSs could collide on raw IDs. Namespaced ID format: `greenhouse:anthropic:4567890`.

---

## 5. Config Format

### `companies.yaml`

```yaml
# Edit this file to add/remove companies. Each entry needs an ats type and a token.
# Token is the company-specific identifier in that ATS.
# For greenhouse: visit boards.greenhouse.io/<token> — that's the slug.
# For ashby: jobs.ashbyhq.com/<token>
# For lever: jobs.lever.co/<token>
# For workday: needs tenant + site, see workday section below.

companies:
  - name: Anthropic
    ats: greenhouse
    token: anthropic
    tier: 1                  # optional, used for sort order in digest
    notes: "Top target"

  - name: NVIDIA
    ats: workday
    tenant: nvidia
    site: NVIDIAExternalCareerSite
    tier: 1

  - name: Modal
    ats: ashby
    token: modal
    tier: 2

  # ... etc

# Optional global overrides
filters:
  role_include_extra: []     # additional regex patterns to include
  role_exclude_extra: []     # additional regex patterns to exclude
  locations_include_extra:
    - "Anywhere"             # treat as remote-friendly
  sponsorship_strict: true   # if true, exclude on description match
```

Validate with pydantic `Companies` model; invalid entries log a warning and get skipped (don't crash the whole run for one bad company).

---

## 6. Fetchers

All fetchers implement:

```python
class Fetcher(ABC):
    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient, entry: CompanyEntry) -> list[Job]:
        ...
```

Each returns a normalized list of `Job` objects with `description` populated. Failures (timeout, non-200, malformed JSON) get logged and return `[]` so one broken company can't kill the run.

### 6.1 Greenhouse

- **Endpoint**: `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`
- **Auth**: none
- **Response shape**:
  ```json
  {
    "jobs": [
      {
        "id": 4567890,
        "title": "Software Engineer, Inference",
        "location": {"name": "San Francisco, CA"},
        "absolute_url": "https://boards.greenhouse.io/anthropic/jobs/4567890",
        "updated_at": "2024-12-01T...",
        "content": "<p>HTML description...</p>",
        "departments": [{"name": "Research"}],
        "offices": [{"name": "San Francisco"}]
      }
    ]
  }
  ```
- **Notes**:
  - `content` is HTML, strip with simple regex `<[^>]+>` before sponsorship scan.
  - `updated_at` ≠ posted_at; do not use as freshness signal.
  - Some companies have multiple boards (e.g., NVIDIA has division-specific boards). Handle by allowing multiple Greenhouse entries per company name.

### 6.2 Ashby

- **Endpoint**: `GET https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true`
- **Auth**: none
- **Response shape**:
  ```json
  {
    "jobs": [
      {
        "id": "uuid-here",
        "title": "ML Engineer",
        "locationName": "Remote, US",
        "employmentType": "FullTime",
        "jobUrl": "https://jobs.ashbyhq.com/modal/uuid",
        "publishedDate": "2024-12-01T...",
        "descriptionHtml": "<p>...</p>",
        "department": "Engineering",
        "team": "Inference",
        "isRemote": true,
        "address": {"postalAddress": {"addressCountry": "US", ...}}
      }
    ]
  }
  ```
- **Notes**:
  - `publishedDate` is reliable for posted_at.
  - `isRemote` + `address.addressCountry` is more reliable than parsing `locationName`.

### 6.3 Lever

- **Endpoint**: `GET https://api.lever.co/v0/postings/{token}?mode=json`
- **Auth**: none
- **Response shape**: array of postings (not wrapped in `jobs` key).
  ```json
  [
    {
      "id": "uuid",
      "text": "Senior Software Engineer",
      "categories": {"location": "San Francisco", "team": "Engineering", "commitment": "Full-time"},
      "hostedUrl": "https://jobs.lever.co/cohere/uuid",
      "createdAt": 1700000000000,
      "descriptionPlain": "...",
      "lists": [{"text": "Requirements", "content": "..."}]
    }
  ]
  ```
- **Notes**:
  - `createdAt` is unix ms.
  - `descriptionPlain` is already clean text.
  - `categories.location` can be a comma-separated list like "SF, NYC, Remote".

### 6.4 Workday

The annoying one. Each company has its own tenant subdomain and site. The endpoint is a POST with an empty filter body that returns paginated job summaries; full description requires a second GET.

- **List endpoint**:
  ```
  POST https://{tenant}.wd1.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
  Content-Type: application/json
  Body: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
  ```
- **Detail endpoint**:
  ```
  GET https://{tenant}.wd1.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{externalPath}
  ```
- **Notes**:
  - Some tenants use `wd5.myworkdayjobs.com` instead of `wd1`. Include the subdomain version in config, e.g., `subdomain: wd5`.
  - Pagination via `offset`. Loop until `total` reached or empty page.
  - User-Agent header recommended; some Workday instances 403 on missing UA.
  - Be polite: 1 req/sec per tenant max. Use a per-tenant async semaphore.
  - Description fetch is per-job; only fetch for jobs that pass the title filter (saves ~90% of detail calls).

Workday config example:
```yaml
- name: NVIDIA
  ats: workday
  tenant: nvidia
  site: NVIDIAExternalCareerSite
  subdomain: wd1               # default: wd1
```

---

## 7. Filters

Filters are applied in order: role → seniority → location → sponsorship. Earliest-rejecting filter wins (cheapest to most expensive).

### 7.1 Role match (`filters/role.py`)

Title-only regex match. Description-based matching is too noisy.

```python
ROLE_INCLUDE = re.compile(
    r"\b("
    r"machine\s+learning|"
    r"\bml\b|mle\b|\bml[-\s]?eng|"
    r"inference|"
    r"mlsys|ml[-\s]?sys(tems)?|"
    r"ai\s+infra|ml\s+infra|ai[-\s]?infrastructure|"
    r"\bgpu\b|\bcuda\b|"
    r"performance\s+engineer|perf\s+engineer|"
    r"compiler|kernel\s+engineer|"
    r"software\s+engineer|swe\b|"
    r"backend\s+engineer|"
    r"distributed\s+systems|distributed\s+training|"
    r"platform\s+engineer|systems\s+engineer|"
    r"member\s+of\s+technical\s+staff|mts\b|"
    r"research\s+engineer|"
    r"forward\s+deployed\s+engineer|fde\b|"
    r"model\s+(deployment|serving)|"
    r"ml\s+platform"
    r")\b",
    re.IGNORECASE,
)

ROLE_EXCLUDE = re.compile(
    r"\b("
    r"intern\b|internship|"
    r"product\s+manager|pm\b|"
    r"designer|design\s+lead|ux|ui\s+(designer|engineer)|"
    r"sales|account\s+executive|ae\b|"
    r"marketing|growth\s+marketer|content\s+marketer|"
    r"recruiter|talent|people\s+ops|"
    r"finance|accounting|legal|paralegal|"
    r"customer\s+success|customer\s+support|"
    r"executive\s+assistant|admin\b"
    r")\b",
    re.IGNORECASE,
)
```

Logic: `match = ROLE_INCLUDE.search(title) and not ROLE_EXCLUDE.search(title)`.

### 7.2 Seniority (`filters/seniority.py`)

New-grad filter, applied after role match.

```python
SENIORITY_EXCLUDE = re.compile(
    r"\b("
    r"senior|sr\.|"
    r"staff|principal|"
    r"\blead\b|tech\s+lead|"
    r"director|head\s+of|"
    r"manager|management|engineering\s+manager|em\b|"
    r"\bvp\b|vice\s+president|"
    r"chief|executive"
    r")\b",
    re.IGNORECASE,
)

SENIORITY_INCLUDE_HINTS = re.compile(
    r"\b("
    r"junior|jr\.|"
    r"entry[-\s]?level|"
    r"new\s+grad|new\s+graduate|"
    r"university\s+grad|"
    r"early\s+career|"
    r"associate|"
    r"\bI\b|\bII\b"      # "Software Engineer I" / "II"
    r")\b",
    re.IGNORECASE,
)
```

Logic:
- If `SENIORITY_EXCLUDE` matches title → reject.
- Otherwise → accept (most new-grad jobs have neutral titles like "Software Engineer", "ML Engineer" with no level marker).

Don't *require* `SENIORITY_INCLUDE_HINTS`. Most acceptable jobs have no level word at all. Hints are only useful for tier-ranking later.

### 7.3 Location (`filters/location.py`)

```python
US_STATES = {  # 2-letter codes + full names; lower-case match
    "al", "alabama", "ak", "alaska", ...  # full list of 50 + DC
}

US_CITIES = {  # major hubs that frequently appear without state
    "san francisco", "sf", "new york", "nyc", "seattle", "boston",
    "los angeles", "la", "austin", "denver", "chicago", "atlanta",
    "washington dc", "san jose", "palo alto", "mountain view",
    "redwood city", "menlo park", "cambridge", "brooklyn",
    "bay area", "silicon valley",
}

US_GENERIC = {"united states", "usa", "u.s.", "u.s.a.", "us only",
              "remote - us", "remote (us)", "remote, us", "remote us",
              "us remote", "remote united states"}

NON_US_BLOCKERS = {  # if location ONLY contains these, reject
    "london", "berlin", "paris", "munich", "amsterdam", "dublin",
    "tel aviv", "tokyo", "singapore", "bangalore", "bengaluru",
    "hyderabad", "mumbai", "delhi", "pune", "shanghai", "beijing",
    "hong kong", "sydney", "melbourne", "toronto", "vancouver",
    "mexico city", "são paulo", "europe", "emea", "apac", "latam",
    "uk", "united kingdom", "germany", "france", "india", "china",
    "japan", "canada", "australia", "ireland", "netherlands",
}
```

Logic:
- Lowercase the location string.
- If it matches anything in `US_GENERIC | US_STATES | US_CITIES` → accept.
- Else if it contains "remote" (no qualifier) → check description for "US" / "United States" indicators; if found, accept; else reject (treat as "global remote", which often excludes US for visa reasons).
- Else if it matches anything in `NON_US_BLOCKERS` → reject.
- Else → accept (loose default; better false-positive than false-negative).

### 7.4 Sponsorship (`filters/sponsorship.py`)

Description text scan. Strip HTML first, lowercase.

```python
NO_SPONSOR_PATTERNS = re.compile(
    r"("
    r"no\s+(visa\s+)?sponsorship|"
    r"unable\s+to\s+(provide\s+)?sponsor|"
    r"cannot\s+(provide\s+)?sponsor|"
    r"do\s+(not|n['']t)\s+(provide\s+|offer\s+)?sponsor|"
    r"does\s+(not|n['']t)\s+(provide\s+|offer\s+)?sponsor|"
    r"will\s+not\s+(provide\s+|offer\s+)?sponsor|"
    r"won['']t\s+sponsor|"
    r"without\s+(needing\s+|requiring\s+)?(visa\s+)?sponsorship|"
    r"without\s+the\s+need\s+for\s+sponsorship|"
    r"must\s+be\s+(legally\s+)?authorized\s+to\s+work\s+in\s+the\s+(us|united\s+states)\s+(without|on\s+a\s+permanent)|"
    r"u\.?s\.?\s+citizen(ship)?\s+(required|only)|"
    r"must\s+be\s+a\s+u\.?s\.?\s+citizen|"
    r"must\s+be\s+a\s+citizen|"
    r"permanent\s+resident\s+(required|status\s+required)|"
    r"\bitar\b|"
    r"security\s+clearance"
    r")",
    re.IGNORECASE,
)
```

Logic: strip HTML → lowercase → if any match, reject.

False-positive watch: phrases like "we sponsor" or "sponsorship available" must not trigger. The patterns above are all explicit *negative* phrases, so they shouldn't, but log every rejection with the matched substring for spot-checking in week 1.

---

## 8. Dedupe & State

The single source of truth is the `seen` table.

### Per-cycle algorithm

```
fetched_jobs = []  # union across all fetchers
for each company in config:
    fetched_jobs += fetch(company)  # all in parallel via asyncio.gather

filtered = filter_pipeline(fetched_jobs)

# Compute new vs existing
fetched_ids = {j.id for j in filtered}
existing_ids = state.get_open_ids()  # all rows where closed_at IS NULL

new_ids = fetched_ids - existing_ids
closed_ids = existing_ids - fetched_ids

# Insert new
for j in filtered if j.id in new_ids:
    state.insert(j)

# Update last_seen for still-open
state.bulk_update_last_seen(fetched_ids & existing_ids)

# Mark closed
state.bulk_close(closed_ids)

# Notify only the new ones
notify(filtered_new_jobs)

# Mark notified
state.mark_notified(notified_ids)
```

### Bootstrap mode

`python -m src.main --bootstrap` does everything except notify. Inserts all currently-listed jobs as `notified=1` so the first real run only sends *truly new* ones.

This is the single most important UX detail. Without it, run 1 spams 200+ messages.

---

## 9. Discord Notifications

### Channel setup

One channel: `#jobs`. Posts go via the bot's REST API (not webhook) because we also need read-reactions later, and using the same auth for both is simpler.

### Message format

One message per cycle, batched by company. Each message has up to 10 embeds (Discord cap). If more than 10 jobs from a single company hit in one cycle (rare), split into multiple messages.

If the cycle has multiple companies with new jobs, send one message per company in tier order (tier 1 first), each with that company's new jobs as embeds.

```json
{
  "content": null,
  "embeds": [
    {
      "title": "Software Engineer, Inference",
      "url": "https://boards.greenhouse.io/anthropic/jobs/4567890",
      "color": 5814783,
      "fields": [
        {"name": "Company", "value": "Anthropic", "inline": true},
        {"name": "Location", "value": "San Francisco, CA", "inline": true},
        {"name": "Posted", "value": "<t:1700000000:R>", "inline": true}
      ],
      "footer": {"text": "id:greenhouse:anthropic:4567890"}
    }
  ]
}
```

Putting the namespaced job ID in the footer means we can reverse-lookup by parsing it later (for reaction sync). Alternative: store `discord_message_id → job_id` in DB at post time, which is cleaner. Do both — footer for human debugging, DB map for reaction sync.

### Color coding (optional)

- Tier 1 → blue (5814783)
- Tier 2 → green (5763719)
- Tier 3 → grey (10070709)

### Rate limit

Discord allows 50 requests / sec for a bot token, way more than we need. But add a 200ms `asyncio.sleep` between batched company posts to be safe.

---

## 10. Applied Tracking via Reactions

### `sync_reactions.py`

Runs as a second step in the same workflow, after `main.py`.

```
for each row in seen WHERE applied=0 AND notified=1 AND first_seen > now() - 30 days:
    if row.discord_message_id is None: skip
    GET /channels/{channel_id}/messages/{message_id}/reactions/✅
    if response is non-empty (any user reacted):
        UPDATE seen SET applied=1, applied_at=now() WHERE id=row.id
```

Don't iterate over *all* messages in the channel; iterate over `seen` rows that have a `discord_message_id` and are unapplied. Cuts API calls drastically.

After marking applied, optionally post a confirmation reaction back (e.g., 🎯 from the bot itself), but skip in v1 to keep things simple.

### Bot permissions needed

- View Channels
- Read Message History
- Send Messages
- Embed Links
- Add Reactions (only if posting back confirmations)

### Reaction conventions

- ✅ → applied (tracked in DB)
- 🚫 → not interested (mark `applied=1` + flag, suppresses any future fuzzy duplicates of same title at same company; v2 feature, log only in v1)
- 👀 → bookmarked / reviewing (v2, no-op in v1)

---

## 11. GitHub Actions

### `.github/workflows/poll.yml`

```yaml
name: poll

on:
  schedule:
    - cron: "*/30 * * * *"
  workflow_dispatch:               # manual trigger button
    inputs:
      bootstrap:
        description: "Bootstrap mode (no notifications)"
        type: boolean
        default: false

permissions:
  contents: write                  # for committing jobs.db back

concurrency:
  group: poll                      # never run two at once
  cancel-in-progress: false

jobs:
  poll:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - run: pip install -r requirements.txt

      - name: Fetch + filter + notify
        env:
          DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
          DISCORD_CHANNEL_ID: ${{ secrets.DISCORD_CHANNEL_ID }}
        run: |
          if [[ "${{ inputs.bootstrap }}" == "true" ]]; then
            python -m src.main --bootstrap
          else
            python -m src.main
          fi

      - name: Sync reactions
        env:
          DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
          DISCORD_CHANNEL_ID: ${{ secrets.DISCORD_CHANNEL_ID }}
        run: python -m src.sync_reactions

      - name: Commit state
        run: |
          git config user.name "job-tracker-bot"
          git config user.email "bot@users.noreply.github.com"
          git add jobs.db
          git diff --staged --quiet || \
            git commit -m "state: $(date -u +%Y-%m-%dT%H:%MZ) [skip ci]"
          git push
```

`[skip ci]` in the commit message prevents recursive workflow triggers (a state commit shouldn't trigger another poll run).

`concurrency` ensures two crons can't race on the same SQLite file.

### Secrets to set in GitHub repo settings → Secrets and variables → Actions

- `DISCORD_BOT_TOKEN`
- `DISCORD_CHANNEL_ID`

That's it. No DB credentials, no API keys.

### Free-tier math

GitHub Actions free for public repos = unlimited. For private = 2000 min/month. Each run ≈ 60–90 sec. 48 runs/day × 30 days = 1440 runs × 1.5 min = 2160 min/month. That's just over the private limit.

**Recommendation: keep the repo public.** The data (companies list, seen jobs) is not sensitive. Tokens stay in Actions secrets and are never written to disk.

---

## 12. State Persistence Strategy

Three options considered, pick #1:

1. **Commit `jobs.db` back to repo on every run.** Pros: durable, inspectable via `sqlite3 jobs.db` locally, full history in git. Cons: bloats repo over time. Mitigation: run `VACUUM` weekly, gitignore the WAL file, don't track `jobs.db-journal`.
2. Actions cache. Pros: faster. Cons: 7-day eviction, can be lost; not durable.
3. Actions artifact upload. Pros: durable for 90 days. Cons: requires download+upload step; harder to inspect.

Going with #1.

After ~6 months the SQLite file will probably be 5–10 MB. Negligible for git. If it bloats, prune `seen` rows where `closed_at < now() - 180 days` periodically.

---

## 13. Bootstrap Procedure

First run sequence:

1. Set up Discord bot, get token, get channel ID.
2. Push the initial repo with `companies.yaml` populated.
3. Set the two GitHub secrets.
4. Manually trigger the workflow with `bootstrap=true`. This populates `jobs.db` with all currently-open postings, marked as `notified=1`.
5. Verify `jobs.db` got committed back, and that no Discord messages were sent.
6. The next scheduled run (within 30 min) will fire normally and only notify on actually-new jobs.

If you skip step 4 you will get 200+ Discord pings on first run.

---

## 14. Seed Company List

Starter `companies.yaml` (50 entries). Edit/prune as you go.

```yaml
companies:
  # === Tier 1: AI labs / inference / model providers ===
  - { name: Anthropic,        ats: greenhouse, token: anthropic,         tier: 1 }
  - { name: OpenAI,           ats: greenhouse, token: openai,            tier: 1 }
  - { name: xAI,              ats: ashby,      token: xai,               tier: 1 }
  - { name: Mistral AI,       ats: ashby,      token: mistralai,         tier: 1 }
  - { name: Cohere,           ats: lever,      token: cohere,            tier: 1 }
  - { name: Hugging Face,     ats: lever,      token: huggingface,       tier: 1 }
  - { name: Perplexity,       ats: ashby,      token: perplexity,        tier: 1 }
  - { name: Character AI,     ats: greenhouse, token: characterai,       tier: 1 }

  # === Tier 1: Inference infra / serving ===
  - { name: Together AI,      ats: ashby,      token: togetherai,        tier: 1 }
  - { name: Fireworks AI,     ats: ashby,      token: fireworksai,       tier: 1 }
  - { name: Baseten,          ats: ashby,      token: baseten,           tier: 1 }
  - { name: Modal,            ats: ashby,      token: modal,             tier: 1 }
  - { name: Replicate,        ats: ashby,      token: replicate,         tier: 1 }
  - { name: Anyscale,         ats: greenhouse, token: anyscale,          tier: 1 }
  - { name: Lightning AI,     ats: greenhouse, token: lightningai,       tier: 1 }

  # === Tier 1: Hardware / accelerators ===
  - { name: Groq,             ats: greenhouse, token: groq,              tier: 1 }
  - { name: Cerebras,         ats: greenhouse, token: cerebrassystems,   tier: 1 }
  - { name: SambaNova,        ats: greenhouse, token: sambanova,         tier: 1 }
  - { name: Tenstorrent,      ats: greenhouse, token: tenstorrent,       tier: 1 }
  - { name: Modular,          ats: greenhouse, token: modular,           tier: 1 }
  - { name: Lambda Labs,      ats: greenhouse, token: lambdalabs,        tier: 2 }
  - { name: CoreWeave,        ats: greenhouse, token: coreweave,         tier: 2 }
  - { name: NVIDIA,           ats: workday,    tenant: nvidia,
      site: NVIDIAExternalCareerSite,                                    tier: 1 }

  # === Tier 2: Big AI-adjacent / data ===
  - { name: Databricks,       ats: greenhouse, token: databricks,        tier: 2 }
  - { name: Scale AI,         ats: greenhouse, token: scaleai,           tier: 2 }
  - { name: Pinecone,         ats: greenhouse, token: pinecone,          tier: 2 }
  - { name: Weaviate,         ats: greenhouse, token: weaviate,          tier: 3 }
  - { name: Snowflake,        ats: greenhouse, token: snowflake,         tier: 3 }
  - { name: Datadog,          ats: greenhouse, token: datadog,           tier: 3 }

  # === Tier 2: Application AI / agent cos ===
  - { name: Cursor,           ats: ashby,      token: cursor,            tier: 1 }
  - { name: Decagon,          ats: ashby,      token: decagon,           tier: 2 }
  - { name: Glean,            ats: greenhouse, token: glean,             tier: 2 }
  - { name: Notion,           ats: ashby,      token: notion,            tier: 2 }
  - { name: Linear,           ats: ashby,      token: linear,            tier: 3 }
  - { name: Vercel,           ats: ashby,      token: vercel,            tier: 3 }
  - { name: Ramp,             ats: ashby,      token: ramp,              tier: 3 }

  # === Tier 2: Big tech (eng/infra) ===
  - { name: Stripe,           ats: greenhouse, token: stripe,            tier: 2 }
  - { name: Airbnb,           ats: greenhouse, token: airbnb,            tier: 3 }
  - { name: Figma,            ats: greenhouse, token: figma,             tier: 3 }
  - { name: Brex,             ats: greenhouse, token: brex,              tier: 3 }
  - { name: Plaid,            ats: greenhouse, token: plaid,             tier: 3 }
  - { name: Robinhood,        ats: greenhouse, token: robinhood,         tier: 3 }

  # === Tier 2: Defense / systems ===
  - { name: Anduril,          ats: greenhouse, token: anduril,           tier: 2 }
  - { name: Palantir,         ats: greenhouse, token: palantir,          tier: 2 }
  - { name: Shield AI,        ats: greenhouse, token: shieldai,          tier: 3 }

  # === Tier 3: HFT / quant (high systems depth) ===
  - { name: Two Sigma,        ats: lever,      token: twosigma,          tier: 3 }
  - { name: Hudson River Trading, ats: greenhouse, token: hudsonrivertrading, tier: 3 }
  - { name: Jump Trading,     ats: greenhouse, token: jumptrading,       tier: 3 }
  - { name: Citadel,          ats: greenhouse, token: citadel,           tier: 3 }

  # === Tier 3: Other systems-y ===
  - { name: Confluent,        ats: greenhouse, token: confluent,         tier: 3 }
  - { name: MongoDB,          ats: greenhouse, token: mongodb,           tier: 3 }

filters:
  sponsorship_strict: true
```

**Verify before first run**: ATS tokens drift. Open each URL manually (`https://boards.greenhouse.io/{token}` etc.) to confirm the token resolves before committing. If a token is wrong, the fetcher will get a 404 and log a warning, but you won't get jobs from that company.

Some I'm uncertain on: `mistralai`, `characterai`, `togetherai`, `fireworksai`, `xai` — verify these specifically.

---

## 15. Edge Cases & Gotchas

1. **First-run spam.** Always bootstrap before enabling cron. (See §13.)
2. **Multi-board companies.** NVIDIA has multiple Greenhouse boards (one per division) plus Workday. Allow same company name with different ATS entries; dedupe at the title+location level if needed.
3. **`updated_at` lies.** Greenhouse's `updated_at` ticks when descriptions are edited. Use first-seen-by-our-system as the freshness signal, not the API field.
4. **HTML in descriptions.** Strip with `re.sub(r"<[^>]+>", " ", text)` then `re.sub(r"\s+", " ", text).strip()` before sponsorship scan. Don't use BeautifulSoup; not worth the dep.
5. **Workday rate limiting.** Some tenants 403 on >1 req/sec. Use `asyncio.Semaphore(1)` per Workday tenant.
6. **Workday subdomain variance.** `wd1` vs `wd5` vs `wd103` etc. Make `subdomain` a config field, default `wd1`.
7. **Title pattern false positives.** "Senior Manager, ML Strategy" matches `ml`. Seniority filter catches "senior". Watch for "AI Operations Manager" etc; if these slip through, add `operations\s+manager` to exclude list.
8. **`Software Engineer I/II/III`** — the Roman numerals look like noise but I = entry, II = mid, III = senior. Treat I and II as new-grad-acceptable. III as borderline; default reject.
9. **Member of Technical Staff.** No level word, often the role you actually want at OpenAI/Anthropic. Don't reject.
10. **Discord embed limits.** 6000 chars total per message, 10 embeds max, 256 char title, 1024 char field value. Trim if needed.
11. **Reaction sync misses recent reactions.** If a job is older than 30 days and you react, sync_reactions skips it. Adjust the window if needed.
12. **Repo permissions.** `permissions: contents: write` is required at workflow level for the commit-back to work. Without it the push silently fails.
13. **Concurrent crons.** `concurrency: { group: poll, cancel-in-progress: false }` queues runs instead of running them in parallel. Without this, two runs racing on `jobs.db` produces a corrupt commit.
14. **Time zones.** Store all timestamps in UTC. Format `<t:UNIX:R>` in Discord embeds for client-local relative time.
15. **Token rotation.** If Discord bot token leaks (e.g., via a stray log line), regenerate immediately and update the secret. Add `DISCORD_BOT_TOKEN` to a log filter so it's never printed.

---

## 16. Build Order

Suggested milestones for Claude Code to work through:

**M1 — skeleton (1–2 hours)**
- Repo layout, `requirements.txt`, `models.py`, `state.py` with schema migration on first run, `config.py` with pydantic validation.
- Working `main.py --bootstrap` that does nothing except open the DB and log "ready".

**M2 — Greenhouse fetcher + role filter only (1 hour)**
- `greenhouse.py` returning normalized Jobs.
- `role.py` filter.
- Local test: `python -m src.main` against 3 companies, prints filtered titles to stdout. No Discord, no DB writes yet.

**M3 — full filter pipeline (1–2 hours)**
- `seniority.py`, `location.py`, `sponsorship.py`.
- HTML stripping helper.
- `--dry-run` flag that prints what would be notified without writing DB or posting.

**M4 — DB writes + dedupe (1 hour)**
- `state.py` insert/update/close logic.
- Bootstrap mode skips notify but writes DB.
- `--bootstrap` integration test.

**M5 — Discord notifications (1–2 hours)**
- Bot token auth, post message with embeds, store `discord_message_id`.
- Batch by company, tier-ordered.

**M6 — Ashby + Lever + Workday fetchers (2–3 hours)**
- One at a time. Add a few companies per ATS to `companies.yaml`. Verify each fetcher in isolation before merging.

**M7 — GitHub Actions (1 hour)**
- `poll.yml` with cron + commit-back.
- Run on `workflow_dispatch` first, verify state commit. Then enable cron.

**M8 — Reaction sync (1 hour)**
- `sync_reactions.py`.
- Test by manually reacting ✅ on a real message, run sync, verify DB.

**M9 — full seed list, prod cron (30 min)**
- Verify all 50 ATS tokens.
- Bootstrap.
- Enable cron.

Total estimated build: ~10–14 hours of focused coding. Most of that is fetcher edge cases and Discord message formatting fiddling.

---

## 17. Manual Setup Checklist (do these BEFORE Claude Code starts)

- [ ] Create a Discord server (or use existing) with a `#jobs` channel.
- [ ] Go to https://discord.com/developers/applications → New Application → Bot tab → Reset Token, save token.
- [ ] In OAuth2 → URL Generator: scopes = `bot`, permissions = `View Channels`, `Send Messages`, `Embed Links`, `Read Message History`, `Add Reactions`. Use generated URL to invite bot to the server.
- [ ] In Discord client: enable Developer Mode (Settings → Advanced), right-click `#jobs` → Copy Channel ID.
- [ ] Create GitHub repo (public) `job-tracker`.
- [ ] In repo settings → Secrets and variables → Actions, add:
  - `DISCORD_BOT_TOKEN`
  - `DISCORD_CHANNEL_ID`
- [ ] In repo settings → Actions → General → Workflow permissions → set to "Read and write permissions".
- [ ] Verify a few ATS tokens by visiting `https://boards.greenhouse.io/{token}`, `https://jobs.ashbyhq.com/{token}`, etc.

After Claude Code finishes implementing:

- [ ] Push initial code.
- [ ] Trigger workflow manually with `bootstrap=true`.
- [ ] Verify `jobs.db` got committed.
- [ ] Verify zero Discord messages were sent.
- [ ] Wait for next scheduled run (or trigger again without bootstrap).
- [ ] Verify Discord starts receiving real new-job pings.
- [ ] React ✅ on one and verify next run marks it applied in DB.

---

## 18. Out of Scope for v1 (parking lot)

- LLM-based role scoring (e.g., Claude rating each job 1–5 for fit).
- Resume keyword overlap scoring.
- Custom scrapers for Google/Meta/Apple's non-Workday platforms.
- Slash commands (`/search`, `/mute company X`).
- Daily / weekly digests in addition to real-time.
- Web dashboard.
- Multi-user support.

These are all easy bolt-ons later. Don't build them in v1.
