"""kaufDA (Bonial) offer source. ALL kaufDA-specific knowledge lives in this file.

Flow (see docs/data_source.md for how this was found):
    GET {API}/v1/brochures/byLocation?partner=kaufda_web&lat=..&lng=..&size=100&page=N
    GET {API}/v1/brochures/{id}/pages?partner=kaufda_web&lat=..&lng=..

The network part (KaufdaSource) is kept separate from the pure parsing part
(parse_offers), so the parser can be tested offline against samples/.
"""

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from deals.fetcher import SourceFormatError
from deals.models import Offer
from deals.parsing.conditions import is_normal_price

log = logging.getLogger(__name__)

SOURCE = "kaufda"
API = "https://content-viewer-be.kaufda.de"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    # Constant from the kaufDA viewer JS bundle; the API expects it.
    "Bonial-Api-Consumer": "web-content-viewer-fe",
    "Accept": "application/json",
}
PARTNER = "kaufda_web"
BERLIN = ZoneInfo("Europe/Berlin")

# Retailers we fetch brochures for (names exactly as the API returns them).
# Non-food chains (furniture, banks, DIY...) also show up in byLocation; we skip those.
# Wholesale (METRO, Selgros) is left out on purpose: it needs a business card.
GROCERY_RETAILERS = frozenset({
    "REWE", "Lidl", "ALDI Nord", "ALDI SÜD", "EDEKA", "E center", "Penny",
    "Netto Marken-Discount", "Netto mit dem Scottie", "Norma", "Kaufland",
    "Bio Company", "Denns BioMarkt", "Alnatura", "Mix Markt",
})

# Deal types in order of preference. Only prices without app/card/coupon/multi-buy
# conditions are considered (see parsing/conditions.py); if an offer only has such
# prices, its regular price is used.
_PAYABLE_DEAL_TYPES = ("SALES_PRICE", "SPECIAL_PRICE", "OTHER")
_REFERENCE_DEAL_TYPES = ("REGULAR_PRICE", "RECOMMENDED_RETAIL_PRICE")


class RateLimiter:
    """Ensures at least `min_interval` seconds between calls to wait()."""

    def __init__(self, min_interval: float, clock=time.monotonic, sleep=time.sleep):
        self.min_interval = min_interval
        self._clock, self._sleep = clock, sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self.min_interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now += remaining
        self._last = now


class KaufdaSource:
    name = SOURCE
    # Bump when parsing rules change, so cached offers parsed the old way are refetched.
    cache_version = 2

    def __init__(
        self,
        client: httpx.Client | None = None,
        min_interval: float = 2.0,
        retailers: frozenset[str] = GROCERY_RETAILERS,
        progress: Callable[[str], None] | None = None,
    ):
        self.client = client or httpx.Client(timeout=30)
        self.limiter = RateLimiter(min_interval)
        self.retailers = retailers
        self.progress = progress or (lambda msg: None)

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        self.limiter.wait()
        resp = self.client.get(API + path, params=params, headers=HEADERS)
        if resp.status_code in (400, 404, 410):
            raise SourceFormatError(
                f"kaufDA returned HTTP {resp.status_code} for {path}. The API has probably "
                "changed; see docs/data_source.md for how to re-discover it."
            )
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError as e:
            raise SourceFormatError(f"kaufDA returned non-JSON for {path}") from e

    def list_brochures(self, lat: float, lng: float) -> list[dict]:
        """All brochures near (lat, lng), across all result pages."""
        result, page = [], 0
        while True:
            data = self._get(
                "/v1/brochures/byLocation",
                {"partner": PARTNER, "lat": lat, "lng": lng, "size": 100, "page": page},
            )
            try:
                result += [item["content"] for item in data["contents"]]
                total_pages = data["page"]["totalPages"]
            except (KeyError, TypeError) as e:
                raise SourceFormatError(f"Unexpected byLocation format: missing {e}") from e
            page += 1
            if page >= total_pages:
                return result

    def fetch_offers(self, lat: float, lng: float) -> list[Offer]:
        fetched_at = datetime.now(BERLIN)
        brochures = [b for b in self.list_brochures(lat, lng) if self._wanted(b)]
        offers: list[Offer] = []
        for i, b in enumerate(brochures, 1):
            self.progress(f"[{i}/{len(brochures)}] {b['publisher']['name']}: {b.get('title', '')}")
            pages = self._get(
                f"/v1/brochures/{b['id']}/pages", {"partner": PARTNER, "lat": lat, "lng": lng}
            )
            offers += parse_offers(b, pages, fetched_at)
        return dedupe(offers)

    def _wanted(self, brochure: dict) -> bool:
        try:
            name, kind = brochure["publisher"]["name"], brochure["type"]
        except (KeyError, TypeError) as e:
            raise SourceFormatError(f"Unexpected brochure format: missing {e}") from e
        # Dynamic brochures use a different endpoint; no grocery chain used them (Phase 1).
        return name in self.retailers and kind == "static_brochure"


