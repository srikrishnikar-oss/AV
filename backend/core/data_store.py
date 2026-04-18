from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import math
import networkx as nx
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]


RADIO_BASELINE_BANDWIDTH = {
    "2G": 0.35,
    "3G": 6.0,
    "4G": 32.0,
    "5G": 110.0,
}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def estimate_tower_bandwidth_mbps(radio_type: str, base_strength: float) -> float:
    baseline = RADIO_BASELINE_BANDWIDTH.get(str(radio_type).upper(), 18.0)
    strength_factor = 0.45 + (_clamp(float(base_strength), 0.0, 100.0) / 100.0) * 0.75
    return round(baseline * strength_factor, 2)


def estimate_segment_bandwidth_mbps(avg_signal: float, provider_best_signal: float) -> float:
    composite_signal = (float(avg_signal) * 0.65) + (float(provider_best_signal) * 0.35)
    normalized = _clamp(composite_signal / 100.0, 0.0, 1.0)
    bandwidth = 1.2 + (normalized**1.55) * 118.0
    return round(bandwidth, 2)


@dataclass
class DatasetStore:
    dataset: str
    road_segments: pd.DataFrame
    towers: pd.DataFrame
    weak_zones: pd.DataFrame
    feedback: pd.DataFrame
    connectivity: pd.DataFrame
    summary_json: dict

    def __post_init__(self) -> None:
        self._augment_bandwidth_fields()
        self._graph = self._build_graph()
        self._node_positions = self._build_node_positions()

    def _augment_bandwidth_fields(self) -> None:
        if "estimated_bandwidth_mbps" not in self.towers.columns:
            self.towers["estimated_bandwidth_mbps"] = self.towers.apply(
                lambda row: estimate_tower_bandwidth_mbps(
                    radio_type=row.get("radio_type", "4G"),
                    base_strength=float(row.get("base_strength", 70.0)),
                ),
                axis=1,
            )

        if "estimated_bandwidth_mbps" not in self.connectivity.columns:
            self.connectivity["estimated_bandwidth_mbps"] = self.connectivity.apply(
                lambda row: estimate_segment_bandwidth_mbps(
                    avg_signal=float(row.get("avg_signal", 0.0)),
                    provider_best_signal=float(row.get("provider_best_signal", row.get("avg_signal", 0.0))),
                ),
                axis=1,
            )

        self.towers["estimated_bandwidth_mbps"] = self.towers["estimated_bandwidth_mbps"].round(2)
        self.connectivity["estimated_bandwidth_mbps"] = self.connectivity["estimated_bandwidth_mbps"].round(2)

    def summary(self) -> dict[str, object]:
        safe_counts = self.connectivity["safe_flag"].value_counts().to_dict()
        return {
            "dataset": self.dataset,
            "city": self.summary_json.get("city", "Bengaluru, Karnataka, India"),
            "road_segments": int(len(self.road_segments)),
            "towers": int(len(self.towers)),
            "weak_zones": int(len(self.weak_zones)),
            "feedback_entries": int(len(self.feedback)),
            "connectivity_rows": int(len(self.connectivity)),
            "safe_segments": int(safe_counts.get(1, 0)),
            "unsafe_segments": int(safe_counts.get(0, 0)),
        }

    def planner_overview(self) -> dict[str, object]:
        metrics = self.connectivity
        return {
            "dataset": self.dataset,
            "avg_signal_mean": round(float(metrics["avg_signal"].mean()), 2),
            "min_signal_mean": round(float(metrics["min_signal"].mean()), 2),
            "estimated_bandwidth_mean_mbps": round(float(metrics["estimated_bandwidth_mbps"].mean()), 2),
            "risk_score_mean": round(float(metrics["risk_score"].mean()), 3),
            "handover_risk_mean": round(float(metrics["handover_risk"].mean()), 3),
            "dead_zone_segments": int(metrics["dead_zone_flag"].sum()),
            "safe_segments": int((metrics["safe_flag"] == 1).sum()),
        }

    def route_options(self, limit: int = 4) -> list[dict[str, object]]:
        ranked = self.connectivity.sort_values(
            ["safe_flag", "risk_score", "avg_signal", "provider_redundancy_score"],
            ascending=[False, True, False, False],
        ).head(limit)
        routes: list[dict[str, object]] = []
        for idx, row in enumerate(ranked.itertuples(index=False), start=1):
            label = ["Fastest", "Balanced", "Most Connected", "Emergency Safe"]
            routes.append(
                {
                    "route_id": f"R{idx:02d}",
                    "route_label": label[idx - 1] if idx <= len(label) else f"Option {idx}",
                    "segment_id": row.segment_id,
                    "avg_signal": row.avg_signal,
                    "min_signal": row.min_signal,
                    "risk_score": row.risk_score,
                    "handover_risk": row.handover_risk,
                    "estimated_bandwidth_mbps": row.estimated_bandwidth_mbps,
                    "safe_flag": row.safe_flag,
                    "dead_zone_flag": row.dead_zone_flag,
                }
            )
        return routes

    def segment_detail(self, segment_id: str) -> dict[str, object] | None:
        road_match = self.road_segments[self.road_segments["segment_id"] == segment_id]
        conn_match = self.connectivity[self.connectivity["segment_id"] == segment_id]
        if road_match.empty or conn_match.empty:
            return None
        detail = {}
        detail.update(road_match.iloc[0].to_dict())
        detail.update(conn_match.iloc[0].to_dict())
        return detail

    def map_payload(self, limit: int = 1200) -> dict[str, object]:
        merged = self.road_segments.merge(self.connectivity, on="segment_id", how="inner")
        ranked = merged.sort_values(
            ["dead_zone_flag", "risk_score", "avg_signal"],
            ascending=[False, False, True],
        )
        focus = pd.concat(
            [
                ranked.head(limit // 2),
                merged.sort_values("avg_signal", ascending=False).head(limit // 2),
            ],
            ignore_index=True,
        ).drop_duplicates(subset=["segment_id"]).head(limit)

        segment_items = focus[
            [
                "segment_id",
                "start_lat",
                "start_lon",
                "end_lat",
                "end_lon",
                "avg_signal",
                "estimated_bandwidth_mbps",
                "risk_score",
                "safe_flag",
                "dead_zone_flag",
            ]
        ].to_dict(orient="records")

        return {
            "dataset": self.dataset,
            "bbox": {
                "lat_min": float(self.road_segments[["start_lat", "end_lat"]].min().min()),
                "lat_max": float(self.road_segments[["start_lat", "end_lat"]].max().max()),
                "lon_min": float(self.road_segments[["start_lon", "end_lon"]].min().min()),
                "lon_max": float(self.road_segments[["start_lon", "end_lon"]].max().max()),
            },
            "segments": segment_items,
            "towers": self.towers.to_dict(orient="records"),
            "weak_zones": self.weak_zones.to_dict(orient="records"),
        }

    def route_map_payload(self, path_geometry: list[dict[str, float]], margin: float = 0.01, limit: int = 2500) -> dict[str, object]:
        lats = [point["lat"] for point in path_geometry]
        lons = [point["lon"] for point in path_geometry]
        bbox = {
            "lat_min": min(lats) - margin,
            "lat_max": max(lats) + margin,
            "lon_min": min(lons) - margin,
            "lon_max": max(lons) + margin,
        }

        merged = self.road_segments.merge(self.connectivity, on="segment_id", how="inner")
        in_bbox = merged[
            merged["midpoint_lat"].between(bbox["lat_min"], bbox["lat_max"])
            & merged["midpoint_lon"].between(bbox["lon_min"], bbox["lon_max"])
        ].copy()

        if len(in_bbox) > limit:
            in_bbox = in_bbox.sort_values(
                ["dead_zone_flag", "risk_score", "avg_signal"],
                ascending=[False, False, True],
            ).head(limit)

        towers = self.towers[
            self.towers["lat"].between(bbox["lat_min"], bbox["lat_max"])
            & self.towers["lon"].between(bbox["lon_min"], bbox["lon_max"])
        ].copy()
        weak_zones = self.weak_zones[
            self.weak_zones["center_lat"].between(bbox["lat_min"], bbox["lat_max"])
            & self.weak_zones["center_lon"].between(bbox["lon_min"], bbox["lon_max"])
        ].copy()

        segment_items = in_bbox[
            [
                "segment_id",
                "start_lat",
                "start_lon",
                "end_lat",
                "end_lon",
                "avg_signal",
                "estimated_bandwidth_mbps",
                "risk_score",
                "safe_flag",
                "dead_zone_flag",
            ]
        ].to_dict(orient="records")

        return {
            "dataset": self.dataset,
            "bbox": bbox,
            "segments": segment_items,
            "towers": towers.to_dict(orient="records"),
            "weak_zones": weak_zones.to_dict(orient="records"),
        }

    def _build_graph(self) -> nx.DiGraph:
        graph = nx.DiGraph()
        merged = self.road_segments.merge(self.connectivity, on="segment_id", how="inner")
        for row in merged.itertuples(index=False):
            signal_score = max(0.0, min(1.0, float(row.avg_signal) / 100.0))
            connectivity_penalty = (1.0 - signal_score) * 100.0
            low_signal_penalty = max(0.0, 55.0 - float(row.min_signal))
            dead_zone_penalty = 800.0 if int(row.dead_zone_flag) == 1 else 0.0
            unsafe_penalty = 120.0 if int(row.safe_flag) == 0 else 0.0
            risk_penalty = float(row.risk_score) * 200.0
            handover_penalty = float(row.handover_risk) * 90.0
            base_travel_time = float(row.travel_time_s)

            graph.add_node(row.start_node, lat=float(row.start_lat), lon=float(row.start_lon))
            graph.add_node(row.end_node, lat=float(row.end_lat), lon=float(row.end_lon))
            graph.add_edge(
                row.start_node,
                row.end_node,
                segment_id=row.segment_id,
                travel_time_s=float(row.travel_time_s),
                length_m=float(row.length_m),
                avg_signal=float(row.avg_signal),
                min_signal=float(row.min_signal),
                risk_score=float(row.risk_score),
                handover_risk=float(row.handover_risk),
                provider_best_signal=float(row.provider_best_signal),
                provider_redundancy_score=float(row.provider_redundancy_score),
                dead_zone_flag=int(row.dead_zone_flag),
                safe_flag=int(row.safe_flag),
                estimated_bandwidth_mbps=float(row.estimated_bandwidth_mbps),
                signal_score=signal_score,
                weight_fastest=base_travel_time,
                weight_balanced=base_travel_time + (connectivity_penalty * 4.5) + (risk_penalty * 0.9) + (dead_zone_penalty * 0.8),
                weight_safe=base_travel_time + (connectivity_penalty * 9.0) + (risk_penalty * 1.4) + dead_zone_penalty + unsafe_penalty + (low_signal_penalty * 6.0) + (handover_penalty * 1.4),
                weight_emergency=base_travel_time + (connectivity_penalty * 13.0) + (risk_penalty * 2.0) + (dead_zone_penalty * 1.6) + (unsafe_penalty * 1.6) + (low_signal_penalty * 9.0) + (handover_penalty * 2.0),
            )
        return graph

    def _build_node_positions(self) -> pd.DataFrame:
        start_nodes = self.road_segments[["start_node", "start_lat", "start_lon"]].rename(
            columns={"start_node": "node_id", "start_lat": "lat", "start_lon": "lon"}
        )
        end_nodes = self.road_segments[["end_node", "end_lat", "end_lon"]].rename(
            columns={"end_node": "node_id", "end_lat": "lat", "end_lon": "lon"}
        )
        return pd.concat([start_nodes, end_nodes], ignore_index=True).drop_duplicates(subset=["node_id"]).reset_index(drop=True)

    def nearest_node(self, lat: float, lon: float) -> int:
        nodes = self._node_positions.copy()
        nodes["distance_sq"] = (nodes["lat"] - lat) ** 2 + (nodes["lon"] - lon) ** 2
        return int(nodes.sort_values("distance_sq").iloc[0]["node_id"])

    def assess_point_risk(self, lat: float, lon: float) -> dict[str, object]:
        merged = self.road_segments.merge(self.connectivity, on="segment_id", how="inner").copy()
        merged["distance_sq"] = (merged["midpoint_lat"] - lat) ** 2 + (merged["midpoint_lon"] - lon) ** 2
        nearest = merged.sort_values("distance_sq").iloc[0]

        weak_zone_hit = None
        if not self.weak_zones.empty:
            zones = self.weak_zones.copy()
            zones["distance_sq"] = (zones["center_lat"] - lat) ** 2 + (zones["center_lon"] - lon) ** 2
            zone = zones.sort_values("distance_sq").iloc[0]
            distance_m = math.sqrt(float(zone["distance_sq"])) * 111000.0
            if distance_m <= float(zone["radius_m"]):
                weak_zone_hit = {
                    "zone_id": zone["zone_id"],
                    "zone_type": zone["zone_type"],
                    "severity": zone["severity"],
                }

        severity = "clear"
        if int(nearest["dead_zone_flag"]) == 1 or float(nearest["min_signal"]) < 28.0:
            severity = "critical"
        elif float(nearest["risk_score"]) >= 0.32 or float(nearest["min_signal"]) < 42.0:
            severity = "warning"
        elif int(nearest["safe_flag"]) == 0 or weak_zone_hit is not None:
            severity = "watch"

        return {
            "segment_id": nearest["segment_id"],
            "avg_signal": round(float(nearest["avg_signal"]), 2),
            "min_signal": round(float(nearest["min_signal"]), 2),
            "estimated_bandwidth_mbps": round(float(nearest["estimated_bandwidth_mbps"]), 2),
            "risk_score": round(float(nearest["risk_score"]), 3),
            "safe_flag": int(nearest["safe_flag"]),
            "dead_zone_flag": int(nearest["dead_zone_flag"]),
            "severity": severity,
            "weak_zone": weak_zone_hit,
        }

    def _route_metrics(self, path: list[int]) -> dict[str, object]:
        segment_rows = []
        for start, end in zip(path[:-1], path[1:]):
            edge = self._graph[start][end]
            segment_rows.append(edge)

        segments_df = pd.DataFrame(segment_rows)
        avg_signal = round(float(segments_df["avg_signal"].mean()), 2)
        min_signal = round(float(segments_df["min_signal"].min()), 2)
        estimated_bandwidth_mbps = round(float(segments_df["estimated_bandwidth_mbps"].mean()), 2)
        risk_score = round(float(segments_df["risk_score"].mean()), 3)
        dead_zone_count = int(segments_df["dead_zone_flag"].sum())
        travel_time_s = round(float(segments_df["travel_time_s"].sum()), 2)

        geometry = []
        for node_id in path:
            node = self._graph.nodes[node_id]
            geometry.append({"lat": node["lat"], "lon": node["lon"]})

        return {
            "path_nodes": path,
            "path_geometry": geometry,
            "segment_ids": segments_df["segment_id"].tolist(),
            "segments": segments_df[
                [
                    "segment_id",
                    "travel_time_s",
                    "length_m",
                    "avg_signal",
                    "min_signal",
                    "estimated_bandwidth_mbps",
                    "risk_score",
                    "handover_risk",
                    "dead_zone_flag",
                    "safe_flag",
                ]
            ].to_dict(orient="records"),
            "travel_time_s": travel_time_s,
            "travel_time_min": round(travel_time_s / 60.0, 2),
            "avg_signal": avg_signal,
            "min_signal": min_signal,
            "estimated_bandwidth_mbps": estimated_bandwidth_mbps,
            "risk_score": risk_score,
            "dead_zone_count": dead_zone_count,
            "safe_flag": 1 if min_signal >= 50.0 and dead_zone_count == 0 and risk_score < 0.4 else 0,
        }

    def plan_routes(self, source_lat: float, source_lon: float, dest_lat: float, dest_lon: float) -> dict[str, object]:
        source_node = self.nearest_node(source_lat, source_lon)
        dest_node = self.nearest_node(dest_lat, dest_lon)

        planners = [
            ("Fastest", "weight_fastest"),
            ("Balanced", "weight_balanced"),
            ("Safe", "weight_safe"),
            ("Emergency", "weight_emergency"),
        ]

        routes = []
        for label, weight_key in planners:
            path = nx.shortest_path(self._graph, source_node, dest_node, weight=weight_key)
            metrics = self._route_metrics(path)
            metrics["route_label"] = label
            metrics["weight_key"] = weight_key
            routes.append(metrics)

        overlaps = self._route_overlap_stats(routes)
        for route in routes:
            route["overlap"] = overlaps.get(route["route_label"], {})

        return {
            "dataset": self.dataset,
            "source_node": source_node,
            "destination_node": dest_node,
            "routes": routes,
            "map_context": self.route_map_payload(routes[0]["path_geometry"]) if routes else None,
            "destination_assessment": self.assess_point_risk(dest_lat, dest_lon),
            "route_overlap": overlaps,
        }

    def predict_signal_risk(
        self,
        route_segments: list[dict[str, object]],
        speed_kmph: float,
        progress_ratio: float = 0.0,
        destination_assessment: dict[str, object] | None = None,
    ) -> dict[str, object]:
        speed_mps = max(1.0, speed_kmph * 1000.0 / 3600.0)
        progress_ratio = min(max(progress_ratio, 0.0), 0.98)
        current_index = int(progress_ratio * max(1, len(route_segments) - 1))

        cumulative_distance = 0.0
        next_event = None

        for offset, segment in enumerate(route_segments[current_index:], start=0):
            risk_score = float(segment["risk_score"])
            min_signal = float(segment["min_signal"])
            dead_zone_flag = int(segment["dead_zone_flag"])
            safe_flag = int(segment["safe_flag"])
            length_m = float(segment["length_m"])

            severity = None
            if dead_zone_flag == 1 or min_signal < 28.0:
                severity = "critical"
            elif risk_score >= 0.32 or min_signal < 42.0:
                severity = "warning"
            elif safe_flag == 0:
                severity = "watch"

            if severity:
                cumulative_distance += length_m * 0.5
                time_to_risk_s = cumulative_distance / speed_mps
                next_event = {
                    "segment_id": segment["segment_id"],
                    "severity": severity,
                    "distance_m": round(cumulative_distance, 1),
                    "time_to_risk_s": round(time_to_risk_s, 1),
                    "time_to_risk_min": round(time_to_risk_s / 60.0, 2),
                    "predicted_min_signal": min_signal,
                    "predicted_bandwidth_mbps": round(float(segment["estimated_bandwidth_mbps"]), 2),
                    "predicted_risk_score": round(risk_score, 3),
                    "message": self._prediction_message(severity, time_to_risk_s),
                }
                break

            cumulative_distance += length_m

        if next_event is None and destination_assessment and destination_assessment["severity"] != "clear":
            destination_message = {
                "critical": "Destination lies in a high-risk signal area.",
                "warning": "Signal degradation expected near the destination.",
                "watch": "Coverage may weaken close to the destination.",
            }[destination_assessment["severity"]]
            next_event = {
                "segment_id": destination_assessment["segment_id"],
                "severity": destination_assessment["severity"],
                "distance_m": 0.0,
                "time_to_risk_s": 0.0,
                "time_to_risk_min": 0.0,
                "predicted_min_signal": destination_assessment["min_signal"],
                "predicted_bandwidth_mbps": destination_assessment["estimated_bandwidth_mbps"],
                "predicted_risk_score": destination_assessment["risk_score"],
                "message": destination_message,
            }

        if next_event is None:
            next_event = {
                "segment_id": None,
                "severity": "clear",
                "distance_m": None,
                "time_to_risk_s": None,
                "time_to_risk_min": None,
                "predicted_min_signal": None,
                "predicted_bandwidth_mbps": None,
                "predicted_risk_score": None,
                "message": "No signal loss expected on the visible route ahead.",
            }

        return {
            "speed_kmph": speed_kmph,
            "progress_ratio": progress_ratio,
            "current_segment_index": current_index,
            "next_risk": next_event,
        }

    @staticmethod
    def _prediction_message(severity: str, time_to_risk_s: float) -> str:
        rounded = max(1, round(time_to_risk_s / 60.0))
        if severity == "critical":
            return f"Signal loss expected in about {rounded} min."
        if severity == "warning":
            return f"Signal degradation expected in about {rounded} min."
        return f"Weak coverage likely in about {rounded} min."

    @staticmethod
    def _route_overlap_stats(routes: list[dict[str, object]]) -> dict[str, dict[str, float]]:
        overlap_stats: dict[str, dict[str, float]] = {}
        for route in routes:
            current_ids = set(route["segment_ids"])
            overlap_stats[route["route_label"]] = {}
            for other in routes:
                if other["route_label"] == route["route_label"]:
                    continue
                other_ids = set(other["segment_ids"])
                union = len(current_ids | other_ids)
                overlap = len(current_ids & other_ids)
                overlap_stats[route["route_label"]][other["route_label"]] = round((overlap / union) if union else 1.0, 3)
        return overlap_stats


def _load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=2)
def get_store(dataset: str) -> DatasetStore:
    if dataset == "mvp":
        raw_dir = PROJECT_ROOT / "data" / "mvp" / "raw"
        processed_dir = PROJECT_ROOT / "data" / "mvp" / "processed"
        road_file = raw_dir / "road_segments_mvp.csv"
        towers_file = raw_dir / "towers_mvp.csv"
        weak_zones_file = raw_dir / "weak_zones_mvp.csv"
        feedback_file = raw_dir / "feedback_mvp.csv"
        connectivity_file = processed_dir / "segment_connectivity_mvp.csv"
        summary_file = processed_dir / "adaptive_signal_map_mvp.json"
    elif dataset == "full":
        raw_dir = PROJECT_ROOT / "data" / "raw"
        processed_dir = PROJECT_ROOT / "data" / "processed"
        road_file = raw_dir / "road_segments.csv"
        towers_file = raw_dir / "towers.csv"
        weak_zones_file = raw_dir / "weak_zones.csv"
        feedback_file = raw_dir / "feedback.csv"
        connectivity_file = processed_dir / "segment_connectivity.csv"
        summary_file = processed_dir / "adaptive_signal_map.json"
    else:
        raise ValueError(f"Unsupported dataset: {dataset}")

    return DatasetStore(
        dataset=dataset,
        road_segments=_load_csv(road_file),
        towers=_load_csv(towers_file),
        weak_zones=_load_csv(weak_zones_file),
        feedback=_load_csv(feedback_file),
        connectivity=_load_csv(connectivity_file),
        summary_json=_load_json(summary_file),
    )
