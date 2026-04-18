from __future__ import annotations

import copy
from functools import lru_cache

import networkx as nx
from fastapi import APIRouter, HTTPException, Query

from backend.core.data_store import get_store
from backend.core.geocoding import geocode_place


router = APIRouter(prefix="/planner", tags=["planner"])


_REROUTE_SEVERITY_ORDER = {
    "clear": 0,
    "watch": 1,
    "warning": 2,
    "critical": 3,
}


def _attach_pnr_node_indices(routes: list[dict[str, object]]) -> list[dict[str, object]]:
    for route in routes:
        pnr = route.get("point_of_no_return")
        path_nodes = route.get("path_nodes") or []
        if not pnr or not path_nodes:
            route["pnr_node_index"] = None
            continue

        pnr_node_id = pnr.get("node_id")
        try:
            route["pnr_node_index"] = path_nodes.index(pnr_node_id)
        except ValueError:
            route["pnr_node_index"] = None
    return routes


@lru_cache(maxsize=128)
def _cached_plan_payload(
    dataset: str,
    source: str,
    destination: str,
    alpha: float,
    provider_baseline: str,
    application_type: str,
    environment_type: str,
    min_signal_threshold_dbm: float,
) -> dict[str, object]:
    store = get_store(dataset)
    source_point = geocode_place(source)
    destination_point = geocode_place(destination)
    plan_result = store.plan_routes(
        source_lat=source_point["lat"],
        source_lon=source_point["lon"],
        dest_lat=destination_point["lat"],
        dest_lon=destination_point["lon"],
        alpha=alpha,
        provider_baseline=provider_baseline,
        application_type=application_type,
        environment_type=environment_type,
        min_signal_threshold_dbm=min_signal_threshold_dbm,
    )
    plan_result["routes"] = _attach_pnr_node_indices(plan_result["routes"])
    return {
        "source": source_point,
        "destination": destination_point,
        "plan_result": plan_result,
    }


def _resolve_plan_payload(
    *,
    dataset: str,
    source: str,
    destination: str,
    alpha: float,
    provider_baseline: str,
    application_type: str,
    environment_type: str,
    min_signal_threshold_dbm: float,
) -> dict[str, object]:
    payload = _cached_plan_payload(
        dataset,
        source.strip(),
        destination.strip(),
        round(alpha, 4),
        provider_baseline.strip(),
        application_type.strip(),
        environment_type.strip(),
        round(min_signal_threshold_dbm, 2),
    )
    return copy.deepcopy(payload)


def _reroute_candidate_key(prediction: dict[str, object]) -> tuple[float, ...]:
    next_risk = prediction.get("next_risk", {})
    severity = str(next_risk.get("severity", "clear"))
    time_to_risk_min = next_risk.get("time_to_risk_min")
    predicted_risk_score = next_risk.get("predicted_risk_score")
    predicted_min_signal = next_risk.get("predicted_min_signal")
    return (
        float(_REROUTE_SEVERITY_ORDER.get(severity, 99)),
        -float(time_to_risk_min if time_to_risk_min is not None else -1.0),
        float(predicted_risk_score if predicted_risk_score is not None else 1.0),
        -float(predicted_min_signal if predicted_min_signal is not None else 0.0),
    )


def _severity_rank(next_risk: dict[str, object]) -> int:
    return int(_REROUTE_SEVERITY_ORDER.get(str(next_risk.get("severity", "clear")), 99))


def _time_to_risk_minutes(next_risk: dict[str, object]) -> float:
    value = next_risk.get("time_to_risk_min")
    if value is None:
        return 999.0
    return float(value)


