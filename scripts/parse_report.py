"""Report how well the unit parser does on the saved samples.

Usage:  .venv/bin/python scripts/parse_report.py [--all-failures] [--samples samples/brochures_10115]
"""

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from deals.fetcher.kaufda import dedupe, parse_offers
from deals.parsing.units import enrich, parse_base_price

ROOT = Path(__file__).resolve().parent.parent


def load_offers(folder: Path):
    now = datetime.now().astimezone()
    offers = []
    for f in sorted(folder.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        offers += parse_offers(d["brochure"], d["pages"], now)
    return [enrich(o) for o in dedupe(offers)]


def is_food(o) -> bool:
    return (o.category or "").startswith("Lebensmittel")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=Path, default=ROOT / "samples" / "brochures_10115")
    ap.add_argument("--all-failures", action="store_true", help="also list non-food failures")
    args = ap.parse_args()

    offers = load_offers(args.samples)
    food = [o for o in offers if is_food(o)]

    def rate(group):
        ok = sum(1 for o in group if o.unit_price_eur is not None)
        return f"{ok}/{len(group)} = {ok / len(group):.1%}"

    print(f"All offers:  {rate(offers)}")
    print(f"Food offers: {rate(food)}")
    with_bp = [o for o in offers if o.raw_base_price_text]
    bp_ok = sum(1 for o in with_bp if parse_base_price(o.raw_base_price_text))
    print(f"Grundpreis texts parsed: {bp_ok}/{len(with_bp)}")
    print("Units (food):", dict(Counter(o.unit for o in food)))

    print("\nGrundpreis texts we could not parse:")
    for o in with_bp:
        if not parse_base_price(o.raw_base_price_text):
            print(f"  {o.raw_base_price_text!r:30}  [{o.retailer}] {o.title}")

    failures = [o for o in (offers if args.all_failures else food) if o.unit_price_eur is None]
    print(f"\nFailures ({'all' if args.all_failures else 'food'}): {len(failures)}")
    for o in failures:
        print(f"  [{o.retailer}] {o.title} | {o.raw_quantity_text!r} | cond={o.price_conditions!r}")


if __name__ == "__main__":
    main()
