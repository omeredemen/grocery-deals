from datetime import date, datetime

from conftest import LAT, LNG, NOW
from rich.console import Console
from typer.testing import CliRunner

from deals import cli
from deals.matching.shopping_list import parse_list
from deals.models import Offer
from deals.optimize.planner import format_amount, make_plan
from deals.report import render_plan
from deals.storage import Storage

DAY = date(2026, 10, 20)


def offer(title, retailer, price, amount, unit, regular=None):
    return Offer(id=f"{retailer}-{title}", source="test", retailer=retailer, title=title, price_eur=price,
                 amount=amount, unit=unit, unit_price_eur=round(price / amount, 4), regular_price_eur=regular,
                 valid_from=date(2026, 10, 19), valid_to=date(2026, 10, 24), fetched_at=NOW)


OFFERS = [
    offer("H-Milch", "Netto", 0.69, 1.0, "l", regular=1.19),
    offer("Frische Vollmilch", "Lidl", 0.95, 1.0, "l", regular=1.39),
    offer("Deutsche Markenbutter", "Lidl", 1.19, 0.25, "kg", regular=2.29),
    offer("Butter", "Netto", 1.29, 0.25, "kg", regular=2.29),
    offer("Röstkaffee Mild mit einem sehr langen Namen", "Lidl", 9.99, 1.0, "kg", regular=13.99),
    offer("Bio Ingwer", "Denns", 0.44, 0.1, "kg", regular=0.59),
]


def render(items: str, penalty: float = 2.0) -> str:
    result = make_plan(parse_list(items), OFFERS, DAY, store_penalty=penalty)
    console = Console(record=True, width=80, color_system=None)
    console.print(render_plan(result, plz="10115", day=DAY, store_penalty=penalty,
                              fetched_at=datetime(2026, 10, 18, 16, 4)))
    return console.export_text()


def test_report_sections():
    out = render("Milch 2l, Butter, Kichererbsen")
    assert "Shopping plan PLZ 10115 · Tue 20.10.2026" in out
    # Netto: 2× 0,69 + 1,29 = 2,67 €; Lidl: 2× 0,95 + 1,19 = 3,09 €; both: 2,57 € + 2 € penalty
    assert "Recommended stores: Netto" in out
    assert "2× 0,69 €" in out and "0,69 €/l" in out and "24.10." in out
    assert "No deal this week: Kichererbsen" in out
    assert "Recommended vs. cheapest per item" in out
    assert "1 more store would save 0,10 € on goods but cost 2,00 € in penalties." in out
    assert "Only normal prices: no app, card, coupon or multi-buy offers." in out


def test_report_lists_items_bought_at_normal_price():
    out = render("Milch 2l, Butter, Ingwer")
    assert "Buy at normal price wherever you shop" in out and "  Ingwer             ~0,59 €" in out
    assert "Denns" not in out


def test_report_fits_80_columns_and_keeps_pack_size_visible():
    out = render("Kaffee, Butter")
    assert max(len(line) for line in out.splitlines()) <= 80
    assert "· 1 kg" in out           # long title shortened, pack size kept
    assert "Items without an amount are compared per typical pack size" not in out  # pay == goods here


def test_report_when_cheapest_is_recommended():
    assert "also the cheapest per item" in render("Butter", penalty=0.0)


def test_report_with_nothing_matching():
    out = render("Kichererbsen")
    assert "No offers match your list on this date." in out
    assert "Recommended vs." not in out


def test_format_amount():
    assert [format_amount(0.5, "kg"), format_amount(0.25, "l"), format_amount(2.0, "l"), format_amount(10, "stk")] == \
        ["500 g", "250 ml", "2 l", "10 Stk"]


def _cli(tmp_path, monkeypatch, mock_kaufda, *args):
    db = tmp_path / "deals.sqlite"
    s = Storage(db)
    s.save_geocode("10115", LAT, LNG)
    s.close()
    monkeypatch.setattr(cli, "get_source", lambda name: mock_kaufda)
    return CliRunner().invoke(cli.app, ["plan", "--plz", "10115", "--db", str(db), *args])


def test_list_file(tmp_path, monkeypatch, mock_kaufda):
    f = tmp_path / "einkauf.txt"
    f.write_text("# Wocheneinkauf\nMilch 2l\nButter, Eier 10   # Freiland\n\nKichererbsen\n", encoding="utf-8")
    result = _cli(tmp_path, monkeypatch, mock_kaufda, "--list-file", str(f), "--date", "2026-10-20")
    assert result.exit_code == 0, result.output
    assert "Recommended stores:" in result.output and "No deal this week: Kichererbsen" in result.output
    assert "Wocheneinkauf" not in result.output        # comments are ignored
    assert "Eier 10 Stk" in result.output


def test_list_options_are_validated(tmp_path, monkeypatch, mock_kaufda):
    assert _cli(tmp_path, monkeypatch, mock_kaufda).exit_code != 0                        # neither
    f = tmp_path / "l.txt"
    f.write_text("Milch")
    assert _cli(tmp_path, monkeypatch, mock_kaufda, "--list", "Milch", "--list-file", str(f)).exit_code != 0
    bad = _cli(tmp_path, monkeypatch, mock_kaufda, "--list", "Milch", "--date", "20.10.2026")
    assert bad.exit_code != 0 and "2026-10-20" in bad.output
