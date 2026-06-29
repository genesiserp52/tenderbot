"""Configuration loading: environment (.env) and filter rules (YAML)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv

load_dotenv()  # populate os.environ from a local .env if present


def _bool(value: str, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    telegram_bot_token: Optional[str]
    telegram_chat_id: Optional[str]
    db_path: Path
    filters_path: Path
    max_pages: int
    headless: bool
    browser_channel: str   # "chrome" | "msedge" | "chromium"
    interval_minutes: int
    notify_delay: float
    source: str            # "auto" | "api" | "scrape"
    api_token: Optional[str]
    api_url: str
    per_page: int

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
            db_path=Path(os.environ.get("TENDERBOT_DB", "data/tenders.db")),
            filters_path=Path(os.environ.get("TENDERBOT_FILTERS", "filters.yaml")),
            max_pages=int(os.environ.get("TENDERBOT_MAX_PAGES", "3")),
            headless=_bool(os.environ.get("TENDERBOT_HEADLESS", "true")),
            browser_channel=os.environ.get("TENDERBOT_BROWSER_CHANNEL", "chrome").strip(),
            interval_minutes=int(os.environ.get("TENDERBOT_INTERVAL_MINUTES", "45")),
            notify_delay=float(os.environ.get("TENDERBOT_NOTIFY_DELAY", "1.5")),
            source=os.environ.get("TENDERBOT_SOURCE", "auto").strip().lower(),
            api_token=os.environ.get("TENDER_API_TOKEN") or None,
            api_url=os.environ.get(
                "TENDER_API_URL", "https://opendata.tender.gov.mn/api/invitation"),
            per_page=int(os.environ.get("TENDERBOT_PER_PAGE", "100")),
        )

    @property
    def resolved_source(self) -> str:
        """Concrete source to use: 'api' if a token is present (in auto), else 'scrape'."""
        if self.source == "api":
            return "api"
        if self.source == "scrape":
            return "scrape"
        # auto
        return "api" if self.api_token else "scrape"

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


@dataclass
class FilterRule:
    name: str
    keywords: List[str] = field(default_factory=list)
    keyword_logic: str = "any"  # "any" | "all"
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    categories: List[str] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)
    buyers: List[str] = field(default_factory=list)


def load_filters(path: Path) -> List[FilterRule]:
    """Load filter rules from a YAML file.

    Returns an empty list (with no error) if the file does not exist, so the
    tool can run in a "report everything" smoke-test mode before the user has
    written their rules.
    """
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a list of filter rules at the top level")

    rules: List[FilterRule] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: rule #{i + 1} is not a mapping")
        rules.append(
            FilterRule(
                name=str(item.get("name", f"rule-{i + 1}")),
                keywords=[str(k) for k in item.get("keywords", [])],
                keyword_logic=str(item.get("keyword_logic", "any")).lower(),
                budget_min=item.get("budget_min"),
                budget_max=item.get("budget_max"),
                categories=[str(c) for c in item.get("categories", [])],
                regions=[str(r) for r in item.get("regions", [])],
                buyers=[str(b) for b in item.get("buyers", [])],
            )
        )
    return rules
