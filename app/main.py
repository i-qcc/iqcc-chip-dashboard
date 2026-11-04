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
CHIP_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def _chip_image_url(backend: str) -> str | None:
    """URL of ``static/chips/<backend>.<ext>`` if such a photo exists."""
    for ext in CHIP_IMAGE_EXTENSIONS:
        name = f"{backend.lower()}{ext}"
        if (BASE_DIR / "static" / "chips" / name).is_file():
            return f"/static/chips/{name}"
    return None


async def _refresh_backend(backend: str) -> None:
    """Fetch + process one backend, updating the cache (never raises).

    The actual network call runs in a worker thread via ``asyncio.to_thread``.
    If the underlying cloud client call hangs (flaky Wi-Fi, a DNS stall, a
    dead TCP connection that never errors out, ...) past the configured
    ``fetch_timeout_seconds``, ``asyncio.wait_for`` abandons waiting on it so
    this backend's refresh loop can retry on schedule instead of being stuck
    forever. The orphaned thread may linger and finish later (harmlessly
    updating the cache then), but it no longer blocks future refreshes.
    """
    try:
        datasets = await asyncio.wait_for(
            asyncio.to_thread(fetch_backend_datasets, backend),
            timeout=settings.fetch_timeout_seconds,
        )
        fetched_at = datetime.now(timezone.utc).isoformat()
        data = build_dashboard_data(
            backend=datasets.backend,
            state=datasets.state,
            wiring=datasets.wiring,
            staleness_hours=settings.staleness_hours,
            fetched_at=fetched_at,
        )
        data["chip_image"] = _chip_image_url(datasets.backend)
        cache.set_backend(datasets.backend, data)
        cache.set_backend_refreshed(backend, fetched_at)
        logger.info(
            "Refreshed '%s': %d qubits, %d pairs",
            datasets.backend,
            data["n_active_qubits"],
            data["n_active_pairs"],
        )
    except TimeoutError:
        logger.error(
            "Timed out after %ss waiting for backend '%s' (stuck network call "
            "abandoned, will retry next cycle)",
            settings.fetch_timeout_seconds,
            backend,
        )
        cache.set_error(backend, f"Timed out after {settings.fetch_timeout_seconds}s")
    except Exception as exc:  # noqa: BLE001 - surface, do not crash the loop
        logger.exception("Failed to refresh backend '%s'", backend)
        cache.set_error(backend, str(exc))


async def _refresh_all() -> None:
    await asyncio.gather(*(_refresh_backend(b) for b in settings.backends))
    cache.set_last_refresh(datetime.now(timezone.utc).isoformat())


async def _refresh_backend_loop(backend: str) -> None:
    """Independent refresh loop for one backend.

    Each backend gets its own task/sleep cycle so a stuck or slow backend
    never delays (or, pre-fix, could indefinitely freeze) refreshes of the
    others, and so one timed-out fetch doesn't push back this backend's own
    next attempt beyond the normal interval.
    """
    while True:
        await _refresh_backend(backend)
        cache.set_last_refresh(datetime.now(timezone.utc).isoformat())
        await asyncio.sleep(settings.refresh_interval_seconds)


async def _watchdog_loop() -> None:
    """Belt-and-suspenders: if a backend hasn't refreshed in a long time even
    with the per-fetch timeout in place (e.g. its refresh task died from an
    unexpected BaseException such as a cancellation), log loudly so this is
    visible in the logs/console rather than silently going stale forever."""
    check_every = max(60, settings.refresh_interval_seconds // 2)
    stale_after = settings.refresh_interval_seconds * 3
    while True:
        await asyncio.sleep(check_every)
        now = datetime.now(timezone.utc)
        for backend, last in cache.last_refresh_per_backend().items():
            if last is None:
                continue
            age = (now - last).total_seconds()
            if age > stale_after:
                logger.error(
                    "Watchdog: backend '%s' has not refreshed in %.0fs "
                    "(expected every %ss) - its refresh loop may be stuck.",
                    backend,
                    age,
                    settings.refresh_interval_seconds,
                )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting dashboard: backends=%s, refresh=%ss, fetch_timeout=%ss, staleness=%sh, rotation=%ss",
        settings.backends,
        settings.refresh_interval_seconds,
        settings.fetch_timeout_seconds,
        settings.staleness_hours,
        settings.rotation_seconds,
    )
    tasks = [asyncio.create_task(_refresh_backend_loop(b)) for b in settings.backends]
    tasks.append(asyncio.create_task(_watchdog_loop()))
    try:
        yield
    finally:
        for task in tasks:
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
