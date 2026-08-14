from __future__ import annotations

import asyncio
import ipaddress
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import (
    APP_VERSION,
    DB_PATH,
    DISABLE_BACKGROUND_TASKS,
    RUNTIME_PATH,
    WEB_DIST,
)
from .db import Database
from .models import CvddReferenceInput
from .service import ResearchService


database = Database(DB_PATH)
service = ResearchService(database)
ALLOWED_HOST_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    database.initialize()
    service.load_metric_names()
    try:
        await asyncio.to_thread(service.refresh_overview_cache)
    except Exception:
        # The API can still start and expose cache diagnostics in /api/health.
        pass
    scheduler_task = (
        None
        if DISABLE_BACKGROUND_TASKS
        else asyncio.create_task(service.scheduler())
    )
    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="BTC Bottom Research Desk",
    version=APP_VERSION,
    lifespan=lifespan,
)


def host_is_allowed(hostname: str | None) -> bool:
    if not hostname:
        return False
    normalized = hostname.rstrip(".").casefold()
    if normalized == "localhost":
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return any(address in network for network in ALLOWED_HOST_NETWORKS)


@app.middleware("http")
async def api_cache_control(request: Request, call_next):
    if not host_is_allowed(request.url.hostname):
        response = JSONResponse(
            {"detail": "Host is not allowed. Use a local, LAN, or Tailscale IP."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    else:
        response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    return response


def runtime_info() -> dict[str, object] | None:
    try:
        return json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "version": APP_VERSION,
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


def require_same_origin_request(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    expected_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin.rstrip("/").casefold() != expected_origin.rstrip("/").casefold():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-origin writes are not allowed.",
        )


@app.post("/api/references/cvdd", status_code=status.HTTP_201_CREATED)
def add_cvdd_reference(
    payload: CvddReferenceInput, request: Request
) -> dict[str, object]:
    require_same_origin_request(request)
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
async def refresh(request: Request) -> dict[str, object]:
    require_same_origin_request(request)
    accepted = service.start_refresh()
    return {"accepted": accepted, "refresh": service.refresh_state}


dist_path = Path(WEB_DIST)
if dist_path.exists():
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="web")
