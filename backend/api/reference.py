from __future__ import annotations

from fastapi import APIRouter, Query

from backend.core.data_store import get_store


router = APIRouter(tags=["reference"])


@router.get("/")
def root() -> dict[str, object]:
    return {
        "message": "Connectivity-Aware Safe Routing Backend",
        "docs": "/docs",
        "datasets": {
            "mvp": "Central Bengaluru MVP dataset",
            "full": "Full Bengaluru dataset",
        },
    }


@router.get("/datasets/{dataset}/summary")
def dataset_summary(dataset: str) -> dict[str, object]:
    store = get_store(dataset)
    return store.summary()


@router.get("/datasets/{dataset}/towers")
def list_towers(dataset: str, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    store = get_store(dataset)
    return {"dataset": dataset, "count": min(limit, len(store.towers)), "items": store.towers.head(limit).to_dict(orient="records")}


@router.get("/datasets/{dataset}/weak-zones")
def list_weak_zones(dataset: str) -> dict[str, object]:
    store = get_store(dataset)
    return {"dataset": dataset, "count": len(store.weak_zones), "items": store.weak_zones.to_dict(orient="records")}


@router.get("/datasets/{dataset}/feedback")
def list_feedback(dataset: str) -> dict[str, object]:
    store = get_store(dataset)
    return {"dataset": dataset, "count": len(store.feedback), "items": store.feedback.to_dict(orient="records")}


@router.get("/datasets/{dataset}/segments")
def list_segments(
    dataset: str,
    limit: int = Query(default=100, ge=1, le=1000),
    safe_flag: int | None = Query(default=None, ge=0, le=1),
) -> dict[str, object]:
    store = get_store(dataset)
    segments = store.connectivity
    if safe_flag is not None:
        segments = segments[segments["safe_flag"] == safe_flag]
    items = segments.head(limit).to_dict(orient="records")
    return {"dataset": dataset, "count": len(items), "items": items}


@router.get("/datasets/{dataset}/map")
def dataset_map(
    dataset: str,
    limit: int = Query(default=1200, ge=100, le=5000),
) -> dict[str, object]:
    store = get_store(dataset)
    return store.map_payload(limit=limit)
