import pytest
from conftest import NOW

from deals.fetcher.kaufda import parse_offers
from deals.parsing.conditions import is_normal_price


@pytest.mark.parametrize("text", [
    "", "je", "Je Stück", "ab 1 Packung", "ab 1 Packung, je", "1 für", "Auch online", "Aktion",
    "ohne App", "Ohne PENNY App", "Preis ohne Treuepunkte", "ohne PAYBACK", "kg-Preis",
    "nur in teilnehmenden Märkten", "je 10-St.-Pckg.", "Einzelpreis",
])
def test_normal(text):
    assert is_normal_price([text])


@pytest.mark.parametrize("text", [
    "Mit Lidl Plus", "APP-PREIS", "App-Preis", "Nur mit App", "+APP", "Mit APP", "im App-Deal",
    "mit PAYBACK", "mit 55 Treuepunkten", "MIT DEM KLEBERABATT", "0,10 € Bonus", "PAPIER- ODER eCOUPON NUTZEN",
    "ab 2 Packungen", "ab 3 Packungen, je", "ab 12 Flaschen", "3 für", "3 kaufen für",
    "beim Kauf von 3 Stk.", "Kombikauf", "Ab 99€ Einkaufswert", "Nur online", "ab ca. 2,5 kg",
])
def test_not_normal(text):
    assert not is_normal_price([text])


BROCHURE = {"id": "b1", "publisher": {"name": "Lidl"}, "validFrom": "2026-10-19T00:00:00", "validUntil": "2026-10-24T23:00:00"}


def _price(deals):
    content = {"id": "x", "products": [{"name": "Butter", "description": []}], "deals": deals}
    offers = parse_offers(BROCHURE, {"contents": [{"offers": [{"content": content}]}]}, NOW)
    return offers[0].price_eur if offers else None


def deal(kind, price, cond=""):
    return {"type": kind, "min": price, "conditions": [{"other": cond}], "priceByBaseUnit": ""}


def test_app_price_is_ignored_in_favour_of_normal_price():
    assert _price([deal("SPECIAL_PRICE", 0.99, "Mit Lidl Plus"), deal("SALES_PRICE", 1.29)]) == 1.29
    # A "sales" price that needs the app is not normal either.
    assert _price([deal("SALES_PRICE", 4.99, "Nur mit App"), deal("REGULAR_PRICE", 6.99)]) == 6.99
    assert _price([deal("SALES_PRICE", 1.19, "Ohne PENNY App"), deal("SPECIAL_PRICE", 0.99, "Mit PENNY App")]) == 1.19


def test_multi_buy_is_ignored():
    assert _price([deal("SPECIAL_PRICE", 2.13, "je, ab 24 Packungen"), deal("SALES_PRICE", 3.09, "je, ab 1 Packung")]) == 3.09


def test_offer_without_any_normal_price_is_dropped():
    assert _price([deal("SPECIAL_PRICE", 0.99, "APP-PREIS")]) is None
