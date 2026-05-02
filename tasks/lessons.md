# Lessons

Patterns to remember and rules to follow when working on this project. Update after every correction.

## ATS tokens drift — verify before committing
**Rule:** Never trust a hand-written ATS token list. Half of them will be wrong, and the wrong ones are not always the "weird" ones.

**Why:** During initial planning I verified ~30 tokens from `SPEC.md` §14. Roughly 11 were wrong — including big ones like `openai`, `cohere`, `xai`, `mistral`, `pinecone`, `lambda`. Several were on a different ATS than the spec claimed (e.g., OpenAI is on Ashby, not Greenhouse; xAI is on Greenhouse, not Ashby).

**How to apply:** When adding a company, hit the API directly (`https://boards-api.greenhouse.io/v1/boards/<token>/jobs` etc.) before committing the YAML entry. If the obvious guess 404s, try the other ATSes before assuming the company doesn't have a public board.

## Some companies aren't on any of the 4 supported ATSes
**Rule:** If a company isn't on Greenhouse / Ashby / Lever / Workday, don't silently drop them — comment them out in `companies.yaml` with the ATS they actually use.

**Why:** Hugging Face is on Workable. The spec doesn't include a Workable adapter, but the user (or future-me) might want to add one. A comment makes it discoverable; a deletion doesn't.

**How to apply:** When verification reveals a non-supported ATS, leave the company in `companies.yaml` as a commented line: `# - Hugging Face — uses Workable, no adapter yet`.

## Many AI-adjacent companies are on Workday
**Rule:** When a Greenhouse/Ashby/Lever guess 404s for a big-name company, default to suspecting Workday before suspecting "wrong token".

**Why:** Anduril, Palantir, Snowflake, NVIDIA — all on Workday. Workday tenants need `tenant`, `site`, and sometimes a non-default `subdomain` (wd5, wd103). The 404 from Greenhouse won't tell you that.

**How to apply:** Check the company's careers page in a browser; the URL pattern `<tenant>.wd<N>.myworkdayjobs.com/<site>` gives you all three config fields.

## Workday's `total` field only appears on page 1
**Rule:** Don't use `payload["total"]` as a paging exit condition past the first request. Use `if not postings` and `if len(postings) < page_size` instead.

**Why:** First request returns `{"total": 2000, "jobPostings": [...20]}`; subsequent requests return `{"total": 0, "jobPostings": [...20]}`. A naive `offset >= total` check stops after page 2 with only 40 of the 2000 jobs.

**How to apply:** Cache `total` from the first page if you want a hard cap; otherwise just keep paging until the response array shrinks.

## Adding a new ATS source must never flood the channel
**Rule:** Don't depend on user discipline ("remember to bootstrap when adding companies"). Auto-detect first-touch sources and silently absorb them.

**Why:** Twice in two days, a user added new companies and triggered a normal cron run, which treated every still-open job at those companies (months-old listings included) as "new" and tried to ping all of them. 200+ Discord messages floods the channel and overwhelms the user. Manual bootstrap discipline doesn't scale across multiple add-companies sessions.

**How to apply:** Before computing new-vs-existing in `main.py`, query `state.get_known_source_keys()` (a set of `"ats:slug"` strings derived from the namespaced job ID prefixes already in seen). For any new_job whose source key isn't in known_sources, insert as `notified=True` immediately — bypass Discord entirely. Log it as "first-touch source auto-bootstrapping". The first real cron tick after adding a source becomes a silent absorption, not a flood.

**Second line of defense:** A `MAX_NOTIFY_PER_RUN` cap (default 50) trips if a normal run still wants to notify too many jobs even after first-touch protection. On trip: mark all as notified=1 silently, log loudly, force operator investigation. Bootstrap mode is exempt from the cap.

