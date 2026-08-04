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
  A second, same-spirit exception: the SSH-jump slices shell out to the host's OpenSSH client
  (`ssh-keygen`, `ssh`) because the feature's contract IS a standard ssh connection — the host
  needs OpenSSH installed.
- Lab-deploying tests are expensive (real containerlab deploys of a tiny two-linux-node lab); they
  live in `test_labs_deploy.py` behind the `deploy` marker — deselect with `-m "not deploy"` for
  the cheap contract run. Everything else (including lab lifecycle, authoring, and grants) works on
  lab *records* only and never deploys.
- One deviation from client-only: the LAN test asserts the host bridge's existence (and its
  removal after destroy) by reading `/sys/class/net` directly — bridge leak-checking is host
  kernel state invisible through the API. It therefore assumes the suite runs on the stack's
  host, which the `deploy` marker already implies.

## Slices

| Module                 | Covers                                                       |
| ---------------------- | ------------------------------------------------------------ |
| `test_health.py`       | liveness, readiness checks                                   |
| `test_auth.py`         | login/me/logout, opaque 401, self password change            |
| `test_api_keys.py`     | key lifecycle, Bearer auth, revocation, deactivation kills keys |
| `test_users.py`        | CRUD, roles, password reset, activate toggle, last-admin guard |
| `test_groups.py`       | CRUD, membership replace, global-only roles, permission inheritance |
| `test_catalog.py`      | role catalog shapes, principals directory, device catalog    |
| `test_labs.py`         | create-record/author/visibility/destroy — the lifecycle split; batch-action 422s + gates |
| `test_lab_authoring.py`| test suites, custom-config templates + topology layout on a record |
| `test_jobs.py`         | async jobs without deploys: remove-job pollable after delete, hiding, history |
| `test_ssh_keys.py`     | SSH public-key records: validation, global fingerprint uniqueness, jump coordinates |
| `test_grants.py`       | delegation, anti-escalation, group grants, ownership transfer |
| `test_templates.py`    | template library: both collections, publish toggle, template:manage split |
| `test_imports.py`      | (+`deploy`) config import: wiring rules, factory output, fidelity diff |
| `test_labs_deploy.py`  | (`deploy`) real deploys as jobs: lifecycle, submit-time mutex, netem, batch actions, power, terminal, events |
| `test_ssh_jump.py`     | (`deploy`) real `ssh` probes through the jump host: permitopen scoping, revocation, fail-safe |

The backend implements the full v1.0 contract (twenty-four deltas — delta 12 made the four long
operations async jobs, which the deploy slice consumes via submit + `wait_job`; delta 13 added the
SSH jump host the ssh slices exercise; delta 14 the link table; deltas 15/16 the cross-lab job
listing and the stream's job events, both covered in the cheap slice; delta 17 reworked test
suites into the render/execute/parse/assert pipeline — the authoring slice covers the schema,
facts endpoint and template validation, and the deploy slice runs a fact-templated ping whose
RENDERED command is asserted against the link table; delta 18 the device catalog, covered in the
catalog slice; delta 19 the deployed-definition snapshot + shared topology layout — the
authoring slice covers the layout roundtrip/replace/permission gate, and the deploy lifecycle
asserts the drift flag across deploy → edit → redeploy → destroy; delta 20 group styles on
the layout — roundtrip, whole-resource replace, hex-pinned color 422; delta 21 the template
library — the templates slice covers both collections, the publish-toggle lifecycle incl. the
live view and soft-delete withdrawal, fragment structural 422s, and the template:manage split;
delta 22 config import — the imports slice covers the catalog's config_import flags, the
factory's output shape and 422 slugs, the permission split, config-diff pre-checks, the
composed lifecycle (custom config BEFORE the definition PUT — its dry create validates
`config:` refs against the stored fileset), and the deploy-marked flagship round trip: import
two VyOS configs → compose → deploy with configure (the carried OSPF applies) → the fidelity
diff reports zero missing lines with the quarantined NTP counted; delta 23 made that wiring
EXPLICIT and required — the slice covers the suggestion-as-advice round trip, an
all-unnumbered wire becoming a `prefix: false` L2 link, a mixed wire suppressing its
unaddressed endpoint, and the wiring_invalid/wiring_conflict 422s; delta 24 batch runtime
actions — the cheap slice covers the up-front 422s (nothing executes) and the
permission/existence split, the deploy slice one batch shaping BOTH endpoints of a link
alongside a deliberately unknown node, proving the batch still RUNS with only that item
ok=false),
and the suite is
**entirely green** (136/136 with the `deploy` marker and `TWINLAB_TEST_LAST_ADMIN_GUARD=1`). It is
the contract's enforcement: run it after backend changes; a new red means either a regression or a
contract change that must go through review.
