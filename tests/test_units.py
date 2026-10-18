"""Unit parser tests. Almost all strings are copied verbatim from samples/."""

import json
import logging
from datetime import datetime

import pytest
from conftest import BROCHURES, NOW

from deals.fetcher.kaufda import dedupe, parse_offers
from deals.models import Offer
from deals.parsing.units import BasePrice, Quantity, enrich, parse_base_price, parse_quantity


# --------------------------------------------------------------- Grundpreis

@pytest.mark.parametrize(
    "text, price, unit",
    [
        ("(1 kg = 9.02)", 9.02, "kg"),
        ("1 kg = 2.49", 2.49, "kg"),
        ("1kg = 55,44", 55.44, "kg"),
        ("(kg = 3.96)", 3.96, "kg"),
        ("3.96 / kg", 3.96, "kg"),
        ("17.25 / kg", 17.25, "kg"),
        ("(0.75 / l)", 0.75, "l"),
        ("1 l = 2,58", 2.58, "l"),
        ("1l = 6,84", 6.84, "l"),
        ("1 Liter = 1.51", 1.51, "l"),
        ("(Liter = 1.38/0.92)", 0.92, "l"),
        ("1 kg = 2.-", 2.0, "kg"),                        # "2.-" means 2,00 €
        ("Entspricht -.33/Stk.", 0.33, "stk"),           # "-.33" means 0,33 €
        ("1 kg = 13.29/11.5", 11.5, "kg"),               # several sizes -> best
        ("(kg = 16.46/13.39)", 13.39, "kg"),
        ("1kg = 4,40/4,13/3,77", 3.77, "kg"),
        ("1 kg = 11.06//7.11", 7.11, "kg"),
        ("(10.64 – 14.90 / kg)", 10.64, "kg"),           # range with en dash
        ("1 kg = 2.64 - 2.20", 2.20, "kg"),
        ("(1kg = 24,92-19,93)", 19.93, "kg"),
        ("1 kg = ab 4.99", 4.99, "kg"),
        ("4.99 €/kg", 4.99, "kg"),
        ("€/100g 9,90€/kg", 9.90, "kg"),
        ("100 g = 0,45", 4.5, "kg"),                     # per 100 g -> per kg
        ("(1 kg = 16.87 ATG)", 16.87, "kg"),
        ("(App: 12.45 / kg)", 12.45, "kg"),
        ("0.59/Stck.", 0.59, "stk"),
        ("je Stück: 0.34", 0.34, "stk"),
        ("je Stück 1,81", 1.81, "stk"),
        ("(Stück = 0.06/0.04)", 0.04, "stk"),
        ("1kg= ab 3.99", 3.99, "kg"),
        ("1 kg=4.38/3.80/3.21", 3.21, "kg"),
    ],
)
def test_parse_base_price(text, price, unit):
    assert parse_base_price(text) == BasePrice(price, unit)


@pytest.mark.parametrize(
    "text",
    [None, "", " ", "pro kg", "1 kg", "11.07", "(2,13)", "= 0.35",
     "1 m³ = 465.92", "1WA = 0,17", "(1 Tab = 0.17)", "(0.28 – 0.35 / WL)", "(Blatt = 0.10)"],
)
def test_parse_base_price_rejects(text):
    # Washing loads, tabs and bare numbers aren't units we compare; don't guess.
    assert parse_base_price(text) is None


# --------------------------------------------------------------- package size