## "Engineer 4" / "Engineer III" / "Engineer L5" titles slip past keyword-only seniority filters
**Rule:** Numbered seniority levels — arabic (3-9), roman (III-X), and L-prefix (L3+) — must be in the seniority exclude list. They're invisible to the standard "senior/staff/lead/manager" word-list because the level IS the seniority signal at companies like Adobe (uses 1-5), Google/Meta (uses L3-L7), Amazon (uses SDE I-III).

**Why:** Adobe's "Machine Learning Engineer 4" job — JD says "5+ years experience" — sailed past my seniority filter because the title has no "Senior" word. Same trap for "Software Engineer III" (spec §15.8 actually called this out — "III as borderline; default reject" — but I forgot to wire it up).

**How to apply:** Add to seniority exclude:
- `engineer|scientist|developer|architect|swe|sde|mle|sre|researcher|analyst` followed by:
  - `I{3,}|IV|V|VI|VII|VIII|IX|X` (roman 3-10)
  - `[3-9]` (arabic 3-9; preserve I/II and 1/2 as new-grad-acceptable)
- Standalone `L[3-9]` or `L1[0-9]` (Google/Meta level naming)
- Anchor each role-word match with whitespace + level so we don't catch unrelated digits ("Engineer for AI 2026 Cohort" should still pass).

## Spec regex patterns need unit verification, not blind trust
**Rule:** Even when the spec says "copy verbatim", run the patterns through hand-crafted positive/negative cases before declaring the filter done.

**Why:** Two real bugs slipped past the spec author:
1. Sponsorship pattern `do\s+(not|n['']t)\s+(provide\s+|offer\s+)?sponsor` doesn't catch the very common "do not provide **visa** sponsorship" because nothing allows "visa" between "provide" and "sponsor". Fix: insert `(visa\s+)?`.
2. Seniority pattern rejects "Member of Technical Staff" because of the word "Staff", but spec §15.9 explicitly says don't reject MTS. Fix: strip the MTS phrase before the seniority check.

**How to apply:** For any pattern in `src/filters/`, write at least ~5 hand-crafted (input, expected) pairs and run them as part of the verify step. Add new pairs whenever a real-world miss surfaces.

## Curated GitHub job lists are a high-leverage shortcut for new-grad SWE coverage
**Rule:** Don't try to verify every YC startup individually. SimplifyJobs/New-Grad-Positions and vanshb03/New-Grad-2026 between them already curate ~900 active new-grad SWE roles, updated multiple times daily. A `github_list` fetcher that parses the README markdown gives you company coverage that direct ATS scraping never will (most small startups use iCIMS, BambooHR, etc. that we don't support).

**Why:** During the v2 expansion, agents brainstormed ~150 candidate companies and verified ~80. Adding the 2 GitHub lists ALSO surfaced ~900 SWE roles, of which ~500 were unique after cross-source dedupe — a 5× boost from one extra fetcher.

**How to apply:** When coverage feels thin, look at what curated lists exist on GitHub for your job category. Markdown table or HTML `<table>` parsing is ~50 LOC. Trade-off: no description body → sponsorship filter degrades to pass-through → rely on title-level emoji flags (🇺🇸 / 🛂) and curator quality.

## SimplifyJobs uses HTML `<table>` not markdown pipes
**Rule:** When parsing curated README tables, support BOTH markdown pipe-tables and HTML `<table>` syntax. Don't assume one format.

**Why:** vanshb03/New-Grad-2026 uses standard markdown `| col | col |` rows. SimplifyJobs/New-Grad-Positions uses inline `<table>/<tr>/<td>` HTML elements with style attributes (the GitHub README renderer accepts both). A markdown-only parser silently returns 0 jobs from SimplifyJobs.

**How to apply:** Try markdown parser first; if it returns no rows, fall back to a regex-based HTML `<tr>/<td>` extractor. Pattern: `<tr>...</tr>` then `<t[dh]>...</t[dh]>` for cells. Strip inner HTML (`<strong>`, `<a>`, `<img>`) when extracting cell text.

