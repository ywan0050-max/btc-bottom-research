from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import DB_PATH, PROJECT_ROOT, WEB_DIST
from .db import Database
from .models import CvddReferenceInput
from .service import ResearchService


database = Database(DB_PATH)
service = ResearchService(database)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    database.initialize()
    service.load_metric_names()
    try:
        await asyncio.to_thread(service.refresh_overview_cache)
    except Exception:
        # The API can still start and expose cache diagnostics in /api/health.
        pass
    scheduler_task = asyncio.create_task(service.scheduler())
    try:
        yield
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="BTC Bottom Research Desk",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def api_cache_control(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


def runtime_info() -> dict[str, object] | None:
    runtime_path = PROJECT_ROOT / ".runtime.json"
    try:
        return json.loads(runtime_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "database": str(DB_PATH),
        "metrics": service.metric_names,
        "refresh": service.refresh_state,
        "scheduler": service.scheduler_state,
        "archive": service.archive_state,
        "overviewCache": service.overview_cache_state,
        "runtime": runtime_info(),
    }


@app.get("/api/overview")
def overview() -> JSONResponse:
    response = JSONResponse(service.overview())
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/series/{metric}")
def metric_series(
    metric: str,
    limit: int = Query(default=1500, ge=10, le=10000),
) -> dict[str, object]:
    if metric not in database.metric_names():
        raise HTTPException(status_code=404, detail=f"Metric {metric} is unavailable.")
    return {"metric": metric, "data": database.series(metric, limit)}


@app.get("/api/sources")
def sources() -> dict[str, object]:
    return {
        "sources": service.sources(),
        "metrics": database.metric_names(),
    }


@app.get("/api/scores")
def score_history(
    limit: int = Query(default=500, ge=10, le=5000),
) -> dict[str, object]:
    return {"data": service.score_history(limit)}


@app.get("/api/references/cvdd")
def cvdd_references() -> dict[str, object]:
    return service.cvdd_references()


def require_loopback_client(request: Request) -> None:
    client_host = request.client.host if request.client else None
    if client_host not in {"127.0.0.1", "::1"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CVDD reference writes are only allowed from this computer.",
        )


@app.post("/api/references/cvdd", status_code=status.HTTP_201_CREATED)
def add_cvdd_reference(
    payload: CvddReferenceInput, request: Request
) -> dict[str, object]:
    require_loopback_client(request)
    return service.add_cvdd_reference(
        payload.source_name,
        payload.source_url,
        payload.observed_date,
        payload.value_usd,
        payload.note,
    )


@app.get("/api/refresh-history")
def refresh_history(
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    return service.refresh_history(limit)


@app.post("/api/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh() -> dict[str, object]:
    accepted = service.start_refresh()
    return {"accepted": accepted, "refresh": service.refresh_state}


dist_path = Path(WEB_DIST)
if dist_path.exists():
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="web")
