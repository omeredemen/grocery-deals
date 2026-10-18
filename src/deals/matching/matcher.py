"""Match shopping list items to offers.

Layers (see SPEC.md, Phase 4):
1. normalize text (text.py)
2. lexical score: does the offer's product noun (title head) or its category
   path name the item? Compound-head rule + rapidfuzz for typos.
3. category filter: drop non-grocery categories (furniture, travel, ...)
4. optional semantic reranker (semantic.py) to rescue synonyms / reject odd matches
5. unit compatibility with the wanted amount
6. list item filters ("bio", "1,5%", "+laktosefrei")
Offers below the score threshold are not matches; an item can end up with none.
"""

import re
from dataclasses import dataclass
from typing import Protocol

from rapidfuzz import fuzz

from deals.matching.text import SYNONYMS, Word, head_words, heads, is_deceptive, normalize, stem, words
from deals.models import ListItem, Offer

# Scores in [0, 1]
HEAD_EXACT = 1.0        # title head is the item:              "Milch" ~ "H-Milch"
HEAD_COMPOUND = 0.95    # title head is a kind of the item:    "Milch" ~ "Vollmilch"
CATEGORY_LEAF = 0.9     # deepest category names the item:     "... > Kaffee > Röstkaffee"
CATEGORY_PARENT = 0.8   # a parent category names it:          "... > Teigwaren > Nudeln > Spaghetti"
CATEGORY_PARENT_WEAK = 0.7  # ...but the title IS the more specific leaf: "Cevapcici" in "Hackfleisch > Cevapcici"
HEAD_SECONDARY = 0.7    # maybe the product: "Tafelschokolade Haselnuss", "Sahne Joghurt"
OTHER_WORD = 0.5        # item appears, but not as the product: "Butter Spekulatius"
THRESHOLD = 0.75
SYNONYM_FACTOR = 0.95   # "Pasta" for "Nudeln" counts slightly less than "Nudeln"

# Semantic reranker (optional): similarities are compared WITHIN a query as z-scores,
# because raw cosine values aren't comparable between queries.
Z_RESCUE = 3.0    # lift an uncertain lexical hit (secondary head, weak category)
Z_VETO = 1.0      # drop a category-only hit the model finds unrelated
Z_SEMANTIC = 4.0  # accept an offer with no lexical evidence at all

# Top-level categories that never hold groceries (a "Kaffeemaschine" isn't Kaffee).
NON_GROCERY = frozenset({
    "Mode und Accessoires", "Möbel und Wohnen", "Elektronik und Technik", "Spielzeug",
    "Heimwerken und Garten", "Dekoration und Geschenkartikel", "Sport und Freizeit",
    "Dienstleistungen", "Medien", "Büro- und Schreibwaren", "Computer und Software",
})


@dataclass(frozen=True)
class Match:
    offer: Offer
    score: float
    reason: str


class Reranker(Protocol):
    """Optional semantic scorer: similarity in [0, 1] between query and each offer."""

    def similarities(self, query: str, offers: list[Offer]) -> list[float]: ...


def word_score(query: str, w: Word) -> float:
    """How well one (normalized, single-word) query matches one offer word."""
    q, h = stem(query), stem(w.head)
    if stem(w.text) == q:  # exactly what was asked for, even "Kokosmilch"
        return HEAD_EXACT
    if is_deceptive(w):
        return 0.0
    if q == h:
        return HEAD_EXACT
    # Compound: the word ends with the query (Voll|milch). Require a real prefix
    # and a query long enough not to hit random endings ("ei" in "Brei").
    if len(query) >= 4 and len(h) - len(q) >= 2 and (h.endswith(q) or w.head.endswith(query)):
        return HEAD_COMPOUND
    # Typos: "Bananne", "Jogurt", "Lachfilet". Unstemmed, so "Banana" != "Bananen".
    if len(query) >= 5 and (r := fuzz.ratio(query, w.head)) >= 88:
        return HEAD_COMPOUND * r / 100
    return 0.0


class Matcher:
    def __init__(self, reranker: Reranker | None = None, threshold: float = THRESHOLD):
        self.reranker = reranker
        self.threshold = threshold

    def match(self, item: ListItem, offers: list[Offer]) -> list[Match]:
        """All offers matching the item, best score first."""
        candidates = []
        for o in offers:
            if not self._grocery(o) or not self._unit_ok(item, o) or not self._filters_ok(item, o):
                continue
            score, reason = lexical_score(item.query, o)
            if score > 0 or self.reranker:
                candidates.append((o, score, reason))

        if self.reranker and len(candidates) > 1:
            sims = self.reranker.similarities(item.query, [c[0] for c in candidates])
            mean = sum(sims) / len(sims)
            std = (sum((x - mean) ** 2 for x in sims) / len(sims)) ** 0.5 or 1.0
            candidates = [self._combine(c, (x - mean) / std) for c, x in zip(candidates, sims)]

        matches = [Match(o, round(s, 3), r) for o, s, r in candidates if s >= self.threshold]
        return sorted(matches, key=lambda m: -m.score)

    def _combine(self, candidate, z: float):
        """Lexical evidence stays primary; semantics only decides uncertain cases."""
        offer, lex, reason = candidate
        if lex >= HEAD_COMPOUND * SYNONYM_FACTOR:
            return offer, lex, reason
        if lex >= self.threshold and z < Z_VETO:
            return offer, 0.0, f"{reason}, vetoed (z={z:.1f})"
        if 0 < lex < self.threshold and z >= Z_RESCUE:
            return offer, self.threshold, f"{reason}, confirmed (z={z:.1f})"
        if lex == 0 and z >= Z_SEMANTIC:
            return offer, self.threshold, f"semantic (z={z:.1f})"
        return offer, lex, reason

    @staticmethod
    def _grocery(o: Offer) -> bool:
        return (o.category or "").split(" > ")[0] not in NON_GROCERY

    @staticmethod
    def _unit_ok(item: ListItem, o: Offer) -> bool:
        # If you want liters, a per-kg offer can't be compared. Offers with an
        # unknown unit are kept (we just can't compute a unit price for them).
        return not (item.wanted_unit and o.unit and o.unit != item.wanted_unit)

    @staticmethod
    def _filters_ok(item: ListItem, o: Offer) -> bool:
        text = " ".join(filter(None, [o.title, o.brand, o.category, o.raw_quantity_text]))
        return all(filter_matches(f, text) for f in item.filters)


