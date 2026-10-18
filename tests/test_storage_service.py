from datetime import timedelta

import httpx
import pytest
from conftest import NOW, SAMPLES

from deals.geo import GeocodeError, geocode_plz
from deals.models import Offer
from deals.service import get_offers
from deals.storage import Storage, area_key


def make_offer(i: int) -> Offer:
    return Offer(id=f"o{i}", source="fake", retailer="Lidl", title=f"Item {i}", price_eur=1.0 + i, fetched_at=NOW)


class FakeSource:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def fetch_offers(self, lat, lng):
        self.calls += 1
        return [make_offer(i) for i in range(3)]


@pytest.fixture
def storage():
    s = Storage(":memory:")
    yield s
    s.close()


def test_offers_roundtrip_and_old_fetches_replaced(storage):
    first = storage.save_offers("fake", "a", [make_offer(1)], NOW)
    second = storage.save_offers("fake", "a", [make_offer(2), make_offer(3)], NOW + timedelta(hours=1))
    assert storage.load_offers(first) == []  # older fetch for the same area was dropped
    assert storage.load_offers(second) == [make_offer(2), make_offer(3)]


def test_freshness(storage):
    storage.save_offers("fake", "a", [make_offer(1)], NOW)
    assert storage.fresh_fetch_id("fake", "a", timedelta(days=3), NOW + timedelta(days=2)) is not None
    assert storage.fresh_fetch_id("fake", "a", timedelta(days=3), NOW + timedelta(days=4)) is None
    assert storage.fresh_fetch_id("fake", "other-area", timedelta(days=3), NOW) is None


def test_get_offers_uses_cache(storage):
    src = FakeSource()
    r1 = get_offers(src, 52.5, 13.4, storage, now=NOW)
    r2 = get_offers(src, 52.5, 13.4, storage, now=NOW + timedelta(days=1))
    assert (r1.from_cache, r2.from_cache) == (False, True)
    assert r2.offers == r1.offers
    assert src.calls == 1

    get_offers(src, 52.5, 13.4, storage, now=NOW + timedelta(days=1), force=True)
    get_offers(src, 52.5, 13.4, storage, now=NOW + timedelta(days=10))  # stale
    assert src.calls == 3


def test_area_key_rounds_coordinates():
    assert area_key(52.5321914, 13.3845571) == area_key(52.53201, 13.38461) == "52.532,13.385"


def test_geocode_uses_nominatim_once(storage):
    requests = []

    def handler(req):
        requests.append(req)
        return httpx.Response(200, content=(SAMPLES / "nominatim_10115.json").read_bytes())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert geocode_plz("10115", storage, client) == (52.5321914, 13.3845571)
    assert geocode_plz("10115", storage, client) == (52.5321914, 13.3845571)
    assert len(requests) == 1
    assert "grocery-deals" in requests[0].headers["User-Agent"]


def test_geocode_rejects_bad_plz(storage):
    with pytest.raises(GeocodeError):
        geocode_plz("1011", storage)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    with pytest.raises(GeocodeError, match="not found"):
        geocode_plz("99999", storage, client)
