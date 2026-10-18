"""Unit price parsing for German offer texts.

Two inputs, in order of reliability:
1. The Grundpreis (PAngV base price), e.g. "(1 kg = 9.02)", "3.96 / kg", "100 g = 0,45".
2. The package size from the description, e.g. "500-g-Packung", "6 x 1,5 l", "10 Stück".

Everything is normalized to three base units: "kg", "l" and "stk" (pieces).

When a text lists several variants ("1 kg = 13.29/11.5", "150/160/175g") we take
the best case for the shopper: the lowest base price / the largest pack. It's
consistent, and you can usually pick the bigger variant in the shop.
"""

import logging
import re
from dataclasses import dataclass

from deals.models import Offer

log = logging.getLogger(__name__)

# Unit spellings -> (base unit, factor to convert one of them into the base unit).
# Longer spellings first so the regex alternation prefers "liter" over "l".
_UNITS: dict[str, tuple[str, float]] = {
    "kilogramm": ("kg", 1), "kilo": ("kg", 1), "kg": ("kg", 1),
    "gramm": ("kg", 0.001), "gr": ("kg", 0.001), "g": ("kg", 0.001),
    "liter": ("l", 1), "ltr": ("l", 1), "l": ("l", 1),
    "ml": ("l", 0.001), "cl": ("l", 0.01),
    "stück": ("stk", 1), "stck": ("stk", 1), "stk": ("stk", 1), "st": ("stk", 1),
}
_UNIT_RE = "|".join(sorted(map(re.escape, _UNITS), key=len, reverse=True))
# Unit must not be followed by a lowercase letter, so "g" doesn't match "gekühlt" and
# "l" not "lecker". Uppercase is allowed for typos like "1000-gPackung".
_UNIT = rf"(?P<unit>{_UNIT_RE})(?-i:(?![a-zäöüß]))"
_UNIT_NC = rf"(?:{_UNIT_RE})(?-i:(?![a-zäöüß]))"  # same, without a capture group
_NUM = r"\d+(?:[.,]\d+)?"
# Alternatives sharing one unit: "225/260", "100 g – 140", "125 g bzw. 180", "250 - 300"
_ALT_SEP = r"\s*(?:/|-|–|bzw\.?|oder)\s*"
_NUMS = rf"(?P<nums>{_NUM}(?:\s*{_UNIT_NC})?(?:{_ALT_SEP}{_NUM}(?:\s*{_UNIT_NC})?)*?)"


@dataclass(frozen=True)
class Quantity:
    amount: float  # in base units
    unit: str      # "kg" | "l" | "stk"


@dataclass(frozen=True)
class BasePrice:
    price: float   # EUR per 1 base unit
    unit: str      # "kg" | "l" | "stk"


def _num(s: str) -> float:
    """German or English decimal: '1,5' / '1.5' -> 1.5."""
    return float(s.replace(",", "."))


def _base(unit: str) -> tuple[str, float]:
    return _UNITS[unit.lower().rstrip(".")]


# ------------------------------------------------------------- Grundpreis

# Prices like "9.02", "1,5", "2.-" (= 2.00) or "-.79" (= 0.79).
_PRICE_RE = re.compile(r"\d+[.,]-|-[.,]\d+|\d+(?:[.,]\d+)?")
# "1 kg = 9.02", "(kg = 3.96)", "100 g = 0,45", "kg-Preis = 2.49", "je Stück: 0.79"
_BP_UNIT_FIRST = re.compile(
    rf"(?:(?:je|pro)\s+)?(?P<qty>{_NUM})?\s*{_UNIT}\.?(?:-preis)?\s*[=:]?\s*(?:ab\s*)?(?P<prices>[\d.,\-/\s]*\d[\d.,\-]*)",
    re.IGNORECASE,
)
# "3.96 / kg", "(0.75 / l)", "1,99 €/kg", "0.66 - 0.80 / kg", "0.25/Stk."
_BP_PRICE_FIRST = re.compile(
    rf"(?P<prices>\d[\d.,\-/\s]*?|-[.,]\d+)\s*(?:€|eur)?\s*/\s*(?P<qty>{_NUM})?\s*{_UNIT}",
    re.IGNORECASE,
)


def parse_base_price(text: str | None) -> BasePrice | None:
    """Parse a Grundpreis text into EUR per base unit, or None."""
    if not text:
        return None
    t = text.replace("–", "-").replace("€", " € ")
    # Try "price / unit" first: in "€/100g 1,99€/kg" the unit-first pattern would
    # wrongly read "100g 1,99".
    for pattern in (_BP_PRICE_FIRST, _BP_UNIT_FIRST):
        m = pattern.search(t)
        if not m:
            continue
        prices = [_parse_price(p) for p in _PRICE_RE.findall(m["prices"])]
        prices = [p for p in prices if p > 0]
        if not prices:
            continue
        unit, factor = _base(m["unit"])
        qty = _num(m["qty"]) if m["qty"] else 1.0
        return BasePrice(round(min(prices) / (qty * factor), 4), unit)
    return None


def _parse_price(s: str) -> float:
    if s.endswith("-"):          # "2.-"
        return float(s[:-2])
    if s.startswith("-"):        # "-.79"
        return float("0." + s[2:])
    return _num(s)


# ------------------------------------------------------------- package size

