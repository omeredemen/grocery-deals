"""Glue between fetchers and the cache. Used by the CLI (and later the planner/UI)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from deals.fetcher import OfferSource, SourceFormatError
from deals.geo import GeocodeError, geocode_plz
from deals.models import Offer
from deals.parsing.units import enrich
from deals.storage import Storage, area_key


class LoadError(RuntimeError):
    """Offers couldn't be loaded; the message is meant for the user."""


@dataclass
class OfferResult:
    offers: list[Offer]
    fetched_at: datetime
    from_cache: bool


def get_offers(
    source: OfferSource,
    lat: float,
    lng: float,
    storage: Storage,
    max_age: timedelta = timedelta(days=3),
    force: bool = False,
    now: datetime | None = None,
) -> OfferResult:
    """Return cached offers for this area if fresh enough, otherwise fetch and cache.

    Unit prices are computed on every load (not stored), so parser improvements
    apply to cached data without refetching.
    """
    now = now or datetime.now().astimezone()
    area = area_key(lat, lng)
    key = f"{source.name}:v{getattr(source, 'cache_version', 1)}"  # new version = old cache ignored
    if not force:
        fetch_id = storage.fresh_fetch_id(key, area, max_age, now)
        if fetch_id is not None:
            offers = [enrich(o) for o in storage.load_offers(fetch_id)]
            return OfferResult(offers, storage.latest_fetch(key, area)[1], from_cache=True)

    offers = source.fetch_offers(lat, lng)
    storage.save_offers(key, area, offers, now)
    return OfferResult([enrich(o) for o in offers], now, from_cache=False)


def offers_for_plz(
    plz: str,
    source: OfferSource,
    db: Path | str,
    max_age: timedelta = timedelta(days=3),
    force: bool = False,
) -> tuple[OfferResult, float, float]:
    """PLZ -> (offers, lat, lng), from the cache when fresh. Shared by the CLI and the UI."""
    storage = Storage(db)
    try:
        lat, lng = geocode_plz(plz, storage)
        return get_offers(source, lat, lng, storage, max_age, force), lat, lng
    except (GeocodeError, SourceFormatError) as e:
        raise LoadError(str(e)) from e
    except httpx.HTTPError as e:
        raise LoadError(f"Network error: {e}") from e
    finally:
        storage.close()
