"""Command-line entry point.

Examples:
    python -m tenderbot --dry-run            # scrape + print matches, no Telegram
    python -m tenderbot --once               # one real cycle (sends Telegram)
    python -m tenderbot --loop               # run forever on an interval
    python -m tenderbot --test-telegram      # send a test message and exit
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from .config import Settings
from .notifier import TelegramNotifier
from .runner import run_once


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tenderbot", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true",
                      help="run a single scrape/notify cycle (default)")
    mode.add_argument("--loop", action="store_true",
                      help="run continuously on TENDERBOT_INTERVAL_MINUTES")
    mode.add_argument("--test-telegram", action="store_true",
                      help="send a single test message and exit")
    p.add_argument("--dry-run", action="store_true",
                   help="print matches instead of sending Telegram messages")
    p.add_argument("--notify-on-seed", action="store_true",
                   help="notify on the first run too (default: seed silently)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    settings = Settings.load()
    log = logging.getLogger("tenderbot")
    log.info("data source: %s", settings.resolved_source)

    if args.test_telegram:
        if not settings.telegram_ready:
            log.error("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first.")
            return 2
        n = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
        ok = n.send("✅ tenderbot test message — your bot is wired up correctly.")
        log.info("test message %s", "sent" if ok else "FAILED")
        return 0 if ok else 1

    if args.loop:
        interval = settings.interval_minutes * 60
        log.info("starting loop, every %d min (Ctrl-C to stop)", settings.interval_minutes)
        while True:
            try:
                res = run_once(settings, dry_run=args.dry_run,
                               notify_on_seed=args.notify_on_seed)
                log.info("cycle done: scraped=%d new=%d matched=%d notified=%d seeded=%s",
                         res.scraped, res.new, res.matched, res.notified, res.seeded)
            except KeyboardInterrupt:
                log.info("interrupted; exiting.")
                return 0
            except Exception:  # keep the loop alive across unexpected errors
                log.exception("cycle crashed; will retry next interval")
            time.sleep(interval)

    # default / --once
    res = run_once(settings, dry_run=args.dry_run, notify_on_seed=args.notify_on_seed)
    log.info("done: scraped=%d new=%d matched=%d notified=%d seeded=%s",
             res.scraped, res.new, res.matched, res.notified, res.seeded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