def _is_materially_safer(primary_prediction: dict[str, object], candidate_prediction: dict[str, object]) -> bool:
    primary_next_risk = primary_prediction.get("next_risk", {})
    candidate_next_risk = candidate_prediction.get("next_risk", {})
    fallback_event_type = str(((primary_prediction.get("fallback_status") or {}).get("last_event") or {}).get("event_type", ""))

    primary_severity = _severity_rank(primary_next_risk)
    candidate_severity = _severity_rank(candidate_next_risk)
    if candidate_severity < primary_severity:
        return True
    if candidate_severity > primary_severity:
        return False

    primary_time = _time_to_risk_minutes(primary_next_risk)
    candidate_time = _time_to_risk_minutes(candidate_next_risk)
    if candidate_time >= primary_time + 0.75:
        return True

    primary_signal = float(primary_next_risk.get("predicted_min_signal") or 0.0)
    candidate_signal = float(candidate_next_risk.get("predicted_min_signal") or 0.0)
    primary_score = float(primary_next_risk.get("predicted_risk_score") or 1.0)
    candidate_score = float(candidate_next_risk.get("predicted_risk_score") or 1.0)
    if fallback_event_type == "PNR_APPROACHING":
        return (candidate_time > primary_time) or (candidate_severity <= primary_severity)
    return (candidate_signal >= primary_signal + 6.0) or (candidate_score <= primary_score - 0.08)


def _choose_reroute(
    store,
    routes: list[dict[str, object]],
    primary_route: dict[str, object],
    primary_prediction: dict[str, object],
    *,
    speed_kmph: float,
    progress_ratio: float,
    destination_assessment: dict[str, object] | None,
) -> tuple[bool, str | None, str | None]:
    primary_next_risk = primary_prediction.get("next_risk", {})
    primary_severity = str(primary_next_risk.get("severity", "clear"))
    fallback_status = primary_prediction.get("fallback_status", {})
    fallback_event_type = str((fallback_status.get("last_event") or {}).get("event_type", ""))
    should_consider_reroute = primary_severity in {"warning", "critical"} or fallback_event_type == "PNR_APPROACHING"
    if not should_consider_reroute:
        return False, None, None

    candidates: list[tuple[tuple[float, ...], dict[str, object], dict[str, object]]] = []
    for route in routes:
        if route["route_label"] == primary_route["route_label"]:
            continue
        candidate_prediction = store.predict_signal_risk(
            route=route,
            speed_kmph=speed_kmph,
            progress_ratio=progress_ratio,
            destination_assessment=destination_assessment,
        )
        candidates.append((_reroute_candidate_key(candidate_prediction), route, candidate_prediction))

    if not candidates:
        return False, None, None

    best_candidate_key, best_candidate, best_candidate_prediction = min(candidates, key=lambda item: item[0])
    if not _is_materially_safer(primary_prediction, best_candidate_prediction):
        return False, None, None

    next_risk_message = str(primary_next_risk.get("message", "Upcoming signal degradation detected."))
    if fallback_event_type == "PNR_APPROACHING":
        next_risk_message = "Point of no return is near."
    candidate_next_risk = best_candidate_prediction.get("next_risk", {})
    candidate_severity = str(candidate_next_risk.get("severity", "clear")).replace("_", " ")
    reroute_reason = (
        f"{next_risk_message} Switching to the {best_candidate['route_label']} route "
        f"to maintain connectivity. Alternate route outlook: {candidate_severity}."
    )
    return True, str(best_candidate["route_label"]), reroute_reason


@router.get("/overview")
def planner_overview(dataset: str = Query(default="mvp", pattern="^(mvp|full)$")) -> dict[str, object]:
    store = get_store(dataset)
    return store.planner_overview()


@router.get("/route-options")
def route_options(
    dataset: str = Query(default="full", pattern="^(mvp|full)$"),
    limit: int = Query(default=4, ge=1, le=12),
) -> dict[str, object]:
    store = get_store(dataset)
    return {"dataset": dataset, "routes": store.route_options(limit=limit)}


