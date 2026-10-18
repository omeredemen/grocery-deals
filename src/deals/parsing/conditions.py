"""Which price conditions mean "not a normal shelf price"?

We only use prices anyone pays at the till: no app, loyalty card, coupon,
multi-buy or online-only prices. Condition texts come from the brochures, e.g.
"Mit Lidl Plus", "APP-PREIS", "ab 3 Packungen", "Nur online", "ohne App".
"""

import re

# Explicitly the normal price: "ohne App", "Ohne PENNY App", "Preis ohne Treuepunkte".
_WITHOUT = re.compile(r"\bohne\b", re.IGNORECASE)

# Needs an app, card, points or coupon.
_MEMBERSHIP = re.compile(
    r"\bapp\b|app-?(?:preis|deal)|lidl\s*plus|payback|treuepunkt|punkte|kleberabatt|kleben"
    r"|coupon|bonus|preis nach rabatt",
    re.IGNORECASE,
)
# Must buy several: "ab 3 Packungen", "3 für", "3 kaufen für", "beim Kauf von 3 Stk.",
# "Kombikauf", "ab 99€ Einkaufswert". "ab 1 Packung" and "1 für" are fine.
_MULTI_BUY = re.compile(
    r"\bab\s+(?:ca\.\s*)?(?:[2-9]|\d{2,})\b|\b(?:[2-9]|\d{2,})\s+(?:kaufen\s+)?für\b"
    r"|beim kauf von|kombikauf|\bmind\.|einkaufswert",
    re.IGNORECASE,
)
_ONLINE_ONLY = re.compile(r"nur\s+online", re.IGNORECASE)


def is_normal_price(conditions: list[str]) -> bool:
    """True if a price with these conditions is a plain in-store price."""
    for text in conditions:
        if _WITHOUT.search(text):
            continue
        if _MEMBERSHIP.search(text) or _MULTI_BUY.search(text) or _ONLINE_ONLY.search(text):
            return False
    return True
