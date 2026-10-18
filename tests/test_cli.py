from conftest import LAT, LNG
from typer.testing import CliRunner

from deals import cli
from deals.storage import Storage


def test_fetch_command_shows_counts_and_caches(tmp_path, monkeypatch, mock_kaufda):
    db = tmp_path / "deals.sqlite"
    s = Storage(db)
    s.save_geocode("10115", LAT, LNG)  # pre-seed so no Nominatim call happens
    s.close()
    monkeypatch.setattr(cli, "get_source", lambda name: mock_kaufda)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["fetch", "--plz", "10115", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "freshly fetched" in result.output
    assert "REWE" in result.output and "Lidl" in result.output

    again = runner.invoke(cli.app, ["fetch", "--plz", "10115", "--db", str(db)])
    assert again.exit_code == 0
    assert "from cache" in again.output


def test_fetch_command_reports_bad_plz(tmp_path):
    result = CliRunner().invoke(cli.app, ["fetch", "--plz", "abc", "--db", str(tmp_path / "x.sqlite")])
    assert result.exit_code == 1
    assert "not a German postal code" in result.output
