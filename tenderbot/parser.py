"""Parse the raw text of a listing row into a :class:`Tender`.

The listing renders each tender as a table row with three cells. Their
``innerText`` (newline-separated) looks like:

  cell 0 (deadline):   "09:00\n2026-07\n27"
  cell 1 (main):       "<NAME>\nЗахиалагчийн нэр: <buyer>\n"
                       "ХАА-ны журам: <method>\n<duration>\n<budget> ₮"
  cell 2 (identifiers):"Урилгын дугаар\n<code>\nЗарласан огноо\n<date>"

The two anchors in the row give the detail URL (with the numeric id) and the
buyer's detail URL. This module is pure/text-only so it is unit-testable
without a browser.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .models import Tender

_LABELS = {
    "buyer": "захиалагчийн нэр",
    "method": "хаа-ны журам",
    "inv_no": "урилгын дугаар",
    "published": "зарласан огноо",
}

_BUDGET_RE = re.compile(r"([\d][\d\s.,]*\d|\d)\s*₮")
_ID_RE = re.compile(r"/invitation/detail/(\d+)")


def parse_budget(text: str) -> tuple[Optional[int], str]:
    """Extract an integer MNT amount from a chunk of text.

    Returns ``(amount_or_None, original_matched_text)``.
    """
    m = _BUDGET_RE.search(text)
    if not m:
        return None, ""
    raw = m.group(0).strip()
    digits = re.sub(r"[^\d]", "", m.group(1))
    return (int(digits) if digits else None), raw


def _clean_lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _strip_label(line: str, label: str) -> str:
    """Remove a leading ``label:`` prefix (case-insensitive) from a line."""
    low = line.lower()
    idx = low.find(label)
    if idx != -1:
        after = line[idx + len(label):]
        return after.lstrip(" : ").strip()
    return line.strip()


def parse_deadline(text: str) -> str:
    """Turn cell 0 ("HH:MM\\nYYYY-MM\\nDD") into "YYYY-MM-DD HH:MM"."""
    lines = _clean_lines(text)
    time_part = ""
    ym = ""
    day = ""
    for ln in lines:
        if re.fullmatch(r"\d{1,2}:\d{2}", ln):
            time_part = ln
        elif re.fullmatch(r"\d{4}-\d{1,2}", ln):
            ym = ln
        elif re.fullmatch(r"\d{1,2}", ln):
            day = ln.zfill(2)
        elif re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", ln):  # already combined
            ym, day = ln.rsplit("-", 1)
            day = day.zfill(2)
    date = f"{ym}-{day}" if ym and day else (ym or "")
    return (f"{date} {time_part}").strip()


def parse_main_cell(text: str) -> dict:
    """Parse the big middle cell into name/buyer/method/budget/duration."""
    lines = _clean_lines(text)
    out = {"name": "", "buyer": "", "procurement_method": "",
           "budget": None, "budget_text": "", "duration": ""}
    if not lines:
        return out

    # Name is the first line that is not a labelled field and not the budget.
    for ln in lines:
        low = ln.lower()
        if low.startswith(_LABELS["buyer"]) or low.startswith(_LABELS["method"]):
            continue
        if "₮" in ln:
            continue
        out["name"] = ln
        break

    for ln in lines:
        low = ln.lower()
        if low.startswith(_LABELS["buyer"]):
            out["buyer"] = _strip_label(ln, _LABELS["buyer"])
        elif low.startswith(_LABELS["method"]):
            out["procurement_method"] = _strip_label(ln, _LABELS["method"])
        elif "₮" in ln:
            amount, raw = parse_budget(ln)
            out["budget"], out["budget_text"] = amount, raw
        elif re.search(r"\b(хоног|сар|жил|өдөр)\b", low):
            out["duration"] = ln
    return out


def parse_identifier_cell(text: str) -> dict:
    """Parse the third cell into code (Урилгын дугаар) and publish date."""
    lines = _clean_lines(text)
    out = {"code": "", "publish_date": ""}
    for i, ln in enumerate(lines):
        low = ln.lower()
        if _LABELS["inv_no"] in low:
            # value is the remainder of the line, or the next line
            val = _strip_label(ln, _LABELS["inv_no"])
            if not val and i + 1 < len(lines):
                val = lines[i + 1]
            out["code"] = val
        elif _LABELS["published"] in low:
            val = _strip_label(ln, _LABELS["published"])
            if not val and i + 1 < len(lines):
                val = lines[i + 1]
            out["publish_date"] = val
    # Fallbacks: a code looks like ABC/2026.../.. ; a date looks like YYYY-MM-DD
    if not out["code"]:
        for ln in lines:
            if "/" in ln and any(c.isdigit() for c in ln):
                out["code"] = ln
                break
    if not out["publish_date"]:
        for ln in lines:
            if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", ln):
                out["publish_date"] = ln
                break
    return out


def extract_id(url: str) -> str:
    m = _ID_RE.search(url or "")
    return m.group(1) if m else ""


def parse_row(cells: List[str], links: List[str]) -> Optional[Tender]:
    """Build a :class:`Tender` from a row's cell texts and anchor hrefs.

    Returns ``None`` if the row has no usable detail link/id (e.g. a header or
    spacer row), so callers can simply skip falsy results.
    """
    detail_url = ""
    for href in links:
        if href and "/invitation/detail/" in href:
            detail_url = href
            break
    tender_id = extract_id(detail_url)
    if not tender_id:
        return None

    deadline = parse_deadline(cells[0]) if len(cells) > 0 else ""
    main = parse_main_cell(cells[1]) if len(cells) > 1 else {}
    ident = parse_identifier_cell(cells[2]) if len(cells) > 2 else {}

    # Best-effort region: the listing has no aimag column, so we leave it blank
    # here and let the filter engine match regions against buyer+name text.
    return Tender(
        tender_id=tender_id,
        code=ident.get("code", ""),
        name=main.get("name", ""),
        buyer=main.get("buyer", ""),
        procurement_method=main.get("procurement_method", ""),
        budget=main.get("budget"),
        budget_text=main.get("budget_text", ""),
        region="",
        publish_date=ident.get("publish_date", ""),
        deadline=deadline,
        status="",
        url=detail_url,
    )
