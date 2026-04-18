from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.api.planner import router as planner_router
from backend.api.reference import router as reference_router
from backend.core.data_store import get_store
from backend.core.geocoding import geocode_place


app = FastAPI(
    title="Connectivity-Aware Safe Routing Backend",
    version="0.1.0",
    description="Backend API for the Bengaluru AV routing MVP dataset.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reference_router)
app.include_router(planner_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/fallback-status")
def fallback_status(
    source: str = Query(..., min_length=3),
    destination: str = Query(..., min_length=3),
    dataset: str = Query(default="full", pattern="^(mvp|full)$"),
    alpha: float = Query(default=0.72, ge=0.0, le=1.0),
    provider_baseline: str = Query(default="Jio"),
    application_type: str = Query(default="Navigation"),
    environment_type: str = Query(default="normal"),
    min_signal_threshold_dbm: float = Query(default=-92.0, ge=-120.0, le=-40.0),
    route_label: str | None = Query(default=None),
    speed_kmph: float = Query(default=35.0, ge=5.0, le=120.0),
    progress_ratio: float = Query(default=0.0, ge=0.0, le=0.98),
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

    if not plan_result["routes"]:
        raise HTTPException(status_code=400, detail="No route options available for fallback evaluation")

    route = next((item for item in plan_result["routes"] if item["route_label"] == route_label), plan_result["routes"][0])
    status = store.fallback_status(route=route, progress_ratio=progress_ratio, speed_kmph=speed_kmph)
    return {
        "dataset": dataset,
        "route_label": route["route_label"],
        "fallback_status": status,
    }
