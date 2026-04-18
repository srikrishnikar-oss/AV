from __future__ import annotations

from typing import Any

import networkx as nx

from backend.core.config import DEGRADATION_THRESHOLDS


def signal_to_dbm(signal_score: float) -> float:
    normalized = max(0.0, min(1.0, float(signal_score) / 100.0))
    return round(-110.0 + normalized * 55.0, 2)


def degradation_state_from_dbm(signal_dbm: float, dead_zone_flag: bool = False) -> str:
    if dead_zone_flag or signal_dbm < DEGRADATION_THRESHOLDS["SUPERVISED_MODE"]:
        return "PULL_OVER"
    if signal_dbm <= DEGRADATION_THRESHOLDS["REDUCED_SPEED"]:
        return "SUPERVISED_MODE"
    if signal_dbm <= DEGRADATION_THRESHOLDS["FULL_AUTONOMY"]:
        return "REDUCED_SPEED"
    return "FULL_AUTONOMY"


def add_degradation_labels(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labeled: list[dict[str, Any]] = []
    for segment in segments:
        signal_dbm = signal_to_dbm(float(segment.get("avg_signal", 0.0)))
        labeled.append(
            {
                **segment,
                "signal_dbm": signal_dbm,
                "degradation_state": degradation_state_from_dbm(
                    signal_dbm,
                    bool(int(segment.get("dead_zone_flag", 0))),
                ),
            }
        )
    return labeled


def find_point_of_no_return(
    graph: nx.DiGraph,
    path_nodes: list[int],
    route_segments: list[dict[str, Any]],
    destination_node: int,
) -> dict[str, Any] | None:
    dead_zone_index = next(
        (index for index, segment in enumerate(route_segments) if int(segment.get("dead_zone_flag", 0)) == 1),
        None,
    )
    if dead_zone_index is None or dead_zone_index <= 0:
        return None

    safe_view = nx.subgraph_view(
        graph,
        filter_edge=lambda u, v: int(graph[u][v].get("dead_zone_flag", 0)) == 0,
    )

    for node_index in range(dead_zone_index, -1, -1):
        node_id = path_nodes[node_index]
        current_next = path_nodes[node_index + 1] if node_index + 1 < len(path_nodes) else None
        try:
            alternative_path = nx.shortest_path(safe_view, node_id, destination_node, weight="weight_safe")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue

        if len(alternative_path) >= 2 and alternative_path[1] != current_next:
            node_data = graph.nodes[node_id]
            return {
                "node_id": int(node_id),
                "lat": float(node_data["lat"]),
                "lon": float(node_data["lon"]),
                "reroute_path_nodes": [int(value) for value in alternative_path],
                "dead_zone_segment_id": route_segments[dead_zone_index]["segment_id"],
                "distance_to_dead_zone_segments": dead_zone_index - node_index + 1,
            }

    return None
