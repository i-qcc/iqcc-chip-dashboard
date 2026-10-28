# IQCC Chip State Dashboard

A kiosk-style web dashboard that presents the **live state of an IQCC quantum
chip** by downloading the latest QuAM `state` / `wiring` from the IQCC cloud and
rendering a rotating set of views (coherence, readout, single- and two-qubit gate
fidelities, native gates, active qubits/pairs).

The dashboard auto-advances through view groups so a subset of the data is shown
neatly on each screen. It periodically re-downloads state from the cloud (default
every 10 minutes) and can display **multiple backends side-by-side**.

## Features

- Backend name, cluster, last calibration time
- QPU grid heatmaps: **T1**, **T2\***, **readout fidelity**, **GEF readout
  fidelity**, **1Q RB fidelity**
- Pair graph: **2Q RB fidelity**, **Bell state fidelity**, CZ gate times
- Native gates and gate times
- Active qubits / active qubit pairs
- **Staleness rule:** metrics that carry a collection timestamp (1Q RB, Bell,
  2Q RB) are hidden when older than the staleness window (default 5 h). T1/T2\*/
  readout/GEF have no timestamp in state and are always shown.
- Auto-rotating kiosk display with progress bar and view indicator dots
- Multiple backends → shown side-by-side on every screen

## Requirements

- Python **3.11+**
- [uv](https://docs.astral.sh/uv/)
- An IQCC cloud API token with access to the desired backend(s)

## Configuration

Copy `.env.example` to `.env` and adjust:

| Variable | Default | Meaning |
|---|---|---|
| `BACKENDS` | `arbel` | Comma-separated backends. >1 → shown side-by-side. |
| `REFRESH_INTERVAL_SECONDS` | `600` | How often to re-download state/wiring. |
| `STALENESS_HOURS` | `5` | Hide timestamped metrics older than this. |
| `ROTATION_SECONDS` | `15` | Dwell time per kiosk view. |
| `IQCC_API_TOKEN` | _(unset)_ | JWT token. If unset, falls back to `~/.config/iqcc_cloud/config.toml`. |
| `IQCC_CLOUD_URL` | _(unset)_ | Optional cloud URL override. |

### Providing the token

Either set `IQCC_API_TOKEN` (recommended for deployment), or configure the
client once locally:

```bash
uv run iqcc-cloud setup   # paste your IQCC API token when prompted
```

## Run locally

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8080
```

Then open <http://localhost:8080>.

Useful endpoints:

- `GET /` — the kiosk dashboard
- `GET /api/data` — processed dashboard JSON for all backends
- `POST /api/refresh` — force an immediate cloud re-download
- `GET /healthz` — liveness probe

## Run with Docker

```bash
docker build -t iqcc-chip-dashboard .
docker run -p 8080:8080 \
  -e BACKENDS=arbel \
  -e IQCC_API_TOKEN="eyJ..." \
  iqcc-chip-dashboard
```

## Deployment notes

Unlike the static `documentation` site, this app needs a **live server** so the
token stays server-side and state is re-downloaded on a timer. Deploy the
container to any host that can run a long-lived process (Cloud Run, a Kubernetes
Deployment, Fly.io, a Cloudflare Container, etc.) and put it behind your normal
ingress / TLS. Provide the API token and backend list via environment variables
/ secrets.

## Project layout

```
app/
  main.py           FastAPI app, background refresh loop, routes
  config.py         Settings from env / .env
  cloud.py          IQCC_Cloud fetch wrapper (state + wiring)
  state_parser.py   QuAM schema extraction, ref resolution, staleness rule
  cache.py          In-memory per-backend cache
  templates/
    dashboard.html  Kiosk shell
  static/
    dashboard.js    Polling, view rotation, SVG QPU-grid rendering
    styles.css      IQCC-branded styling
```
