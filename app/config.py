"""Application configuration.

Settings are read from environment variables (optionally via a local ``.env``
file) with sensible defaults so the app runs out of the box for the ``arbel``
backend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """Populate ``os.environ`` from a local ``.env`` file if present.

    Kept dependency-free: only ``KEY=VALUE`` lines are parsed and existing
    environment variables always take precedence.
    """
    dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _parse_backends(raw: str) -> list[str]:
    """Parse a comma-separated backend list, ignoring blanks."""
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Resolved application settings."""

    backends: list[str] = field(default_factory=lambda: ["arbel"])
    refresh_interval_seconds: int = 600
    staleness_hours: float = 5.0
    rotation_seconds: int = 15
    api_token: str | None = None
    cloud_url: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        backends = _parse_backends(os.environ.get("BACKENDS", "arbel")) or ["arbel"]
        return cls(
            backends=backends,
            refresh_interval_seconds=int(os.environ.get("REFRESH_INTERVAL_SECONDS", "600")),
            staleness_hours=float(os.environ.get("STALENESS_HOURS", "5")),
            rotation_seconds=int(os.environ.get("ROTATION_SECONDS", "15")),
            api_token=os.environ.get("IQCC_API_TOKEN") or None,
            cloud_url=os.environ.get("IQCC_CLOUD_URL") or None,
        )


settings = Settings.from_env()
