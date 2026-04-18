from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import math
import networkx as nx
import pandas as pd

from backend.core.alerts import banners_from_fallback_status, build_alert
from backend.core.config import (
    APPLICATION_PROFILES,
    DEGRADED_SPEED_LIMIT,
    MAX_OUTAGE_SECONDS,
    MIN_SIGNAL_THRESHOLD,
    PNR_LOOKAHEAD_SEGMENTS,
    SIGNAL_RECOVERY_POLL_SECONDS,
)
from backend.core.point_of_no_return import degradation_state_from_dbm, signal_to_dbm
from backend.core.safety_constraints import enrich_route_for_safety


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROVIDER_KEY_MAP = {
    "Airtel": "airtel",
    "BSNL": "bsnl",
    "Jio": "jio",
    "Vi": "vi",
}


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
    environment_profiles: pd.DataFrame
    connectivity: pd.DataFrame
    summary_json: dict

    def __post_init__(self) -> None:
        self._apply_weak_zone_overlays()
        self._augment_bandwidth_fields()
        self._provider_towers = {
            str(provider): group.reset_index(drop=True)
            for provider, group in self.towers.groupby("provider")
        }
        self._graph_segments = self._prepare_graph_segments()
        self._graph = self._build_graph()
        self._node_positions = self._build_node_positions()
        self._fallback_status = self._default_fallback_status()

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _default_fallback_status(self) -> dict[str, Any]:
        return {
            "vehicle_state": "FULL_AUTONOMY",
            "active_degradation_level": "FULL_AUTONOMY",
            "dead_zone_timer_s": 0.0,
            "last_known_gps": None,
            "last_event": None,
            "alerts": [],
            "cloud_features_enabled": True,
            "speed_limit_kmph": None,
            "cached_route": None,
            "route_id": None,
            "residual_signal_check_interval_s": SIGNAL_RECOVERY_POLL_SECONDS,
            "entered_dead_zone_progress": None,
            "entered_dead_zone_at": None,
            "pullover_target": None,
        }

    def _environment_multiplier(self, environment_type: str) -> float:
        if not environment_type:
            return 1.0
        match = self.environment_profiles[
            self.environment_profiles["environment_type"].astype(str).str.lower() == environment_type.strip().lower()
        ]
        if not match.empty:
            return float(match.iloc[0]["signal_multiplier"])
        if environment_type.strip().lower() == "rural_sparse":
            return 0.78
        return 1.0

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

    def _apply_weak_zone_overlays(self) -> None:
        if self.weak_zones.empty:
            return

        overlay = self.road_segments[["segment_id", "midpoint_lat", "midpoint_lon"]].merge(
            self.connectivity,
            on="segment_id",
            how="inner",
        )

        zone_risk_masks: list[pd.Series] = []
        dead_zone_masks: list[pd.Series] = []

        for zone in self.weak_zones.itertuples(index=False):
            distance_m = (
                ((overlay["midpoint_lat"] - float(zone.center_lat)) ** 2 + (overlay["midpoint_lon"] - float(zone.center_lon)) ** 2) ** 0.5
            ) * 111000.0
            inside_zone = distance_m <= float(zone.radius_m)
            if not inside_zone.any():
                continue

            severity = str(zone.severity).lower()
            attenuation = float(zone.attenuation_factor)
            if severity == "high" or attenuation <= 0.45:
                overlay.loc[inside_zone, "dead_zone_flag"] = 1
                overlay.loc[inside_zone, "safe_flag"] = 0
                overlay.loc[inside_zone, "risk_score"] = overlay.loc[inside_zone, "risk_score"].clip(lower=0.78)
                overlay.loc[inside_zone, "min_signal"] = overlay.loc[inside_zone, "min_signal"].clip(upper=24.0)
                overlay.loc[inside_zone, "avg_signal"] = overlay.loc[inside_zone, "avg_signal"].clip(upper=36.0)
                dead_zone_masks.append(inside_zone)
            elif severity == "medium" or attenuation <= 0.7:
                overlay.loc[inside_zone, "safe_flag"] = 0
                overlay.loc[inside_zone, "risk_score"] = overlay.loc[inside_zone, "risk_score"].clip(lower=0.56)
                overlay.loc[inside_zone, "min_signal"] = overlay.loc[inside_zone, "min_signal"].clip(upper=38.0)
                overlay.loc[inside_zone, "avg_signal"] = overlay.loc[inside_zone, "avg_signal"].clip(upper=48.0)
                zone_risk_masks.append(inside_zone)
            else:
                overlay.loc[inside_zone, "risk_score"] = overlay.loc[inside_zone, "risk_score"].clip(lower=0.38)
                overlay.loc[inside_zone, "min_signal"] = overlay.loc[inside_zone, "min_signal"].clip(upper=48.0)

        overlay["estimated_bandwidth_mbps"] = overlay.apply(
            lambda row: estimate_segment_bandwidth_mbps(
                avg_signal=float(row["avg_signal"]),
                provider_best_signal=float(row["provider_best_signal"]),
            ),
            axis=1,
        )

        updated = overlay[
            [
                "segment_id",
                "avg_signal",
                "min_signal",
                "provider_best_signal",
                "provider_redundancy_score",
                "dead_zone_flag",
                "risk_score",
                "handover_risk",
                "safe_flag",
                "estimated_bandwidth_mbps",
            ]
        ].copy()

        self.connectivity = updated

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
        for row in self._graph_segments.itertuples(index=False):
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
                midpoint_lat=float(row.midpoint_lat),
                midpoint_lon=float(row.midpoint_lon),
                provider_support_airtel=float(getattr(row, "provider_support_airtel", 1.0)),
                provider_support_bsnl=float(getattr(row, "provider_support_bsnl", 1.0)),
                provider_support_jio=float(getattr(row, "provider_support_jio", 1.0)),
                provider_support_vi=float(getattr(row, "provider_support_vi", 1.0)),
                provider_bandwidth_airtel=float(getattr(row, "provider_bandwidth_airtel", row.estimated_bandwidth_mbps)),
                provider_bandwidth_bsnl=float(getattr(row, "provider_bandwidth_bsnl", row.estimated_bandwidth_mbps)),
                provider_bandwidth_jio=float(getattr(row, "provider_bandwidth_jio", row.estimated_bandwidth_mbps)),
                provider_bandwidth_vi=float(getattr(row, "provider_bandwidth_vi", row.estimated_bandwidth_mbps)),
                signal_score=signal_score,
                weight_fastest=base_travel_time,
                weight_balanced=base_travel_time + (connectivity_penalty * 4.5) + (risk_penalty * 0.9) + (dead_zone_penalty * 0.8),
                weight_safe=base_travel_time + (connectivity_penalty * 16.0) + (risk_penalty * 3.2) + (dead_zone_penalty * 8.0) + (unsafe_penalty * 4.0) + (low_signal_penalty * 14.0) + (handover_penalty * 2.6),
                weight_emergency=base_travel_time + (connectivity_penalty * 21.0) + (risk_penalty * 4.4) + (dead_zone_penalty * 12.0) + (unsafe_penalty * 6.0) + (low_signal_penalty * 18.0) + (handover_penalty * 3.2),
            )
        return graph

    def _prepare_graph_segments(self) -> pd.DataFrame:
        merged = self.road_segments.merge(self.connectivity, on="segment_id", how="inner").copy()

        for provider, key in PROVIDER_KEY_MAP.items():
            towers = self._provider_towers.get(provider)
            support_col = f"provider_support_{key}"
            bandwidth_col = f"provider_bandwidth_{key}"
            if towers is None or towers.empty:
                merged[support_col] = 0.08
                merged[bandwidth_col] = 0.0
                continue

            best_support = pd.Series(0.0, index=merged.index, dtype="float64")
            best_bandwidth = pd.Series(0.0, index=merged.index, dtype="float64")

            for tower in towers.itertuples(index=False):
                distance_m = (
                    ((merged["midpoint_lat"] - float(tower.lat)) ** 2 + (merged["midpoint_lon"] - float(tower.lon)) ** 2) ** 0.5
                ) * 111000.0
                support = (1.0 - (distance_m / float(tower.coverage_radius_m))).clip(lower=0.0) * float(tower.base_strength) / 100.0
                is_better = support > best_support
                best_support = best_support.where(~is_better, support)
                best_bandwidth = best_bandwidth.where(~is_better, float(tower.estimated_bandwidth_mbps))

            merged[support_col] = best_support.round(3)
            merged[bandwidth_col] = best_bandwidth.round(2)

        return merged

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
                    "midpoint_lat",
                    "midpoint_lon",
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

    @staticmethod
    def _sample_path_points(path_geometry: list[dict[str, float]], sample_count: int = 14) -> list[dict[str, float]]:
        if len(path_geometry) <= sample_count:
            return path_geometry
        step = max(1, len(path_geometry) // sample_count)
        return path_geometry[::step][:sample_count]

    @staticmethod
    def _tower_signal_score(
        point_lat: float,
        point_lon: float,
        tower_lat: float,
        tower_lon: float,
        base_strength: float,
        coverage_radius_m: float,
    ) -> float:
        distance_m = math.sqrt((point_lat - tower_lat) ** 2 + (point_lon - tower_lon) ** 2) * 111000.0
        if coverage_radius_m <= 0:
            return 0.0
        return max(0.0, float(base_strength) * max(0.0, 1.0 - distance_m / float(coverage_radius_m)))

    def _provider_route_support(self, path_geometry: list[dict[str, float]], provider_baseline: str) -> dict[str, float]:
        if not path_geometry or provider_baseline in {"", "All providers", None}:
            return {"operator_support_score": 1.0, "operator_support_bandwidth_mbps": round(float(self.towers["estimated_bandwidth_mbps"].mean()), 2)}

        sampled_points = self._sample_path_points(path_geometry)
        latitudes = [point["lat"] for point in sampled_points]
        longitudes = [point["lon"] for point in sampled_points]
        margin = 0.03

        towers = self.towers[
            (self.towers["provider"] == provider_baseline)
            & self.towers["lat"].between(min(latitudes) - margin, max(latitudes) + margin)
            & self.towers["lon"].between(min(longitudes) - margin, max(longitudes) + margin)
        ].copy()

        if towers.empty:
            return {"operator_support_score": 0.12, "operator_support_bandwidth_mbps": 0.0}

        support_scores: list[float] = []
        bandwidth_scores: list[float] = []
        for point in sampled_points:
            towers["provider_fit"] = towers.apply(
                lambda row: self._tower_signal_score(
                    point_lat=point["lat"],
                    point_lon=point["lon"],
                    tower_lat=float(row["lat"]),
                    tower_lon=float(row["lon"]),
                    base_strength=float(row["base_strength"]),
                    coverage_radius_m=float(row["coverage_radius_m"]),
                ),
                axis=1,
            )
            best = towers.sort_values("provider_fit", ascending=False).iloc[0]
            support_scores.append(float(best["provider_fit"]) / 100.0)
            bandwidth_scores.append(float(best["estimated_bandwidth_mbps"]))

        return {
            "operator_support_score": round(sum(support_scores) / max(len(support_scores), 1), 3),
            "operator_support_bandwidth_mbps": round(sum(bandwidth_scores) / max(len(bandwidth_scores), 1), 2),
        }

    def _route_support_by_provider(self, path_geometry: list[dict[str, float]]) -> dict[str, dict[str, float]]:
        provider_support: dict[str, dict[str, float]] = {}
        for provider in PROVIDER_KEY_MAP:
            support = self._provider_route_support(path_geometry, provider)
            provider_support[provider] = {
                "score": float(support["operator_support_score"]),
                "bandwidth_mbps": float(support["operator_support_bandwidth_mbps"]),
            }
        return provider_support

    @staticmethod
    def _apply_support_multiplier(route_metrics: dict[str, Any], multiplier: float) -> None:
        route_metrics["operator_support_score"] = round(float(route_metrics.get("operator_support_score", 1.0)) * multiplier, 3)
        route_metrics["operator_support_bandwidth_mbps"] = round(float(route_metrics.get("operator_support_bandwidth_mbps", 0.0)) * multiplier, 2)
        provider_support = route_metrics.get("operator_support_by_provider")
        if isinstance(provider_support, dict):
            route_metrics["operator_support_by_provider"] = {
                provider: {
                    "score": round(float(values.get("score", 1.0)) * multiplier, 3),
                    "bandwidth_mbps": round(float(values.get("bandwidth_mbps", 0.0)) * multiplier, 2),
                }
                for provider, values in provider_support.items()
            }

    def _apply_environment_context(self, route_metrics: dict[str, Any], environment_type: str) -> dict[str, Any]:
        environment = (environment_type or "normal").strip()
        multiplier = self._environment_multiplier(environment)
        normalized_name = environment.lower().replace(" ", "_")

        signal_adjust = route_metrics["avg_signal"] * multiplier
        min_signal_adjust = route_metrics["min_signal"] * multiplier
        route_metrics["avg_signal"] = round(max(0.0, min(100.0, signal_adjust)), 2)
        route_metrics["min_signal"] = round(max(0.0, min(100.0, min_signal_adjust)), 2)
        route_metrics["estimated_bandwidth_mbps"] = round(route_metrics["estimated_bandwidth_mbps"] * max(0.32, multiplier), 2)

        if normalized_name in {"rain", "heavy_rain"}:
            route_metrics["risk_score"] = round(min(1.0, route_metrics["risk_score"] + (0.05 if normalized_name == "rain" else 0.11)), 3)
            self._apply_support_multiplier(route_metrics, 0.93 if normalized_name == "rain" else 0.86)
        elif normalized_name == "urban_dense":
            route_metrics["risk_score"] = round(max(0.0, route_metrics["risk_score"] - 0.03), 3)
            route_metrics["estimated_bandwidth_mbps"] = round(route_metrics["estimated_bandwidth_mbps"] * 1.08, 2)
            self._apply_support_multiplier(route_metrics, 1.05)
        elif normalized_name == "rural_sparse":
            route_metrics["risk_score"] = round(min(1.0, route_metrics["risk_score"] + 0.12), 3)
            route_metrics["estimated_bandwidth_mbps"] = round(route_metrics["estimated_bandwidth_mbps"] * 0.76, 2)
            self._apply_support_multiplier(route_metrics, 0.72)
        elif normalized_name in {"tunnel", "underpass"}:
            route_metrics["risk_score"] = round(min(1.0, route_metrics["risk_score"] + 0.14), 3)
            self._apply_support_multiplier(route_metrics, 0.78)

        adjusted_segments: list[dict[str, Any]] = []
        for segment in route_metrics["segments"]:
            avg_signal = max(0.0, min(100.0, float(segment["avg_signal"]) * multiplier))
            min_signal = max(0.0, min(100.0, float(segment["min_signal"]) * multiplier))
            bandwidth = float(segment["estimated_bandwidth_mbps"]) * max(0.32, multiplier)
            risk_score = float(segment["risk_score"])

            if normalized_name in {"rain", "heavy_rain"}:
                risk_score = min(1.0, risk_score + (0.05 if normalized_name == "rain" else 0.11))
            elif normalized_name == "urban_dense":
                risk_score = max(0.0, risk_score - 0.03)
                bandwidth *= 1.08
            elif normalized_name == "rural_sparse":
                risk_score = min(1.0, risk_score + 0.12)
                bandwidth *= 0.76
            elif normalized_name in {"tunnel", "underpass"}:
                risk_score = min(1.0, risk_score + 0.14)

            adjusted_segments.append(
                {
                    **segment,
                    "avg_signal": round(avg_signal, 2),
                    "min_signal": round(min_signal, 2),
                    "estimated_bandwidth_mbps": round(bandwidth, 2),
                    "risk_score": round(risk_score, 3),
                }
            )

        route_metrics["segments"] = adjusted_segments
        route_metrics["environment_type"] = environment
        route_metrics["environment_multiplier"] = round(multiplier, 2)
        route_metrics["safe_flag"] = 1 if route_metrics["min_signal"] >= 50.0 and route_metrics["dead_zone_count"] == 0 and route_metrics["risk_score"] < 0.4 else 0
        return route_metrics

    def _provider_edge_support(self, edge_data: dict[str, Any], provider_baseline: str) -> dict[str, float]:
        if provider_baseline in {"", "All providers", None}:
            return {"operator_support_score": 1.0, "operator_support_bandwidth_mbps": float(edge_data.get("estimated_bandwidth_mbps", 0.0))}
        key = str(provider_baseline).strip().lower()
        return {
            "operator_support_score": float(edge_data.get(f"provider_support_{key}", 0.08)),
            "operator_support_bandwidth_mbps": float(edge_data.get(f"provider_bandwidth_{key}", 0.0)),
        }

    def _provider_weight_function(self, weight_key: str, provider_baseline: str):
        if provider_baseline in {"", "All providers", None}:
            return weight_key

        provider_penalty_multipliers = {
            "weight_fastest": 120.0,
            "weight_balanced": 220.0,
            "weight_safe": 360.0,
            "weight_emergency": 480.0,
        }
        bandwidth_bonus_multipliers = {
            "weight_fastest": 8.0,
            "weight_balanced": 12.0,
            "weight_safe": 18.0,
            "weight_emergency": 22.0,
        }
        penalty_multiplier = provider_penalty_multipliers.get(weight_key, 220.0)
        bandwidth_multiplier = bandwidth_bonus_multipliers.get(weight_key, 12.0)

        def weight(_u: int, _v: int, edge_data: dict[str, Any]) -> float:
            base_weight = float(edge_data.get(weight_key, edge_data.get("travel_time_s", 0.0)))
            provider_support = self._provider_edge_support(edge_data, provider_baseline)
            support_penalty = (1.0 - float(provider_support["operator_support_score"])) ** 2
            bandwidth_bonus = min(float(provider_support["operator_support_bandwidth_mbps"]) / 100.0, 1.0)
            return base_weight + (support_penalty * penalty_multiplier) - (bandwidth_bonus * bandwidth_multiplier)

        return weight

    @staticmethod
    def _normalize_series(values: list[float]) -> tuple[float, float]:
        return (min(values), max(values)) if values else (0.0, 1.0)

    @staticmethod
    def _normalize_value(value: float, low: float, high: float) -> float:
        if high <= low:
            return 0.0
        return max(0.0, min(1.0, (value - low) / (high - low)))

    def _application_profile(self, application_type: str) -> dict[str, float]:
        return APPLICATION_PROFILES.get(application_type, APPLICATION_PROFILES["Navigation"])

    @staticmethod
    def _route_safety_tuple(route: dict[str, Any]) -> tuple[float, ...]:
        degradation_summary = route.get("degradation_summary", {})
        return (
            float(route.get("dead_zone_count", 0)),
            1.0 if route.get("point_of_no_return") else 0.0,
            1.0 if route.get("threshold_breach") else 0.0,
            float(degradation_summary.get("PULL_OVER", 0)),
            float(degradation_summary.get("SUPERVISED_MODE", 0)),
            float(route.get("risk_score", 0.0)),
            -float(route.get("min_signal", 0.0)),
            float(route.get("travel_time_min", 0.0)),
        )

    @staticmethod
    def _route_emergency_tuple(route: dict[str, Any]) -> tuple[float, ...]:
        degradation_summary = route.get("degradation_summary", {})
        return (
            float(route.get("dead_zone_count", 0)),
            1.0 if route.get("point_of_no_return") else 0.0,
            float(degradation_summary.get("PULL_OVER", 0)),
            float(degradation_summary.get("SUPERVISED_MODE", 0)),
            1.0 if route.get("threshold_breach") else 0.0,
            float(route.get("risk_score", 0.0)),
            -float(route.get("min_signal", 0.0)),
            float(route.get("travel_time_min", 0.0)),
        )

    @staticmethod
    def _route_balanced_tuple(route: dict[str, Any]) -> tuple[float, ...]:
        return (
            float(route.get("dead_zone_count", 0)),
            float(route.get("risk_score", 0.0)),
            -float(route.get("min_signal", 0.0)),
            float(route.get("travel_time_min", 0.0)),
        )

    def _relabel_routes_by_outcome(self, routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not routes:
            return []

        candidates = list(routes)
        for route in candidates:
            route["route_origin_label"] = route.get("route_label")

        assigned: dict[str, dict[str, Any]] = {}
        remaining = list(candidates)

        def take_best(label: str, key_func) -> None:
            nonlocal remaining
            if not remaining:
                return
            best = min(remaining, key=key_func)
            assigned[label] = best
            remaining = [route for route in remaining if route is not best]

        take_best("Safe", self._route_safety_tuple)
        take_best("Emergency", self._route_emergency_tuple)
        take_best("Fastest", lambda route: float(route.get("travel_time_min", 0.0)))
        take_best("Balanced", self._route_balanced_tuple)

        ordered_labels = ["Fastest", "Balanced", "Safe", "Emergency"]
        relabeled: list[dict[str, Any]] = []
        for label in ordered_labels:
            route = assigned.get(label)
            if route is None:
                continue
            route["route_label"] = label
            route["safety_rank"] = ordered_labels.index(label) + 1
            relabeled.append(route)

        return relabeled

    @staticmethod
    def _application_route_bias(application_type: str, route_label: str) -> float:
        route_bias = {
            "Navigation": {"Balanced": -0.04, "Safe": -0.01, "Fastest": 0.03, "Emergency": 0.08},
            "Telematics": {"Balanced": -0.03, "Safe": -0.02, "Fastest": 0.08, "Emergency": 0.03},
            "Ride-hail": {"Fastest": -0.05, "Balanced": -0.01, "Safe": 0.04, "Emergency": 0.09},
            "OTA Update": {"Safe": -0.05, "Emergency": -0.02, "Balanced": 0.02, "Fastest": 0.12},
        }
        return float(route_bias.get(application_type, {}).get(route_label, 0.0))

    def _rank_routes_for_context(
        self,
        routes: list[dict[str, Any]],
        alpha: float,
        provider_baseline: str,
        application_type: str,
    ) -> list[dict[str, Any]]:
        if not routes:
            return []

        profile = self._application_profile(application_type)
        travel_low, travel_high = self._normalize_series([float(route["travel_time_min"]) for route in routes])
        risk_low, risk_high = self._normalize_series([float(route["risk_score"]) for route in routes])
        signal_low, signal_high = self._normalize_series([float(route["min_signal"]) for route in routes])
        bandwidth_low, bandwidth_high = self._normalize_series([float(route["estimated_bandwidth_mbps"]) for route in routes])

        ranked: list[dict[str, Any]] = []
        for route in routes:
            travel_penalty = self._normalize_value(float(route["travel_time_min"]), travel_low, travel_high)
            risk_penalty = self._normalize_value(float(route["risk_score"]), risk_low, risk_high)
            signal_penalty = 1.0 - self._normalize_value(float(route["min_signal"]), signal_low, signal_high)
            bandwidth_penalty = 1.0 - self._normalize_value(float(route["estimated_bandwidth_mbps"]), bandwidth_low, bandwidth_high)
            dead_zone_penalty = min(1.0, float(route["dead_zone_count"]) / 3.0)
            operator_penalty = 1.0 - float(route.get("operator_support_score", 1.0))
            threshold_penalty = 0.4 if route.get("threshold_breach") else 0.0
            application_bias = self._application_route_bias(application_type, str(route.get("route_label", "")))

            connectivity_penalty = (
                risk_penalty * profile["risk_weight"]
                + signal_penalty * profile["signal_weight"]
                + bandwidth_penalty * profile["bandwidth_weight"]
                + dead_zone_penalty * 0.22
                + operator_penalty * 0.36
                + threshold_penalty
                + application_bias
            )
            travel_component = travel_penalty * (0.55 + profile["travel_weight"])
            route["context_score"] = round(((1.0 - alpha) * travel_component) + (alpha * connectivity_penalty), 4)
            route["context_provider"] = provider_baseline
            route["context_application"] = application_type
            ranked.append(route)

        return sorted(ranked, key=lambda route: route["context_score"])

    def _nearest_safe_stop(self, lat: float, lon: float) -> dict[str, Any] | None:
        merged = self.road_segments.merge(self.connectivity, on="segment_id", how="inner").copy()
        candidates = merged[
            (merged["safe_flag"] == 1)
            & (merged["dead_zone_flag"] == 0)
            & (~merged["road_type"].astype(str).str.contains("motorway", case=False, na=False))
        ].copy()
        if candidates.empty:
            return None
        candidates["distance_sq"] = (candidates["midpoint_lat"] - lat) ** 2 + (candidates["midpoint_lon"] - lon) ** 2
        best = candidates.sort_values(["distance_sq", "risk_score"]).iloc[0]
        return {
            "segment_id": best["segment_id"],
            "lat": float(best["midpoint_lat"]),
            "lon": float(best["midpoint_lon"]),
            "road_type": best["road_type"],
        }

    def _fail_safe_preparation(self, route: dict[str, Any], gps: dict[str, float]) -> dict[str, Any]:
        cached_route = {
            "route_label": route["route_label"],
            "path_geometry": route["path_geometry"],
            "segments": route["segments"],
            "cached_at": self._utc_now_iso(),
        }
        self._fallback_status.update(
            {
                "vehicle_state": "REDUCED_SPEED",
                "active_degradation_level": "REDUCED_SPEED",
                "cached_route": cached_route,
                "speed_limit_kmph": DEGRADED_SPEED_LIMIT,
                "cloud_features_enabled": False,
                "last_known_gps": gps,
                "last_event": build_alert(
                    "PNR_APPROACHING",
                    "warning",
                    "Approaching point of no return. Preparing vehicle for degraded connectivity.",
                    gps=gps,
                    timestamp=self._utc_now_iso(),
                ),
            }
        )
        return self._fallback_status

    def _local_autonomy_mode(self, route: dict[str, Any], gps: dict[str, float], progress_ratio: float, outage_seconds: float) -> dict[str, Any]:
        self._fallback_status.update(
            {
                "vehicle_state": "SUPERVISED_MODE",
                "active_degradation_level": "PULL_OVER",
                "last_known_gps": gps,
                "dead_zone_timer_s": round(outage_seconds, 1),
                "route_id": route["route_label"],
            }
        )
        if self._fallback_status.get("entered_dead_zone_progress") is None:
            self._fallback_status["entered_dead_zone_progress"] = progress_ratio
            self._fallback_status["entered_dead_zone_at"] = self._utc_now_iso()
        return self._fallback_status

    def _safe_pullover(self, gps: dict[str, float], route_id: str, reason_code: str = "DEAD_ZONE_TIMEOUT") -> dict[str, Any]:
        stop = self._nearest_safe_stop(gps["lat"], gps["lon"])
        self._fallback_status.update(
            {
                "vehicle_state": "PULL_OVER",
                "active_degradation_level": "PULL_OVER",
                "pullover_target": stop,
                "last_known_gps": gps,
                "last_event": build_alert(
                    "VEHICLE_HALTED",
                    "critical",
                    "Vehicle halted after prolonged outage. Navigating to safest available pull-over point.",
                    gps=gps,
                    timestamp=self._utc_now_iso(),
                    route_id=route_id,
                    reason_code=reason_code,
                    stopping_point=stop,
                ),
            }
        )
        return self._fallback_status

    def _resume_normal_mode(self, gps: dict[str, float]) -> dict[str, Any]:
        duration = float(self._fallback_status.get("dead_zone_timer_s", 0.0))
        self._fallback_status.update(
            {
                "vehicle_state": "FULL_AUTONOMY",
                "active_degradation_level": "FULL_AUTONOMY",
                "dead_zone_timer_s": 0.0,
                "entered_dead_zone_progress": None,
                "entered_dead_zone_at": None,
                "last_known_gps": gps,
                "cloud_features_enabled": True,
                "speed_limit_kmph": None,
                "last_event": build_alert(
                    "SIGNAL_RECOVERED",
                    "info",
                    "Signal recovered. Resuming normal autonomy and cloud sync.",
                    gps=gps,
                    timestamp=self._utc_now_iso(),
                    outage_duration_s=round(duration, 1),
                ),
            }
        )
        return self._fallback_status

    def fallback_status(
        self,
        route: dict[str, Any],
        progress_ratio: float,
        speed_kmph: float,
    ) -> dict[str, Any]:
        if not route.get("segments"):
            return self._fallback_status

        current_index = min(len(route["segments"]) - 1, int(progress_ratio * max(1, len(route["segments"]) - 1)))
        current_segment = route["segments"][current_index]
        gps_index = min(len(route["path_geometry"]) - 1, current_index)
        gps = route["path_geometry"][gps_index]
        signal_dbm = float(current_segment.get("signal_dbm", signal_to_dbm(float(current_segment.get("avg_signal", 0.0)))))
        degradation_level = degradation_state_from_dbm(signal_dbm, bool(int(current_segment.get("dead_zone_flag", 0))))

        self._fallback_status["last_known_gps"] = gps
        self._fallback_status["active_degradation_level"] = degradation_level
        self._fallback_status["route_id"] = route["route_label"]

        pnr = route.get("point_of_no_return")
        if pnr and current_index >= max(0, int(pnr["distance_to_dead_zone_segments"]) - PNR_LOOKAHEAD_SEGMENTS):
            if pnr.get("reroute_path_nodes"):
                self._fallback_status.update(
                    {
                        "vehicle_state": "REDUCED_SPEED",
                        "speed_limit_kmph": DEGRADED_SPEED_LIMIT,
                        "cloud_features_enabled": True,
                        "last_event": build_alert(
                            "PNR_APPROACHING",
                            "warning",
                            "Point of no return is near. Dynamic reroute to a safer corridor is available.",
                            gps=gps,
                            timestamp=self._utc_now_iso(),
                            reroute_available=True,
                            reroute_path_nodes=pnr["reroute_path_nodes"],
                        ),
                    }
                )
            else:
                self._fail_safe_preparation(route, gps)

        if int(current_segment.get("dead_zone_flag", 0)) == 1:
            started_progress = self._fallback_status.get("entered_dead_zone_progress")
            if started_progress is None:
                started_progress = progress_ratio
                self._fallback_status["entered_dead_zone_progress"] = progress_ratio
            outage_seconds = max(0.0, float(route["travel_time_s"]) * max(0.0, progress_ratio - float(started_progress)))
            self._local_autonomy_mode(route, gps, progress_ratio, outage_seconds)
            if outage_seconds >= MAX_OUTAGE_SECONDS:
                self._safe_pullover(gps, route["route_label"])
        else:
            if self._fallback_status.get("entered_dead_zone_progress") is not None:
                self._resume_normal_mode(gps)
            else:
                self._fallback_status["vehicle_state"] = degradation_level

        self._fallback_status["alerts"] = banners_from_fallback_status(self._fallback_status)
        self._fallback_status["speed_kmph"] = speed_kmph
        return self._fallback_status

    def plan_routes(
        self,
        source_lat: float,
        source_lon: float,
        dest_lat: float,
        dest_lon: float,
        alpha: float = 0.72,
        provider_baseline: str = "Jio",
        application_type: str = "Navigation",
        environment_type: str = "normal",
        min_signal_threshold_dbm: float = MIN_SIGNAL_THRESHOLD,
    ) -> dict[str, object]:
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
            path = nx.shortest_path(
                self._graph,
                source_node,
                dest_node,
                weight=self._provider_weight_function(weight_key, provider_baseline),
            )
            metrics = self._route_metrics(path)
            metrics = enrich_route_for_safety(
                graph=self._graph,
                route_metrics=metrics,
                destination_node=dest_node,
                min_signal_threshold_dbm=min_signal_threshold_dbm,
            )
            metrics["operator_support_by_provider"] = self._route_support_by_provider(metrics["path_geometry"])
            metrics.update(self._provider_route_support(metrics["path_geometry"], provider_baseline))
            metrics = self._apply_environment_context(metrics, environment_type)
            metrics["route_label"] = label
            metrics["weight_key"] = weight_key
            routes.append(metrics)

        routes = self._relabel_routes_by_outcome(routes)
        routes = self._rank_routes_for_context(routes, alpha=alpha, provider_baseline=provider_baseline, application_type=application_type)
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
            "recommended_route_label": routes[0]["route_label"] if routes else None,
            "environment_type": environment_type,
        }

    def predict_signal_risk(
        self,
        route: dict[str, Any],
        speed_kmph: float,
        progress_ratio: float = 0.0,
        destination_assessment: dict[str, object] | None = None,
    ) -> dict[str, object]:
        route_segments = route["segments"]
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
            "fallback_status": self.fallback_status(route=route, progress_ratio=progress_ratio, speed_kmph=speed_kmph),
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
        environment_file = raw_dir / "environment_profiles_mvp.csv"
        connectivity_file = processed_dir / "segment_connectivity_mvp.csv"
        summary_file = processed_dir / "adaptive_signal_map_mvp.json"
    elif dataset == "full":
        raw_dir = PROJECT_ROOT / "data" / "raw"
        processed_dir = PROJECT_ROOT / "data" / "processed"
        road_file = raw_dir / "road_segments.csv"
        towers_file = raw_dir / "towers.csv"
        weak_zones_file = raw_dir / "weak_zones.csv"
        feedback_file = raw_dir / "feedback.csv"
        environment_file = raw_dir / "environment_profiles.csv"
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
        environment_profiles=_load_csv(environment_file),
        connectivity=_load_csv(connectivity_file),
        summary_json=_load_json(summary_file),
    )
