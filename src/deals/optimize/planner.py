"""Choose which stores to visit for a shopping list.

1. Keep offers valid on the shopping date.
2. For each list item, its candidate offers = the matcher's matches, compared only
   within one unit (the wanted unit, or else the unit most matches use).
3. The cost of buying an item with an offer:
   - wanted amount given ("Milch 2l"): whole packs, ceil(wanted / pack size) x price.
     So needing 500 g never picks a 2 kg pack just because its per-kg price is lower.
   - no amount: unit price x a typical pack size (the median pack size among the
     item's offers). That's "best = lowest unit price", expressed in euros so it can
     be weighed against the store penalty.
4. An item doesn't have to be bought on deal: you can buy it at its normal price in
   whatever store you visit anyway. Its normal price is estimated from the regular
   (struck-through) prices / RRPs of its offers; if none are given, from its typical
   deal price x the typical markup of regular over deal prices in this week's
   brochures (about 1.3, i.e. deals are ~24% off).
5. Brute force over all sets of retailers (2^10 = 1024 for 10 retailers, instant):
   each item takes the cheaper of its best deal within the set and its normal price;
   objective = sum of item costs + penalty x (number of stores - 1).
"""

import math
from dataclasses import dataclass, field
from datetime import date
from itertools import combinations
from statistics import median

from deals.matching.matcher import Matcher, dominant_unit
from deals.models import ListItem, Offer

DEFAULT_MARKUP = 1.3  # used when no offer shows a regular price
MAX_RETAILERS = 16  # 2^16 subsets is still fast; above that we'd need something smarter


@dataclass(frozen=True)
class Choice:
    offer: Offer
    packs: int        # packs to buy (1 when no amount was given)
    cost: float       # cost used for optimizing (see module docstring)
    pay: float        # what you actually pay at the till: packs x price


@dataclass
class ItemOptions:
    item: ListItem
    unit: str | None
    reference_amount: float | None      # typical pack size, used when no amount wanted
    by_retailer: dict[str, Choice]      # cheapest choice per retailer
    normal_cost: float | None = None    # estimated cost without a deal (same basis as Choice.cost)
    normal_basis: str = ""              # how normal_cost was estimated


@dataclass
class Plan:
    stores: list[str]
    choices: dict[str, Choice]          # item text -> choice
    total_cost: float                   # sum of item costs
    penalty: float                      # store penalty x (stores - 1)
    no_deal: list[ListItem] = field(default_factory=list)
    # item text -> options, for items better bought at normal price (deal not worth the trip)
    off_deal: dict[str, ItemOptions] = field(default_factory=dict)

    @property
    def objective(self) -> float:
        return self.total_cost + self.penalty

    @property
    def total_pay(self) -> float:
        return sum(c.pay for c in self.choices.values())


@dataclass
class PlanResult:
    recommended: Plan
    cheapest_per_item: Plan             # every item at its cheapest store, ignoring store count
    not_yet_valid: int                  # matched offers that start after the shopping date


def format_amount(amount: float, unit: str) -> str:
    """0.5 kg -> "500 g", 0.25 l -> "250 ml", 10 stk -> "10 Stk"."""
    if unit == "kg" and amount < 1:
        return f"{amount * 1000:g} g"
    if unit == "l" and amount < 1:
        return f"{amount * 1000:g} ml"
    return f"{amount:g} {'Stk' if unit == 'stk' else unit}"


def item_key(item: ListItem) -> str:
    """Display name of a list item, e.g. "Milch 1,5% 2 l" or "milk → Milch 2 l"."""
    name = f"{item.original} → {item.query}" if item.original else item.query
    extra = " ".join(item.filters)
    amount = format_amount(item.wanted_amount, item.wanted_unit) if item.wanted_amount else ""
    return " ".join(x for x in (name, extra, amount) if x)


def valid_on(o: Offer, day: date) -> bool:
    return (o.valid_from is None or o.valid_from <= day) and (o.valid_to is None or day <= o.valid_to)


def offer_choice(item: ListItem, o: Offer, reference_amount: float | None) -> Choice:
    if item.wanted_amount and o.amount and o.unit == item.wanted_unit:
        packs = max(1, math.ceil(item.wanted_amount / o.amount - 1e-9))
        return Choice(o, packs, round(packs * o.price_eur, 2), round(packs * o.price_eur, 2))
    if o.unit_price_eur is not None and reference_amount:
        return Choice(o, 1, round(o.unit_price_eur * reference_amount, 2), o.price_eur)
    return Choice(o, 1, o.price_eur, o.price_eur)  # unknown unit: the pack price is all we have


def typical_markup(offers: list[Offer]) -> float:
    """Median regular price / deal price over offers that show both."""
    ratios = [o.regular_price_eur / o.price_eur for o in offers
              if o.regular_price_eur and o.regular_price_eur > o.price_eur > 0]
    return round(median(ratios), 3) if ratios else DEFAULT_MARKUP


