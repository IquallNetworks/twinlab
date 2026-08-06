# twinlab-backend

The FastAPI service behind Twinlab: it owns the lab lifecycle, the durable lab records, jobs,
RBAC, validation, config import and the template library, and serves the whole `/api/v1` surface
the frontend and `twinlab-client` speak to.

Turning a definition into a running lab is a three-way handoff — the backend runs `netlab create`
to generate the containerlab topology, deploys that topology through the
[clab-api server](https://containerlab.dev/manual/api-server/) (piped inline as `topologyContent`),
and delegates config push to the netlab-runner sidecar. **netlab is only ever a generator and
configurator — never `netlab up`**, which would `sudo` and fuse deploy and config into one opaque
step.

The API contract is `../docs/twinlab_client_shape.py`, enforced against a live stack by
`../blackbox`.

## Layout

```
api/          the HTTP surface, one module per resource group
auth/         credentials, sessions, API keys, SSH keys, RBAC catalog + resolver
db/           SQLAlchemy models and session plumbing
services/     everything the routes delegate to
migrations/   Alembic (run by the container entrypoint)
```

| Module | What it owns |
| --- | --- |
| `models.py` | The wire shapes — every request and response body, and the name rules that gate them. |
| `api_errors.py` | The one error envelope `{code, message, extras}` plus the handlers that wrap FastAPI validation and framework errors in it. Every non-2xx wears it. |
| `result.py` | `Ok`/`Err` — errors are values here; `try`/`except` lives only in boundary adapters. |
| `config.py` | Environment-sourced settings, loaded as a typed `Result` (not pydantic-settings). |
| `api/labs.py` | The lifecycle (create → author → deploy), runtime control, netem, batch actions, links, interfaces, facts, layout, suites and custom config. |
| `api/jobs.py`, `api/events.py`, `api/terminal.py` | Job polling and the cross-lab listing; the SSE stream; the node-terminal WebSocket. |
| `api/auth.py`, `api/users.py`, `api/groups.py`, `api/grants.py`, `api/roles.py`, `api/directory.py` | Credentials and the RBAC surface. |
| `api/internal.py` | `GET /internal/ssh/authorized-keys` — deliberately **not** under `/api/v1`, so the frontend proxy cannot expose it. The jump host's `AuthorizedKeysCommand` calls it per connection. |
| `api/catalog.py`, `api/templates.py`, `api/imports.py` | The device catalog, the template library, and config import. |
| `services/netlab.py` | The `netlab create` subprocess boundary. |
| `services/clab_api.py` | The clab-api client — every authenticated call goes through one `_authed` helper, with the retry policy for that server's per-lab netem mutex and transient 5xx. |
| `services/runner_client.py`, `services/host_prep.py` | The netlab-runner and hostprep sidecars. |
| `services/lab_store.py`, `services/job_store.py`, `services/job_events.py` | Lab records; the jobs table (whose partial unique index *is* the per-lab operation mutex) and its startup/shutdown orphan sweeps; the lossy in-process job-event broker. |
| `services/validation.py` | The test-suite pipeline: render → execute → parse → assert. |
| `services/fact_namespace.py` | The fact namespace partition — a promised core plus per-object `_extras`, applied at every serve boundary. |
| `services/configimport/` | The config-import factory: per-platform parsers, declared wiring, skeleton emission, the interface map, carry rewrite and quarantine. |
| `services/device_catalog.py`, `services/network_templates.py`, `services/template_store.py` | The supported-device catalog and both template collections. |
| `services/mgmt_subnet.py` | Per-lab management `/24` allocation from the pool. |

Several modules mirror data from the installed netlab (the module-support matrix, default images,
device kernel modules). Each has a **drift-guard test** that fails when the installed netlab
disagrees — that is what keeps the mirror honest across upgrades.

## Configuration

Read from the environment. Required — startup fails with a typed error if any is missing:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres DSN |
| `CLAB_API_URL` | Base URL of the clab-api server (no trailing slash) |
| `CLAB_API_USERNAME` / `CLAB_API_PASSWORD` | Host/PAM user the clab-api server authenticates |
| `NETLAB_RUNNER_URL` | Base URL of the config-push sidecar |
| `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` | Admin created on first startup, only while the users table is empty |

Optional, each defaulted in `config.py` next to the reason for its value:

| Variable | Purpose |
| --- | --- |
| `SESSION_COOKIE_NAME` / `SESSION_TTL_HOURS` / `SESSION_COOKIE_SECURE` | Login session cookie (`secure` defaults true — set it false for local HTTP dev) |
| `MGMT_SUBNET_POOL` | Pool the per-lab management `/24`s are carved from |
| `SSH_JUMP_TOKEN` / `SSH_JUMP_ADDRESS` | The jump host's shared secret (unset ⇒ `/internal` 404s) and the externally reachable `host:port` advertised on `GET /ssh-access` |
| `HOSTPREP_URL` / `HOSTPREP_TOKEN` | The host-preparation sidecar. One feature, so setting only one of them fails loading rather than half-enabling it |
| `LAB_FILES_DIR` | Host-shared directory for netlab's generated `node_files/`. **Same-path invariant**: the identical absolute path on the host and inside both this container and clab-api. Unset keeps the old bind-stripping behavior |

## Development

```sh
uv sync
uv run ruff format . && uv run ruff check .   # format + lint
uv run basedpyright                           # types (strict; warnings are errors)
uv run pytest                                 # tests
uv run uvicorn twinlab_backend.app:app --reload
```

All four are gates — "done" means every one is green. `typings/` holds local stubs that give the
untyped third-party imports (napalm, textfsm, ntc-templates, netutils) precise types rather than
suppressions.

Migrations are Alembic under `migrations/`; the container runs `alembic upgrade head` before
starting the app.

After a change here, run `../blackbox` against a live stack. A new red there is either a
regression or a contract change — and contract changes go through review.