# "je 100 g", "Je 1 kg", "je 0,75-l-Flasche", "pro kg": the price is for exactly this.
_PER_RE = re.compile(rf"\b(?:je|pro)\s+(?P<nums>{_NUM})?\s*-?\s*{_UNIT}", re.IGNORECASE)
# ...but "18 g Protein pro 100 g" is nutrition info, not a price basis.
_NUTRIENT_RE = re.compile(r"(protein|eiweiß|fett|zucker|kohlenhydrate|ballaststoffe)\w*\s*$", re.IGNORECASE)
# One amount inside an alternatives list, optionally with its own unit ("799 g" in "799 g–1,2 kg").
_ALT_AMOUNT_RE = re.compile(rf"(?P<num>{_NUM})(?:\s*{_UNIT})?", re.IGNORECASE)
# Optional multipack "6 x " / "2x", then the amount(s), then the unit.
# Skips per-unit sizes ("pro 100 g", "20 Stück à 90 g", "180g Portionen") and
# nutrition info ("25g Protein"), so the whole pack size is found instead.
_QTY_RE = re.compile(
    rf"(?:(?P<mult>\d+)\s*[x×]\s*)?(?<!\d)(?<!\d[.,])(?<!pro )(?<!à )(?<!à){_NUMS}\s*-?\s*{_UNIT}"
    r"(?!\s*(?:protein|eiweiß|fett|zucker|kohlenhydrate|ballaststoffe|portion))",
    re.IGNORECASE,
)
# "4er-Pack", "24er-Packung", "100er-Dose", "11er Bund"
_ER_PACK_RE = re.compile(
    r"\b(?P<n>\d+)er\b(?=[\s-])"                           # "4er-Pack", "11er Bund"
    r"|\b(?P<n2>\d+)\s+(?:frische\s+)?(?:eier|packung)\b",  # "10 Eier", "18 Packung"
    re.IGNORECASE,
)
# A bare "Stück" / "je St." / "Bund" without a number means one piece.
_ONE_PIECE_RE = re.compile(r"(?<![\w-])(?:je\s+)?(?:stück|stk|st|bund)\b\.?(?!-)", re.IGNORECASE)
# Loose produce sold by weight: "kg-Preis", "Klasse I, kg".
_PER_KG_RE = re.compile(r"(?<![\w-])kg(?:-preis)?(?![\w-])", re.IGNORECASE)
# "1.600 g" uses a dot as thousands separator.
_THOUSANDS_RE = re.compile(r"\d{1,3}\.\d{3}")


def _amount(num: str, factor: float) -> float:
    if factor < 1 and _THOUSANDS_RE.fullmatch(num):  # only for g/ml: "1.600 g", not "1.250 kg"
        return float(num.replace(".", "")) * factor
    return _num(num) * factor


def parse_quantity(*texts: str | None) -> Quantity | None:
    """Find the package size in the given texts (checked in order).

    Priority: an explicit "je/pro <amount>" > a weight/volume > a piece count.
    """
    texts = [t for t in texts if t]
    for t in texts:
        for m in _PER_RE.finditer(t):
            if _NUTRIENT_RE.search(t[: m.start()]):
                continue
            unit, factor = _base(m["unit"])
            return Quantity(_round(_amount(m["nums"], factor) if m["nums"] else factor), unit)

    pieces: Quantity | None = None
    for t in texts:
        for m in _QTY_RE.finditer(t):
            unit, factor = _base(m["unit"])
            # Several variants -> the largest pack (best case, see module docstring).
            amount = max(
                (
                    _amount(a["num"], _base(a["unit"])[1] if a["unit"] else factor)
                    for a in _ALT_AMOUNT_RE.finditer(m["nums"])
                    if not a["unit"] or _base(a["unit"])[0] == unit
                ),
                default=None,
            )
            if amount is None:
                continue
            if m["mult"]:
                amount *= int(m["mult"])
            if unit != "stk":
                return Quantity(_round(amount), unit)
            pieces = pieces or Quantity(amount, unit)
        if not pieces and (m := _ER_PACK_RE.search(t)):
            pieces = Quantity(float(m["n"] or m["n2"]), "stk")
    if pieces:
        return pieces
    for t in texts:
        if _PER_KG_RE.search(t):
            return Quantity(1.0, "kg")
    for t in texts:
        if _ONE_PIECE_RE.search(t):
            return Quantity(1.0, "stk")
    return None


def _round(x: float) -> float:
    return round(x, 6)  # avoid 0.30000000000000004 from g->kg conversion


# ------------------------------------------------------------- offers

def enrich(offer: Offer) -> Offer:
    """Return a copy of the offer with amount, unit and unit_price_eur filled in."""
    bp = parse_base_price(offer.raw_base_price_text)
    # An unparseable Grundpreis can still say what the price is for ("pro kg", "1 kg");
    # that's more specific than the description, so it's checked first.
    extra = None if bp else offer.raw_base_price_text
    qty = parse_quantity(extra, offer.raw_quantity_text, offer.price_conditions, offer.title)

    if bp:
        # Pack size implied by the Grundpreis; prefer the parsed one if it roughly agrees.
        amount = round(offer.price_eur / bp.price, 3)
        if qty and qty.unit == bp.unit:
            if 0.5 <= qty.amount / amount <= 2:
                amount = qty.amount
            else:
                log.info("Grundpreis %r disagrees with quantity %r for offer %s (%s)",
                         offer.raw_base_price_text, offer.raw_quantity_text, offer.id, offer.title)
        return offer.model_copy(update={"amount": amount, "unit": bp.unit, "unit_price_eur": bp.price})

    if qty and qty.amount > 0:
        return offer.model_copy(update={
            "amount": qty.amount, "unit": qty.unit,
            "unit_price_eur": round(offer.price_eur / qty.amount, 4),
        })

    log.info("Could not parse quantity for offer %s (%s, %s): %r / %r", offer.id, offer.retailer,
             offer.title, offer.raw_quantity_text, offer.raw_base_price_text)
    return offer
