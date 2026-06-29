"""Playwright-based scraper for user.tender.gov.mn.

Why Playwright and not requests+BeautifulSoup: the portal sits behind a
Cloudflare "managed challenge" (the "Just a moment…" interstitial). A plain
HTTP client only ever receives the 403 challenge page, never the listing. A
real browser engine solves the JS challenge automatically, so Playwright is
required rather than optional.

The scraper:
  1. Opens a persistent browser context (so the ``cf_clearance`` cookie is
     reused between runs, minimising challenges).
  2. Navigates to the invitation listing and waits for the challenge to clear.
  3. Reads each row's text + links via the page DOM and parses them.
  4. Walks pages by invoking the site's own ``changePage(n, perPage)`` JS,
     which is more robust than reverse-engineering the AJAX payload.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

from .models import Tender
from .parser import parse_row

log = logging.getLogger("tenderbot.scraper")

BASE = "https://user.tender.gov.mn"
LISTING_URL = f"{BASE}/mn/invitation"
WARMUP_URL = "https://tender.gov.mn/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# Markers in the page <title> that mean the interstitial is showing.
_CHALLENGE_TITLE_MARKERS = ("just a moment", "performing security verification",
                            "checking your browser", "attention required")
# Stronger markers checked against the (short) body of the interstitial. These
# are specific enough not to false-positive on the real listing.
_CHALLENGE_BODY_MARKERS = ("verifying you are human", "performing security verification",
                           "checking your browser before", "enable javascript and cookies")


class ScrapeError(RuntimeError):
    pass


def _challenge_present(page: Page) -> bool:
    title = (page.title() or "").lower()
    if any(m in title for m in _CHALLENGE_TITLE_MARKERS):
        return True
    try:
        body = page.evaluate(
            "() => document.body ? document.body.innerText.slice(0, 500).toLowerCase() : ''")
    except Exception:
        return False
    return any(m in (body or "") for m in _CHALLENGE_BODY_MARKERS)


def _wait_for_challenge(page: Page, timeout: float = 35.0) -> bool:
    """Poll until the Cloudflare interstitial clears. Returns True on success."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _challenge_present(page):
            return True
        time.sleep(2.0)
    return not _challenge_present(page)


@contextmanager
def browser_page(headless: bool = True, profile_dir: str = ".pw-profile",
                 channel: str = "chrome") -> Iterator[Page]:
    """Yield a ready Page using a persistent context for cookie reuse.

    ``channel`` selects the browser binary: "chrome"/"msedge" drive the real
    installed browser (far better at passing Cloudflare managed challenges than
    the bundled ``chrome-headless-shell``); "" or "chromium" uses Playwright's
    bundled Chromium. We fall back to bundled Chromium if the channel is
    unavailable.
    """
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    args = ["--disable-blink-features=AutomationControlled"]
    launch_kwargs = dict(
        user_data_dir=profile_dir,
        headless=headless,
        locale="mn-MN",
        user_agent=USER_AGENT,
        viewport={"width": 1366, "height": 768},
        args=args,
    )
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                channel=(channel or None), **launch_kwargs)
        except Exception as exc:
            if channel and channel != "chromium":
                log.warning("channel %r unavailable (%s); using bundled chromium",
                            channel, str(exc).splitlines()[0])
                ctx = p.chromium.launch_persistent_context(**launch_kwargs)
            else:
                raise
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            yield page
        finally:
            ctx.close()


def _read_rows(page: Page) -> List[Tender]:
    """Read and parse every visible tender row on the current page."""
    raw = page.evaluate(
        """() => {
            const rows = [...document.querySelectorAll('table tbody tr')];
            return rows.map(r => ({
                cells: [...r.querySelectorAll('td')].map(td => td.innerText),
                links: [...r.querySelectorAll('a')].map(a => a.href),
            }));
        }"""
    )
    tenders: List[Tender] = []
    for item in raw:
        try:
            t = parse_row(item.get("cells", []), item.get("links", []))
        except Exception as exc:  # never let one bad row kill the batch
            log.warning("failed to parse a row: %s", exc)
            continue
        if t:
            tenders.append(t)
    return tenders


