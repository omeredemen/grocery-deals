import json
from pathlib import Path

import pytest
from conftest import BROCHURES, NOW

from deals.fetcher.kaufda import dedupe, parse_offers
from deals.matching.matcher import Matcher
from deals.matching.shopping_list import parse_item
from deals.matching.translate import translate
from deals.parsing.units import enrich

EVAL = Path(__file__).resolve().parent / "eval" / "matching_eval.json"

# Every item of the evaluation set, written the way an English speaker would.
ENGLISH = {
    "Milch": "milk", "Milch 2l": "milk 2l", "Milch 1,5%": "milk 1,5%", "Eier": "eggs", "Bananen": "bananas",
    "Kaffee": "coffee", "Butter": "butter", "Brot": "bread", "Gouda": "gouda", "Joghurt": "yogurt",
    "Äpfel": "apples", "Äpfel bio": "organic apples", "Tomaten": "tomatoes", "Kartoffeln": "potatoes",
    "Zwiebeln": "onions", "Nudeln": "noodles", "Pasta": "pasta", "Reis": "rice", "Hackfleisch": "minced meat",
    "Hackfleisch bio": "organic minced meat", "Hähnchenbrust": "chicken breast", "Lachs": "salmon",
    "Mehl": "flour", "Zucker": "sugar", "Olivenöl": "olive oil", "Mineralwasser": "mineral water",
    "Bier": "beer", "Orangensaft": "orange juice", "Toilettenpapier": "toilet paper",
    "Frischkäse": "cream cheese", "Mozzarella": "mozzarella", "Paprika": "bell peppers",
    "Gurke": "cucumber", "Haferflocken": "oats", "Schokolade": "chocolate", "Quark": "quark",
    "Sahne": "cream", "Hefe": "yeast", "Ingwer": "ginger", "Spülmittel": "dish soap",
    "Kichererbsen": "chickpeas",
}


@pytest.mark.parametrize(
    "english, german",
    [
        ("milk", "Milch"), ("Milk", "Milch"), ("eggs", "Eier"), ("strawberries", "Erdbeeren"),
        ("tomatoes", "Tomaten"), ("chicken breasts", "Hähnchenbrust"), ("toilet paper", "Toilettenpapier"),
        ("sausages", "Würstchen"), ("coconut milk", "Kokosmilch"),
    ],
)
def test_translate(english, german):
    assert translate(english) == german


@pytest.mark.parametrize("word", ["Kaffee", "Nutella", "Brötchen", ""])
def test_unknown_words_are_kept(word):
    assert translate(word) is None


def test_parse_item_translates_and_keeps_original():
    item = parse_item("organic chicken breasts 500g")
    assert (item.query, item.original, item.filters, item.wanted_amount, item.wanted_unit) == \
        ("Hähnchenbrust", "chicken breasts", ["bio"], 0.5, "kg")
    assert parse_item("eggs 10 pcs").wanted_amount == 10.0
    assert parse_item("oat milk +lactose-free").filters == ["laktosefrei"]
    assert parse_item("Milch").original is None
    assert parse_item("butter").original is None  # same word in both languages


@pytest.fixture(scope="module")
def sample_offers():
    offers = []
    for f in sorted(BROCHURES.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        offers += parse_offers(d["brochure"], d["pages"], NOW)
    return [enrich(o) for o in dedupe(offers)]


def test_english_list_finds_the_same_offers(sample_offers):
    items = [e["item"] for e in json.loads(EVAL.read_text())["items"]]
    assert set(items) == set(ENGLISH), "keep ENGLISH in sync with the eval set"
    m = Matcher()
    for german in items:
        de = {x.offer.id for x in m.match(parse_item(german), sample_offers)}
        en = {x.offer.id for x in m.match(parse_item(ENGLISH[german]), sample_offers)}
        assert en == de, f"{ENGLISH[german]!r} vs {german!r}"


def test_exact_query_for_a_deceptive_compound(sample_offers):
    # "Kokosmilch" never matches "Milch", but searching for it directly must work.
    titles = [x.offer.title for x in Matcher().match(parse_item("coconut milk"), sample_offers)]
    assert "Kokosmilch" in titles
    assert "Kokosmilch" not in [x.offer.title for x in Matcher().match(parse_item("milk"), sample_offers)]
