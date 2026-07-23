# twinlab-backend

FastAPI service that turns a declarative netlab definition into a running lab:
it runs `netlab create` to generate a containerlab topology, then deploys that
topology through the [containerlab API server](https://containerlab.dev/manual/api-server/).
netlab is only ever used as a generator — never `netlab up`.

## Layout

- `config.py` — environment-sourced settings, loaded as a typed `Result`.
- `services/netlab.py` — `netlab create` adapter (subprocess boundary).
- `services/clab_api.py` — clab-api-server client (login → deploy).
- `services/db.py` — Postgres reachability probe (TCP; schema is empty for now).
- `api/health.py` — liveness (`/api/v1/health`) and readiness (`/api/v1/health/ready`).
- `api/labs.py` — `POST /api/v1/labs`: the netlab→containerlab deploy handoff.

## Configuration

All required, read from the environment (no defaults):

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Postgres DSN |
| `CLAB_API_URL` | Base URL of the clab-api server (no trailing slash) |
| `CLAB_API_USERNAME` | Host/PAM user the clab-api server authenticates |
| `CLAB_API_PASSWORD` | That user's password |

## Development

```sh
uv sync
uv run ruff format . && uv run ruff check .   # format + lint
uv run basedpyright                           # types (strict)
uv run pytest                                 # tests
uv run uvicorn twinlab_backend.app:app --reload
```
