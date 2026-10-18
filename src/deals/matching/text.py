"""Text normalization for matching German product names.

The key idea is the *compound head*: in German compounds the LAST part is the
thing itself (Voll|milch is milk, Milch|schokolade is chocolate). So a list
item matches a word only if the word ends with it.
"""

import re
from dataclasses import dataclass

_UMLAUTS = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e", "è": "e", "à": "a"})

# Suffixes that describe the form, not the product: Lachs|filet is still Lachs.
_FORM_SUFFIXES = (
    "filetportionen", "filetstucke", "portionen", "portion", "filets", "filet",
    "stucke", "stuck", "scheiben", "seite", "spitzen", "zubereitung", "pads", "kapseln",
)

# Compounds whose head looks like the query but which are a different product.
# Found while labelling the evaluation set (tests/eval/matching_eval.json).
DECEPTIVE_COMPOUNDS = frozenset({
    "seelachs", "schweinelachs", "lammlachs", "granatapfel", "erdapfel",
    "erdnussbutter", "kakaobutter", "sheabutter", "buttermilch", "kondensmilch",
    "kokosmilch", "sonnenmilch", "mullermilch", "kaffeemilch", "zahnpasta",
    "marzipanbrot", "milchreis", "hafermilch", "sojamilch", "mandelmilch",
    "marzipankartoffel", "vanillezucker", "vanillinzucker",
})

# Different words for the same product (normalized). Embeddings didn't find these
# reliably (see docs/matching.md), so a small curated table it is. Extend as needed.
_PASTA = ["nudeln", "pasta", "teigwaren", "spaghetti", "penne", "fusilli", "farfalle",
          "tagliatelle", "linguine", "linguini", "makkaroni", "rigatoni", "fettuccine"]
SYNONYMS: dict[str, list[str]] = {
    **{w: [x for x in _PASTA if x != w] for w in ("nudeln", "pasta", "teigwaren")},
    "mineralwasser": ["wasser"],
    "kaffee": ["caffe"],  # not "coffee": that is iced/ready-to-drink coffee here
    "hahnchen": ["huhn", "huhnchen"],
    "hackfleisch": ["hack", "gehacktes"],
}

# Capitalized words in titles that are never the product itself.
_NOT_HEADS = frozenset({
    "xxl", "xl", "bio", "extra", "classic", "classico", "original", "premium", "mini", "maxi",
    "light", "zero", "natur", "jung", "mittelalt", "alt", "rot", "gelb", "grun", "weiss",
    "gerieben", "stuck", "frisch", "frische", "frischer", "deutsche", "deutscher", "deutsches",
    "neu", "neue", "family", "big", "duo", "set", "pack", "box", "mix", "intenso", "mild",
    "der", "die", "das", "unser", "unsere", "mein", "meine", "type", "delikatess",
    # pure form words: "Lachs Filetportionen" is Lachs
    "filet", "filets", "portion", "portionen", "filetportionen", "scheiben", "stucke",
})
# Capitalized adjectives in titles: "Frische Vollmilch", "Rote Tafeläpfel", "Norwegischer Lachs".
# Known adjective stems (any inflection) plus unmistakable adjective suffixes.
_ADJECTIVE_STEMS = frozenset({
    "frisch", "rot", "gelb", "grun", "weiss", "schwarz", "deutsch", "fein", "best", "zart",
    "klassisch", "gemischt", "nativ", "golden", "gross", "klein", "saftig", "knusprig", "lecker",
    "mager", "gross", "edel", "echt", "neu", "jung", "alt", "mild", "suss", "herzhaft", "cremig",
})
# "-isch" but not Fleisch/Fisch/Tisch
_ADJECTIVE_SUFFIX = re.compile(r"(?:(?<![eft])isch|ig|bar|frei|lich)(?:e|er|es|en|em)?$")


def _is_adjective(word: str) -> bool:
    base = re.sub(r"(?:e|er|es|en|em)$", "", word)
    return base in _ADJECTIVE_STEMS or word in _ADJECTIVE_STEMS or bool(_ADJECTIVE_SUFFIX.search(word))

