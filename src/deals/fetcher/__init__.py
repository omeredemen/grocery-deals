"""Offer sources. Every site-specific detail lives in one module per source.

A source only has to provide a name and `fetch_offers(lat, lng)`. To add e.g.
marktguru later: write fetcher/marktguru.py with such a class and register it.
"""

from typing import Protocol

from deals.models import Offer


class SourceFormatError(RuntimeError):
    """The site's data no longer looks like we expect (it probably changed)."""


class OfferSource(Protocol):
    name: str
    cache_version: int  # bump when parsing changes so old cached offers are refetched

    def fetch_offers(self, lat: float, lng: float) -> list[Offer]: ...


def get_source(name: str) -> OfferSource:
    # Imported here so importing the package doesn't pull in every source.
    if name == "kaufda":
        from deals.fetcher.kaufda import KaufdaSource

        return KaufdaSource()
    raise ValueError(f"Unknown source: {name!r}")
