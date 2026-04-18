from __future__ import annotations

from functools import lru_cache

import requests


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "AVRoutingSuite/0.1 (academic prototype)"
LOCAL_PLACE_INDEX = {
    "jayanagar": {
        "display_name": "Jayanagar, Bengaluru, Karnataka, India",
        "lat": 12.929273,
        "lon": 77.582422,
    },
    "jayanagar, bengaluru": {
        "display_name": "Jayanagar, Bengaluru, Karnataka, India",
        "lat": 12.929273,
        "lon": 77.582422,
    },
    "majestic": {
        "display_name": "Majestic, Bengaluru, Karnataka, India",
        "lat": 12.978411,
        "lon": 77.572339,
    },
    "majestic, bengaluru": {
        "display_name": "Majestic, Bengaluru, Karnataka, India",
        "lat": 12.978411,
        "lon": 77.572339,
    },
    "kempegowda bus station": {
        "display_name": "Kempegowda Bus Station, Majestic, Bengaluru, Karnataka, India",
        "lat": 12.978411,
        "lon": 77.572339,
    },
    "kempegowda bus station, bengaluru": {
        "display_name": "Kempegowda Bus Station, Majestic, Bengaluru, Karnataka, India",
        "lat": 12.978411,
        "lon": 77.572339,
    },
    "shivajinagar": {
        "display_name": "Shivajinagar, Bengaluru, Karnataka, India",
        "lat": 12.985447,
        "lon": 77.604652,
    },
    "shivajinagar, bengaluru": {
        "display_name": "Shivajinagar, Bengaluru, Karnataka, India",
        "lat": 12.985447,
        "lon": 77.604652,
    },
    "malleswaram": {
        "display_name": "Malleswaram, Bengaluru, Karnataka, India",
        "lat": 13.003076,
        "lon": 77.570434,
    },
    "malleswaram, bengaluru": {
        "display_name": "Malleswaram, Bengaluru, Karnataka, India",
        "lat": 13.003076,
        "lon": 77.570434,
    },
    "rajajinagar": {
        "display_name": "Rajajinagar, Bengaluru, Karnataka, India",
        "lat": 12.991409,
        "lon": 77.554413,
    },
    "rajajinagar, bengaluru": {
        "display_name": "Rajajinagar, Bengaluru, Karnataka, India",
        "lat": 12.991409,
        "lon": 77.554413,
    },
    "basavanagudi": {
        "display_name": "Basavanagudi, Bengaluru, Karnataka, India",
        "lat": 12.941726,
        "lon": 77.575502,
    },
    "basavanagudi, bengaluru": {
        "display_name": "Basavanagudi, Bengaluru, Karnataka, India",
        "lat": 12.941726,
        "lon": 77.575502,
    },
    "lalbagh": {
        "display_name": "Lalbagh, Bengaluru, Karnataka, India",
        "lat": 12.950743,
        "lon": 77.584777,
    },
    "lalbagh, bengaluru": {
        "display_name": "Lalbagh, Bengaluru, Karnataka, India",
        "lat": 12.950743,
        "lon": 77.584777,
    },
    "richmond town": {
        "display_name": "Richmond Town, Bengaluru, Karnataka, India",
        "lat": 12.961114,
        "lon": 77.599364,
    },
    "richmond town, bengaluru": {
        "display_name": "Richmond Town, Bengaluru, Karnataka, India",
        "lat": 12.961114,
        "lon": 77.599364,
    },
    "church street": {
        "display_name": "Church Street, Bengaluru, Karnataka, India",
        "lat": 12.974563,
        "lon": 77.607674,
    },
    "church street, bengaluru": {
        "display_name": "Church Street, Bengaluru, Karnataka, India",
        "lat": 12.974563,
        "lon": 77.607674,
    },
    "brigade road": {
        "display_name": "Brigade Road, Bengaluru, Karnataka, India",
        "lat": 12.971619,
        "lon": 77.606814,
    },
    "brigade road, bengaluru": {
        "display_name": "Brigade Road, Bengaluru, Karnataka, India",
        "lat": 12.971619,
        "lon": 77.606814,
    },
    "ulsoor": {
        "display_name": "Ulsoor, Bengaluru, Karnataka, India",
        "lat": 12.982555,
        "lon": 77.620992,
    },
    "ulsoor, bengaluru": {
        "display_name": "Ulsoor, Bengaluru, Karnataka, India",
        "lat": 12.982555,
        "lon": 77.620992,
    },
    "domlur": {
        "display_name": "Domlur, Bengaluru, Karnataka, India",
        "lat": 12.960992,
        "lon": 77.638726,
    },
    "domlur, bengaluru": {
        "display_name": "Domlur, Bengaluru, Karnataka, India",
        "lat": 12.960992,
        "lon": 77.638726,
    },
    "vidhana soudha": {
        "display_name": "Vidhana Soudha, Bengaluru, Karnataka, India",
        "lat": 12.979928,
        "lon": 77.591149,
    },
    "vidhana soudha, bengaluru": {
        "display_name": "Vidhana Soudha, Bengaluru, Karnataka, India",
        "lat": 12.979928,
        "lon": 77.591149,
    },
    "cunningham road": {
        "display_name": "Cunningham Road, Bengaluru, Karnataka, India",
        "lat": 12.990051,
        "lon": 77.59486,
    },
    "cunningham road, bengaluru": {
        "display_name": "Cunningham Road, Bengaluru, Karnataka, India",
        "lat": 12.990051,
        "lon": 77.59486,
    },
    "seshadripuram": {
        "display_name": "Seshadripuram, Bengaluru, Karnataka, India",
        "lat": 12.993476,
        "lon": 77.57254,
    },
    "seshadripuram, bengaluru": {
        "display_name": "Seshadripuram, Bengaluru, Karnataka, India",
        "lat": 12.993476,
        "lon": 77.57254,
    },
    "indra nagar": {
        "display_name": "Indiranagar, Bengaluru, Karnataka, India",
        "lat": 12.978369,
        "lon": 77.640835,
    },
    "indiranagar": {
        "display_name": "Indiranagar, Bengaluru, Karnataka, India",
        "lat": 12.978369,
        "lon": 77.640835,
    },
    "indiranagar, bengaluru": {
        "display_name": "Indiranagar, Bengaluru, Karnataka, India",
        "lat": 12.978369,
        "lon": 77.640835,
    },
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
            "Location lookup timed out. Try a Central Bengaluru place like Jayanagar, Majestic, Shivajinagar, "
            "Malleswaram, Rajajinagar, Basavanagudi, Lalbagh, Richmond Town, MG Road, Church Street, Ulsoor, "
            "Domlur, Cubbon Park, or Indiranagar."
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
