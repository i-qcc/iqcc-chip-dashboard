"""In-memory store for the most recently processed dashboard payloads."""

from __future__ import annotations

import threading
from typing import Any, Optional


class DashboardCache:
    """Thread-safe holder for per-backend dashboard data and refresh status."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._backends: dict[str, dict[str, Any]] = {}
        self._errors: dict[str, str] = {}
        self._last_refresh: Optional[str] = None

    def set_backend(self, backend: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._backends[backend] = data
            self._errors.pop(backend, None)

    def set_error(self, backend: str, message: str) -> None:
        with self._lock:
            self._errors[backend] = message

    def set_last_refresh(self, iso_timestamp: str) -> None:
        with self._lock:
            self._last_refresh = iso_timestamp

    def snapshot(self, backend_order: list[str]) -> dict[str, Any]:
        """Return a serializable snapshot ordered per the configured backends."""
        with self._lock:
            ordered = [
                self._backends[b] for b in backend_order if b in self._backends
            ]
            return {
                "last_refresh": self._last_refresh,
                "backends": ordered,
                "errors": dict(self._errors),
            }


cache = DashboardCache()