@pytest.mark.parametrize(
    "text, amount, unit",
    [
        # plain and hyphenated package sizes
        ("versch. Sorten 420-g-Pckg.", 0.42, "kg"),
        ("104-g-Pckg.", 0.104, "kg"),
        ("3-kg-Karton", 3.0, "kg"),
        ("Deutschland Kl. II 1 kg Beutel", 1.0, "kg"),
        ("Mariniert. Ca. 1,5 kg", 1.5, "kg"),
        ("Halbtrockener italienischer Rotwein, 0,75-L-Flasche", 0.75, "l"),
        ("3,5% Fettgehalt 5-l-Bag-in-Box", 5.0, "l"),
        ("Grob gehackt, 4250-ml-Dose", 4.25, "l"),
        ("Süß 3200-g-PET-Dose", 3.2, "kg"),
        ("• Ganze Bohne\n• Verschiedene Sorten\n• je 1000-gPackung", 1.0, "kg"),
        ("Schinkenwürfel ca.1-kg-Packung", 1.0, "kg"),
        ("aus Apfelsaftkonzentrat, 100% Fruchtgehalt 1L PET-DPG-Flasche zzgl. 0,25 Pfand", 1.0, "l"),
        ("versch. Sorten, 400 ml DPG-Flasche + 0,25 Pfand", 0.4, "l"),
        ("Alkoholhaltiges Mischgetränk, 10% vol 0,25 l zzgl. 0.25 Pfand", 0.25, "l"),
        # thousands separator
        ("Aus Brandenburg, Tiefkühlung, je 1.600 g", 1.6, "kg"),
        ("Backkuchen 1.250 g", 1.25, "kg"),
        # multipacks
        ("Gerieben 2x5-g-Packung", 0.01, "kg"),
        ("20 x 0,5 Liter\nzzgl. 3.10 Pfand", 10.0, "l"),
        ("Verschiedene Sorten 20 x 0,5-l-Flasche zzgl. Pfand", 10.0, "l"),
        ("24 x 0,33-l-Flasche, zzgl. Pfand", 7.92, "l"),
        ("Abgabe nur in 24er-Packung 24 x 45-g-Stück", 1.08, "kg"),
        # variants / ranges -> largest pack
        ("In Scheiben. Gekühlt. Je 225/260 g", 0.26, "kg"),
        ("oder Lakritz, versch. Sorten 150/160/175g Beutel", 0.175, "kg"),
        ("gekühlt, versch. Sorten 100 g – 140 g", 0.14, "kg"),
        ("Versch. Sorten, z. B. St. Agur oder St. Albray; 125 g bzw. 180 g; Packung", 0.18, "kg"),
        ("Vom irischen Weiderind. Ca. 799 g–1,2 kg", 1.2, "kg"),
        # "je"/"pro" says what the price is for
        ("je 300 g", 0.3, "kg"),
        ("mild, 3,8% Fett. je 500 g", 0.5, "kg"),
        ("je 1-l-Flasche", 1.0, "l"),
        ("Je 1 kg. Standardpackung: 750 g", 1.0, "kg"),
        ("AA Qualität, Wildfang, Indischer Ozean Ca. 2-4 kg/Loin, je kg", 1.0, "kg"),
        ("mild geräuchert, ganze Stücke ca. 2,3 kg pro kg", 1.0, "kg"),
        ("Deutschland, Kl. I, pro kg", 1.0, "kg"),
        ("Gekühlt je 1 kg 20 Stück", 1.0, "kg"),
        ("pariert, mit Haut, küchenfertig ca. 250g\npro 100 g", 0.1, "kg"),
        ("Abtropfgewicht = 150 g, je 380 g", 0.38, "kg"),
        # nutrition, per-piece and portion sizes are not the pack size
        ("aus 50 % Schwein und 50 % Rind, bis zu 18 g Protein pro 100 g 500 g", 0.5, "kg"),
        ("versch. Sorten, bis zu 25g PROTEIN pro 100g 400 g", 0.4, "kg"),
        ("20 Stück à 90 g, Ohne Brotwürfel 1,8-kg-Packung", 1.8, "kg"),
        ("160-180g Portionen, Mit Glasur 800-g-Beutel", 0.8, "kg"),
        # weight beats piece count
        ("264 g 10 + 2 Stück", 0.264, "kg"),
        # pieces
        ("10-St.-Pckg.", 10.0, "stk"),
        ("Verschiedene Sorten, 100er-Dose", 100.0, "stk"),
        ("Fairtrade, in versch. Farben ca. 30cm lang 11er Bund", 11.0, "stk"),
        ("aus Bodenhaltung 18 Packung", 18.0, "stk"),
        ("aus Bodenhaltung 18 Frische Eier Packung", 18.0, "stk"),
        ("Kl. I, je Stück", 1.0, "stk"),
        ("Brasilien Sorte: siehe Etikett, Kl. I, je St.", 1.0, "stk"),
        ("Deutschland Bund", 1.0, "stk"),
        # loose produce priced per kg
        ("Klasse I, kg", 1.0, "kg"),
        ("lose, Ursprung: Kolumbien/\nGuatemala/Ecuador/\nElfenbeinküste\nkg-Preis", 1.0, "kg"),
    ],
)
def test_parse_quantity(text, amount, unit):
    q = parse_quantity(text)
    assert q is not None, text
    assert q.unit == unit
    assert q.amount == pytest.approx(amount)


