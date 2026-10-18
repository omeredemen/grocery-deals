from datetime import date

import pytest
from conftest import NOW

from deals.fetcher import SourceFormatError
from deals.fetcher.kaufda import _choose_deal, _utc_to_berlin_date, dedupe, parse_offers


@pytest.fixture(scope="module")
def offers(sample_brochures):
    result = []
    for b in sample_brochures:
        result += parse_offers(b["brochure"], b["pages"], NOW)
    return result


def by_title(offers, retailer, title):
    return next(o for o in offers if o.retailer == retailer and o.title == title)


def test_parses_all_samples(offers):
    assert len(offers) > 4500
    assert {o.source for o in offers} == {"kaufda"}
    for o in offers:
        assert o.price_eur > 0
        assert o.title
        assert o.valid_from <= o.valid_to


def test_known_offer_fields(offers):
    butter = by_title(offers, "Netto Marken-Discount", "Butter oder Streichzart")
    assert butter.brand == "Weihenstephan"
    assert butter.price_eur == 0.99
    assert butter.regular_price_eur == 2.99
    assert butter.raw_quantity_text == "gekühlt, versch. Sorten 250 g"
    assert butter.raw_base_price_text == "3.96 / kg"
    assert butter.category.endswith("Milchprodukte > Butter")
    # 2026-10-18T22:00Z .. 2026-10-24T21:59Z  ->  Mon 19 .. Sat 24 in Berlin
    assert (butter.valid_from, butter.valid_to) == (date(2026, 10, 19), date(2026, 10, 24))


def test_sales_price_preferred_over_app_price(offers):
    # Deals: SPECIAL 7.49 (+APP), SALES 8.49, REGULAR 17.99
    pils = by_title(offers, "Netto Marken-Discount", "Premium Pils")
    assert pils.price_eur == 8.49
    assert pils.regular_price_eur == 17.99
    assert pils.raw_base_price_text == "(0.85 / l)"


def test_offer_validity_can_differ_from_brochure(offers):
    # ALDI "ab Donnerstag" items are only valid Thu-Sat in a Mon-Sat brochure.
    sugar = by_title(offers, "ALDI Nord", "Puderzucker")
    assert (sugar.valid_from, sugar.valid_to) == (date(2026, 10, 22), date(2026, 10, 24))


def test_dedupe_removes_identical_brochure_variants(offers):
    unique = dedupe(offers)
    assert len(unique) < len(offers)
    keys = [(o.retailer, o.title, o.price_eur, o.raw_quantity_text, o.valid_from, o.valid_to) for o in unique]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    "deals, expected",
    [
        ([{"type": "SPECIAL_PRICE", "min": 1.0}, {"type": "SALES_PRICE", "min": 2.0}], 2.0),
        ([{"type": "SALES_PRICE", "min": 3.0}, {"type": "SALES_PRICE", "min": 2.5}], 2.5),
        ([{"type": "SPECIAL_PRICE", "min": 1.0}, {"type": "REGULAR_PRICE", "min": 2.0}], 1.0),
        ([{"type": "RECOMMENDED_RETAIL_PRICE", "min": 4.0}], 4.0),
        ([{"type": "OTHER", "min": 0}], None),  # coupon banners have price 0
        ([], None),
    ],
)
def test_choose_deal(deals, expected):
    chosen = _choose_deal(deals)
    assert (chosen["min"] if chosen else None) == expected


@pytest.mark.parametrize(
    "text, end, expected",
    [
        ("2026-10-18T22:00:00.000+0000", False, date(2026, 10, 19)),  # CEST midnight
        ("2026-10-24T21:59:59.000+0000", True, date(2026, 10, 24)),
        ("2026-10-24T22:00:00.000+0000", True, date(2026, 10, 24)),  # ends at 00:00 -> previous day
        ("2026-10-28T22:59:00.000+0000", True, date(2026, 10, 28)),  # after DST switch: CET 23:59
        (None, False, None),
    ],
)
def test_utc_to_berlin_date(text, end, expected):
    assert _utc_to_berlin_date(text, end=end) == expected


def _minimal_offer(**overrides):
    content = {
        "id": "x1",
        "products": [{"name": "Milch", "brandName": "Weide", "description": [{"paragraph": "1-l-Packung"}]}],
        "deals": [{"type": "SALES_PRICE", "min": 0.99, "conditions": [], "priceByBaseUnit": " "}],
    }
    content.update(overrides)
    return {"contents": [{"number": 0, "offers": [{"content": content}]}]}


BROCHURE = {"id": "b1", "publisher": {"name": "Penny"}, "validFrom": "2026-10-19T00:00:00", "validUntil": "2026-10-25T00:00:00"}


def test_falls_back_to_brochure_validity_and_blank_texts():
    [offer] = parse_offers(BROCHURE, _minimal_offer(), NOW)
    assert (offer.valid_from, offer.valid_to) == (date(2026, 10, 19), date(2026, 10, 24))
    assert offer.raw_base_price_text is None  # " " is treated as missing
    assert offer.category is None


def test_missing_fields_raise_format_error():
    with pytest.raises(SourceFormatError):
        parse_offers(BROCHURE, {"items": []}, NOW)
    broken = _minimal_offer()
    del broken["contents"][0]["offers"][0]["content"]["deals"]
    with pytest.raises(SourceFormatError, match="Unexpected offer format"):
        parse_offers(BROCHURE, broken, NOW)