@router.get("/segments/{segment_id}")
def segment_detail(segment_id: str, dataset: str = Query(default="mvp", pattern="^(mvp|full)$")) -> dict[str, object]:
    store = get_store(dataset)
    detail = store.segment_detail(segment_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Segment {segment_id} not found")
    return detail


@router.get("/geocode")
def geocode(query: str = Query(..., min_length=3)) -> dict[str, object]:
    try:
        return geocode_place(query)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/plan")
def plan(
    source: str = Query(..., min_length=3),
    destination: str = Query(..., min_length=3),
    dataset: str = Query(default="full", pattern="^(mvp|full)$"),
    alpha: float = Query(default=0.72, ge=0.0, le=1.0),
    provider_baseline: str = Query(default="Jio"),
    application_type: str = Query(default="Navigation"),
    environment_type: str = Query(default="normal"),
    min_signal_threshold_dbm: float = Query(default=-92.0, ge=-120.0, le=-40.0),
) -> dict[str, object]:
    try:
        payload = _resolve_plan_payload(
            dataset=dataset,
            source=source,
            destination=destination,
            alpha=alpha,
            provider_baseline=provider_baseline,
            application_type=application_type,
            environment_type=environment_type,
            min_signal_threshold_dbm=min_signal_threshold_dbm,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except nx.NetworkXNoPath as error:  # type: ignore[name-defined]
        raise HTTPException(status_code=400, detail="No route found between the selected points") from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    source_point = payload["source"]
    destination_point = payload["destination"]
    plan_result = payload["plan_result"]

    return {
        "dataset": dataset,
        "source": source_point,
        "destination": destination_point,
        "routes": plan_result["routes"],
        "map_context": plan_result["map_context"],
        "destination_assessment": plan_result["destination_assessment"],
        "recommended_route_label": plan_result["recommended_route_label"],
        "environment_type": plan_result["environment_type"],
    }


@router.get("/predict-risk")
def predict_risk(
    source: str = Query(..., min_length=3),
    destination: str = Query(..., min_length=3),
    speed_kmph: float = Query(default=35.0, ge=5.0, le=120.0),
    progress_ratio: float = Query(default=0.0, ge=0.0, le=0.98),
    dataset: str = Query(default="full", pattern="^(mvp|full)$"),
    alpha: float = Query(default=0.72, ge=0.0, le=1.0),
    provider_baseline: str = Query(default="Jio"),
    application_type: str = Query(default="Navigation"),
    environment_type: str = Query(default="normal"),
    min_signal_threshold_dbm: float = Query(default=-92.0, ge=-120.0, le=-40.0),
    route_label: str | None = Query(default=None),
) -> dict[str, object]:
    store = get_store(dataset)
    try:
        payload = _resolve_plan_payload(
            dataset=dataset,
            source=source,
            destination=destination,
            alpha=alpha,
            provider_baseline=provider_baseline,
            application_type=application_type,
            environment_type=environment_type,
            min_signal_threshold_dbm=min_signal_threshold_dbm,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except nx.NetworkXNoPath as error:
        raise HTTPException(status_code=400, detail="No route found between the selected points") from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    source_point = payload["source"]
    destination_point = payload["destination"]
    plan_result = payload["plan_result"]

    if not plan_result["routes"]:
        raise HTTPException(status_code=400, detail="No route options available for prediction")

    primary_route = next(
        (route for route in plan_result["routes"] if route["route_label"] == route_label),
        plan_result["routes"][0],
    )
    prediction = store.predict_signal_risk(
        route=primary_route,
        speed_kmph=speed_kmph,
        progress_ratio=progress_ratio,
        destination_assessment=plan_result["destination_assessment"],
    )
    should_reroute, recommended_route_label, reroute_reason = _choose_reroute(
        store,
        plan_result["routes"],
        primary_route,
        prediction,
        speed_kmph=speed_kmph,
        progress_ratio=progress_ratio,
        destination_assessment=plan_result["destination_assessment"],
    )

    return {
        "dataset": dataset,
        "source": source_point,
        "destination": destination_point,
        "route_label": primary_route["route_label"],
        "prediction": prediction,
        "destination_assessment": plan_result["destination_assessment"],
        "should_reroute": should_reroute,
        "reroute_reason": reroute_reason,
        "recommended_route_label": recommended_route_label,
    }
