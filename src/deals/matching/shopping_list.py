"""Parse a shopping list like "Milch 2l, Eier 10, Äpfel bio, Milch 1,5%".

Per item:
- an amount with optional unit ("2l", "500 g", "10") -> wanted_amount/unit
  (a bare number means pieces)
- "bio", percentages ("1,5%") and "+word" -> filters
- the rest is the query; English items are translated ("milk" -> "Milch")
"""

import re

from deals.models import ListItem
from deals.matching.translate import FILTERS_EN_DE, translate
from deals.parsing.units import parse_quantity

_KNOWN_FILTERS = {"bio": "bio", **FILTERS_EN_DE}
_PERCENT = re.compile(r"^\d+(?:[.,]\d+)?%$")
_AMOUNT = re.compile(
    r"(?<!\S)(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>kg|g|l|ml|cl|stück|stk|st|pcs|pc|pieces)?\.?(?!\S)",
    re.IGNORECASE,
)


def parse_item(text: str) -> ListItem:
    wanted_amount = wanted_unit = None
    if m := _AMOUNT.search(text):
        unit = m["unit"] or "Stück"
        if unit.lower() in ("pcs", "pc", "pieces"):
            unit = "Stück"
        q = parse_quantity(f"{m['num']} {unit}")
        if q:
            wanted_amount, wanted_unit = q.amount, q.unit
        text = text[: m.start()] + text[m.end():]

    filters, query = [], []
    # "1,5 %" -> "1,5%" so it stays one token
    for token in re.sub(r"(\d)\s+%", r"\1%", text).split():
        if token.startswith("+") and len(token) > 1:
            filters.append(FILTERS_EN_DE.get(token[1:].lower(), token[1:]))
        elif token.lower() in _KNOWN_FILTERS:
            filters.append(_KNOWN_FILTERS[token.lower()])
        elif _PERCENT.match(token):
            filters.append(token)
        else:
            query.append(token)
    typed = " ".join(query)
    german = translate(typed)
    shown = typed if german and german.lower() != typed.lower() else None  # not "butter -> Butter"
    return ListItem(query=german or typed, original=shown,
                    filters=filters, wanted_amount=wanted_amount, wanted_unit=wanted_unit)


def parse_list(text: str) -> list[ListItem]:
    """Items are separated by newlines or commas (but not decimal commas like 1,5).
    Everything after a # on a line is a comment."""
    text = re.sub(r"#.*", "", text)
    parts = re.split(r"\n|,(?!\d)", text)
    return [parse_item(p) for p in parts if p.strip()]
