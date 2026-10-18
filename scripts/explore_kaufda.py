"""Phase 1 exploration script: download raw kaufDA data into samples/.

Stdlib only (no venv needed). This is NOT the real fetcher — Phase 2 will turn
the findings into src/deals/fetcher/kaufda.py. See docs/data_source.md.

Usage:  python3 scripts/explore_kaufda.py 10115
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
API = "https://content-viewer-be.kaufda.de"
HEADERS = {
    # Normal browser UA; the API also wants this consumer header (value taken
    # from the kaufDA content-viewer JS bundle).
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Bonial-Api-Consumer": "web-content-viewer-fe",
    "Accept": "application/json",
}
DELAY_S = 2.0  # be polite: one request every 2 seconds

# Retailers we care about for groceries (names exactly as the API returns them).
GROCERY = {
    "REWE", "Lidl", "ALDI Nord", "EDEKA", "E center", "Penny", "Netto Marken-Discount",
    "Netto mit dem Scottie", "Norma", "Kaufland", "Bio Company", "Denns BioMarkt",
    "Alnatura", "Mix Markt", "Selgros", "METRO",
}


def get_json(url: str, params: dict | None = None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    time.sleep(DELAY_S)
    return data


def geocode(plz: str) -> tuple[float, float]:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"postalcode": plz, "country": "de", "format": "json", "limit": 1}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "grocery-deals-personal/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        hit = json.load(r)[0]
    return float(hit["lat"]), float(hit["lon"])


def main(plz: str) -> None:
    lat, lng = geocode(plz)
    print(f"PLZ {plz} -> lat={lat} lng={lng}")
    loc = {"lat": lat, "lng": lng, "partner": "kaufda_web"}

    brochures, page = [], 0
    while True:
        d = get_json(f"{API}/v1/brochures/byLocation", {**loc, "size": 100, "page": page})
        brochures += d["contents"]
        if page + 1 >= d["page"]["totalPages"]:
            break
        page += 1
    out = SAMPLES / f"byLocation_{plz}.json"
    out.write_text(json.dumps(brochures, ensure_ascii=False, indent=1))
    print(f"{len(brochures)} brochures -> {out.name}")

    bdir = SAMPLES / f"brochures_{plz}"
    bdir.mkdir(exist_ok=True)
    for b in brochures:
        c = b["content"]
        name = c["publisher"]["name"]
        if name not in GROCERY or c["type"] != "static_brochure":
            continue
        pages = get_json(f"{API}/v1/brochures/{c['id']}/pages", loc)
        n = sum(len(p.get("offers") or []) for p in pages["contents"])
        (bdir / f"{c['id']}.json").write_text(
            json.dumps({"brochure": c, "pages": pages}, ensure_ascii=False, indent=1)
        )
        print(f"  {name:24} {c['title'][:40]:40} {c['validFrom'][:10]}..{c['validUntil'][:10]} offers={n}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "10115")
