# Berlin Grocery Deal Finder

Finds this week's supermarket deals (kaufDA brochures) for your shopping list and
suggests which stores to visit. Personal project; see `SPEC.md` for the full plan.

## Setup
```
python3 -m venv .venv          # if ensurepip is missing: python3 -m venv --without-pip .venv + get-pip.py
.venv/bin/pip install -e '.[dev]'
```

## Use
```
deals plan --plz 10115 --list "Milch 2l, Eier 10, Bananen, Kaffee, Butter" --store-penalty 2
deals plan --plz 10115 --list-file einkauf.example.txt --date 2026-10-22
deals match --plz 10115 --list "Milch, Kaffee"   # which offers match (debugging)
deals fetch --plz 10115 [--force]                # refresh the offer cache (kept 3 days)
deals ui                                         # web UI (pip install -e '.[ui]')
```
List syntax: `Milch 2l`, `Eier 10`, `Äpfel bio`, `Milch 1,5%`, `Joghurt +laktosefrei`.
English works for ~150 common items (`milk 2l`, `eggs 10 pcs`, `organic apples`,
`chicken breast 500g`); see `src/deals/matching/translate.py` to add more.
Options: `--date` (default today), `--store-penalty` (EUR per extra store, default 2).
Only normal in-store prices are used: no app/loyalty/coupon/multi-buy prices, no wholesale
(METRO/Selgros). Items whose deal isn't worth an extra store are bought at normal price.

## Develop
```
.venv/bin/pytest                                   # offline, uses samples/
.venv/bin/python scripts/parse_report.py           # unit price parse rate
.venv/bin/python scripts/eval_matching.py --holdout # matching accuracy
```
Docs: `docs/data_source.md` (kaufDA API), `docs/matching.md` (matching + evaluation).