def _goto_listing(page: Page, attempts: int = 4, cooldown: float = 20.0) -> None:
    """Load the listing, retrying with an increasing cooldown.

    Cloudflare escalates challenge difficulty when an IP makes many rapid
    requests; the escalation decays with time, so we back off (cooldown,
    2*cooldown, 3*cooldown…) between attempts rather than hammering. A reload
    is cheaper than a fresh navigation, so retries reload in place first.
    """
    last_err = "unknown"
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            wait_s = cooldown * (attempt - 1)
            log.info("cooling down %.0fs before retry %d/%d", wait_s, attempt, attempts)
            time.sleep(wait_s)
        try:
            # Warm up on the apex domain first; it reliably solves the challenge
            # and sets the clearance cookie covering the user. subdomain.
            page.goto(WARMUP_URL, wait_until="domcontentloaded", timeout=45000)
            _wait_for_challenge(page, timeout=45)
            page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
            if not _wait_for_challenge(page, timeout=50):
                # One in-place reload often clears a challenge that the first
                # navigation didn't finish solving.
                try:
                    page.reload(wait_until="domcontentloaded", timeout=60000)
                    _wait_for_challenge(page, timeout=50)
                except PWTimeout:
                    pass
            if _challenge_present(page):
                last_err = "Cloudflare challenge did not clear"
                log.warning("attempt %d/%d: %s", attempt, attempts, last_err)
                continue
            page.wait_for_selector("table tbody tr", timeout=25000)
            return
        except PWTimeout as exc:
            last_err = f"timeout: {exc}"
            log.warning("attempt %d/%d navigation failed: %s", attempt, attempts, last_err)
    raise ScrapeError(f"could not load listing after {attempts} attempts: {last_err}")


def scrape(max_pages: int = 3, headless: bool = True,
           profile_dir: str = ".pw-profile", channel: str = "chrome") -> List[Tender]:
    """Scrape up to ``max_pages`` of the invitation listing.

    Returns a de-duplicated list of tenders (first occurrence wins). Raises
    :class:`ScrapeError` only if the very first page cannot be loaded; later
    page failures are logged and skipped so a transient hiccup still yields
    the tenders already collected.
    """
    collected: dict[str, Tender] = {}
    with browser_page(headless=headless, profile_dir=profile_dir, channel=channel) as page:
        _goto_listing(page)

        for page_no in range(1, max_pages + 1):
            if page_no > 1:
                if not _change_page(page, page_no):
                    log.warning("could not advance to page %d; stopping", page_no)
                    break
            rows = _read_rows(page)
            log.info("page %d: %d tenders", page_no, len(rows))
            if not rows:
                break
            new_on_page = 0
            for t in rows:
                if t.tender_id not in collected:
                    collected[t.tender_id] = t
                    new_on_page += 1
            # If a page returned only tenders we've already seen, pagination
            # likely isn't advancing — stop to avoid spinning.
            if page_no > 1 and new_on_page == 0:
                break

    return list(collected.values())


_FIRST_DETAIL_JS = """() => {
    const r = document.querySelector("table tbody tr a[href*='/invitation/detail/']");
    return r ? r.href : '';
}"""

_CHANGED_JS = """(prev) => {
    const r = document.querySelector("table tbody tr a[href*='/invitation/detail/']");
    return !!r && r.href !== prev;
}"""


def _change_page(page: Page, page_no: int, per_page: int = 20) -> bool:
    """Drive the site's own pagination JS and wait for the table to refresh."""
    try:
        first_before = page.evaluate(_FIRST_DETAIL_JS)
        # The site exposes changePage(page, perPage); guard in case it isn't
        # present (e.g. only one page of results).
        has_fn = page.evaluate("() => typeof changePage === 'function'")
        if not has_fn:
            log.info("changePage() not defined; assuming single page")
            return False
        page.evaluate(f"() => changePage({page_no}, {per_page})")
        page.wait_for_function(_CHANGED_JS, arg=first_before, timeout=15000)
        return True
    except PWTimeout:
        return False
    except Exception as exc:
        log.warning("changePage(%d) failed: %s", page_no, exc)
        return False
