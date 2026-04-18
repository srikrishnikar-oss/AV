from __future__ import annotations

from functools import lru_cache

import requests


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "AVRoutingSuite/0.1 (academic prototype)"
LOCAL_PLACE_INDEX = {
    "cubbon park": {
        "display_name": "Cubbon Park, Bengaluru, Karnataka, India",
        "lat": 12.976347,
        "lon": 77.592917,
    },
    "cubbon park, bengaluru": {
        "display_name": "Cubbon Park, Bengaluru, Karnataka, India",
        "lat": 12.976347,
        "lon": 77.592917,
    },
    "indiranagar metro station": {
        "display_name": "Indiranagar Metro Station, Bengaluru, Karnataka, India",
        "lat": 12.978371,
        "lon": 77.640835,
    },
    "indiranagar metro station, bengaluru": {
        "display_name": "Indiranagar Metro Station, Bengaluru, Karnataka, India",
        "lat": 12.978371,
        "lon": 77.640835,
    },
    "mg road": {
        "display_name": "MG Road, Bengaluru, Karnataka, India",
        "lat": 12.975526,
        "lon": 77.60679,
    },
    "mg road, bengaluru": {
        "display_name": "MG Road, Bengaluru, Karnataka, India",
        "lat": 12.975526,
        "lon": 77.60679,
    },
    "koramangala": {
        "display_name": "Koramangala, Bengaluru, Karnataka, India",
        "lat": 12.935193,
        "lon": 77.624481,
    },
    "koramangala, bengaluru": {
        "display_name": "Koramangala, Bengaluru, Karnataka, India",
        "lat": 12.935193,
        "lon": 77.624481,
    },
    "electronic city": {
        "display_name": "Electronic City, Bengaluru, Karnataka, India",
        "lat": 12.839935,
        "lon": 77.677033,
    },
    "electronic city, bengaluru": {
        "display_name": "Electronic City, Bengaluru, Karnataka, India",
        "lat": 12.839935,
        "lon": 77.677033,
    },
    "kempegowda international airport": {
        "display_name": "Kempegowda International Airport, Bengaluru, Karnataka, India",
        "lat": 13.198635,
        "lon": 77.706593,
    },
    "kempegowda international airport, bengaluru": {
        "display_name": "Kempegowda International Airport, Bengaluru, Karnataka, India",
        "lat": 13.198635,
        "lon": 77.706593,
    },
    "whitefield": {
        "display_name": "Whitefield, Bengaluru, Karnataka, India",
        "lat": 12.969637,
        "lon": 77.749745,
    },
    "whitefield, bengaluru": {
        "display_name": "Whitefield, Bengaluru, Karnataka, India",
        "lat": 12.969637,
        "lon": 77.749745,
    },
    "banashankari": {
        "display_name": "Banashankari, Bengaluru, Karnataka, India",
        "lat": 12.925453,
        "lon": 77.546757,
    },
    "banashankari, bengaluru": {
        "display_name": "Banashankari, Bengaluru, Karnataka, India",
        "lat": 12.925453,
        "lon": 77.546757,
    },
}


def _normalize_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


@lru_cache(maxsize=128)
def geocode_place(query: str) -> dict[str, object]:
    normalized_query = _normalize_query(query)
    local_match = LOCAL_PLACE_INDEX.get(normalized_query)
    if local_match is not None:
        return {
            "query": query,
            "display_name": local_match["display_name"],
            "lat": float(local_match["lat"]),
            "lon": float(local_match["lon"]),
        }

    for known_query, local_entry in LOCAL_PLACE_INDEX.items():
        if normalized_query in known_query or known_query in normalized_query:
            return {
                "query": query,
                "display_name": local_entry["display_name"],
                "lat": float(local_entry["lat"]),
                "lon": float(local_entry["lon"]),
            }

    try:
        response = requests.get(
            NOMINATIM_URL,
            params={
                "q": query,
                "format": "jsonv2",
                "limit": 1,
                "countrycodes": "in",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=4,
        )
        response.raise_for_status()
        items = response.json()
    except requests.RequestException as error:
        raise ValueError(
            "Location lookup timed out. For the demo, try Cubbon Park, Indiranagar Metro Station, MG Road, "
            "Koramangala, Whitefield, Banashankari, Electronic City, or Kempegowda International Airport."
        ) from error

    if not items:
        raise ValueError(f"No location found for '{query}'")

    item = items[0]
    return {
        "query": query,
        "display_name": item.get("display_name", query),
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
    }
