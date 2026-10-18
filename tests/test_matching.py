import json
import sys
from pathlib import Path

import pytest
from conftest import BROCHURES, NOW

from deals.fetcher.kaufda import dedupe, parse_offers
from deals.matching.matcher import (
    HEAD_COMPOUND,
    THRESHOLD,
    Matcher,
    dominant_unit,
    filter_matches,
    lexical_score,
    word_score,
)
from deals.matching.shopping_list import parse_item, parse_list
from deals.matching.text import head_words, normalize, stem, words
from deals.models import ListItem, Offer
from deals.parsing.units import enrich

ROOT = Path(__file__).resolve().parent.parent


def offer(title, category=None, unit=None, qty=None, brand=None, oid="x") -> Offer:
    return Offer(id=oid, source="test", retailer="R", title=title, category=category, brand=brand,
                 unit=unit, raw_quantity_text=qty, price_eur=1.0, fetched_at=NOW)


@pytest.fixture(scope="module")
def sample_offers():
    offers = []
    for f in sorted(BROCHURES.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        offers += parse_offers(d["brochure"], d["pages"], NOW)
    return [enrich(o) for o in dedupe(offers)]


# --------------------------------------------------------------- text

def test_normalize_and_stem():
    assert normalize("Äpfel") == "apfel"
    assert stem("bananen") == stem("banane") == "banan"
    assert stem("kartoffeln") == "kartoffel"
    assert stem("eier") == "eier"  # too short to stem


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Frische Vollmilch 3,5%", ["vollmilch"]),
        ("Butter oder Streichzart", ["butter", "streichzart"]),
        ("Natives Olivenöl Extra XXL", ["olivenol"]),
        ("Joghurt mit der Ecke", ["joghurt"]),
        ("Thunfisch für Pasta Tomate", ["thunfisch"]),
        ("Hackfleisch gemischt", ["hackfleisch"]),        # "-isch" but not an adjective
        ("Norwegische Lachs Filetportionen", ["lachs"]),  # form word skipped
        ("Lachs-Filets", ["lachs"]),
        ("Basmati Reis XXL", ["reis"]),                   # compound written apart
        ("bier oder biermischgetränke", ["bier", "biermischgetranke"]),
    ],
)
def test_head_words(title, expected):
    assert [w.text for w in head_words(title)] == expected


@pytest.mark.parametrize(
    "query, word, matches",
    [
        ("milch", "Vollmilch", True),
        ("milch", "H-Milch", True),
        ("milch", "Milchschokolade", False),   # the classic false match
        ("milch", "Milchreis", False),
        ("milch", "Kokosmilch", False),        # deceptive compound
        ("milch", "Buttermilch", False),
        ("lachs", "Räucherlachs", True),
        ("lachs", "Lachsfiletportionen", True),  # form suffix
        ("lachs", "Seelachsfilet", False),       # pollock, not salmon
        ("bananen", "Banane", True),
        ("bananen", "Bananenchips", False),
        ("eier", "Brei", False),
        ("joghurt", "Jogurt", True),             # typo
        ("pasta", "Zahnpasta", False),
    ],
)
def test_word_score(query, word, matches):
    [w] = words(word)
    assert (word_score(normalize(query), w) >= HEAD_COMPOUND * 0.88) == matches


# --------------------------------------------------------------- lexical score

def test_category_names_the_product():
    o = offer("Caffè Crema", "Lebensmittel und Getränke > Produkte > Getränke > Heißgetränk > Kaffee > Kaffeevariationen > Caffè Crema")
    assert lexical_score("Kaffee", o)[0] >= THRESHOLD


def test_brand_lists_in_category_are_skipped():
    # "Hasseröder" is a brand under "Biermarken"; the product type is "Bier".
    o = offer("Premium Pils", "Lebensmittel und Getränke > Produkte > Getränke > Alkoholische Getränke > Bier > Biermarken > Hasseröder")
    assert lexical_score("Bier", o)[0] >= THRESHOLD


def test_parent_category_alone_is_not_enough():
    o = offer("Cevapcici", "Lebensmittel und Getränke > Produkte > Lebensmittel > Fleisch > Fleischzubereitungen > Hackfleisch > Cevapcici")
    assert lexical_score("Hackfleisch", o)[0] < THRESHOLD


def test_secondary_head_is_uncertain():
    # "Sahne Joghurt" is yoghurt; "Sahne" only *might* be the product.
    assert lexical_score("Sahne", offer("Sahne Joghurt"))[0] < THRESHOLD
    assert lexical_score("Joghurt", offer("Sahne Joghurt"))[0] >= THRESHOLD


def test_synonyms():
    assert lexical_score("Nudeln", offer("Klassische Pasta"))[0] >= THRESHOLD
    assert lexical_score("Pasta", offer("Dinkel Nudeln"))[0] >= THRESHOLD


def test_multi_word_query():
    assert lexical_score("Hackfleisch gemischt", offer("Hackfleisch gemischt"))[0] >= THRESHOLD
    assert lexical_score("Hackfleisch gemischt", offer("Rinder-Hackfleisch"))[0] == 0


# --------------------------------------------------------------- filters & units

