from __future__ import annotations

from typing import Any

import networkx as nx

from backend.core.config import MIN_SIGNAL_THRESHOLD
from backend.core.point_of_no_return import add_degradation_labels, find_point_of_no_return


def enrich_route_for_safety(
    graph: nx.DiGraph,
    route_metrics: dict[str, Any],
    destination_node: int,
    min_signal_threshold_dbm: float | None = None,
) -> dict[str, Any]:
    threshold = float(min_signal_threshold_dbm if min_signal_threshold_dbm is not None else MIN_SIGNAL_THRESHOLD)
    enriched_segments = add_degradation_labels(route_metrics["segments"])
    pnr = find_point_of_no_return(
        graph=graph,
        path_nodes=route_metrics["path_nodes"],
        route_segments=enriched_segments,
        destination_node=destination_node,
    )

    route_metrics["segments"] = enriched_segments
    route_metrics["point_of_no_return"] = pnr
    route_metrics["degradation_states"] = [segment["degradation_state"] for segment in enriched_segments]
    route_metrics["degradation_summary"] = {
        state: sum(1 for segment in enriched_segments if segment["degradation_state"] == state)
        for state in ["FULL_AUTONOMY", "REDUCED_SPEED", "SUPERVISED_MODE", "PULL_OVER"]
    }
    route_metrics["min_signal_threshold_dbm"] = threshold
    route_metrics["threshold_breach"] = any(segment["signal_dbm"] < threshold for segment in enriched_segments)
    route_metrics["strict_safe"] = (
        route_metrics["dead_zone_count"] == 0
        and pnr is None
        and not route_metrics["threshold_breach"]
        and route_metrics["degradation_summary"]["PULL_OVER"] == 0
        and route_metrics["degradation_summary"]["SUPERVISED_MODE"] == 0
    )
    return route_metrics