# ---------------------------------------------------------------- pure parsing

def parse_offers(brochure: dict, pages: dict, fetched_at: datetime) -> list[Offer]:
    """Convert one brochure's raw /pages response into Offer objects."""
    try:
        page_list = pages["contents"]
        retailer = brochure["publisher"]["name"]
    except (KeyError, TypeError) as e:
        raise SourceFormatError(f"Unexpected /pages format: missing {e}") from e

    offers = []
    for page in page_list:
        for item in page.get("offers") or []:
            try:
                offer = _parse_offer(item["content"], brochure, retailer, fetched_at)
            except (KeyError, TypeError, IndexError) as e:
                raise SourceFormatError(
                    f"Unexpected offer format in brochure {brochure.get('id')}: {e!r}"
                ) from e
            if offer is not None:
                offers.append(offer)
    return offers


def _parse_offer(c: dict, brochure: dict, retailer: str, fetched_at: datetime) -> Offer | None:
    products = c["products"]
    deal = _choose_deal(c["deals"])
    if not products or deal is None:
        # Not a format change, just an offer we can't use (e.g. "20 % Rabatt" banner).
        log.info("Skipping offer %s without product/price", c["id"])
        return None

    names = _unique(p["name"] for p in products)
    brands = _unique(p.get("brandName") for p in products)
    descriptions = _unique(
        " ".join(d["paragraph"] for d in p.get("description") or []).strip() for p in products
    )
    category_path = [cp["name"] for cp in products[0].get("categoryPaths") or []]
    regular = [d["min"] for d in c["deals"] if d["type"] in _REFERENCE_DEAL_TYPES and d["min"]]
    valid_from, valid_to = _validity(c, brochure)

    return Offer(
        id=c["id"],
        source=SOURCE,
        retailer=retailer,
        title=" / ".join(names),
        brand=" / ".join(brands) or None,
        category=" > ".join(category_path) or None,
        price_eur=deal["min"],
        regular_price_eur=max(regular) if regular else None,
        price_conditions="; ".join(
            _unique((cond.get("other") or "").strip() for cond in deal.get("conditions") or [])
        ) or None,
        raw_quantity_text=" | ".join(descriptions) or None,
        raw_base_price_text=(deal.get("priceByBaseUnit") or "").strip() or None,
        brochure_id=brochure["id"],
        valid_from=valid_from,
        valid_to=valid_to,
        fetched_at=fetched_at,
    )


def _choose_deal(deals: list[dict]) -> dict | None:
    """Pick the price a normal shopper pays: the cheapest unconditional deal of the
    most preferred type. Falls back to a regular price if that's all there is."""
    normal = [d for d in deals if is_normal_price([c.get("other") or "" for c in d.get("conditions") or []])]
    for kind in _PAYABLE_DEAL_TYPES + _REFERENCE_DEAL_TYPES:
        candidates = [d for d in normal if d["type"] == kind and (d.get("min") or 0) > 0]
        if candidates:
            return min(candidates, key=lambda d: d["min"])
    return None


def _validity(c: dict, brochure: dict) -> tuple[date | None, date | None]:
    """Offer validity as Berlin-local dates. Offers often differ from their
    brochure (e.g. Thursday-only deals), so the offer's own dates win."""
    profiles = c.get("publicationProfiles") or []
    if profiles and profiles[0].get("validity"):
        v = profiles[0]["validity"]
        return _utc_to_berlin_date(v.get("startDate")), _utc_to_berlin_date(v.get("endDate"), end=True)
    # byLocation brochure dates are naive Berlin local time.
    start, end = brochure.get("validFrom"), brochure.get("validUntil")
    return (
        datetime.fromisoformat(start).date() if start else None,
        _end_date(datetime.fromisoformat(end)) if end else None,
    )


def _utc_to_berlin_date(s: str | None, end: bool = False) -> date | None:
    """'2026-10-18T22:00:00.000+0000' -> 2026-10-19 (midnight in Berlin)."""
    if not s:
        return None
    dt = datetime.fromisoformat(s).astimezone(BERLIN)  # 3.11+ accepts "+0000"
    return _end_date(dt) if end else dt.date()


def _end_date(dt: datetime) -> date:
    # An end of exactly 00:00 means "until the end of the previous day".
    if (dt.hour, dt.minute, dt.second) == (0, 0, 0):
        return dt.date() - timedelta(days=1)
    return dt.date()


def _unique(values) -> list:
    """Non-empty values, duplicates removed, order kept."""
    return list(dict.fromkeys(v for v in values if v))


def dedupe(offers: list[Offer]) -> list[Offer]:
    """REWE etc. publish several overlapping brochure variants with different
    offer ids, so we dedupe on content instead of id."""
    seen, result = set(), []
    for o in offers:
        key = (o.retailer, o.title, o.price_eur, o.raw_quantity_text, o.valid_from, o.valid_to)
        if key not in seen:
            seen.add(key)
            result.append(o)
    return result
