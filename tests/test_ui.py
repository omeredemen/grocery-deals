"""Runs the real Streamlit script with AppTest against a cache pre-filled from samples/
(so no network). Skipped if streamlit isn't installed (it's the optional 'ui' extra)."""

import json
from datetime import date, datetime
from pathlib import Path

import pytest
from conftest import BROCHURES, LAT, LNG

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from deals.fetcher.kaufda import BERLIN, GROCERY_RETAILERS, KaufdaSource, dedupe, parse_offers  # noqa: E402
from deals.storage import Storage, area_key  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "src" / "deals" / "ui" / "app.py"


@pytest.fixture
def app(tmp_path, monkeypatch):
    db = tmp_path / "deals.sqlite"
    now = datetime.now(BERLIN)
    offers = []
    for f in sorted(BROCHURES.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        offers += parse_offers(d["brochure"], d["pages"], now)
    s = Storage(db)
    s.save_geocode("10115", LAT, LNG)
    s.save_offers(f"kaufda:v{KaufdaSource.cache_version}", area_key(LAT, LNG),
                  [o for o in dedupe(offers) if o.retailer in GROCERY_RETAILERS], now)
    s.close()
    monkeypatch.setenv("DEALS_DB", str(db))
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    return at


def submit(at, shopping_list, plz="10115"):
    at.text_input[0].set_value(plz)
    at.date_input[0].set_value(date(2026, 10, 20))
    at.text_area[0].set_value(shopping_list)
    at.button[0].click()
    return at.run()


def test_start_page_shows_only_the_form(app):
    assert not app.exception
    assert app.text_area[0].value.startswith("Milch 2l")
    assert not app.metric


def test_plan(app):
    at = submit(app, "Milch 2l\nButter\nBananen\nKichererbsen")
    assert not at.exception
    assert any(s.value.startswith("Recommended stores:") for s in at.subheader)
    assert [m.label for m in at.metric] == ["Stores", "Total incl. penalty", "At the till (deals)"]
    assert any("Kichererbsen" in w.value for w in at.warning)
    assert len(at.dataframe) >= 2  # store table(s) + comparison


def test_unknown_plz_shows_error(app):
    at = submit(app, "Milch", plz="abc")
    assert any("not a German postal code" in e.value for e in at.error)
