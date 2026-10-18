"""Evaluate the matcher against the hand-labelled set in tests/eval/matching_eval.json.

Usage:
    .venv/bin/python scripts/eval_matching.py              # lexical only
    .venv/bin/python scripts/eval_matching.py --semantic   # + embedding reranker
    .venv/bin/python scripts/eval_matching.py -v           # list wrong matches / misses

Metrics per item, over all sample offers ("ambiguous" labels are ignored):
- precision: matched offers that are relevant
- recall:    relevant offers that were matched
- best pick: is the offer the planner would choose (lowest unit price among
             matches) acceptable? For items with no relevant offer, "no match" is correct.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from parse_report import load_offers  # noqa: E402

from deals.matching.matcher import Matcher, dominant_unit  # noqa: E402
from deals.matching.shopping_list import parse_item  # noqa: E402

EVAL_FILE = ROOT / "tests" / "eval" / "matching_eval.json"
HOLDOUT_FILE = ROOT / "tests" / "eval" / "matching_holdout.json"


def best_pick(matches):
    unit = dominant_unit(matches)
    priced = [m.offer for m in matches if m.offer.unit_price_eur is not None and m.offer.unit == unit]
    pool = priced or [m.offer for m in matches]
    return min(pool, key=lambda o: (o.unit_price_eur or o.price_eur)) if pool else None


def evaluate(matcher: Matcher, offers, labels, verbose: bool = False) -> dict:
    by_prefix = {o.id[:8]: o for o in offers}
    tp = fp = fn = picks_ok = 0
    rows = []
    for entry in labels:
        relevant, ambiguous = set(entry["relevant"]), set(entry["ambiguous"])
        # Offers can disappear when parsing rules change (e.g. no normal price left);
        # they can't be matched, so they don't count.
        gone = (relevant | ambiguous) - by_prefix.keys()
        if gone:
            print(f"  ({entry['item']}: {len(gone)} labelled offer(s) not in the parsed offers, ignored)")
            relevant, ambiguous = relevant - gone, ambiguous - gone

        matches = matcher.match(parse_item(entry["item"]), offers)
        got = {m.offer.id[:8] for m in matches} - ambiguous
        t, f, n = len(got & relevant), len(got - relevant), len(relevant - got)
        tp, fp, fn = tp + t, fp + f, fn + n

        pick = best_pick(matches)
        pick_ok = (pick is None) if not relevant else (pick is not None and pick.id[:8] in relevant | ambiguous)
        picks_ok += pick_ok
        rows.append((entry["item"], t, f, n, pick, pick_ok))

        if verbose and (f or n or not pick_ok):
            reasons = {m.offer.id[:8]: m.reason for m in matches}
            for oid in sorted(got - relevant):
                print(f"    FP {entry['item']:14} {by_prefix[oid].retailer:12} {by_prefix[oid].title[:45]:45} ({reasons[oid]})")
            for oid in sorted(relevant - got):
                o = by_prefix[oid]
                print(f"    FN {entry['item']:14} {o.retailer:12} {o.title[:45]:45} | {o.category}")

    print(f"{'item':16} {'TP':>3} {'FP':>3} {'FN':>3}  best pick")
    for item, t, f, n, pick, ok in rows:
        pick_txt = f"{pick.retailer}: {pick.title[:40]} ({pick.unit_price_eur}/{pick.unit})" if pick else "no match"
        print(f"{item:16} {t:3} {f:3} {n:3}  {'ok ' if ok else 'BAD'} {pick_txt}")
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    result = {"precision": precision, "recall": recall,
              "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
              "best_pick_accuracy": picks_ok / len(labels), "items": len(labels)}
    print(f"\nprecision {precision:.1%}  recall {recall:.1%}  F1 {result['f1']:.1%}  "
          f"best pick correct {picks_ok}/{len(labels)} = {result['best_pick_accuracy']:.1%}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--semantic", action="store_true", help="use the embedding reranker")
    ap.add_argument("--holdout", action="store_true", help="use the held-out set (never used for tuning)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    reranker = None
    if args.semantic:
        from deals.matching.semantic import E5Reranker
        reranker = E5Reranker()
    offers = load_offers(ROOT / "samples" / "brochures_10115")
    labels = json.loads((HOLDOUT_FILE if args.holdout else EVAL_FILE).read_text(encoding="utf-8"))["items"]
    evaluate(Matcher(reranker=reranker), offers, labels, args.verbose)


if __name__ == "__main__":
    main()
