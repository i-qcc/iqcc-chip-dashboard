# IQCC Chip State Dashboard

A kiosk-style web dashboard that presents the **live state of an IQCC quantum
chip** by downloading the latest QuAM `state` / `wiring` from the IQCC cloud and
rendering a rotating set of views (coherence, readout, single- and two-qubit gate
fidelities, native gates, active qubits/pairs).

The dashboard auto-advances through view groups so a subset of the data is shown
neatly on each screen. It periodically re-downloads state from the cloud (default
every 10 minutes) and can display **multiple backends side-by-side**.

## Features

- Backend name, last calibration time
- Chip photo in the bottom-left corner when `app/static/chips/<backend>.jpg`
  exists. Add one with
  `uv run --no-project --with opencv-python-headless scripts/enhance_chip_image.py <photo> <backend>`,
  which also boosts fine chip details. Raw photos are kept in `chip_photos/`.
- QPU grid heatmaps: **T1**, **T2\***, **readout fidelity**, **1Q RB
  fidelity**
- Pair graph: **2Q RB fidelity**, CZ gate times
- Native gates and gate times
- Active qubits / active qubit pairs
- **Staleness rule:** metrics that carry a collection timestamp (1Q RB,
  2Q RB) are hidden when older than the staleness window (default 5 h). T1/T2\*/
  readout have no timestamp in state and are always shown.
- Auto-rotating kiosk display with a small countdown to the next view
- Multiple backends → shown side-by-side on every screen

## Requirements

- Python **3.11+**
- [uv](https://docs.astral.sh/uv/)
- An IQCC cloud API token with access to the desired backend(s)

## Configuration

Copy `.env.example` to `.env` and adjust:

| Variable | Default | Meaning |
|---|---|---|
| `BACKENDS` | `arbel` | Comma-separated backends. >1 → shown side-by-side. Leave unset on a kiosk to use `DEFAULT_BACKENDS` from `app/config.py` so a push to `main` can roll out a new default to every kiosk via the launcher's auto-update, with no per-machine edits. |
| `REFRESH_INTERVAL_SECONDS` | `600` | How often to re-download state/wiring. |
| `FETCH_TIMEOUT_SECONDS` | `90` | Max time to wait for one backend's cloud fetch before giving up and retrying next cycle; prevents a stuck/dead network call from freezing updates indefinitely. |
| `STALENESS_HOURS` | `5` | Hide timestamped metrics older than this. |
| `ROTATION_SECONDS` | `10.5` | Dwell time per kiosk view. |
| `IQCC_API_TOKEN_<BACKEND>` | _(unset)_ | Per-backend JWT token, e.g. `IQCC_API_TOKEN_ARBEL`. Tokens are backend-specific. |
| `IQCC_API_TOKEN` | _(unset)_ | Fallback token for backends without their own. If neither is set, falls back to `~/.config/iqcc_cloud/config.toml`. |
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
