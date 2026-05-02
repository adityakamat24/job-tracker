# Job Tracker — todo

Mirror of the approved plan (`C:\Users\twent\.claude\plans\eager-wiggling-crescent.md`).

## Phase 1 — Skeleton ✅
- [x] `requirements.txt`
- [x] `.gitignore`
- [x] `tasks/todo.md`
- [x] `tasks/lessons.md`
- [x] `src/__init__.py`, `src/models.py`, `src/utils.py`, `src/config.py`, `src/state.py`

## Phase 2 — Fetchers ✅
- [x] `src/fetchers/__init__.py`, `base.py`, `greenhouse.py`, `ashby.py`, `lever.py`, `workday.py`

## Phase 3 — Filters ✅
- [x] `src/filters/__init__.py`, `role.py`, `seniority.py`, `location.py`, `sponsorship.py`, `pipeline.py`

## Phase 4 — Discord + main entries ✅
- [x] `src/discord.py`, `src/main.py`, `src/sync_reactions.py`

## Phase 5 — Config + workflow + README ✅
- [x] `companies.yaml` (verified token corrections applied)
- [x] `.github/workflows/poll.yml`
- [x] `README.md`

## Phase 6 — Smoke test ✅
- [x] `python -m src.main --dry-run` — 5171 fetched → 544 final, no crashes
- [x] `python -m src.main --bootstrap` — DB populated, all rows `notified=1`
- [x] Inspected sponsorship rejections; only true positives remain (xAI ITAR, Scale TS/SCI)

---

## Review

### What got built
- 4 ATS adapters (Greenhouse, Ashby, Lever, Workday), all returning normalized `Job` objects.
- 4-stage filter pipeline (role → seniority → location → sponsorship), short-circuits on first reject.
- SQLite state with seen/run_log schema, bootstrap-aware insert, dedupe via `closed_at`.
- Discord client (just httpx, no library); batched embeds at ≤10 per message, tier-colored, 200 ms throttle, 429 handling.
- `main.py` orchestrator: parallel fetch via `asyncio.gather`, per-tenant Workday semaphore, deferred description fetch for Workday survivors only.
- `sync_reactions.py` ✅-tracker over `unapplied_recent` rows (no full-channel scan).
- GitHub Actions workflow with cron, manual bootstrap input, `[skip ci]` state commits, concurrency lock.

### Smoke test numbers
```
fetched=5171 (24 companies)
  → role_ok=1268 (-3903 cheap rejects)
  → seniority_ok=708 (-560 senior/staff/lead/manager/etc.)
  → location_ok=546 (-162 non-US)
  → final=544 (-2 sponsorship)
```
End-to-end run was ~3 min wall-clock — most of that is Workday's 1 req/sec serialization (~50 pages × 1 s × 2 round-trips for NVIDIA).

### Decisions worth flagging
- Verified the suspect ATS tokens during planning. ~11 needed corrections (OpenAI, xAI, Mistral, Cohere, Character AI, Together AI, Fireworks AI, Anyscale, Pinecone, Lambda Labs, SambaNova) and 1 needed an ATS we don't support (Hugging Face → Workable). Companies that didn't resolve on a first guess are commented out in `companies.yaml` under a `# TODO: verify` block — bootstrap surfaces 404s gracefully via fetcher logs.
- NVIDIA Workday is on `wd5`, not the spec's default `wd1`. Subdomain is now a config field.
- Workday's `total` field only appears on page 1 — pagination uses `len(postings) < page_size` as the exit condition.
- Filter regexes from the spec had two real bugs (sponsorship missed "do not provide visa sponsorship"; seniority rejected "Member of Technical Staff" on the word "Staff"). Both fixed; lessons captured in `tasks/lessons.md`.
- 2-letter US state codes substring-matching foreign cities (`or` ⊂ Bangalore, `mo` ⊂ Remote, etc.) was a real false-positive class. Switched location matching to whole-word.
- Added a softening guard for security-clearance/ITAR rejections — "not required, but a plus" no longer triggers.
- Mistral leaves `locationName` empty and encodes the city in the title; added a title-fallback for non-US blocker matching.

### Cleanup follow-ups (not blocking)
1. Verify the rest of the spec §14 seed companies (Groq, Anduril, Palantir, Snowflake, Datadog, Two Sigma, etc.). Most are likely on Workday and need `tenant`/`site`/`subdomain` discovery — the URL bar on each company's careers page gives all three.
2. Consider a Workable adapter to unlock Hugging Face (and others — Workable hosts a lot of small/mid AI cos).
3. The sponsorship reject for "Mistral Forward Deployed in EMEA" (description mentions "high-level security clearance") is borderline — the role *is* in EMEA, so it's the right outcome, but it gets there via the wrong filter. Worth a closer look once real ping volume is observable.
4. Workday's 50-page cap (1000 jobs/tenant/cycle) is enough for v1 but not for permanent. NVIDIA reports 2000 — we miss the back half. Bumping `_MAX_PAGES` is fine if cycle time stays under the 10-min CI budget.