## Workday's `externalPath` already starts with `/job/` for detail URLs
**Rule:** Build detail URLs as `f"{base}{external_path}"`, not `f"{base}/job{external_path}"`. The `/job/` prefix is already in `externalPath`.

**Why:** Workday's detail endpoint at `/wday/cxs/<tenant>/<site>/job/<...>` returns 406 Not Acceptable if you double-prefix to `.../job/job/<...>`. NVIDIA's detail backfill silently failed across all jobs until this was caught.

**How to apply:** Defensive: `suffix = path if path.startswith("/job") else f"/job{path}"`.

## Workable's widget API doesn't expose job descriptions
**Rule:** Don't rely on the sponsorship filter for Workable jobs. The widget API at `apply.workable.com/api/v1/widget/accounts/<token>` returns title + location + URL but no description body — the description is loaded via authenticated XHR after page render.

**Why:** Workable splits its API into a public *widget* tier (no description) and an authenticated *spi/v3* tier (full data, requires per-tenant token). Without the auth tier, jobs come through with `description=""`. The sponsorship filter is built to pass empty descriptions through (better false-positive than false-negative), so Workable jobs reach Discord without any sponsorship vetting.

**How to apply:** When adding more Workable companies, accept that they bypass the sponsorship gate. The location filter (which has a title-fallback for empty `locationName`) does the heavy lifting for non-US rejection. If you really want sponsorship filtering for a specific Workable company, either fall back to fetching the HTML detail page and grepping for sponsorship keywords, or wire up the spi/v3 endpoint with the tenant's API token.

## Workday's `externalPath` already starts with `/job/`
**Rule:** When building a Workday job-detail URL from `externalPath`, don't prepend `/job` — `externalPath` is `/job/...` already, and double-prefixing produces `/job/job/...` which 406s.

**Why:** I originally wrote `f"{base}/job{external_path}"` based on a Workday docs snippet I half-remembered. Real `externalPath` values look like `/job/US-CA-Santa-Clara/Some-Title_JR123` — already prefixed. The detail endpoint then 406s on `/wday/cxs/<tenant>/<site>/job/job/...`.

**How to apply:** Build the URL as `f"{base}{external_path}"` if `external_path.startswith("/job")`, otherwise `f"{base}/job{external_path}"` as a fallback. Verify by hitting one detail URL manually and confirming `jobPostingInfo` is in the response.

## Many "obvious" ATS guesses are wrong even after research
**Rule:** Token discovery isn't a one-and-done. Even after a thorough verification pass, ~5-10% of entries will still 404 in production because tokens drift between research time and your run.

**Why:** During the comprehensive expansion pass, agents verified ~150 companies via WebFetch. After consolidating, the first real bootstrap surfaced 7 fresh 404s — Crusoe (had moved greenhouse → ashby), Weaviate (greenhouse → ashby), Confluent (greenhouse → ashby), Fireblocks (ashby → greenhouse), and 3 others (RunPod, Comet ML, Rabbit) that had no resolvable token at all. Tokens drift; companies migrate ATSes.

**How to apply:** Bootstrap is the real verification step. Treat the "WARNING ... HTTP 404" lines in the first run as a punch-list — fix or comment out each one before relying on the cron. Recurring 404s on the same entry over multiple runs mean the company has fully changed ATSes; re-discover.

## 2-letter state codes substring-match foreign city names
**Rule:** Match US state codes / hubs as whole words, never as substrings.

**Why:** `or` (Oregon) is a substring of "Bangalore". `ga` (Georgia) → "Bangalore". `nd` (North Dakota) → "London". `mo` (Missouri) → "Remote". `al` (Alabama) → "Bangalore". A naive `if hub in piece` check passes London, Bangalore, and Remote as US locations.

**How to apply:** Use word-boundary regex matching: `re.search(rf"(?<![a-z]){re.escape(hub)}(?![a-z])", text, re.IGNORECASE)`. Plain `\b` is unreliable for two-letter ascii tokens because the boundary can fire inside other words too.
