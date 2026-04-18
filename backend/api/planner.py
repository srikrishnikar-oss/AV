from __future__ import annotations

import networkx as nx
from fastapi import APIRouter, HTTPException, Query

from backend.core.data_store import get_store
from backend.core.geocoding import geocode_place


router = APIRouter(prefix="/planner", tags=["planner"])


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
    store = get_store(dataset)
    try:
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
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except nx.NetworkXNoPath as error:  # type: ignore[name-defined]
        raise HTTPException(status_code=400, detail="No route found between the selected points") from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

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
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except nx.NetworkXNoPath as error:
        raise HTTPException(status_code=400, detail="No route found between the selected points") from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

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

    return {
        "dataset": dataset,
        "source": source_point,
        "destination": destination_point,
        "route_label": primary_route["route_label"],
        "prediction": prediction,
        "destination_assessment": plan_result["destination_assessment"],
    }