@pytest.mark.parametrize(
    "text",
    [
        None,
        "Deutschland, Kl. I, aus Niedersachsen und Mecklenburg-Vorpommern",
        "softer Donut mit einer weißen Fettglasur und mit buntem Schokolinsen-Crunch",
        "versch. Sorten, Beutel",
        "Im 13-cm-Kulturtopf; ca. 27–32 cm hoch; Herkunft: Deutschland",
        "100 DEN 38/40-46/48",
        "gekühlt, versch. Sorten",        # "g" must not match the start of "gekühlt"
    ],
)
def test_parse_quantity_rejects(text):
    assert parse_quantity(text) is None


def test_quantity_texts_checked_in_order():
    assert parse_quantity(None, "Je Stück", "Bananen") == Quantity(1.0, "stk")
    assert parse_quantity("versch. Sorten", "pro kg") == Quantity(1.0, "kg")


# --------------------------------------------------------------- enrich

def offer(price, qty=None, bp=None, cond=None, title="X") -> Offer:
    return Offer(id="o", source="test", retailer="R", title=title, price_eur=price,
                 raw_quantity_text=qty, raw_base_price_text=bp, price_conditions=cond, fetched_at=NOW)


def test_enrich_prefers_grundpreis():
    o = enrich(offer(0.99, "gekühlt, versch. Sorten 250 g", "3.96 / kg"))
    assert (o.unit_price_eur, o.unit, o.amount) == (3.96, "kg", 0.25)


def test_enrich_computes_from_quantity():
    o = enrich(offer(2.49, "Deutschland Kl. II 1 kg Beutel"))
    assert (o.unit_price_eur, o.unit, o.amount) == (2.49, "kg", 1.0)
    o = enrich(offer(1.49, "versch. Sorten 6 x 1,5 l"))
    assert (o.unit, o.amount) == ("l", 9.0)
    assert o.unit_price_eur == pytest.approx(0.1656, abs=1e-4)


def test_enrich_uses_grundpreis_amount_when_quantity_disagrees():
    # Grundpreis is per drained weight (Abtropfgewicht), so the "je 380 g" doesn't fit.
    o = enrich(offer(1.99, "Abtropfgewicht = 150 g, je 380 g", "(1 kg = 13.27)"))
    assert o.unit_price_eur == 13.27
    assert o.amount == pytest.approx(0.15, abs=1e-3)


def test_enrich_reads_quantity_from_unparseable_grundpreis():
    # 'pro kg' in the Grundpreis field means the price is per kg, not per 200 g pack.
    o = enrich(offer(23.9, "heißgeräuchert ca. 200-g-Schale", "1 kg"))
    assert (o.unit_price_eur, o.unit) == (23.9, "kg")


def test_enrich_uses_conditions():
    o = enrich(offer(0.99, "Deutschland, Kl. I", cond="pro kg"))
    assert (o.unit_price_eur, o.unit) == (0.99, "kg")


def test_enrich_logs_failures(caplog):
    with caplog.at_level(logging.INFO, logger="deals.parsing.units"):
        o = enrich(offer(0.89, "Deutschland, Kl. I", title="Eisbergsalat"))
    assert o.unit_price_eur is None and o.amount is None
    assert "Could not parse quantity" in caplog.text and "Eisbergsalat" in caplog.text


def test_parse_rate_on_samples():
    """Regression guard: >95% of food offers in the samples get a unit price."""
    now = datetime.now().astimezone()
    offers = []
    for f in sorted(BROCHURES.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        offers += parse_offers(d["brochure"], d["pages"], now)
    food = [enrich(o) for o in dedupe(offers) if (o.category or "").startswith("Lebensmittel")]
    rate = sum(o.unit_price_eur is not None for o in food) / len(food)
    assert rate > 0.95
