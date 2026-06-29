# CLAUDE.md — Mongolia Tender Filter & Notifier

## What we're building
A tool that watches Mongolian government tenders, filters them against my saved
criteria, and sends me a Telegram message whenever a new tender matches. The
official site's own filters don't work reliably, so this replaces them.

This file is the project spec / handoff. Read it fully before writing code.

## Source
- Primary target: **tender.gov.mn / user.tender.gov.mn** (the national
  e-procurement portal). Scrape the public tender listing.
- An official REST API also exists (`opendata.tender.gov.mn`) but requires
  registering with the agency for a Bearer token. We chose **scraping** to avoid
  that bureaucracy. Keep the API in mind as a fallback if scraping proves
  fragile.
- **First task before coding:** inspect the live listing page. Determine whether
  it is plain server-rendered HTML or JS-rendered. That decides the tool:
  - Plain HTML → `requests` + `BeautifulSoup` (preferred, lightweight)
  - JS-rendered → `Playwright` headless (heavier but necessary)
  - Note: direct fetches got bot-blocked during planning, so expect to set a
    realistic User-Agent and possibly throttle / use Playwright.

## Core components
1. **Scraper** — pulls each tender's fields from the listing on a schedule.
   Target fields: tender name, tender code, budget/estimated value, tender
   type/category, region (aimag/soum), publish date, submission deadline,
   open date, status, and the tender detail URL.
2. **Storage** — SQLite. Key each tender by its unique code/ID so we only
   notify on *new* tenders or *status changes*, never re-notify the same one.
3. **Filter engine** — checks each new tender against saved criteria. Must
   support, individually and in combination:
   - keyword match in tender name
   - budget range (min/max)
   - category/type + region (aimag)
   Filters should live in a simple editable config (e.g. `filters.yaml` or
   `filters.json`) so I can change criteria without touching code. Support
   multiple independent filter rules (each can fire its own notification).
4. **Notifier** — Telegram bot. One message per matching tender, including
   name, budget, deadline, category, region, and a direct link. Group or
   rate-limit sensibly if many match at once.

## Scheduling & hosting
- Runs continuously, scrape every **30–60 minutes** via cron (or an internal
  scheduler like APScheduler).
- Target deploy: a cheap VPS (Hetzner ~€4/mo or DigitalOcean/Vultr ~$5–6/mo).
  GitHub Actions scheduled workflow is an acceptable $0 alternative.
- I want **minimal involvement**: build it end-to-end, then give me a short
  deploy runbook. The only values I should need to supply are the Telegram bot
  token, my chat ID, and my filter criteria.

## Secrets / config
- Telegram bot token + chat ID via environment variables or a `.env` file
  (never hardcoded, never committed). Provide a `.env.example`.
- Filter criteria in the editable config file described above.

## Deliverables
- Working scraper + filter + SQLite + Telegram notifier in a clean git repo.
- `requirements.txt` (or `pyproject.toml`).
- `.env.example` and a sample `filters` config.
- `README.md` with: how it works, how to set filters, how to get a Telegram bot
  token + chat ID, and a step-by-step VPS deploy + cron runbook.
- A way to test locally against the live site before deploying (e.g. a
  `--dry-run` that prints matches instead of sending Telegram messages).

## Constraints / notes
- Be polite to the source: realistic User-Agent, throttle requests, don't hammer.
- Handle the site being down or HTML changing without crashing the whole loop;
  log errors and continue.
- Language: site content is largely Mongolian (Cyrillic) — handle UTF-8
  throughout and don't assume ASCII in tender names.

## Status
Planning done. Implementation not started. Begin by inspecting the live site
structure, then propose the file layout before writing the bulk of the code.