"""FastAPI application: periodic cloud refresh + rotating kiosk dashboard."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .cache import cache
from .cloud import fetch_backend_datasets
from .config import settings
from .state_parser import build_dashboard_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


async def _refresh_backend(backend: str) -> None:
    """Fetch + process one backend, updating the cache (never raises)."""
    try:
        datasets = await asyncio.to_thread(fetch_backend_datasets, backend)
        fetched_at = datetime.now(timezone.utc).isoformat()
        data = build_dashboard_data(
            backend=datasets.backend,
            state=datasets.state,
            wiring=datasets.wiring,
            staleness_hours=settings.staleness_hours,
            fetched_at=fetched_at,
        )
        cache.set_backend(datasets.backend, data)
        logger.info(
            "Refreshed '%s': %d qubits, %d pairs",
            datasets.backend,
            data["n_active_qubits"],
            data["n_active_pairs"],
        )
    except Exception as exc:  # noqa: BLE001 - surface, do not crash the loop
        logger.exception("Failed to refresh backend '%s'", backend)
        cache.set_error(backend, str(exc))


async def _refresh_all() -> None:
    await asyncio.gather(*(_refresh_backend(b) for b in settings.backends))
    cache.set_last_refresh(datetime.now(timezone.utc).isoformat())


async def _refresh_loop() -> None:
    while True:
        await _refresh_all()
        await asyncio.sleep(settings.refresh_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting dashboard: backends=%s, refresh=%ss, staleness=%sh, rotation=%ss",
        settings.backends,
        settings.refresh_interval_seconds,
        settings.staleness_hours,
        settings.rotation_seconds,
    )
    task = asyncio.create_task(_refresh_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="IQCC Chip State Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/api/data")
async def api_data() -> JSONResponse:
    payload = cache.snapshot(settings.backends)
    payload["config"] = {
        "rotation_seconds": settings.rotation_seconds,
        "refresh_interval_seconds": settings.refresh_interval_seconds,
        "staleness_hours": settings.staleness_hours,
        "backends": settings.backends,
    }
    return JSONResponse(payload)


@app.post("/api/refresh")
async def api_refresh() -> JSONResponse:
    """Force an immediate refresh (useful for testing / manual reloads)."""
    await _refresh_all()
    return JSONResponse({"status": "ok", "last_refresh": cache.snapshot([]).get("last_refresh")})


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "rotation_seconds": settings.rotation_seconds,
            "refresh_interval_seconds": settings.refresh_interval_seconds,
        },
    )
