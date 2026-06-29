"""SQLite persistence and new/changed-tender detection."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import List, Optional

from .models import Tender

log = logging.getLogger("tenderbot.storage")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenders (
    tender_id   TEXT PRIMARY KEY,
    code        TEXT,
    name        TEXT,
    buyer       TEXT,
    procurement_method TEXT,
    budget      INTEGER,
    budget_text TEXT,
    region      TEXT,
    publish_date TEXT,
    deadline    TEXT,
    status      TEXT,
    url         TEXT,
    signature   TEXT,
    notified    INTEGER NOT NULL DEFAULT 0,
    first_seen  TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Storage:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def exists(self, tender_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM tenders WHERE tender_id = ?", (tender_id,)
        )
        return cur.fetchone() is not None

    def get_signature(self, tender_id: str) -> Optional[str]:
        cur = self.conn.execute(
            "SELECT signature FROM tenders WHERE tender_id = ?", (tender_id,)
        )
        row = cur.fetchone()
        return row["signature"] if row else None

    def classify(self, tenders: List[Tender]) -> tuple[List[Tender], List[Tender]]:
        """Split a scraped batch into (brand_new, changed) lists.

        ``brand_new``  : tender_id never seen before.
        ``changed``    : seen before, but status/deadline/budget differ.
        """
        new: List[Tender] = []
        changed: List[Tender] = []
        for t in tenders:
            prev_sig = self.get_signature(t.tender_id)
            if prev_sig is None:
                new.append(t)
            elif prev_sig != t.signature():
                changed.append(t)
        return new, changed

    def upsert(self, tender: Tender, mark_notified: bool = False) -> None:
        row = tender.to_row()
        row["signature"] = tender.signature()
        cols = ["tender_id", "code", "name", "buyer", "procurement_method",
                "budget", "budget_text", "region", "publish_date", "deadline",
                "status", "url", "signature"]
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "tender_id")
        notified_clause = ", notified=1" if mark_notified else ""
        sql = (
            f"INSERT INTO tenders ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(tender_id) DO UPDATE SET {updates}, "
            f"last_seen=datetime('now'){notified_clause}"
        )
        self.conn.execute(sql, [row[c] for c in cols])
        if mark_notified and not self.exists(tender.tender_id):
            pass  # row was just inserted above; notified handled for updates only
        self.conn.commit()

    def mark_notified(self, tender_id: str) -> None:
        self.conn.execute(
            "UPDATE tenders SET notified = 1 WHERE tender_id = ?", (tender_id,)
        )
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
