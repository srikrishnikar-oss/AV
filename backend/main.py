from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.planner import router as planner_router
from backend.api.reference import router as reference_router


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
