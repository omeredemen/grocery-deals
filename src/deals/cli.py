"""Command-line interface: `deals fetch --plz 10115`, `deals match --plz 10115 --list "Milch, Eier"`."""

import logging
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from deals.fetcher import get_source
from deals.matching.matcher import Matcher, dominant_unit
from deals.matching.shopping_list import parse_list
from deals.optimize.planner import make_plan
from deals.report import print_plan
from deals.service import LoadError, OfferResult, offers_for_plz
from deals.storage import DEFAULT_DB

app = typer.Typer(help="Find the cheapest grocery deals near you (Berlin, kaufDA).")
console = Console()


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug logs.")):
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


PLZ = typer.Option(..., help="German postal code, e.g. 10115")
MAX_AGE = typer.Option(3, help="Reuse cached offers younger than this many days.")
FORCE = typer.Option(False, help="Ignore the cache and refetch.")
SOURCE = typer.Option("kaufda", help="Offer source.")
DB = typer.Option(DEFAULT_DB, help="SQLite cache file.")


def _load(plz: str, max_age_days: float, force: bool, source: str, db: Path) -> tuple[OfferResult, float, float]:
    """Offers for a PLZ (from cache or freshly fetched); exits with a message on errors."""
    with console.status("Fetching offers...") as status:
        src = get_source(source)
        if hasattr(src, "progress"):
            src.progress = lambda msg: status.update(f"Fetching {msg}")
        try:
            return offers_for_plz(plz, src, db, timedelta(days=max_age_days), force)
        except LoadError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)


@app.command()
def fetch(plz: str = PLZ, max_age_days: float = MAX_AGE, force: bool = FORCE, source: str = SOURCE, db: Path = DB):
    """Fetch current offers for an area and show a count per retailer."""
    result, lat, lng = _load(plz, max_age_days, force, source, db)
    origin = "from cache" if result.from_cache else "freshly fetched"
    console.print(
        f"PLZ {plz} ({lat:.4f}, {lng:.4f}): [bold]{len(result.offers)}[/bold] offers, "
        f"{origin} at {result.fetched_at:%Y-%m-%d %H:%M}"
    )
    table = Table("Retailer", "Offers", "Food offers", "Food with unit price")
    total = Counter(o.retailer for o in result.offers)
    food_offers = [o for o in result.offers if (o.category or "").startswith("Lebensmittel")]
    food = Counter(o.retailer for o in food_offers)
    priced = Counter(o.retailer for o in food_offers if o.unit_price_eur is not None)
    for retailer, n in total.most_common():
        table.add_row(retailer, str(n), str(food[retailer]), str(priced[retailer]))
    console.print(table)


@app.command()
def match(
    plz: str = PLZ,
    shopping_list: str = typer.Option(..., "--list", help='e.g. "Milch 2l, Eier, Äpfel bio"'),
    top: int = typer.Option(5, help="Show this many offers per item (cheapest first)."),
    semantic: bool = typer.Option(False, help="Use the embedding reranker (needs the 'semantic' extra)."),
    max_age_days: float = MAX_AGE, force: bool = FORCE, source: str = SOURCE, db: Path = DB,
):
    """Show which offers match each shopping list item (Phase 4 debugging view)."""
    result, _, _ = _load(plz, max_age_days, force, source, db)
    reranker = None
    if semantic:
        from deals.matching.semantic import E5Reranker
        reranker = E5Reranker()
    matcher = Matcher(reranker=reranker)

    for item in parse_list(shopping_list):
        matches = matcher.match(item, result.offers)
        extras = " ".join(filter(None, [", ".join(item.filters),
                                        f"{item.wanted_amount:g} {item.wanted_unit}" if item.wanted_amount else ""]))
        console.rule(f"[bold]{item.query}[/bold] {extras}".strip())
        if not matches:
            console.print("  [yellow]No deal found this week.[/yellow]")
            continue
        unit = dominant_unit(matches)
        # Cheapest per unit first; offers in another unit or without unit price after.
        matches.sort(key=lambda m: (m.offer.unit != unit, m.offer.unit_price_eur is None,
                                    m.offer.unit_price_eur or m.offer.price_eur))
        table = Table("Retailer", "Offer", "Price", "Per unit", "Valid", "Why", box=None)
        for m in matches[:top]:
            o = m.offer
            per_unit = f"{o.unit_price_eur:.2f} €/{o.unit}" if o.unit_price_eur is not None else "?"
            table.add_row(o.retailer, o.title[:40], f"{o.price_eur:.2f} €", per_unit,
                          f"{o.valid_from:%d.%m}–{o.valid_to:%d.%m}" if o.valid_to else "", f"{m.reason} ({m.score})")
        console.print(table)
        if len(matches) > top:
            console.print(f"  … and {len(matches) - top} more")


@app.command()
def plan(
    plz: str = PLZ,
    shopping_list: str = typer.Option(None, "--list", help='e.g. "Milch 2l, Eier 10, Bananen, Kaffee, Butter"'),
    list_file: Path = typer.Option(None, "--list-file", exists=True, dir_okay=False,
                                   help="Text file, one item per line (or comma-separated); # starts a comment."),
    store_penalty: float = typer.Option(2.0, help="Extra cost (EUR) you assign to each additional store."),
    shopping_date: str = typer.Option(None, "--date", help="YYYY-MM-DD, default today."),
    max_age_days: float = MAX_AGE, force: bool = FORCE, source: str = SOURCE, db: Path = DB,
):
    """Plan which stores to visit for a shopping list."""
    if (shopping_list is None) == (list_file is None):
        raise typer.BadParameter("give either --list or --list-file")
    try:
        day = date.fromisoformat(shopping_date) if shopping_date else date.today()
    except ValueError:
        raise typer.BadParameter(f"--date must look like 2026-10-20, got {shopping_date!r}")
    text = list_file.read_text(encoding="utf-8") if list_file else shopping_list
    items = parse_list(text)
    if not items:
        raise typer.BadParameter("the shopping list is empty")

    loaded, _, _ = _load(plz, max_age_days, force, source, db)
    result = make_plan(items, loaded.offers, day, store_penalty)
    print_plan(console, result, plz=plz, day=day, store_penalty=store_penalty, fetched_at=loaded.fetched_at)


@app.command()
def ui(port: int = typer.Option(8501, help="Port for the web UI.")):
    """Start the web UI (needs the 'ui' extra: pip install -e '.[ui]')."""
    import subprocess
    import sys

    app_path = Path(__file__).parent / "ui" / "app.py"
    raise typer.Exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path),
                                      "--server.port", str(port)]))


if __name__ == "__main__":
    app()
