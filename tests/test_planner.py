import json
from datetime import date

import pytest
from conftest import BROCHURES, LAT, LNG, NOW
from typer.testing import CliRunner

from deals import cli
from deals.fetcher.kaufda import dedupe, parse_offers
from deals.matching.shopping_list import parse_item, parse_list
from deals.models import ListItem, Offer
from deals.fetcher.kaufda import GROCERY_RETAILERS
from deals.optimize.planner import (
    ItemOptions, best_plan, item_options, make_plan, offer_choice, typical_markup, valid_on,
)
from deals.matching.matcher import Matcher
from deals.parsing.units import enrich
from deals.storage import Storage

DAY = date(2026, 10, 20)


def offer(title, retailer, price, amount=None, unit=None, oid=None,
          valid=(date(2026, 10, 19), date(2026, 10, 24)), regular=None):
    return Offer(
        id=oid or f"{retailer}-{title}-{price}", source="test", retailer=retailer, title=title,
        price_eur=price, amount=amount, unit=unit, regular_price_eur=regular,
        unit_price_eur=round(price / amount, 4) if amount else None,
        valid_from=valid[0], valid_to=valid[1], fetched_at=NOW,
    )


# --------------------------------------------------------------- single offers

def test_valid_on():
    o = offer("Milch", "Lidl", 1.0)
    assert valid_on(o, date(2026, 10, 19)) and valid_on(o, date(2026, 10, 24))
    assert not valid_on(o, date(2026, 10, 18)) and not valid_on(o, date(2026, 10, 25))


def test_wanted_amount_buys_whole_packs():
    item = parse_item("Milch 2l")
    assert offer_choice(item, offer("H-Milch", "A", 0.69, 1.0, "l"), None).pay == 1.38      # 2 packs
    assert offer_choice(item, offer("H-Milch 12x1l", "B", 8.50, 12.0, "l"), None).pay == 8.50  # 1 crate


def test_small_need_does_not_pick_big_pack():
    """SPEC: needing 500 g shouldn't pick a 2 kg pack just because its unit price is lower."""
    item = parse_item("Hackfleisch 500g")
    small = offer("Hackfleisch", "A", 3.00, 0.5, "kg")   # 6.00 €/kg
    big = offer("Hackfleisch", "B", 8.00, 2.0, "kg")     # 4.00 €/kg, but 8 € for what you need
    opts = item_options(item, [small, big], Matcher())
    assert best_plan([opts], 2.0).choices["Hackfleisch 500 g"].offer is small


def test_without_amount_lowest_unit_price_wins():
    item = parse_item("Kaffee")
    cheap_per_kg = offer("Kaffee", "A", 9.99, 1.0, "kg")    # 9.99 €/kg
    small_pack = offer("Kaffee", "B", 5.49, 0.5, "kg")      # 10.98 €/kg
    plan = best_plan([item_options(item, [cheap_per_kg, small_pack], Matcher())], 0.0)
    assert plan.choices["Kaffee"].offer is cheap_per_kg
    assert plan.choices["Kaffee"].pay == 9.99


def test_other_units_are_not_compared():
    item = parse_item("Kaffee")
    offers = [offer("Kaffee", "A", 9.99, 1.0, "kg"), offer("Kaffee", "A", 5.0, 0.5, "kg"),
              offer("Kaffee Latte Macchiato", "B", 0.99, 1.0, "stk")]
    opts = item_options(item, offers, Matcher())
    assert opts.unit == "kg" and set(opts.by_retailer) == {"A"}


# --------------------------------------------------------------- store combinations

def _opts(item: str, prices: dict[str, float], regular: float | None = None) -> ItemOptions:
    i = ListItem(query=item)
    return item_options(i, [offer(item, r, p, 1.0, "kg", regular=regular) for r, p in prices.items()], Matcher())


def test_penalty_tradeoff():
    # High regular prices, so buying off-deal is never attractive here.
    options = [_opts("Butter", {"A": 1.00, "B": 0.50}, regular=3.0), _opts("Milch", {"A": 1.00}, regular=3.0)]
    assert best_plan(options, 2.0).stores == ["A"]               # saving 0.50 < penalty 2.00
    assert best_plan(options, 0.2).stores == ["A", "B"]          # saving 0.50 > penalty 0.20
    plan = best_plan(options, 0.2)
    assert (plan.total_cost, plan.penalty) == (1.50, 0.2)


