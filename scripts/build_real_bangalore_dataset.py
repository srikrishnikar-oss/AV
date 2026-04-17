from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import LineString, Point


CITY_NAME = "Bengaluru, Karnataka, India"
DEFAULT_BOUNDS = {
    "north": 13.15,
    "south": 12.85,
    "east": 77.75,
    "west": 77.45,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a Bangalore routing dataset from OpenStreetMap and OpenCellID."
    )
    parser.add_argument(
        "--city",
        default=CITY_NAME,
        help="Place name for OSMnx graph lookup.",
    )
    parser.add_argument(
        "--output-root",
        default="data",
        help="Root directory for raw/processed output folders.",
    )
    parser.add_argument(
        "--opencellid-csv",
        required=True,
        help="Path to the downloaded OpenCellID CSV export.",
    )
    parser.add_argument(
        "--provider-mapping",
        default="config/provider_mapping.sample.json",
        help="Optional JSON file mapping MCC-MNC keys to provider names.",
    )
    return parser.parse_args()


def load_provider_mapping(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_dirs(output_root: Path) -> tuple[Path, Path]:
    raw_dir = output_root / "raw"
    processed_dir = output_root / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir, processed_dir


def midpoint_for_geometry(geometry: LineString | None, u_lon: float, u_lat: float, v_lon: float, v_lat: float) -> Point:
    if geometry is None or geometry.is_empty:
        geometry = LineString([(u_lon, u_lat), (v_lon, v_lat)])
    return geometry.interpolate(0.5, normalized=True)


def build_road_segments(city: str) -> gpd.GeoDataFrame:
    graph = ox.graph_from_place(city, network_type="drive", simplify=True)
    graph = ox.routing.add_edge_speeds(graph)
    graph = ox.routing.add_edge_travel_times(graph)

    nodes_gdf, edges_gdf = ox.graph_to_gdfs(graph, nodes=True, edges=True)
    nodes = nodes_gdf[["x", "y"]].rename(columns={"x": "lon", "y": "lat"})

    road_segments = edges_gdf.reset_index().copy()
    road_segments["start_lon"] = road_segments["u"].map(nodes["lon"])
    road_segments["start_lat"] = road_segments["u"].map(nodes["lat"])
    road_segments["end_lon"] = road_segments["v"].map(nodes["lon"])
    road_segments["end_lat"] = road_segments["v"].map(nodes["lat"])
    road_segments["road_type"] = road_segments["highway"].apply(
        lambda value: value[0] if isinstance(value, list) else value
    )
    road_segments["midpoint"] = road_segments.apply(
        lambda row: midpoint_for_geometry(
            row.geometry,
            row.start_lon,
            row.start_lat,
            row.end_lon,
            row.end_lat,
        ),
        axis=1,
    )
    road_segments["midpoint_lat"] = road_segments["midpoint"].apply(lambda point: point.y)
    road_segments["midpoint_lon"] = road_segments["midpoint"].apply(lambda point: point.x)
    road_segments["segment_id"] = [f"S{i:05d}" for i in range(1, len(road_segments) + 1)]

    keep_cols = [
        "segment_id",
        "u",
        "v",
        "start_lat",
        "start_lon",
        "end_lat",
        "end_lon",
        "midpoint_lat",
        "midpoint_lon",
        "length",
        "travel_time",
        "road_type",
        "geometry",
    ]
    road_segments = road_segments[keep_cols].rename(
        columns={
            "u": "start_node",
            "v": "end_node",
            "length": "length_m",
            "travel_time": "travel_time_s",
        }
    )
    return gpd.GeoDataFrame(road_segments, geometry="geometry", crs="EPSG:4326")


def normalize_radio_type(value: object) -> str:
    if pd.isna(value):
        return "unknown"
    text = str(value).strip().upper()
    aliases = {
        "NR": "5G",
        "LTE": "4G",
        "UMTS": "3G",
        "WCDMA": "3G",
        "GSM": "2G",
    }
    return aliases.get(text, text)


def default_signal_for_radio(radio_type: str) -> float:
    if radio_type == "5G":
        return 90.0
    if radio_type == "4G":
        return 80.0
    if radio_type == "3G":
        return 62.0
    if radio_type == "2G":
        return 45.0
    return 55.0


def default_radius_for_radio(radio_type: str) -> float:
    if radio_type == "5G":
        return 1200.0
    if radio_type == "4G":
        return 2500.0
    if radio_type == "3G":
        return 3500.0
    if radio_type == "2G":
        return 4500.0
    return 3000.0


def map_provider(row: pd.Series, provider_mapping: Dict[str, str]) -> str:
    mcc = str(int(row["mcc"])) if not pd.isna(row.get("mcc")) else "unknown"
    mnc = str(int(row["net"])) if not pd.isna(row.get("net")) else "unknown"
    key = f"{mcc}-{mnc}"
    return provider_mapping.get(key, f"MCC{mcc}-MNC{mnc}")


def load_towers(csv_path: Path, provider_mapping: Dict[str, str], bounds: Dict[str, float]) -> gpd.GeoDataFrame:
    towers = pd.read_csv(csv_path, low_memory=False)

    normalized_required = {"tower_id", "lat", "lon", "provider", "radio_type", "base_strength", "coverage_radius_m"}
    if normalized_required.issubset(set(towers.columns)):
        towers = towers.dropna(subset=["lat", "lon"]).copy()
        towers = towers[
            towers["lat"].between(bounds["south"], bounds["north"])
            & towers["lon"].between(bounds["west"], bounds["east"])
        ].copy()
        geometry = gpd.points_from_xy(towers["lon"], towers["lat"])
        return gpd.GeoDataFrame(towers[list(normalized_required)], geometry=geometry, crs="EPSG:4326")

    required_cols = {"lat", "lon", "radio"}
    missing = required_cols - set(towers.columns)
    if missing:
        raise ValueError(f"OpenCellID CSV is missing required columns: {sorted(missing)}")

    towers = towers.dropna(subset=["lat", "lon"]).copy()
    towers = towers[
        towers["lat"].between(bounds["south"], bounds["north"])
        & towers["lon"].between(bounds["west"], bounds["east"])
    ].copy()
    towers["radio_type"] = towers["radio"].apply(normalize_radio_type)
    towers["base_strength"] = towers["averageSignal"] if "averageSignal" in towers.columns else math.nan
    towers["base_strength"] = towers.apply(
        lambda row: row["base_strength"]
        if pd.notna(row["base_strength"]) and row["base_strength"] > 0
        else default_signal_for_radio(row["radio_type"]),
        axis=1,
    )
    towers["coverage_radius_m"] = towers["range"] if "range" in towers.columns else math.nan
    towers["coverage_radius_m"] = towers.apply(
        lambda row: row["coverage_radius_m"]
        if pd.notna(row["coverage_radius_m"]) and row["coverage_radius_m"] > 0
        else default_radius_for_radio(row["radio_type"]),
        axis=1,
    )
    towers["provider"] = towers.apply(lambda row: map_provider(row, provider_mapping), axis=1)
    towers["tower_id"] = [f"T{i:05d}" for i in range(1, len(towers) + 1)]

    keep_cols = [
        "tower_id",
        "lat",
        "lon",
        "provider",
        "radio_type",
        "base_strength",
        "coverage_radius_m",
    ]
    towers = towers[keep_cols].drop_duplicates(subset=["lat", "lon", "provider", "radio_type"])
    geometry = gpd.points_from_xy(towers["lon"], towers["lat"])
    return gpd.GeoDataFrame(towers, geometry=geometry, crs="EPSG:4326")


def load_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def compute_connectivity(
    road_segments: gpd.GeoDataFrame,
    towers: gpd.GeoDataFrame,
    weak_zones: pd.DataFrame,
    feedback: pd.DataFrame,
) -> pd.DataFrame:
    road_proj = road_segments.to_crs(epsg=32643)
    towers_proj = towers.to_crs(epsg=32643)

    tower_records = []
    for row in towers_proj.itertuples(index=False):
        tower_records.append(
            {
                "tower_id": row.tower_id,
                "provider": row.provider,
                "base_strength": float(row.base_strength),
                "coverage_radius_m": float(row.coverage_radius_m),
                "geometry": row.geometry,
            }
        )

    zone_records = []
    if not weak_zones.empty:
        zones_gdf = gpd.GeoDataFrame(
            weak_zones.copy(),
            geometry=gpd.points_from_xy(weak_zones["center_lon"], weak_zones["center_lat"]),
            crs="EPSG:4326",
        ).to_crs(epsg=32643)
        for row in zones_gdf.itertuples(index=False):
            zone_records.append(
                {
                    "zone_id": row.zone_id,
                    "radius_m": float(row.radius_m),
                    "attenuation_factor": float(row.attenuation_factor),
                    "geometry": row.geometry,
                }
            )

    feedback_records = []
    if not feedback.empty:
        feedback_gdf = gpd.GeoDataFrame(
            feedback.copy(),
            geometry=gpd.points_from_xy(feedback["lon"], feedback["lat"]),
            crs="EPSG:4326",
        ).to_crs(epsg=32643)
        for row in feedback_gdf.itertuples(index=False):
            feedback_records.append(
                {
                    "weight_adjustment": abs(float(row.weight_adjustment)),
                    "count": float(row.count),
                    "geometry": row.geometry,
                }
            )

    rows = []
    providers = sorted(towers["provider"].unique().tolist())
    for segment in road_proj.itertuples(index=False):
        provider_signals = {provider: 0.0 for provider in providers}

        for tower in tower_records:
            distance = segment.geometry.distance(tower["geometry"])
            if distance <= tower["coverage_radius_m"]:
                signal = tower["base_strength"] * max(0.0, 1.0 - distance / tower["coverage_radius_m"])
                provider_signals[tower["provider"]] = max(provider_signals[tower["provider"]], signal)
        provider_strengths = sorted([value for value in provider_signals.values() if value > 0.0], reverse=True)
        best_signal = provider_strengths[0] if provider_strengths else 0.0
        second_signal = provider_strengths[1] if len(provider_strengths) > 1 else 0.0
        top_provider_strengths = provider_strengths[:3]
        avg_signal = sum(top_provider_strengths) / len(top_provider_strengths) if top_provider_strengths else 0.0
        min_signal = min(top_provider_strengths) if top_provider_strengths else 0.0

        attenuation = 1.0
        zone_penalty = 0.0
        dead_zone_flag = 0
        for zone in zone_records:
            if segment.geometry.distance(zone["geometry"]) <= zone["radius_m"]:
                attenuation *= zone["attenuation_factor"]
                zone_penalty += 1.0 - zone["attenuation_factor"]
                if zone["attenuation_factor"] <= 0.35:
                    dead_zone_flag = 1

        feedback_penalty = 0.0
        for item in feedback_records:
            if segment.geometry.distance(item["geometry"]) <= 280.0:
                feedback_penalty += item["weight_adjustment"] * min(1.0, item["count"] / 5.0)

        avg_signal *= attenuation * (1.0 - min(feedback_penalty, 0.35))
        best_signal *= attenuation * (1.0 - min(feedback_penalty, 0.30))
        min_signal *= attenuation * (1.0 - min(feedback_penalty, 0.40))

        strong_provider_count = sum(1 for value in provider_signals.values() if value >= 25.0)
        provider_redundancy_score = min(160.0, best_signal + 0.75 * second_signal)
        latency_risk = max(0.0, min(1.0, 1.0 - avg_signal / 100.0))
        handover_risk = max(
            0.05,
            min(
                0.95,
                (max(0, 4 - strong_provider_count) * 0.08)
                + (feedback_penalty * 0.25)
                + (zone_penalty * 0.08),
            ),
        )
        risk_score = max(
            0.0,
            min(
                1.0,
                (latency_risk * 0.45)
                + (dead_zone_flag * 0.30)
                + (feedback_penalty * 0.20)
                + (zone_penalty * 0.10)
                + (handover_risk * 0.15),
            ),
        )
        safe_flag = 1 if min_signal >= 50.0 and dead_zone_flag == 0 and risk_score < 0.4 else 0

        rows.append(
            {
                "segment_id": segment.segment_id,
                "avg_signal": round(avg_signal, 2),
                "min_signal": round(min_signal, 2),
                "provider_best_signal": round(best_signal, 2),
                "provider_redundancy_score": round(provider_redundancy_score, 2),
                "dead_zone_flag": dead_zone_flag,
                "risk_score": round(risk_score, 3),
                "handover_risk": round(handover_risk, 3),
                "safe_flag": safe_flag,
            }
        )

    return pd.DataFrame(rows)


def write_outputs(
    raw_dir: Path,
    processed_dir: Path,
    road_segments: gpd.GeoDataFrame,
    towers: gpd.GeoDataFrame,
    weak_zones: pd.DataFrame,
    feedback: pd.DataFrame,
    environment_profiles: pd.DataFrame,
    segment_connectivity: pd.DataFrame,
) -> None:
    road_csv = road_segments.drop(columns=["geometry"]).copy()
    road_csv.to_csv(raw_dir / "road_segments.csv", index=False)
    towers.drop(columns=["geometry"]).to_csv(raw_dir / "towers.csv", index=False)
    if not weak_zones.empty:
        weak_zones.to_csv(raw_dir / "weak_zones.csv", index=False)
    if not feedback.empty:
        feedback.to_csv(raw_dir / "feedback.csv", index=False)
    if not environment_profiles.empty:
        environment_profiles.to_csv(raw_dir / "environment_profiles.csv", index=False)

    segment_connectivity.to_csv(processed_dir / "segment_connectivity.csv", index=False)
    summary = {
        "city": CITY_NAME,
        "road_segments": int(len(road_segments)),
        "towers": int(len(towers)),
        "weak_zones": int(len(weak_zones)),
        "feedback_entries": int(len(feedback)),
        "connectivity_rows": int(len(segment_connectivity)),
    }
    (processed_dir / "adaptive_signal_map.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    output_root = Path(args.output_root)
    raw_dir, processed_dir = ensure_dirs(output_root)
    provider_mapping = load_provider_mapping(Path(args.provider_mapping))

    road_segments = build_road_segments(args.city)
    bounds = {
        "north": float(road_segments["start_lat"].max()) + 0.01,
        "south": float(road_segments["start_lat"].min()) - 0.01,
        "east": float(road_segments["start_lon"].max()) + 0.01,
        "west": float(road_segments["start_lon"].min()) - 0.01,
    }
    for key, value in DEFAULT_BOUNDS.items():
        bounds.setdefault(key, value)

    towers = load_towers(Path(args.opencellid_csv), provider_mapping, bounds)
    weak_zones = load_csv_if_exists(raw_dir / "weak_zones.csv")
    feedback = load_csv_if_exists(raw_dir / "feedback.csv")
    environment_profiles = load_csv_if_exists(raw_dir / "environment_profiles.csv")
    segment_connectivity = compute_connectivity(road_segments, towers, weak_zones, feedback)
    write_outputs(
        raw_dir,
        processed_dir,
        road_segments,
        towers,
        weak_zones,
        feedback,
        environment_profiles,
        segment_connectivity,
    )

    print("Real Bangalore dataset generated successfully.")
    print(f"Road segments: {len(road_segments)}")
    print(f"Towers: {len(towers)}")
    print(f"Weak zones: {len(weak_zones)}")
    print(f"Feedback entries: {len(feedback)}")


if __name__ == "__main__":
    main()