def item_options(item: ListItem, offers: list[Offer], matcher: Matcher,
                 markup: float = DEFAULT_MARKUP) -> ItemOptions:
    matches = matcher.match(item, offers)
    unit = item.wanted_unit or dominant_unit(matches)
    comparable = [m.offer for m in matches if m.offer.unit == unit and m.offer.unit_price_eur is not None]
    # If most matches have no comparable unit price (e.g. toilet paper, where only one
    # offer had a parseable size), compare everything by pack price instead of dropping
    # the majority, which would force a visit to the one store with a unit price.
    if len(comparable) * 2 < len(matches):
        comparable = []
    candidates = comparable or [m.offer for m in matches]
    amounts = [o.amount for o in comparable if o.amount]
    reference = median(amounts) if amounts and not item.wanted_amount else None

    by_retailer: dict[str, Choice] = {}
    for o in candidates:
        c = offer_choice(item, o, reference)
        best = by_retailer.get(o.retailer)
        if best is None or (c.cost, c.offer.unit_price_eur or 0) < (best.cost, best.offer.unit_price_eur or 0):
            by_retailer[o.retailer] = c
    normal_cost, basis = _normal_cost(item, candidates, reference, markup)
    return ItemOptions(item, unit if comparable else None, reference, by_retailer, normal_cost, basis)


def _normal_cost(item: ListItem, candidates: list[Offer], reference: float | None,
                 markup: float) -> tuple[float | None, str]:
    """Estimated cost of the item without a deal, on the same basis as Choice.cost."""
    regular = []
    for o in candidates:
        if o.regular_price_eur and o.regular_price_eur > o.price_eur:
            factor = o.regular_price_eur / o.price_eur
            at_regular = o.model_copy(update={
                "price_eur": o.regular_price_eur,
                "unit_price_eur": o.unit_price_eur * factor if o.unit_price_eur is not None else None,
            })
            regular.append(offer_choice(item, at_regular, reference).cost)
    if regular:
        return round(median(regular), 2), f"median regular price of {len(regular)} offer(s)"
    if candidates:
        typical = median(offer_choice(item, o, reference).cost for o in candidates)
        return round(typical * markup, 2), f"typical deal x {markup:g} (no regular prices given)"
    return None, ""


def best_plan(options: list[ItemOptions], store_penalty: float) -> Plan:
    """Cheapest plan over all retailer subsets (including visiting no deal store at all)."""
    with_deals = [o for o in options if o.by_retailer]
    no_deal = [o.item for o in options if not o.by_retailer]
    retailers = sorted({r for o in with_deals for r in o.by_retailer})
    if len(retailers) > MAX_RETAILERS:
        raise ValueError(f"{len(retailers)} retailers is too many for brute force (max {MAX_RETAILERS})")

    best: Plan | None = None
    for k in range(len(retailers) + 1):
        for subset in combinations(retailers, k):
            choices, off_deal, total = {}, {}, 0.0
            for opt in with_deals:
                in_subset = [opt.by_retailer[r] for r in subset if r in opt.by_retailer]
                deal = min(in_subset, key=lambda c: c.cost) if in_subset else None
                if deal and (opt.normal_cost is None or deal.cost <= opt.normal_cost):
                    choices[item_key(opt.item)] = deal
                    total += deal.cost
                else:  # buy at normal price in any store you visit
                    off_deal[item_key(opt.item)] = opt
                    total += opt.normal_cost
            used = sorted({c.offer.retailer for c in choices.values()})  # drop unused stores
            plan = Plan(used, choices, round(total, 2), store_penalty * max(0, len(used) - 1), no_deal, off_deal)
            # Subsets come smallest first, so on a tie the plan with fewer stores is kept.
            if best is None or plan.objective < best.objective - 1e-9:
                best = plan
    return best or Plan([], {}, 0.0, 0.0, no_deal)


def make_plan(
    items: list[ListItem],
    offers: list[Offer],
    shopping_date: date,
    store_penalty: float = 2.0,
    matcher: Matcher | None = None,
) -> PlanResult:
    matcher = matcher or Matcher()
    valid = [o for o in offers if valid_on(o, shopping_date)]
    markup = typical_markup(valid)
    options = [item_options(i, valid, matcher, markup) for i in items]

    later = [o for o in offers if o.valid_from and o.valid_from > shopping_date]
    not_yet_valid = sum(len(matcher.match(i, later)) for i in items) if later else 0

    recommended = best_plan(options, store_penalty)
    # For comparison: every item at its own cheapest store, however many stores that is.
    cheapest_choices = {
        item_key(o.item): min(o.by_retailer.values(), key=lambda c: c.cost) for o in options if o.by_retailer
    }
    stores = sorted({c.offer.retailer for c in cheapest_choices.values()})
    cheapest = Plan(stores, cheapest_choices, round(sum(c.cost for c in cheapest_choices.values()), 2),
                    store_penalty * max(0, len(stores) - 1), recommended.no_deal)
    return PlanResult(recommended, cheapest, not_yet_valid)
