# Twinlab black-box suite

End-to-end tests that exercise a **live Twinlab stack** through `twinlab-client`, treating the
backend as a black box. The suite pins the **v1.0 target contract** (`docs/twinlab_client_shape.py`
plus the client's docstrings): where the running backend predates the contract rework, the
corresponding tests fail — **a red test against the pre-rework backend is a rework checklist item,
not a suite bug.** Do not soften a test to match today's wire.

## Running

The suite needs a running stack (`docker compose -p twinlab up -d`) and the bootstrap admin
credentials. Configuration is environment-only, all variables required:

```sh
export TWINLAB_URL=http://localhost:5173
export TWINLAB_ADMIN_USERNAME=...   # the backend's BOOTSTRAP_ADMIN_USERNAME
export TWINLAB_ADMIN_PASSWORD=...   # the backend's BOOTSTRAP_ADMIN_PASSWORD

uv run pytest
```

The compose stack publishes only the frontend port (5173), whose dev server proxies `/api/v1` to
the backend — so `TWINLAB_URL` points at the frontend by default. Point it straight at the backend
(`http://localhost:8000`) if you publish that port instead.

A session-scoped gate calls `GET /health/ready` first and aborts the whole run if the backend is
unreachable or degraded — no test runs against a broken stack.

One probe is opt-in: `TWINLAB_TEST_LAST_ADMIN_GUARD=1` enables the last-admin-guard test, which
must aim a deactivation at the bootstrap admin itself — if the backend serves the endpoint but the
guard is missing (a plausible mid-rework state), the "failing" test would lock the stack out. Leave
it unset until the guard is implemented.

## Conventions

- Every created resource uses a unique generated name (no fixed fixtures to collide on); cleanup is
  best-effort so a failed run doesn't cascade, but tests never *depend* on cleanup having worked.
- Tests speak only through `twinlab-client` — no raw HTTP, no peeking into the database or the
  compose stack. If a behavior can't be asserted through the API, that's an API gap to raise.
  One deliberate exception: wire-level security probes (e.g. the API-key secret must never appear
  in a listing payload) use raw HTTP, because the typed client cannot observe extra wire fields.
- Lab-deploying tests are expensive (real containerlab deploys of a tiny two-linux-node lab); they
  live in `test_labs_deploy.py` behind the `deploy` marker — deselect with `-m "not deploy"` for
  the cheap contract run. Everything else (including lab lifecycle, authoring, and grants) works on
  lab *records* only and never deploys.

## Slices

| Module                 | Covers                                                       |
| ---------------------- | ------------------------------------------------------------ |
| `test_health.py`       | liveness, readiness checks                                   |
| `test_auth.py`         | login/me/logout, opaque 401, self password change            |
| `test_api_keys.py`     | key lifecycle, Bearer auth, revocation, deactivation kills keys |
| `test_users.py`        | CRUD, roles, password reset, activate toggle, last-admin guard |
| `test_groups.py`       | CRUD, membership replace, global-only roles, permission inheritance |
| `test_catalog.py`      | role catalog shapes, principals directory                    |
| `test_labs.py`         | create-record/author/visibility/destroy — the lifecycle split |
| `test_lab_authoring.py`| test suites + custom-config templates on a record            |
| `test_grants.py`       | delegation, anti-escalation, group grants, ownership transfer |
| `test_labs_deploy.py`  | (`deploy`) real deploys: lifecycle, mutex, netem, power, terminal, events |

Against the pre-rework backend (bc89daa wire), the health/auth/users/groups/catalog slices run
green except where an approved endpoint is missing; everything lab-record-based is red because the
create/author/deploy lifecycle split is not served yet. That red set *is* the backend-rework
checklist.
