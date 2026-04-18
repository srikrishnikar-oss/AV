from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


CORE_BBOX = {
    "lat_min": 12.96,
    "lat_max": 12.99,
    "lon_min": 77.58,
    "lon_max": 77.62,
}

TOWER_MARGIN = 0.02
ZONE_MARGIN = 0.01


def filter_bbox(frame: pd.DataFrame, lat_col: str, lon_col: str, bbox: dict[str, float], margin: float = 0.0) -> pd.DataFrame:
    return frame[
        frame[lat_col].between(bbox["lat_min"] - margin, bbox["lat_max"] + margin)
        & frame[lon_col].between(bbox["lon_min"] - margin, bbox["lon_max"] + margin)
    ].copy()


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    raw_dir = project_root / "data" / "raw"
    processed_dir = project_root / "data" / "processed"
    mvp_raw_dir = project_root / "data" / "mvp" / "raw"
    mvp_processed_dir = project_root / "data" / "mvp" / "processed"
    mvp_raw_dir.mkdir(parents=True, exist_ok=True)
    mvp_processed_dir.mkdir(parents=True, exist_ok=True)

    roads = pd.read_csv(raw_dir / "road_segments.csv")
    connectivity = pd.read_csv(processed_dir / "segment_connectivity.csv")
    towers = pd.read_csv(raw_dir / "towers_mvp.csv")
    weak_zones = pd.read_csv(raw_dir / "weak_zones.csv")
    feedback = pd.read_csv(raw_dir / "feedback.csv")
    environment = pd.read_csv(raw_dir / "environment_profiles.csv")

    roads_mvp = filter_bbox(roads, "midpoint_lat", "midpoint_lon", CORE_BBOX)
    segment_ids = set(roads_mvp["segment_id"])
    connectivity_mvp = connectivity[connectivity["segment_id"].isin(segment_ids)].copy()
    towers_mvp = filter_bbox(towers, "lat", "lon", CORE_BBOX, margin=TOWER_MARGIN)
    weak_zones_mvp = filter_bbox(weak_zones, "center_lat", "center_lon", CORE_BBOX, margin=ZONE_MARGIN)
    feedback_mvp = filter_bbox(feedback, "lat", "lon", CORE_BBOX, margin=ZONE_MARGIN)

    roads_mvp.to_csv(mvp_raw_dir / "road_segments_mvp.csv", index=False)
    towers_mvp.to_csv(mvp_raw_dir / "towers_mvp.csv", index=False)
    weak_zones_mvp.to_csv(mvp_raw_dir / "weak_zones_mvp.csv", index=False)
    feedback_mvp.to_csv(mvp_raw_dir / "feedback_mvp.csv", index=False)
    environment.to_csv(mvp_raw_dir / "environment_profiles_mvp.csv", index=False)
    connectivity_mvp.to_csv(mvp_processed_dir / "segment_connectivity_mvp.csv", index=False)

    summary = {
        "city": "Bengaluru, Karnataka, India",
        "dataset_type": "central_bangalore_mvp_subset",
        "bbox": CORE_BBOX,
        "road_segments": int(len(roads_mvp)),
        "towers": int(len(towers_mvp)),
        "weak_zones": int(len(weak_zones_mvp)),
        "feedback_entries": int(len(feedback_mvp)),
        "connectivity_rows": int(len(connectivity_mvp)),
    }
    (mvp_processed_dir / "adaptive_signal_map_mvp.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
