
# Mongolia Tender Filter & Notifier (`tenderbot`)

Watches the Mongolian national e-procurement portal
([user.tender.gov.mn](https://user.tender.gov.mn/mn/invitation)), filters new
tender invitations against your own criteria, and sends you a **Telegram**
message for each match. Built because the site's own filters are unreliable.

---

## How it works

```
Playwright (solves Cloudflare)  →  parse rows  →  SQLite (dedupe)  →  filters  →  Telegram
```

1. **Scraper** (`tenderbot/scraper.py`) — the portal sits behind a Cloudflare
   *managed challenge* ("Just a moment…"). A plain HTTP request only ever sees
   the challenge page, so we drive a **real browser via Playwright**, which
   solves the JS challenge automatically. By default it drives your installed
   **Google Chrome** (`TENDERBOT_BROWSER_CHANNEL=chrome`) rather than
   Playwright's bundled `chrome-headless-shell`, because real Chrome passes the
   managed challenge far more reliably. A persistent profile (`.pw-profile/`)
   caches the `cf_clearance` cookie between runs, and failed loads retry with an
   increasing cooldown (Cloudflare escalates against rapid repeat hits from one
   IP, which decays with time). Pagination uses the site's own `changePage()`.

   > **Alternative source — the official API.** The code can instead pull from
   > `opendata.tender.gov.mn/api/invitation` (structured JSON, *no* Cloudflare)
   > if you obtain a Bearer token from the agency. Set `TENDER_API_TOKEN` in
   > `.env` and it is used automatically (`TENDERBOT_SOURCE=auto`), falling back
   > to scraping on any API error. Most robust if you can get a token;
   > otherwise scraping is the default and needs no registration.
2. **Storage** (`storage.py`) — SQLite keyed by each tender's stable numeric id
   (from its detail URL). You are only notified about **new** tenders or ones
   whose status / deadline / budget **changed** — never the same one twice.
3. **Filter engine** (`filters.py`) — checks each new tender against the rules
   in `filters.yaml`. Multiple independent rules; a tender is reported if it
   matches **any** rule.
4. **Notifier** (`notifier.py`) — one Telegram message per matching tender with
   name, code, budget, deadline, method, dates and a direct link. Rate-limited
   and 429-aware.

### Fields captured per tender
name, code (Урилгын дугаар), buyer (Захиалагчийн нэр), budget (₮),
procurement method (ХАА-ны журам), publish date, submission deadline, detail
URL. *(The public listing has no dedicated aimag/region column, so `region`
filtering is a best-effort text match against the buyer + name — see below.)*

---

## Quick start (local)

Requires **Python 3.10+**.

```bash
# 1. Install dependencies. The scraper drives your installed Google Chrome by
#    default; if you don't have Chrome, install Playwright's Chromium instead
#    (and set TENDERBOT_BROWSER_CHANNEL=chromium in .env).
pip install -r requirements.txt
python -m playwright install chromium   # fallback browser; harmless to install

# 2. Configure
cp .env.example .env            # then edit (Telegram token + chat id)
cp filters.example.yaml filters.yaml   # then edit your criteria

# 3. Test against the live site WITHOUT sending Telegram messages
python -m tenderbot --dry-run
```

`--dry-run` prints every matching tender to the console instead of sending
Telegram messages — use it to tune your filters against real, live data.

When you're happy:

```bash
python -m tenderbot --test-telegram   # confirm the bot can message you
python -m tenderbot --once            # one real cycle
python -m tenderbot --loop            # run forever (every TENDERBOT_INTERVAL_MINUTES)
```

> **First run is silent by design.** On an empty database the tool *seeds*
> every currently-listed tender without notifying, so a fresh deploy doesn't
> blast you with dozens of existing tenders. From the second run on you only
> get genuinely new ones. Pass `--notify-on-seed` to override.

---

## Writing filters (`filters.yaml`)

A list of independent rules. Within a rule, **every** condition you set must
pass (AND); a tender is reported if it matches **any** rule. Omit a condition to
ignore it. Full reference and examples are in
[`filters.example.yaml`](filters.example.yaml).

```yaml
- name: "Construction jobs in my budget"
  keywords: ["барилга", "засвар", "зураг төсөв"]
  keyword_logic: any          # "any" (default) or "all"
  budget_min: 50000000        # MNT
  budget_max: 2000000000

- name: "Anything from the water authority"
  buyers: ["Ус сувгийн удирдах газар"]
```

| Condition | Matches against | Notes |
|-----------|-----------------|-------|
| `keywords` + `keyword_logic` | tender **name** | case-insensitive |
| `budget_min` / `budget_max` | **budget** (MNT) | tenders with no parseable budget never satisfy a budget bound |
| `categories` | **procurement method** | substring, any-of |
| `buyers` | **buyer name** | substring, any-of |
| `regions` | **buyer + name** text | best-effort; the listing exposes no aimag field |

Edit the file and restart `--loop` (or just let the next `--once`/cron run pick
it up — it's re-read every cycle).

---

## Getting a Telegram bot token + chat id

1. In Telegram, message **@BotFather** → `/newbot` → follow prompts. It gives
   you a **token** like `123456789:ABCdef...`. Put it in `.env` as
   `TELEGRAM_BOT_TOKEN`.
2. Send any message to your new bot (search its @username, tap *Start*).
3. Get your **chat id**: open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and read
   `result[].message.chat.id` — or just message **@userinfobot**. Put it in
   `.env` as `TELEGRAM_CHAT_ID`.
4. Verify: `python -m tenderbot --test-telegram`.

---

## Configuration reference (`.env`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `TELEGRAM_BOT_TOKEN` | – | from @BotFather (required to send) |
| `TELEGRAM_CHAT_ID` | – | where to send (required to send) |
| `TENDERBOT_DB` | `data/tenders.db` | SQLite file |
| `TENDERBOT_FILTERS` | `filters.yaml` | rules file |
| `TENDERBOT_MAX_PAGES` | `3` | listing pages per run (20 tenders/page) |
| `TENDERBOT_HEADLESS` | `true` | set `false` to watch the browser locally |
| `TENDERBOT_BROWSER_CHANNEL` | `chrome` | `chrome`/`msedge`/`chromium` — real Chrome passes Cloudflare best |
| `TENDERBOT_SOURCE` | `auto` | `auto`/`api`/`scrape`; `auto` uses the API only if a token is set |
| `TENDER_API_TOKEN` | – | optional agency Bearer token → use the API instead of scraping |
| `TENDERBOT_INTERVAL_MINUTES` | `45` | gap between cycles in `--loop` |
| `TENDERBOT_NOTIFY_DELAY` | `1.5` | seconds between Telegram messages |

---

## Deploy runbook — cheap VPS (Ubuntu 22.04/24.04)

Tested target: Hetzner CX22 (~€4/mo) or any DigitalOcean/Vultr ~$5 box. ~1 GB
RAM is enough for headless Chromium at this volume.

```bash
# --- 1. System deps ---
sudo apt update && sudo apt install -y python3-venv python3-pip git

# --- 2. Get the code ---
git clone <your-repo-url> tenderbot && cd tenderbot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# --- 3. Install a browser for Playwright to drive ---
# Best Cloudflare success: real Google Chrome (keep TENDERBOT_BROWSER_CHANNEL=chrome)
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb
python -m playwright install-deps chromium   # shared libs Chrome/Chromium need
# …or, if you prefer the bundled Chromium, set TENDERBOT_BROWSER_CHANNEL=chromium
# in .env and run instead:  python -m playwright install --with-deps chromium

# --- 4. Configure ---
cp .env.example .env && nano .env                 # Telegram token + chat id
cp filters.example.yaml filters.yaml && nano filters.yaml

# --- 5. Seed + smoke-test once ---
python -m tenderbot --dry-run        # sanity-check filters against live data
python -m tenderbot --test-telegram  # confirm Telegram delivery
python -m tenderbot --once           # seeds the DB silently on first run
```

### Run it on a schedule

**Option A — built-in loop under systemd (recommended).** Survives reboots,
restarts on crash, one long-lived browser-friendly process.

Create `/etc/systemd/system/tenderbot.service`:

```ini
[Unit]
Description=Mongolia tender notifier
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOURUSER
WorkingDirectory=/home/YOURUSER/tenderbot
ExecStart=/home/YOURUSER/tenderbot/.venv/bin/python -m tenderbot --loop
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tenderbot
journalctl -u tenderbot -f          # watch logs
```

**Option B — cron** (one-shot every 45 min). Use `--once`; the persistent
profile keeps the Cloudflare cookie warm between runs:

```cron
*/45 * * * * cd /home/YOURUSER/tenderbot && .venv/bin/python -m tenderbot --once >> tenderbot.log 2>&1
```

### Free alternative — GitHub Actions

A scheduled workflow ($0) can run `--once` on a cron. Store the database as a
cached/committed artifact between runs (otherwise every run re-seeds and never
notifies), and put the Telegram token + chat id in repository **Secrets**. Note
GitHub's scheduled crons are best-effort and can be delayed under load; a €4
VPS is more reliable for time-sensitive tenders.

---

## Resilience & politeness

- A bad row, a down site, or an HTML change is logged and skipped — the loop
  keeps running rather than crashing (`--loop` catches per-cycle exceptions).
- The scraper retries the Cloudflare handshake a few times before giving up on
  a cycle.
- Realistic User-Agent, a single browser, small page counts, and a polite
  default 45-minute interval keep load on the source minimal.
- Everything is UTF-8; Mongolian Cyrillic tender names are handled throughout.

---

## Project layout

```
tenderbot/
├── tenderbot/
│   ├── cli.py        # argument parsing, --dry-run/--once/--loop/--test-telegram
│   ├── config.py     # .env + filters.yaml loading
│   ├── models.py     # Tender dataclass
│   ├── scraper.py    # Playwright + Cloudflare handling + pagination
│   ├── parser.py     # row text -> Tender (pure, unit-tested)
│   ├── storage.py    # SQLite + new/changed detection
│   ├── filters.py    # rule matching
│   ├── notifier.py   # Telegram delivery + message formatting
│   └── runner.py     # orchestration
├── tests/test_parser.py
├── filters.example.yaml
├── .env.example
├── requirements.txt
└── README.md
```

Run the parser tests with `python tests/test_parser.py` (or `pytest`).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Cloudflare challenge did not clear` | Usually transient IP throttling from rapid repeat hits; the scraper retries with a cooldown. If persistent: ensure `TENDERBOT_BROWSER_CHANNEL=chrome` (real Chrome passes best), delete `.pw-profile/`, wait ~15 min, or run `TENDERBOT_HEADLESS=false` locally to watch it. |
| `channel ... unavailable` / no Chrome | Install Google Chrome, or set `TENDERBOT_BROWSER_CHANNEL=chromium` and run `python -m playwright install chromium`. |
| No Telegram messages but matches found in `--dry-run` | Token/chat id missing or wrong → `python -m tenderbot --test-telegram`. |
| Flooded on first real run | You skipped the silent seed — let the first `--once` run seed, or it already did; only genuinely new tenders notify afterwards. |
| Want more/less coverage | Tune `TENDERBOT_MAX_PAGES`. |

---

## Fallback: the official API

An official REST API exists (`opendata.tender.gov.mn/api/invitation`) but
requires registering with the procurement agency for a Bearer token. Scraping
was chosen to avoid that. If scraping ever becomes too fragile, that API is the
robust fallback — the parsing/storage/filter/notify pipeline here would stay
the same; only `scraper.py` would be swapped for an API client.
```