# The product noun comes before these: "Joghurt mit der Ecke", "Thunfisch für Pasta".
_PHRASE_BREAK = re.compile(r"\s(?:mit|in|im|aus|vom|von|für|fur|nach|auf|zum|zur|ohne)\s", re.IGNORECASE)
_ALTERNATIVES = re.compile(r"\s*(?:/|\||,|&|\+|\soder\s|\sund\s|\sbzw\.?\s)\s*", re.IGNORECASE)
# Words with inner hyphens; a trailing hyphen marks an elided word ("Butter- oder Marzipanstollen").
_WORD = re.compile(r"[^\W_]+(?:-[^\W_]+)*-?")


def normalize(text: str) -> str:
    return text.lower().translate(_UMLAUTS)


def stem(word: str) -> str:
    """Very small German plural/inflection stemmer: Bananen/Banane -> banan."""
    for suffix in ("en", "er", "e", "n"):
        if len(word) > 4 and word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def strip_form(word: str) -> str:
    """lachsfiletportionen -> lachs, hahnchenbrustfilet -> hahnchenbrust."""
    changed = True
    while changed:
        changed = False
        for suffix in _FORM_SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                word, changed = word[: -len(suffix)], True
    return word


@dataclass(frozen=True)
class Head:
    word: "Word"
    primary: bool  # False: the noun MIGHT be the product ("Sahne" in "Sahne Joghurt")


@dataclass(frozen=True)
class Word:
    text: str        # normalized, hyphens removed: "h-milch" -> "hmilch"
    head: str        # last hyphen part, form suffix stripped: "milch"
    elided: bool     # "Butter-" in "Butter- oder Marzipanstollen"


def words(text: str) -> list[Word]:
    result = []
    for m in _WORD.finditer(normalize(text)):
        raw = m.group(0)
        elided = raw.endswith("-")
        parts = [p for p in raw.strip("-").split("-") if p]
        while len(parts) > 1 and parts[-1] in _NOT_HEADS:  # "Lachs-Filets" -> lachs
            parts.pop()
        if not parts:
            continue
        result.append(Word("".join(parts), strip_form(parts[-1]), elided))
    return result


def is_deceptive(w: Word) -> bool:
    return any(x in DECEPTIVE_COMPOUNDS for x in {w.text, w.head, stem(w.text), stem(w.head), strip_form(w.text)})


def head_words(title: str) -> list[Word]:
    """Primary product nouns of a title (see heads())."""
    return [h.word for h in heads(title) if h.primary]


def heads(title: str) -> list[Head]:
    """The product noun(s) of each alternative in a title, skipping adjectives and filler.

    Two capitalized nouns are ambiguous: "Sahne Joghurt"/"Basmati Reis" are
    compounds written apart (product = last noun), but "Gouda Holland jung"/
    "Tafelschokolade Haselnuss" name the product first. So the last noun is
    primary and the first noun is a secondary (uncertain) head.
    "Butter oder Streichzart" -> [butter, streichzart]
    "Natives Olivenöl Extra"  -> [olivenol]
    "Joghurt mit der Ecke"    -> [joghurt]
    """
    result = []
    for alternative in _ALTERNATIVES.split(title):
        alternative = _PHRASE_BREAK.split(f" {alternative} ")[0]
        tokens = [
            (raw, w) for raw, w in zip(_WORD.findall(alternative), words(alternative))
            if not w.elided and w.text not in _NOT_HEADS and stem(w.text) not in _NOT_HEADS
            and not w.text.isdigit()
        ]
        nouns = [w for raw, w in tokens if raw[:1].isupper() and not _is_adjective(w.text)]
        if nouns:
            result.append(Head(nouns[-1], True))
            if len(nouns) > 1:
                result.append(Head(nouns[0], False))
        elif tokens:  # all lowercase titles: German puts the noun last
            result.append(Head(tokens[-1][1], True))
    return result
