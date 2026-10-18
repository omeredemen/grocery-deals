"""Streamlit UI: enter a PLZ and a shopping list, see the plan.

Run:  deals ui        (or: streamlit run src/deals/ui/app.py)
"""

import os
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from deals.fetcher import get_source
from deals.matching.matcher import Matcher
from deals.matching.shopping_list import parse_list
from deals.optimize.planner import PlanResult, item_key, make_plan
from deals.report import eur, offer_label, per_unit
from deals.service import LoadError, offers_for_plz
from deals.storage import DEFAULT_DB

EXAMPLE_LIST = "Milch 2l\nEier 10\nBananen\nKaffee 500g\nButter\nNudeln 500g\nHackfleisch 500g\nÄpfel bio"

st.set_page_config(page_title="Grocery deals", page_icon="🛒", layout="centered")
st.title("🛒 Berlin grocery deals")
st.caption("This week's supermarket brochure offers (kaufDA), matched to your shopping list. "
           "Normal in-store prices only: no app, card, coupon or multi-buy offers.")

# A form, so the plan is computed when you press the button, not on every keystroke.
with st.form("plan"):
    col1, col2 = st.columns([1, 2])
    plz = col1.text_input("PLZ", value="10115", max_chars=5)
    day = col2.date_input("Shopping date", value=date.today(), format="DD.MM.YYYY")
    shopping_list = st.text_area("Shopping list (one item per line)", value=EXAMPLE_LIST, height=200,
                                 help="German or English. Examples: Milch 2l · eggs 10 · Äpfel bio · organic apples · "
                                      "Milch 1,5% · Joghurt +laktosefrei")
    penalty = st.slider("Store penalty: how many € is one extra store worth to you?", 0.0, 10.0, 2.0, 0.5)
    force = st.checkbox("Refetch offers (otherwise cached for 3 days)")
    submitted = st.form_submit_button("Plan my shopping", type="primary")

if submitted:
    st.session_state["request"] = (plz.strip(), day, shopping_list, penalty, force)

if "request" not in st.session_state:
    st.stop()

plz, day, shopping_list, penalty, force = st.session_state["request"]
items = parse_list(shopping_list)
if not items:
    st.warning("The shopping list is empty.")
    st.stop()

db = Path(os.environ.get("DEALS_DB", DEFAULT_DB))
try:
    with st.spinner("Loading offers… (the first fetch for an area takes about a minute)"):
        loaded, _, _ = offers_for_plz(plz, get_source("kaufda"), db, timedelta(days=3), force)
except LoadError as e:
    st.error(str(e))
    st.stop()

result: PlanResult = make_plan(items, loaded.offers, day, penalty)
rec, cheap = result.recommended, result.cheapest_per_item

st.divider()
c1, c2, c3 = st.columns(3)
c1.metric("Stores", len(rec.stores))
c2.metric("Total incl. penalty", eur(rec.objective),
          delta=f"{eur(cheap.objective - rec.objective)} better than cheapest-per-item"
          if cheap.objective - rec.objective >= 0.005 else None)
c3.metric("At the till (deals)", eur(rec.total_pay))

if rec.stores:
    st.subheader("Recommended stores: " + ", ".join(rec.stores))
    for store in rec.stores:
        rows = [
            {"Item": key, "Offer · pack": offer_label(c),
             "Price": (f"{c.packs}× " if c.packs > 1 else "") + eur(c.offer.price_eur),
             "Per unit": per_unit(c.offer.unit_price_eur, c.offer.unit),
             "Valid until": f"{c.offer.valid_to:%d.%m.}" if c.offer.valid_to else ""}
            for key, c in rec.choices.items() if c.offer.retailer == store
        ]
        st.markdown(f"**{store}** · subtotal {eur(sum(c.pay for c in rec.choices.values() if c.offer.retailer == store))}")
        st.dataframe(rows, hide_index=True, use_container_width=True)
elif not rec.off_deal:
    st.warning("No offers match your list on this date.")

if rec.off_deal:
    st.info("**Buy at normal price wherever you shop** (deal not worth an extra store):\n\n" +
            "\n".join(f"- {item}: ~{eur(o.normal_cost)}" for item, o in rec.off_deal.items()))
if rec.no_deal:
    st.warning("**No deal this week:** " + ", ".join(item_key(i) for i in rec.no_deal))

st.subheader("Recommended vs. cheapest per item")
st.dataframe(
    [
        {"": "Stores", "Recommended": str(len(rec.stores)), "Cheapest per item": str(len(cheap.stores))},
        {"": "Goods (comparable)", "Recommended": eur(rec.total_cost), "Cheapest per item": eur(cheap.total_cost)},
        {"": "Store penalty", "Recommended": eur(rec.penalty), "Cheapest per item": eur(cheap.penalty)},
        {"": "Total", "Recommended": eur(rec.objective), "Cheapest per item": eur(cheap.objective)},
    ],
    hide_index=True,
)
if cheap.stores and len(cheap.stores) > len(rec.stores) and cheap.total_cost < rec.total_cost:
    extra = len(cheap.stores) - len(rec.stores)
    st.caption(f"{extra} more store{'s' if extra > 1 else ''} would save {eur(rec.total_cost - cheap.total_cost)} "
               f"on goods but cost {eur(cheap.penalty - rec.penalty)} in penalties.")

with st.expander("All matching offers per item"):
    matcher = Matcher()
    for item in items:
        matches = matcher.match(item, loaded.offers)
        st.markdown(f"**{item_key(item)}**: {len(matches)} match(es)")
        if matches:
            matches.sort(key=lambda m: (m.offer.unit_price_eur is None, m.offer.unit_price_eur or m.offer.price_eur))
            st.dataframe(
                [{"Store": m.offer.retailer, "Offer": m.offer.title, "Price": eur(m.offer.price_eur),
                  "Per unit": per_unit(m.offer.unit_price_eur, m.offer.unit),
                  "Valid": f"{m.offer.valid_from:%d.%m.}–{m.offer.valid_to:%d.%m.}" if m.offer.valid_to else "",
                  "Why": m.reason} for m in matches[:15]],
                hide_index=True, use_container_width=True,
            )

notes = []
if result.not_yet_valid:
    notes.append(f"{result.not_yet_valid} matching offers start after {day:%d.%m.}; pick a later date to include them.")
if rec.off_deal:
    notes.append("Normal prices are estimates from the brochures' regular/RRP prices.")
notes.append(f"Offers loaded {loaded.fetched_at:%d.%m. %H:%M}.")
st.caption(" · ".join(notes))