---

## Coverage expansion pass (post-spec)

### What changed
- Added a **Workable** adapter (`src/fetchers/workable.py`) — unlocks Hugging Face and other AI-startup-heavy companies. ATS enum, config validator, and registry all updated. Known limitation: widget API doesn't expose descriptions, so Workable jobs bypass the sponsorship filter (documented in README + lessons).
- Bumped `WorkdayFetcher._MAX_PAGES` from 50 → 100 so NVIDIA-tier orgs get full coverage (2000 jobs / 20 per page = 100 pages).
- Fixed the Workday detail URL construction — `externalPath` already starts with `/job/`, double-prefixing was producing `/job/job/...` and 406'ing.
- Spawned 4 parallel research agents covering: AI labs / AI infra / hardware-robotics-biotech / big-tech-fintech-defense. Total verified: **124 companies** (up from 25), spanning 5 ATSes.

### Coverage stats (post-expansion)
- companies.yaml: **124 verified** (29 tier-1, 84 tier-2, 11 tier-3) across greenhouse/ashby/lever/workday/workable.
- Dry-run funnel: fetched=13413 → role_ok=2971 → seniority_ok=1279 → location_ok=937 → final=933.
- Wall-clock: ~5m20s for full cycle (fits the 10-min CI budget).

### Still parked
- iCIMS / SmartRecruiters / JobVite adapters (each is 50-100 LOC and unlocks 10-30 more cos; biggest gap is iCIMS for big enterprise)
- Workday-tenant discovery for the TODO block in companies.yaml (Anduril, Palantir, Snowflake, Cloudflare, HashiCorp, Atlassian, Block, Plaid, CrowdStrike, etc. — all known Workday users, just need someone to grab `tenant`/`site` from each careers URL)
- HFT firms (Citadel, Two Sigma, HRT, etc.) mostly use closed/internal systems; would need custom scrapers
- Workable description fetching (would need spi/v3 + per-tenant API token; out of scope)

---

## Coverage expansion v2 (188 sources)

### What changed
- Added **SmartRecruiters** adapter (`src/fetchers/smartrecruiters.py`) — paginates `https://api.smartrecruiters.com/v1/companies/<token>/postings`, defers per-job description fetch via the `ref` URL only for jobs that survive the title filter.
- Added **GitHubList** "fetcher" (`src/fetchers/github_list.py`) — pulls curated job lists from public GitHub READMEs. Supports BOTH markdown pipe-tables (vanshb03) and HTML `<table>` tags (SimplifyJobs). Handles `↳` continuation rows, skips closed (🔒) entries, parses relative ages (`5d`, `2mo`) and absolute dates (`Apr 25`).
- Added **cross-source dedupe** in `main.py` — collapses `(company, title)` collisions across fetchers, preferring entries with non-empty descriptions.
- Added **emoji rejections** to role filter — 🇺🇸 (US-citizen-only) and 🛂 (no-sponsorship) flagged in title get rejected at the cheapest filter stage.
- 5 parallel research agents covered: YC W24/W25/S24/S25 batches, crypto/Web3, climate/industrial, deeper robotics/biotech-AI, Workday tenant discovery.

### Coverage stats
- companies.yaml: **188 sources** across 7 ATS types (greenhouse 83, ashby 91, lever 4, workable 3, workday 4, smartrecruiters 1, github_list 2).
- Funnel (latest dry-run): fetched 19,943 → cross-source dedupe → 16,690 → role 3,477 → seniority 1,839 → location 1,480 → final **1,430 candidates** (up from 933 in v1).
- Wall-clock: ~6m17s (still inside 10-min CI budget).

### Bug fixes during expansion
- `src/fetchers/workday.py`: detail URL was double-prefixing `/job/job/...` and 406'ing — fixed by detecting if `externalPath` already starts with `/job`.
- 3 stale tokens removed/corrected (Plus.ai unresolvable, Unify unresolvable, Arcade moved greenhouse → ashby).
- 4 lessons added to `tasks/lessons.md` (curated-list shortcut, HTML table parsing, Workday URL fix, Workable description gap).

### Notable additions worth highlighting
- DeepMind (greenhouse), Visa (smartrecruiters), Mercury, Webflow, Zapier
- Crypto top tier: Alchemy, Uniswap Labs, Phantom, Polygon, Gemini, Ripple, ConsenSys, OpenSea, Paradigm, a16z crypto, Ledger
- Climate top tier: Form Energy, Helion, Twelve, Boston Metal
- Robotics/biotech: Recursion, Applied Intuition, Roivant, Iterative Health, Abridge, Cradle, Pony.ai
- Workday wins: CrowdStrike, Boeing, Target
- Late discovery: Kraken (ashby), Anchorage Digital (lever)
