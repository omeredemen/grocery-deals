import httpx
import pytest
from conftest import LAT, LNG

from deals.fetcher import SourceFormatError
from deals.fetcher.kaufda import KaufdaSource, RateLimiter


def test_list_brochures_follows_pagination(mock_kaufda):
    brochures = mock_kaufda.list_brochures(LAT, LNG)
    assert len(brochures) == 139  # 100 on page 0 + 39 on page 1


def test_fetch_offers_only_grocery_static_brochures(mock_kaufda):
    offers = mock_kaufda.fetch_offers(LAT, LNG)
    retailers = {o.retailer for o in offers}
    assert {"REWE", "Lidl", "ALDI Nord", "EDEKA", "Penny"} <= retailers
    assert not retailers & {"IKEA", "BAUHAUS", "dm-drogerie markt"}
    assert len(offers) > 3500


def _source(handler) -> KaufdaSource:
    return KaufdaSource(client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0)


def test_http_404_means_format_changed():
    src = _source(lambda req: httpx.Response(404))
    with pytest.raises(SourceFormatError, match="HTTP 404"):
        src.list_brochures(LAT, LNG)


def test_unexpected_json_shape():
    src = _source(lambda req: httpx.Response(200, json={"results": []}))
    with pytest.raises(SourceFormatError, match="byLocation"):
        src.list_brochures(LAT, LNG)


def test_non_json_response():
    src = _source(lambda req: httpx.Response(200, text="<html>captcha</html>"))
    with pytest.raises(SourceFormatError, match="non-JSON"):
        src.list_brochures(LAT, LNG)


def test_rate_limiter_waits_between_calls():
    t = [100.0]
    slept = []

    def sleep(s):
        slept.append(s)
        t[0] += s

    limiter = RateLimiter(2.0, clock=lambda: t[0], sleep=sleep)
    limiter.wait()          # first call: no wait
    t[0] += 0.5
    limiter.wait()          # 0.5 s later: wait the remaining 1.5 s
    t[0] += 5
    limiter.wait()          # long after: no wait
    assert slept == [1.5]
