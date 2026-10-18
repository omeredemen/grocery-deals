"""Shared fixtures. Tests never hit the live site: HTTP goes through
httpx.MockTransport, which serves the files saved in samples/."""

import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from deals.fetcher.kaufda import BERLIN, KaufdaSource

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
BROCHURES = SAMPLES / "brochures_10115"
LAT, LNG = 52.5321914, 13.3845571
NOW = datetime(2026, 10, 18, 16, 0, tzinfo=BERLIN)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def sample_brochures() -> list[dict]:
    """[{"brochure": ..., "pages": ...}, ...] for the 29 saved grocery brochures."""
    return [load(p) for p in sorted(BROCHURES.glob("*.json"))]


def kaufda_handler(request: httpx.Request) -> httpx.Response:
    """Fake content-viewer-be.kaufda.de backed by samples/."""
    assert request.headers["Bonial-Api-Consumer"] == "web-content-viewer-fe"
    path = request.url.path
    if path == "/v1/brochures/byLocation":
        page = request.url.params["page"]
        return httpx.Response(200, json=load(SAMPLES / f"api_byLocation_10115_page{page}.json"))
    if path.startswith("/v1/brochures/") and path.endswith("/pages"):
        brochure_id = path.split("/")[3]
        f = BROCHURES / f"{brochure_id}.json"
        return httpx.Response(200, json=load(f)["pages"]) if f.exists() else httpx.Response(404)
    return httpx.Response(404)


@pytest.fixture
def mock_kaufda() -> KaufdaSource:
    client = httpx.Client(transport=httpx.MockTransport(kaufda_handler))
    return KaufdaSource(client=client, min_interval=0)
