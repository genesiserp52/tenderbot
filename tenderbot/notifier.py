"""Telegram notification delivery."""
from __future__ import annotations

import html
import logging
import time
from typing import List, Optional

import requests

from .models import Tender

log = logging.getLogger("tenderbot.notifier")

_API = "https://api.telegram.org/bot{token}/sendMessage"


def _fmt_budget(t: Tender) -> str:
    if t.budget is not None:
        return f"{t.budget:,} ₮".replace(",", "'")
    return t.budget_text or "—"


def format_message(tender: Tender, matched_rules: List[str]) -> str:
    """Build an HTML-formatted Telegram message for one tender."""
    e = html.escape
    lines = [
        f"🆕 <b>{e(tender.name or 'Шинэ тендер')}</b>",
        "",
        f"🏷 <b>Дугаар:</b> {e(tender.code or '—')}",
        f"🏢 <b>Захиалагч:</b> {e(tender.buyer or '—')}",
        f"💰 <b>Төсөв:</b> {e(_fmt_budget(tender))}",
        f"📂 <b>Журам:</b> {e(tender.procurement_method or '—')}",
        f"📅 <b>Зарласан:</b> {e(tender.publish_date or '—')}",
        f"⏰ <b>Эцсийн хугацаа:</b> {e(tender.deadline or '—')}",
    ]
    if tender.category:
        lines.append(f"🗂 <b>Төрөл:</b> {e(tender.category)}")
    if tender.open_date:
        lines.append(f"📂 <b>Нээх огноо:</b> {e(tender.open_date)}")
    if tender.region:
        lines.append(f"📍 <b>Бүс:</b> {e(tender.region)}")
    if matched_rules:
        lines.append(f"🔎 <b>Шүүлтүүр:</b> {e(', '.join(matched_rules))}")
    if tender.url:
        lines.append("")
        lines.append(f'🔗 <a href="{e(tender.url)}">Дэлгэрэнгүй</a>')
    return "\n".join(lines)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, delay: float = 1.5,
                 session: Optional[requests.Session] = None):
        self.token = token
        self.chat_id = chat_id
        self.delay = delay
        self.session = session or requests.Session()

    def send(self, text: str) -> bool:
        url = _API.format(token=self.token)
        try:
            resp = self.session.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            log.error("Telegram request failed: %s", exc)
            return False
        if resp.status_code == 429:
            retry = resp.json().get("parameters", {}).get("retry_after", 5)
            log.warning("rate limited; sleeping %ss", retry)
            time.sleep(retry + 1)
            return self.send(text)
        if not resp.ok:
            log.error("Telegram error %s: %s", resp.status_code, resp.text[:300])
            return False
        return True

    def notify_tender(self, tender: Tender, matched_rules: List[str]) -> bool:
        ok = self.send(format_message(tender, matched_rules))
        if self.delay:
            time.sleep(self.delay)
        return ok
