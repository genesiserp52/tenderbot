"""Official open-data API client for tender invitations.

This is the robust alternative to scraping: ``opendata.tender.gov.mn`` is NOT
behind Cloudflare and returns structured JSON. It requires a Bearer token that
the procurement agency issues on request.

Endpoint (POST, form-encoded):
    https://opendata.tender.gov.mn/api/invitation
    headers: Authorization: Bearer <token>
    body:    current_page (>=1), per_page (1..100), tenderYear (optional)

Response:
    {"return_code": 200, "message": "Амжилттай", "total": N,
     "per_page": "...", "current_page": "...",
     "data": [ {invitationId, tenderName, invitationNumber, totalBudget,
                budgetEntityName, ruleName, tenderTypeName, publishDate,
                receiveDate, openDate, docStatusName, ...}, ... ]}

The endpoint paginates but exposes no sort parameter, so we detect the
ordering from a sample page (invitationId is a chronological epoch-ms value)
and fetch from the newest end, then sort newest-first ourselves.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import List, Optional

import requests

from .models import Tender

log = logging.getLogger("tenderbot.api")

DEFAULT_URL = "https://opendata.tender.gov.mn/api/invitation"
DETAIL_URL = "https://user.tender.gov.mn/mn/invitation/detail/{id}"


class APIError(RuntimeError):
    pass


def _clean_dt(value: str) -> str:
    """Normalise "2026-06-24 12:00:00" -> "2026-06-24 12:00" (drop seconds)."""
    if not value:
        return ""
    value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%Y-%m-%d %H:%M") if (dt.hour or dt.minute) else dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value.split(" ")[0]  # fall back to the date part


def record_to_tender(rec: dict) -> Optional[Tender]:
    inv_id = rec.get("invitationId")
    if inv_id in (None, ""):
        return None
    inv_id = str(inv_id)
    budget = rec.get("totalBudget")
    try:
        budget = int(budget) if budget not in (None, "") else None
    except (TypeError, ValueError):
        budget = None
    return Tender(
        tender_id=inv_id,
        code=rec.get("invitationNumber") or rec.get("tenderCode") or "",
        name=rec.get("tenderName") or "",
        buyer=rec.get("budgetEntityName") or "",
        procurement_method=rec.get("ruleName") or "",
        budget=budget,
        budget_text=(f"{budget:,} ₮".replace(",", "'") if budget is not None else ""),
        category=rec.get("tenderTypeName") or "",
        region="",  # API has no dedicated aimag field either
        publish_date=_clean_dt(rec.get("publishDate") or ""),
        deadline=_clean_dt(rec.get("receiveDate") or ""),
        open_date=_clean_dt(rec.get("openDate") or ""),
        status=rec.get("docStatusName") or "",
        url=DETAIL_URL.format(id=inv_id),
    )


class TenderAPIClient:
    def __init__(self, token: str, url: str = DEFAULT_URL,
                 session: Optional[requests.Session] = None, timeout: int = 30):
        if not token:
            raise APIError("API token is required")
        self.token = token.strip()
        self.url = url
        self.timeout = timeout
        self.session = session or requests.Session()

    def _post(self, current_page: int, per_page: int,
              tender_year: Optional[int]) -> dict:
        body = {"current_page": current_page, "per_page": per_page}
        if tender_year:
            body["tenderYear"] = tender_year
        try:
            resp = self.session.post(
                self.url,
                data=body,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise APIError(f"request failed: {exc}") from exc
        if resp.status_code in (401, 403):
            raise APIError(f"auth rejected ({resp.status_code}); check your token")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise APIError(f"non-JSON response ({resp.status_code}): {resp.text[:200]}") from exc
        code = payload.get("return_code", payload.get("returncode"))
        if code not in (200, "200"):
            raise APIError(f"API error {code}: {payload.get('message')}")
        return payload

    def fetch_recent(self, want: int = 60, per_page: int = 100,
                     tender_year: Optional[int] = None) -> List[Tender]:
        """Return up to ``want`` of the most recently published tenders.

        Detects page ordering automatically and reads from the newest end.
        """
        if tender_year is None:
            tender_year = datetime.now().year
        per_page = max(1, min(per_page, 100))

        first = self._post(1, per_page, tender_year)
        total = int(first.get("total") or 0)
        data = first.get("data") or []
        if total == 0 or not data:
            log.info("API returned 0 tenders for year %s", tender_year)
            return []
        last_page = max(1, math.ceil(total / per_page))
        ascending = _page_is_ascending(data)
        log.info("API: total=%d pages=%d order=%s", total, last_page,
                 "ascending" if ascending else "descending")

        # Choose the pages holding the newest records.
        n_pages = max(1, math.ceil(want / per_page))
        if ascending:
            pages = list(range(last_page, max(0, last_page - n_pages), -1))
        else:
            pages = list(range(1, min(last_page, n_pages) + 1))

        records: List[dict] = []
        for pg in pages:
            payload = first if pg == 1 else self._post(pg, per_page, tender_year)
            records.extend(payload.get("data") or [])

        tenders = [t for t in (record_to_tender(r) for r in records) if t]
        # Newest first by invitationId (chronological epoch-ms).
        tenders.sort(key=lambda t: int(t.tender_id) if t.tender_id.isdigit() else 0,
                     reverse=True)
        # De-dupe (page windows can overlap) and cap.
        seen: set[str] = set()
        unique: List[Tender] = []
        for t in tenders:
            if t.tender_id not in seen:
                seen.add(t.tender_id)
                unique.append(t)
        return unique[:want]

    def check_auth(self) -> bool:
        """Lightweight token check: fetch one record."""
        self._post(1, 1, datetime.now().year)
        return True


def _page_is_ascending(data: List[dict]) -> bool:
    """True if records run oldest->newest (invitationId increasing)."""
    ids = [int(r["invitationId"]) for r in data
           if str(r.get("invitationId", "")).isdigit()]
    if len(ids) < 2:
        return False  # assume newest-first when we can't tell
    return ids[-1] > ids[0]