def lexical_score(query: str, o: Offer) -> tuple[float, str]:
    """Best evidence that the offer IS the queried product, with a reason."""
    q_words = [w.text for w in words(query)]
    if not q_words:
        return 0.0, ""
    if len(q_words) > 1:
        return _multi_word_score(q_words, o)
    best = _single_word_score(q_words[0], o)
    for synonym in SYNONYMS.get(q_words[0], []):
        s, r = _single_word_score(synonym, o)
        if s * SYNONYM_FACTOR > best[0]:
            best = (round(s * SYNONYM_FACTOR, 3), f"{r} (synonym '{synonym}')")
    return best


def _single_word_score(q: str, o: Offer) -> tuple[float, str]:
    # A deceptive word in the title ("Kokosmilch", "Alaska-Seelachs") overrides
    # whatever else the title or category says.
    if any(is_deceptive(w) and _ends_with(w, q) and stem(w.text) != stem(q) for w in words(o.title)):
        return 0.0, ""

    best, reason = 0.0, ""
    for h in heads(o.title):
        s = word_score(q, h.word)
        if s and not h.primary:
            s = HEAD_SECONDARY
        if s > best:
            best, reason = s, f"title '{h.word.text}'" + ("" if h.primary else " (secondary)")
    if best >= HEAD_COMPOUND:
        return best, reason

    path = _product_path(o.category)
    title_heads = {w.text for w in head_words(o.title)}
    for depth, element in enumerate(reversed(path)):
        for w in head_words(element):
            if word_score(q, w) >= HEAD_COMPOUND:
                if depth == 0:
                    s = CATEGORY_LEAF
                else:
                    leaf = {x.text for x in head_words(path[-1])}
                    s = CATEGORY_PARENT_WEAK if leaf & title_heads else CATEGORY_PARENT
                if s > best:
                    best, reason = s, f"category '{element}'"
    if best:
        return best, reason

    if not best and any(word_score(q, w) for w in words(o.title)):
        return OTHER_WORD, "word in title"
    return best, reason


def _ends_with(w: Word, q: str) -> bool:
    return w.text.endswith(q) or stem(w.text).endswith(stem(q))


def dominant_unit(matches: list[Match]) -> str | None:
    """The unit most matches are priced in. Offers in other units (a latte per piece
    among coffee per kg) can't be compared by unit price, so callers use only these."""
    units = [m.offer.unit for m in matches if m.offer.unit]
    return max(set(units), key=units.count) if units else None


_BRAND_OR_VARIETY_LIST = re.compile(r"(?:marken|sorten|variationen)$")


def _product_path(category: str | None) -> list[str]:
    """The informative part of a category path.

    "Lebensmittel und Getränke > Produkte > Getränke > ... > Bier > Biermarken > Hasseröder"
    -> [..., "Bier"]: only "Produkte" paths are a product taxonomy ("Marken" paths
    end in brand names), and after "Biermarken"/"Apfelsorten"/"Kaffeevariationen"
    come brands and varieties, so the element before it is the product type.
    """
    path = (category or "").split(" > ")
    if len(path) <= 3 or path[1] != "Produkte":
        return []
    path = path[3:]
    for i, element in enumerate(path):
        if _BRAND_OR_VARIETY_LIST.search(normalize(element)):
            return path[:i]
    return path


def _multi_word_score(q_words: list[str], o: Offer) -> tuple[float, str]:
    """"Hackfleisch gemischt": one word must be the product, the others must
    appear somewhere (title or description), like adjectives."""
    text_words = words(" ".join(filter(None, [o.title, o.raw_quantity_text, o.category])))
    best, reason = 0.0, ""
    for i, head in enumerate(q_words):
        s, r = lexical_score(head, o)
        others = q_words[:i] + q_words[i + 1:]
        if s and all(any(stem(x) == stem(w.text) or stem(x) == stem(w.head) for w in text_words) for x in others):
            if s > best:
                best, reason = s, r
    return best, reason


_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?")


def filter_matches(f: str, text: str) -> bool:
    """"1,5%" -> that fat/percentage appears; words -> appear as word, prefix or suffix
    ("bio" matches "Bio-Äpfel", "Bioland", "EDEKA Bio")."""
    if f.endswith("%") and (m := _NUMBER.match(f)):
        num = re.escape(m.group(0)).replace(",", "[.,]").replace(r"\.", "[.,]")
        # "1,5 % Fett", "1,5/3,5% Fett", "Milch 1,5% Fett"
        return re.search(rf"(?<![\d.,]){num}(?![\d])[^%]{{0,20}}%", text) is not None
    target = stem(normalize(f))
    return any(
        w.text.startswith(target) or w.text.endswith(target) or stem(w.text) == target
        for w in words(text)
    )