def test_deal_skipped_when_not_worth_a_store():
    options = [_opts("Butter", {"A": 1.0}, regular=1.3), _opts("Ingwer", {"C": 0.44}, regular=0.60)]
    plan = best_plan(options, 5.0)       # saving 0.16 € on Ingwer isn't worth 5 €
    assert plan.stores == ["A"] and list(plan.off_deal) == ["Ingwer"]
    assert plan.total_cost == 1.60       # 1.00 deal + 0.60 normal price
    assert best_plan(options, 0.1).stores == ["A", "C"]


def test_normal_price_estimate():
    # From regular prices when given...
    opts = _opts("Butter", {"A": 1.0, "B": 2.0}, regular=3.0)
    assert opts.normal_cost == 3.0 and "regular" in opts.normal_basis
    # ...otherwise typical deal x markup.
    i = ListItem(query="Butter")
    opts = item_options(i, [offer("Butter", "A", 1.0, 1.0, "kg"), offer("Butter", "B", 2.0, 1.0, "kg")], Matcher(), 1.3)
    assert opts.normal_cost == 1.95 and "x 1.3" in opts.normal_basis
    assert typical_markup([offer("x", "A", 1.0, regular=1.2), offer("y", "A", 1.0, regular=1.5),
                           offer("z", "A", 1.0)]) == 1.35


def test_items_without_deal_are_listed():
    options = [_opts("Butter", {"A": 1.0}), item_options(ListItem(query="Kichererbsen"), [], Matcher())]
    plan = best_plan(options, 2.0)
    assert [i.query for i in plan.no_deal] == ["Kichererbsen"] and list(plan.choices) == ["Butter"]


def test_make_plan_dates():
    offers = [
        offer("Butter", "Lidl", 1.29, 0.25, "kg", regular=2.0),
        offer("Butter", "Penny", 0.99, 0.25, "kg", valid=(date(2026, 10, 22), date(2026, 10, 24)), regular=2.0),
    ]
    result = make_plan([ListItem(query="Butter")], offers, DAY)
    assert result.recommended.stores == ["Lidl"]
    assert result.not_yet_valid == 1
    assert make_plan([ListItem(query="Butter")], offers, date(2026, 10, 22)).recommended.stores == ["Penny"]


# --------------------------------------------------------------- real samples

@pytest.fixture(scope="module")
def sample_offers():
    offers = []
    for f in sorted(BROCHURES.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        offers += parse_offers(d["brochure"], d["pages"], NOW)
    # The samples predate dropping wholesale chains from the fetcher.
    return [enrich(o) for o in dedupe(offers) if o.retailer in GROCERY_RETAILERS]


@pytest.mark.parametrize("penalty", [0.0, 0.5, 2.0, 10.0])
def test_plan_on_samples(sample_offers, penalty):
    items = parse_list("Milch 2l, Eier 10, Bananen, Kaffee, Butter, Nudeln 500g, Hackfleisch 500g, Kichererbsen")
    result = make_plan(items, sample_offers, DAY, store_penalty=penalty)
    rec, cheapest = result.recommended, result.cheapest_per_item
    assert [i.query for i in rec.no_deal] == ["Kichererbsen"]
    assert len(rec.choices) + len(rec.off_deal) == 7
    assert all(valid_on(c.offer, DAY) for c in rec.choices.values())
    # The recommended plan is optimal, so never worse than buying everything at its cheapest store.
    assert rec.objective <= cheapest.objective + 1e-9
    if penalty == 0.0:
        assert rec.total_cost <= cheapest.total_cost + 1e-9
    if penalty == 10.0:
        assert len(rec.stores) <= 1


def test_plan_command(tmp_path, monkeypatch, mock_kaufda):
    db = tmp_path / "deals.sqlite"
    s = Storage(db)
    s.save_geocode("10115", LAT, LNG)
    s.close()
    monkeypatch.setattr(cli, "get_source", lambda name: mock_kaufda)
    result = CliRunner().invoke(cli.app, ["plan", "--plz", "10115", "--list", "Milch 2l, Butter, Kichererbsen",
                                          "--date", "2026-10-20", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "Recommended stores:" in result.output
    assert "No deal this week: Kichererbsen" in result.output


def test_one_unit_priced_offer_does_not_force_its_store():
    """Regression: only METRO's toilet paper had a unit price, so all others were dropped
    and METRO became mandatory. With mostly unpriced offers, compare pack prices."""
    item = ListItem(query="Toilettenpapier")
    offers = [offer("Toilettenpapier", "METRO", 10.94, 1.0, "stk"),
              offer("Toilettenpapier", "Lidl", 2.55), offer("Toilettenpapier", "REWE", 3.99)]
    opts = item_options(item, offers, Matcher())
    assert set(opts.by_retailer) == {"METRO", "Lidl", "REWE"}
    assert best_plan([opts], 2.0).stores == ["Lidl"]
