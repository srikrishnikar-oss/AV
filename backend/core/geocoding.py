from __future__ import annotations

from functools import lru_cache

import requests


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "AVRoutingSuite/0.1 (academic prototype)"


@lru_cache(maxsize=128)
def geocode_place(query: str) -> dict[str, object]:
    response = requests.get(
        NOMINATIM_URL,
        params={
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": "in",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    response.raise_for_status()
    items = response.json()
    if not items:
        raise ValueError(f"No location found for '{query}'")

    item = items[0]
    return {
        "query": query,
        "display_name": item.get("display_name", query),
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
    }