@pytest.mark.parametrize(
    "f, text, ok",
    [
        ("1,5%", "Haltbare Milch 1,5% Fett", True),
        ("1,5%", "1,5 % Fett 1 Liter", True),
        ("1,5%", "1,5/1,8/ 3,5/3,8% Fett 1l Packung", True),
        ("1,5%", "3,5% Fett", False),
        ("1,5%", "11,5% Fett", False),
        ("bio", "Bio Äpfel", True),
        ("bio", "Tafeläpfel EDEKA Bio", True),
        ("bio", "Bioland Apfelsaft", True),
        ("bio", "Rote Äpfel", False),
        ("laktosefrei", "Laktosefreie H-Milch", True),
    ],
)
def test_filter_matches(f, text, ok):
    assert filter_matches(f, text) == ok


def test_matcher_filters_units_and_non_grocery():
    m = Matcher()
    milk = offer("Frische Vollmilch", unit="l", oid="milk")
    choc = offer("Milchschokolade", unit="kg", oid="choc")
    machine = offer("Milchaufschäumer", category="Elektronik und Technik > Produkte > Küche", oid="m")
    frother = offer("Milch-Aufschäumer", category="Elektronik und Technik > Produkte > Küche", oid="f")
    assert [x.offer.id for x in m.match(ListItem(query="Milch"), [milk, choc, machine, frother])] == ["milk"]
    assert m.match(ListItem(query="Milch", wanted_unit="kg"), [milk]) == []


def test_dominant_unit():
    m = Matcher()
    offers = [offer("Kaffee", unit="kg", oid="a"), offer("Kaffee", unit="kg", oid="b"),
              offer("Kaffee Latte Macchiato", unit="stk", oid="c")]
    assert dominant_unit(m.match(ListItem(query="Kaffee"), offers)) == "kg"


class FakeReranker:
    def __init__(self, favourite):
        self.favourite = favourite

    def similarities(self, query, offers):
        return [1.0 if o.id == self.favourite else 0.0 for o in offers]


def test_reranker_can_rescue_and_veto():
    offers = [offer(f"Ding {i}", oid=str(i)) for i in range(30)] + [offer("Spaghetti No. 5", oid="spaghetti")]
    # "Spaghetti" isn't lexically "Teigware", but the (fake) model is sure.
    assert [m.offer.id for m in Matcher(FakeReranker("spaghetti")).match(ListItem(query="Teigware"), offers)] == ["spaghetti"]
    assert Matcher().match(ListItem(query="Teigware"), offers) == []


# --------------------------------------------------------------- shopping list

@pytest.mark.parametrize(
    "text, query, filters, amount, unit",
    [
        ("Milch 2l", "Milch", [], 2.0, "l"),
        ("Milch 2 l", "Milch", [], 2.0, "l"),
        ("Eier 10", "Eier", [], 10.0, "stk"),
        ("Hackfleisch gemischt 500g", "Hackfleisch gemischt", [], 0.5, "kg"),
        ("Milch 1,5% bio", "Milch", ["1,5%", "bio"], None, None),
        ("Joghurt +laktosefrei", "Joghurt", ["laktosefrei"], None, None),
        ("Äpfel", "Äpfel", [], None, None),
    ],
)
def test_parse_item(text, query, filters, amount, unit):
    item = parse_item(text)
    assert (item.query, item.filters, item.wanted_amount, item.wanted_unit) == (query, filters, amount, unit)


def test_parse_list_keeps_decimal_commas():
    items = parse_list("Milch 1,5%, Eier\nBananen")
    assert [i.query for i in items] == ["Milch", "Eier", "Bananen"]
    assert items[0].filters == ["1,5%"]


# --------------------------------------------------------------- real samples

def test_obvious_false_matches_avoided(sample_offers):
    m = Matcher()
    milk_titles = [x.offer.title.lower() for x in m.match(ListItem(query="Milch"), sample_offers)]
    assert milk_titles and not any(x in t for t in milk_titles for x in ("milchschokolade", "milchreis", "milch reis"))
    assert not any("reise" in x.offer.title.lower() or "Kreuzfahrt" in x.offer.title
                   for x in m.match(ListItem(query="Reis"), sample_offers))
    assert not any("Zahnpasta" in x.offer.title for x in m.match(ListItem(query="Pasta"), sample_offers))
    assert not any("Hefeweizen" in x.offer.title for x in m.match(ListItem(query="Hefe"), sample_offers))


@pytest.mark.xfail(strict=True, reason="known limitation: a variety named last looks like the product "
                   "('Tafelschokolade Alpenmilch' vs 'Sahne Joghurt'), see docs/matching.md")
def test_variety_named_last(sample_offers):
    titles = [x.offer.title for x in Matcher().match(ListItem(query="Milch"), sample_offers)]
    assert "Tafelschokolade Alpenmilch" not in titles


def test_no_deal_means_no_match(sample_offers):
    assert Matcher().match(ListItem(query="Kichererbsen"), sample_offers) == []


def test_evaluation_set_regression(sample_offers, capsys):
    """Guard against regressions; numbers when this was written:
    precision 86%, recall 95%, best pick 39/41 (tuned set); held-out 78% / 91% / 9/10."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from eval_matching import EVAL_FILE, HOLDOUT_FILE, evaluate

    tuned = evaluate(Matcher(), sample_offers, json.loads(EVAL_FILE.read_text())["items"])
    assert tuned["precision"] >= 0.85 and tuned["recall"] >= 0.92 and tuned["best_pick_accuracy"] >= 0.95
    held_out = evaluate(Matcher(), sample_offers, json.loads(HOLDOUT_FILE.read_text())["items"])
    assert held_out["precision"] >= 0.75 and held_out["recall"] >= 0.9 and held_out["best_pick_accuracy"] >= 0.9
