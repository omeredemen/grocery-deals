"""SQLite cache: geocodes, fetch runs per area, and offers. One DB file.

Offers are stored as JSON (the pydantic model) plus a few columns we may want
to query directly. Storing JSON keeps the schema stable while Offer evolves.
"""

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from deals.models import Offer

DEFAULT_DB = Path(os.environ.get("DEALS_DB", "data/deals.sqlite"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS geocodes (
    plz TEXT PRIMARY KEY, lat REAL NOT NULL, lng REAL NOT NULL, label TEXT
);
CREATE TABLE IF NOT EXISTS fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL, area TEXT NOT NULL,
    fetched_at TEXT NOT NULL, n_offers INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS offers (
    fetch_id INTEGER NOT NULL REFERENCES fetches(id) ON DELETE CASCADE,
    id TEXT NOT NULL, retailer TEXT NOT NULL, title TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (fetch_id, id)
);
"""


def area_key(lat: float, lng: float) -> str:
    """Areas are identified by coordinates rounded to ~100 m."""
    return f"{lat:.3f},{lng:.3f}"


class Storage:
    def __init__(self, path: Path | str = DEFAULT_DB):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(_SCHEMA)

    def close(self) -> None:
        self.db.close()

    # --- geocodes (cached forever; postal codes don't move)
    def get_geocode(self, plz: str) -> tuple[float, float] | None:
        row = self.db.execute("SELECT lat, lng FROM geocodes WHERE plz = ?", (plz,)).fetchone()
        return (row[0], row[1]) if row else None

    def save_geocode(self, plz: str, lat: float, lng: float, label: str | None = None) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO geocodes VALUES (?, ?, ?, ?)", (plz, lat, lng, label)
            )

    # --- offers
    def latest_fetch(self, source: str, area: str) -> tuple[int, datetime] | None:
        row = self.db.execute(
            "SELECT id, fetched_at FROM fetches WHERE source = ? AND area = ? "
            "ORDER BY fetched_at DESC LIMIT 1",
            (source, area),
        ).fetchone()
        return (row[0], datetime.fromisoformat(row[1])) if row else None

    def fresh_fetch_id(self, source: str, area: str, max_age: timedelta, now: datetime) -> int | None:
        """Id of the latest fetch if it's younger than max_age, else None."""
        latest = self.latest_fetch(source, area)
        if latest and now - latest[1] < max_age:
            return latest[0]
        return None

    def save_offers(self, source: str, area: str, offers: list[Offer], fetched_at: datetime) -> int:
        """Store a new fetch and drop older fetches of the same area."""
        with self.db:  # one transaction
            cur = self.db.execute(
                "INSERT INTO fetches (source, area, fetched_at, n_offers) VALUES (?, ?, ?, ?)",
                (source, area, fetched_at.isoformat(), len(offers)),
            )
            fetch_id = cur.lastrowid
            self.db.executemany(
                "INSERT INTO offers VALUES (?, ?, ?, ?, ?)",
                [(fetch_id, o.id, o.retailer, o.title, o.model_dump_json()) for o in offers],
            )
            self.db.execute(
                "DELETE FROM fetches WHERE source = ? AND area = ? AND id != ?",
                (source, area, fetch_id),
            )
        return fetch_id

    def load_offers(self, fetch_id: int) -> list[Offer]:
        rows = self.db.execute("SELECT data FROM offers WHERE fetch_id = ?", (fetch_id,))
        return [Offer.model_validate_json(r[0]) for r in rows]
