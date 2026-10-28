"""Extract dashboard-ready metrics from a QuAM ``state``/``wiring`` pair.

This module knows the QuAM state schema for a FluxTunableQuam chip and turns the
raw JSON into a compact, front-end-friendly structure. It also:

* resolves QuAM JSON-pointer references (``#/...``, ``#./...``, ``#../...``) so
  gate lengths and the active CZ macro can be read;
* computes readout / GEF readout fidelity from confusion matrices;
* applies the staleness rule: metrics carrying a collection timestamp
  (1Q RB, Bell state, 2Q RB) are hidden when older than ``staleness_hours``;
  metrics without a timestamp (T1, T2*, readout, GEF) are always shown.

Coherence times are stored in seconds and reported in microseconds. Pulse
lengths are stored (and reported) in nanoseconds.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Native single-qubit gates to report, mapped to the operation key that holds
# the canonical pulse length.
NATIVE_1Q_GATES = ["x180", "x90", "y180", "y90"]

_TS_RE = re.compile(
    r"(?P<dt>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*GMT(?P<off>[+-]\d+)?"
)


# --------------------------------------------------------------------------- #
# JSON-pointer / reference resolution
# --------------------------------------------------------------------------- #
def _get_by_path(root: dict, path: list[str]) -> Any:
    node: Any = root
    for key in path:
        node = node[key]
    return node


def _resolve_pointer(root: dict, container_path: list[str], ref: str):
    """Resolve a QuAM reference string.

    Args:
        root: The full state document.
        container_path: Path (list of keys) to the dict that *contains* the key
            whose value is ``ref``.
        ref: A reference string beginning with ``#``.

    Returns:
        Tuple ``(value, path_to_value)``.
    """
    body = ref[1:]
    if body.startswith("/"):
        target = [p for p in body.split("/") if p]
    else:
        parts = body.split("/")
        dots = parts[0].count(".")
        up = max(dots - 1, 0)
        base = list(container_path)
        for _ in range(up):
            if base:
                base = base[:-1]
        target = base + parts[1:]
    return _get_by_path(root, target), target


def _deref(root: dict, container_path: list[str], value: Any, key: str):
    """Fully resolve ``container[key]`` following any chain of references.

    Returns ``(resolved_value, path_to_resolved_value)`` where the path points
    at the resolved value node itself, so child references can be resolved from
    it as their container.
    """
    path = container_path + [key]
    guard = 0
    while isinstance(value, str) and value.startswith("#") and guard < 16:
        value, path = _resolve_pointer(root, path[:-1], value)
        guard += 1
    return value, path


# --------------------------------------------------------------------------- #
# Timestamp / staleness helpers
# --------------------------------------------------------------------------- #
def parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
    """Parse a ``"YYYY-MM-DD HH:MM:SS GMT+N"`` timestamp into an aware datetime."""
    if not raw or not isinstance(raw, str):
        return None
    match = _TS_RE.search(raw)
    if not match:
        return None
    dt = datetime.strptime(match.group("dt"), "%Y-%m-%d %H:%M:%S")
    off = match.group("off")
    hours = int(off) if off else 0
    return dt.replace(tzinfo=timezone(timedelta(hours=hours)))


def _is_fresh(ts: Optional[datetime], staleness_hours: float) -> bool:
    if ts is None:
        return False
    now = datetime.now(timezone.utc)
    return (now - ts) <= timedelta(hours=staleness_hours)


def _timestamped_metric(
    value: Optional[float],
    raw_ts: Optional[str],
    staleness_hours: float,
) -> Optional[dict]:
    """Return a metric dict, or ``None`` when stale/missing.

    Applies the 5-hour staleness rule: a value is only surfaced when it has a
    valid, fresh timestamp.
    """
    if value is None:
        return None
    ts = parse_timestamp(raw_ts)
    if not _is_fresh(ts, staleness_hours):
        return None
    return {"value": value, "updated_at": raw_ts}


# --------------------------------------------------------------------------- #
# Small extraction helpers
# --------------------------------------------------------------------------- #
def _to_us(seconds: Any) -> Optional[float]:
    if not isinstance(seconds, (int, float)):
        return None
    return round(seconds * 1e6, 2)


def _diagonal_fidelity(matrix: Any) -> Optional[float]:
    """Average of the diagonal of a (square) confusion matrix, as a fraction."""
    if not isinstance(matrix, list) or not matrix:
        return None
    try:
        n = len(matrix)
        diag = sum(float(matrix[i][i]) for i in range(n))
        return round(diag / n, 4)
    except (IndexError, TypeError, ValueError):
        return None


def _pulse_length_ns(root: dict, ops_path: list[str], op_key: str) -> Optional[int]:
    """Resolve the pulse length (ns) for an operation, following references."""
    try:
        ops = _get_by_path(root, ops_path)
    except (KeyError, TypeError):
        return None
    if op_key not in ops:
        return None
    pulse, pulse_path = _deref(root, ops_path, ops[op_key], op_key)
    if not isinstance(pulse, dict):
        return None
    if "length" not in pulse:
        return None
    length, _ = _deref(root, pulse_path, pulse["length"], "length")
    return length if isinstance(length, (int, float)) else None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def build_dashboard_data(
    backend: str,
    state: dict,
    wiring: dict,
    staleness_hours: float = 5.0,
    fetched_at: Optional[str] = None,
) -> dict:
    """Build the dashboard payload for a single backend."""
    active_qubit_set = set(state.get("active_qubit_names", []))
    active_pair_set = set(state.get("active_qubit_pair_names", []))

    backend_name = (
        wiring.get("network", {}).get("quantum_computer_backend")
        or backend
    )

    all_timestamps: list[datetime] = []

    # Include ALL qubits (active and inactive) with an ``active`` flag so the
    # frontend can render inactive qubits as small gray circles.
    all_qubit_names = list(state.get("qubits", {}).keys())
    qubits = [
        _build_qubit(state, name, staleness_hours, all_timestamps,
                     active=name in active_qubit_set)
        for name in all_qubit_names
    ]

    # Include ALL qubit pairs so pair-connecting edges are drawn for the full
    # chip topology.
    all_pair_names = list(state.get("qubit_pairs", {}).keys())
    pairs = [
        _build_pair(state, name, staleness_hours, all_timestamps,
                    active=name in active_pair_set)
        for name in all_pair_names
    ]

    last_cal = max(all_timestamps).isoformat() if all_timestamps else None

    native_gates = _native_gates(state, list(active_qubit_set))

    return {
        "backend": backend_name,
        "cluster_name": wiring.get("network", {}).get("cluster_name"),
        "fetched_at": fetched_at,
        "last_calibration": last_cal,
        "n_active_qubits": len(active_qubit_set),
        "n_active_pairs": len(active_pair_set),
        "active_qubits": sorted(active_qubit_set),
        "active_pairs": sorted(active_pair_set),
        "native_gates": native_gates,
        "qubits": qubits,
        "pairs": pairs,
    }


def _build_qubit(
    state: dict,
    name: str,
    staleness_hours: float,
    all_timestamps: list[datetime],
    *,
    active: bool = True,
) -> dict:
    q = state["qubits"][name]
    resonator = q.get("resonator", {}) or {}

    grid = _parse_grid(q.get("grid_location"))

    # 1Q RB fidelity (timestamped -> staleness applies)
    gate_fid = q.get("gate_fidelity", {}) or {}
    rb_raw_ts = gate_fid.get("averaged_updated_at")
    rb = _timestamped_metric(gate_fid.get("averaged"), rb_raw_ts, staleness_hours)
    # Always track the timestamp for last-calibration even if the metric is stale.
    ts = parse_timestamp(rb_raw_ts)
    if ts:
        all_timestamps.append(ts)

    return {
        "id": q.get("id", name),
        "active": active,
        "grid": grid,
        "f_01": q.get("f_01"),
        "t1_us": _to_us(q.get("T1")),
        "t2star_us": _to_us(q.get("T2ramsey")),
        "t2echo_us": _to_us(q.get("T2echo")),
        "readout_fidelity": _diagonal_fidelity(resonator.get("confusion_matrix")),
        "gef_readout_fidelity": _diagonal_fidelity(
            resonator.get("gef_confusion_matrix")
        ),
        "rb_1q_fidelity": rb,
    }


def _build_pair(
    state: dict,
    name: str,
    staleness_hours: float,
    all_timestamps: list[datetime],
    *,
    active: bool = True,
) -> dict:
    pair = state["qubit_pairs"][name]
    control = _ref_leaf(pair.get("qubit_control"))
    target = _ref_leaf(pair.get("qubit_target"))

    macro, macro_path = _active_cz_macro(state, name)
    fidelity = macro.get("fidelity", {}) if isinstance(macro, dict) else {}

    bell = fidelity.get("Bell_State", {}) or {}
    bell_metric = _timestamped_metric(
        bell.get("Fidelity"), bell.get("updated_at"), staleness_hours
    )
    ts = parse_timestamp(bell.get("updated_at"))
    if ts:
        all_timestamps.append(ts)

    rb2q = fidelity.get("StandardRB", {}) or {}
    rb2q_metric = _timestamped_metric(
        rb2q.get("average_gate_fidelity"), rb2q.get("updated_at"), staleness_hours
    )
    ts = parse_timestamp(rb2q.get("updated_at"))
    if ts:
        all_timestamps.append(ts)

    cz_length = None
    if isinstance(macro, dict):
        flux = macro.get("flux_pulse_qubit", {}) or {}
        length = flux.get("length")
        if isinstance(length, (int, float)):
            cz_length = length

    return {
        "id": pair.get("id", name),
        "active": active,
        "control": control,
        "target": target,
        "cz_length_ns": cz_length,
        "bell_fidelity": bell_metric,
        "rb_2q_fidelity": rb2q_metric,
    }


def _active_cz_macro(state: dict, pair_name: str):
    """Follow ``macros.cz`` to the active CZ macro; fallback to ``cz_unipolar``."""
    macros = state["qubit_pairs"][pair_name].get("macros", {}) or {}
    cz_ref = macros.get("cz")
    base_path = ["qubit_pairs", pair_name, "macros"]
    if isinstance(cz_ref, str) and cz_ref.startswith("#"):
        try:
            macro, macro_path = _deref(state, base_path, cz_ref, "cz")
            if isinstance(macro, dict):
                return macro, macro_path
        except (KeyError, TypeError):
            pass
    for fallback in ("cz_unipolar", "cz_flattop", "cz_bipolar"):
        if isinstance(macros.get(fallback), dict):
            return macros[fallback], base_path + [fallback]
    return {}, base_path


def _native_gates(state: dict, active_qubits: list[str]) -> list[dict]:
    """Report native 1Q gate names and a representative (median) length in ns."""
    lengths: dict[str, list[int]] = {g: [] for g in NATIVE_1Q_GATES}
    qubits = state.get("qubits", {})
    for name in active_qubits:
        q = qubits.get(name)
        if not q:
            continue
        ops_path = ["qubits", name, "xy", "operations"]
        for gate in NATIVE_1Q_GATES:
            length = _pulse_length_ns(state, ops_path, gate)
            if isinstance(length, (int, float)):
                lengths[gate].append(int(length))

    result = []
    for gate in NATIVE_1Q_GATES:
        vals = sorted(lengths[gate])
        median = vals[len(vals) // 2] if vals else None
        result.append({"name": gate, "length_ns": median})

    # CZ is the native two-qubit gate; report a representative length.
    cz_lengths: list[int] = []
    for pair_name in state.get("active_qubit_pair_names", []):
        if pair_name not in state.get("qubit_pairs", {}):
            continue
        macro, _ = _active_cz_macro(state, pair_name)
        if isinstance(macro, dict):
            flux = macro.get("flux_pulse_qubit", {}) or {}
            if isinstance(flux.get("length"), (int, float)):
                cz_lengths.append(int(flux["length"]))
    cz_lengths.sort()
    cz_median = cz_lengths[len(cz_lengths) // 2] if cz_lengths else None
    result.append({"name": "CZ", "length_ns": cz_median})

    return result


def _parse_grid(raw: Any) -> Optional[dict]:
    if not isinstance(raw, str) or "," not in raw:
        return None
    try:
        col, row = raw.split(",")
        return {"col": int(col.strip()), "row": int(row.strip())}
    except ValueError:
        return None


def _ref_leaf(ref: Any) -> Optional[str]:
    """Return the last path element of a reference like ``#/qubits/qA2``."""
    if isinstance(ref, str) and "/" in ref:
        return ref.rstrip("/").split("/")[-1]
    return ref if isinstance(ref, str) else None
