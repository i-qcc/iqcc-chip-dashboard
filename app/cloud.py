"""Thin wrapper around ``iqcc_cloud_client`` to fetch chip state and wiring.

The IQCC cloud client is synchronous and network-bound, so callers should run
:func:`fetch_backend_datasets` in a thread (e.g. via ``asyncio.to_thread``) to
avoid blocking the event loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from iqcc_cloud_client import IQCC_Cloud

from .config import settings

logger = logging.getLogger(__name__)


@dataclass
class BackendDatasets:
    """Raw datasets downloaded from the cloud for a single backend."""

    backend: str
    state: dict[str, Any]
    wiring: dict[str, Any]
    state_timestamp: str | None = None
    wiring_timestamp: str | None = None


def fetch_backend_datasets(backend: str) -> BackendDatasets:
    """Download the latest ``state`` and ``wiring`` datasets for ``backend``.

    Args:
        backend: Quantum computer backend name (e.g. ``"arbel"``).

    Returns:
        A :class:`BackendDatasets` with the raw JSON payloads.

    Raises:
        Exception: Propagates any error from the cloud client so the caller can
            decide how to surface it in the dashboard.
    """
    kwargs: dict[str, Any] = {"quantum_computer_backend": backend}
    if settings.api_token:
        kwargs["api_token"] = settings.api_token
    if settings.cloud_url:
        kwargs["url"] = settings.cloud_url

    logger.info("Fetching latest state/wiring for backend '%s'", backend)
    qc = IQCC_Cloud(**kwargs)

    latest_wiring = qc.state.get_latest("wiring")
    latest_state = qc.state.get_latest("state")

    if latest_state is None or latest_wiring is None:
        raise RuntimeError(f"No state/wiring datasets available for backend '{backend}'")

    return BackendDatasets(
        backend=backend,
        state=latest_state.data,
        wiring=latest_wiring.data,
        state_timestamp=_dataset_timestamp(latest_state),
        wiring_timestamp=_dataset_timestamp(latest_wiring),
    )


def _dataset_timestamp(dataset: Any) -> str | None:
    """Best-effort extraction of the dataset push timestamp as a string."""
    ts = getattr(dataset, "timestamp", None)
    if ts is None:
        return None
    return str(ts)
