"""Orchestration: scrape -> detect new -> filter -> notify -> persist."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from .api_source import APIError, TenderAPIClient
from .config import FilterRule, Settings, load_filters
from .filters import matching_rules
from .models import Tender
from .notifier import TelegramNotifier, format_message
from .scraper import ScrapeError, scrape
from .storage import Storage

log = logging.getLogger("tenderbot.runner")


def fetch_tenders(settings: Settings) -> List[Tender]:
    """Fetch the current tenders from the configured source.

    In "auto" mode the API is preferred when a token is present (no Cloudflare,
    structured JSON) and we transparently fall back to scraping if the API
    call fails. Explicit "api"/"scrape" disable the fallback.
    """
    source = settings.resolved_source
    if source == "api":
        try:
            client = TenderAPIClient(settings.api_token, url=settings.api_url)
            want = max(1, settings.max_pages) * settings.per_page
            tenders = client.fetch_recent(want=want, per_page=settings.per_page)
            log.info("fetched %d tenders via API", len(tenders))
            return tenders
        except APIError as exc:
            if settings.source == "api":
                raise
            log.warning("API fetch failed (%s); falling back to scraping", exc)
    # scrape path
    tenders = scrape(max_pages=settings.max_pages, headless=settings.headless,
                     channel=settings.browser_channel)
    log.info("fetched %d tenders via scraping", len(tenders))
    return tenders


@dataclass
class RunResult:
    scraped: int
    new: int
    matched: int
    notified: int
    seeded: bool


def run_once(settings: Settings, *, dry_run: bool = False,
             notify_on_seed: bool = False) -> RunResult:
    """Execute a single scrape/filter/notify cycle.

    On the very first run against an empty database we *seed* (store every
    tender without notifying) so a fresh deploy does not blast dozens of
    historical tenders at you. Pass ``notify_on_seed=True`` to override.
    """
    rules: List[FilterRule] = load_filters(settings.filters_path)
    if not rules:
        log.warning("No filter rules loaded from %s — every new tender will "
                    "be reported.", settings.filters_path)

    try:
        tenders = fetch_tenders(settings)
    except (ScrapeError, APIError) as exc:
        log.error("fetch failed: %s", exc)
        return RunResult(0, 0, 0, 0, False)

    notifier: Optional[TelegramNotifier] = None
    if not dry_run and settings.telegram_ready:
        notifier = TelegramNotifier(
            settings.telegram_bot_token, settings.telegram_chat_id,
            delay=settings.notify_delay,
        )
    elif not dry_run and not settings.telegram_ready:
        log.warning("Telegram not configured; behaving as --dry-run.")

    with Storage(settings.db_path) as store:
        seeding = store.count() == 0 and not notify_on_seed
        new, changed = store.classify(tenders)
        log.info("new=%d changed=%d (db had %d)", len(new), len(changed), store.count())

        candidates = new + changed
        matched_count = 0
        notified_count = 0

        for tender in candidates:
            names = matching_rules(tender, rules) if rules else ["(no filters)"]
            should_report = bool(names)
            if should_report:
                matched_count += 1

            if seeding:
                store.upsert(tender)
                continue

            if should_report:
                if dry_run or notifier is None:
                    print(format_message(tender, names))
                    print("-" * 60)
                    store.upsert(tender)
                else:
                    ok = notifier.notify_tender(tender, names)
                    store.upsert(tender, mark_notified=ok)
                    if ok:
                        notified_count += 1
            else:
                store.upsert(tender)

        # Make sure every scraped tender is recorded (so unmatched ones are not
        # re-evaluated as "new" forever).
        seen = {t.tender_id for t in candidates}
        for tender in tenders:
            if tender.tender_id not in seen:
                store.upsert(tender)

        if seeding:
            log.info("seeded %d tenders without notifying (first run)", len(tenders))

        return RunResult(
            scraped=len(tenders),
            new=len(new),
            matched=matched_count,
            notified=notified_count,
            seeded=seeding,
        )
