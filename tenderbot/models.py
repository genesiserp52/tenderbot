
"""Data model for a scraped tender."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Tender:
    """A single tender invitation parsed from the listing.

    ``tender_id`` (the numeric id from the detail URL) is the stable primary
    key used for de-duplication. ``code`` (Урилгын дугаар) is also unique but
    we key on the id because it is what the site itself uses internally.
    """

    tender_id: str
    code: str = ""
    name: str = ""
    buyer: str = ""               # Захиалагчийн нэр
    procurement_method: str = ""  # ХАА-ны журам
    budget: Optional[int] = None  # in MNT (tugrik); None if unparseable
    budget_text: str = ""         # original budget text, e.g. "109,329,420 ₮"
    category: str = ""            # tender type, e.g. Бараа/Ажил/Үйлчилгээ (API only)
    region: str = ""              # best-effort; listing has no dedicated field
    publish_date: str = ""        # Зарласан огноо, ISO-ish (YYYY-MM-DD)
    deadline: str = ""            # submission deadline, "YYYY-MM-DD HH:MM"
    open_date: str = ""           # tender open date (API only)
    status: str = ""
    url: str = ""                 # detail page URL

    def to_row(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> "Tender":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in row.items() if k in known})

    def signature(self) -> str:
        """Fields whose change should count as a meaningful update."""
        return f"{self.status}|{self.deadline}|{self.budget}"
