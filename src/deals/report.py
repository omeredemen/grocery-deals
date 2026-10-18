"""Render a shopping plan for the terminal with rich (kept apart from the CLI so it's testable)."""

from datetime import date, datetime

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from deals.optimize.planner import Choice, Plan, PlanResult, format_amount, item_key

OFFER_WIDTH = 24


def eur(x: float) -> str:
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")  # German style: 1.234,56 €


def per_unit(price: float | None, unit: str | None) -> str:
    return f"{eur(price)}/{unit}" if price is not None else "–"


def render_plan(
    result: PlanResult,
    *,
    plz: str,
    day: date,
    store_penalty: float,
    fetched_at: datetime,
) -> Group:
    rec, cheap = result.recommended, result.cheapest_per_item
    parts = []

    header = Text.assemble(
        ("Shopping plan ", "bold"), f"PLZ {plz} · {day:%a %d.%m.%Y} · ",
        f"Store penalty {eur(store_penalty)} · offers from {fetched_at:%d.%m. %H:%M}",
    )
    parts.append(Panel(header, box=box.ROUNDED))

    if rec.stores:
        parts.append(Text.assemble("Recommended stores: ", (", ".join(rec.stores), "bold green")))
        parts.append(_store_tables(rec))
    elif not rec.off_deal:
        parts.append(Text("No offers match your list on this date.", style="yellow"))

    if rec.off_deal:
        parts.append(Text.assemble(("Buy at normal price wherever you shop", "bold"),
                                   " (deal not worth an extra store):"))
        for item, opt in rec.off_deal.items():
            parts.append(Text(f"  {item:<18} ~{eur(opt.normal_cost)}"))
    if rec.no_deal:
        parts.append(Text.assemble(("No deal this week: ", "yellow"), ", ".join(item_key(i) for i in rec.no_deal)))

    if rec.stores:
        parts.append(Text.assemble("At the till for the deals above: ", (eur(rec.total_pay), "bold")))
        parts.append(_comparison(rec, cheap))
        parts.append(_verdict(rec, cheap))
    parts.extend(_notes(result, rec, day))
    return Group(*parts)


def _store_tables(plan: Plan) -> Group:
    tables = []
    for store in plan.stores:
        # Fixed widths so the per-store tables line up (fits 80 columns).
        t = Table(title=store, title_justify="left", title_style="bold", box=box.SIMPLE_HEAD,
                  show_edge=False, pad_edge=False)
        t.add_column("Item", width=17)
        t.add_column("Offer · pack", width=OFFER_WIDTH, no_wrap=True)
        t.add_column("Price", width=10, justify="right")
        t.add_column("Per unit", width=11, justify="right")
        t.add_column("Until", width=6, justify="right", no_wrap=True)
        subtotal = 0.0
        for item, c in plan.choices.items():
            if c.offer.retailer != store:
                continue
            o = c.offer
            price = eur(c.pay) if c.packs == 1 else f"{c.packs}× {eur(o.price_eur)}"
            t.add_row(item, offer_label(c), price, per_unit(o.unit_price_eur, o.unit),
                      f"{o.valid_to:%d.%m.}" if o.valid_to else "")
            subtotal += c.pay
        t.add_row("", Text("subtotal", style="dim"), Text(eur(subtotal), style="bold"), "", "")
        tables.append(t)
    return Group(*tables)


def offer_label(c: Choice) -> str:
    """Title, shortened so the pack size at the end always stays visible."""
    o = c.offer
    size = f" · {format_amount(o.amount, o.unit)}" if o.amount and o.unit else ""
    room = OFFER_WIDTH - len(size)
    title = o.title if len(o.title) <= room else o.title[: room - 1] + "…"
    return title + size


def _comparison(rec: Plan, cheap: Plan) -> Table:
    t = Table(title="Recommended vs. cheapest per item", title_justify="left", box=box.SIMPLE_HEAD,
              show_edge=False, pad_edge=False)
    t.add_column("")
    t.add_column("Recommended", justify="right")
    t.add_column("Cheapest per item", justify="right")
    t.add_row("Stores", str(len(rec.stores)), str(len(cheap.stores)))
    t.add_row("Goods (comparable)", eur(rec.total_cost), eur(cheap.total_cost))
    t.add_row("Store penalty", eur(rec.penalty), eur(cheap.penalty))
    t.add_row(Text("Total", style="bold"), Text(eur(rec.objective), style="bold green"), eur(cheap.objective))
    return t


def _verdict(rec: Plan, cheap: Plan) -> Text:
    extra_stores = len(cheap.stores) - len(rec.stores)
    extra_goods = rec.total_cost - cheap.total_cost
    if extra_stores <= 0 or extra_goods < 0.005:
        return Text("The recommended plan is also the cheapest per item.", style="green")
    return Text(
        f"{extra_stores} more store{'s' if extra_stores > 1 else ''} would save "
        f"{eur(extra_goods)} on goods but cost {eur(cheap.penalty - rec.penalty)} in penalties.",
        style="green",
    )


def _notes(result: PlanResult, rec: Plan, day: date) -> list[Text]:
    notes = []
    unpriced = [item for item, c in rec.choices.items() if c.offer.unit_price_eur is None]
    if unpriced:
        notes.append(f"No unit price for {', '.join(unpriced)}: compared by pack price only.")
    if rec.off_deal:
        notes.append("Normal prices are estimates from the brochures' regular/RRP prices.")
    off_deal_cost = sum(o.normal_cost for o in rec.off_deal.values())
    if abs(rec.total_pay + off_deal_cost - rec.total_cost) >= 0.005:
        notes.append("Items without an amount are compared per typical pack size (unit price × "
                     "typical size), so 'Goods' differs from the till total. Add an amount, "
                     "e.g. 'Kaffee 500g', to plan exact quantities.")
    if result.not_yet_valid:
        notes.append(f"{result.not_yet_valid} matching offers start after {day:%d.%m.} (try --date).")
    notes.append("Only normal prices: no app, card, coupon or multi-buy offers.")
    return [Text(f"• {n}", style="dim") for n in notes]


def print_plan(console: Console, result: PlanResult, **kwargs) -> None:
    console.print(render_plan(result, **kwargs))
