"""Core data models shared by all modules."""

from datetime import date, datetime

from pydantic import BaseModel


class Offer(BaseModel):
    id: str
    source: str                          # "kaufda"
    retailer: str                        # "REWE", "Lidl", "ALDI Nord", ...
    title: str
    brand: str | None = None
    category: str | None = None          # e.g. "Lebensmittel und Getränke > Marken"
    price_eur: float                     # the price you pay (see fetcher for how it's chosen)
    regular_price_eur: float | None = None   # strike-through / RRP price, if given
    price_conditions: str | None = None  # e.g. "Mit Lidl Plus", "je"
    # Filled in by the unit parser (Phase 3):
    amount: float | None = None          # normalized amount, e.g. 9.0
    unit: str | None = None              # "kg", "l", "stk"
    unit_price_eur: float | None = None  # price per kg / l / stk
    # Raw texts kept for parsing and debugging:
    raw_quantity_text: str | None = None     # product description, holds the package size
    raw_base_price_text: str | None = None   # Grundpreis text, e.g. "(1 kg = 9.02)"
    brochure_id: str | None = None
    valid_from: date | None = None       # Berlin local dates, inclusive
    valid_to: date | None = None
    fetched_at: datetime


class ListItem(BaseModel):
    """One shopping list entry, e.g. "Milch 2l bio"."""

    query: str                           # "Milch" (German, used for matching)
    original: str | None = None          # what was typed, if translated: "milk"
    filters: list[str] = []              # e.g. ["bio", "3,5%"]
    wanted_amount: float | None = None   # in base units, e.g. 2.0
    wanted_unit: str | None = None       # "kg" | "l" | "stk"
