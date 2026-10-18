"""PLZ -> (lat, lng) via Nominatim (OpenStreetMap), cached in SQLite.

Nominatim's usage policy: identify yourself in the User-Agent, max 1 request/s.
We cache results forever, so each PLZ is looked up only once.
"""

import httpx

from deals.storage import Storage

NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "grocery-deals-personal/0.1 (personal project)"


class GeocodeError(RuntimeError):
    pass


def geocode_plz(plz: str, storage: Storage, client: httpx.Client | None = None) -> tuple[float, float]:
    if not (plz.isdigit() and len(plz) == 5):
        raise GeocodeError(f"{plz!r} is not a German postal code (5 digits)")
    cached = storage.get_geocode(plz)
    if cached:
        return cached

    client = client or httpx.Client(timeout=30)
    resp = client.get(
        NOMINATIM,
        params={"postalcode": plz, "country": "de", "format": "json", "limit": 1},
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        raise GeocodeError(f"Postal code {plz} not found")
    lat, lng = float(hits[0]["lat"]), float(hits[0]["lon"])
    storage.save_geocode(plz, lat, lng, hits[0].get("display_name"))
    return lat, lng
