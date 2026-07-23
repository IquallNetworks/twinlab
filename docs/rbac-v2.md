# RBAC v2 — scoped roles, groups, and owner-delegated grants

Status: **implemented** (2026-07-23). This is the durable record of the model and the
phased implementation plan. The design below shipped whole; the phased plan at the end
is retained as the map of what was built (and how to verify it).

## Why

RBAC v1 (shipped) is a flat, global model: users hold roles, roles bundle
code-defined permissions, and a permission is a single global question — *does this
user hold X?* — decided without regard to which lab. There is no per-lab
authorization, no ownership enforcement (labs carry `owner_id` but nothing consults
it), and no way to delegate access to a lab. `GET /labs` returns every lab to every
reader; `/events` relays every lab's events to any `lab:read` holder.

v2 makes authorization **scoped**: *does this user hold X **on this lab**?* The model
is Kubernetes-style **RoleBindings** — separate *what a role can do* (permission
bundle) from *where it applies* (scope) from *who holds it* (principal).

## The four concepts

| Concept | v1 → v2 | What it is |
|---|---|---|
| **Principal** | extended | A **user** *or* a **group**. Bindings target either. |
| **Permission** | reclassified | An action, tagged **lab-scoped** or **global-only**. |
| **Role** | extended | A named permission bundle, tagged with the scope(s) it may be bound at. |
| **Binding** | **new** | The join: *(principal) holds (role) at (scope)*, scope = **global** or **a specific lab**. |

## Permissions

Two v1 permissions split, because scoping forces apart questions v1 conflated
(`lab:create` = "make a new lab" is a different question from "change an existing
one"; there is no lab to scope to at creation time).

**Lab-scoped** — bindable per-lab *or* globally; a **global** binding of a lab-scoped
permission means "on every lab, including future ones":

| Permission | Covers | v1 origin |
|---|---|---|
| `lab:read` | list/get, logs, interfaces, events, netem-show, suite/custom-config read | same |
| `lab:edit` | edit definition, redeploy, author test-suites + custom-config | **split from `lab:create`** |
| `lab:configure` | configure, power control, save, netem-set | same |
| `lab:validate` | run a suite on demand | same |
| `lab:terminal` | node console | same |
| `lab:destroy` | teardown / delete | same |
| `lab:grant` | manage bindings on this lab (delegate roles) | **new** — owner-implicit |

**Global-only** — a lab scope is meaningless:

| Permission | Covers | v1 origin |
|---|---|---|
| `lab:create` | create a *brand-new* lab (creator becomes owner) | **new meaning** — split from v1 `lab:create` |
| `user:manage` | user CRUD + role assignment | same |
| `group:manage` | create groups, manage membership | **new** (separate from `user:manage` by decision) |

## Roles

Roles stay **code-defined bundles, re-seeded on startup** (v1 pattern — adding a role
is code + re-seed, no migration). Each role additionally declares the scope(s) it may
be bound at.

**Global-bindable:**

| Role | Permissions | Meaning |
|---|---|---|
| `admin` | *all* | Superuser — everything, everywhere. |
| `global_operator` | `lab:create` + all lab-scoped, global | Read-write + create on **all** labs; no user/group admin. |
| `global_viewer` | `lab:read`, global | View **all** labs. |
| `creator` | `lab:create` only | May create labs; owns what they create, nothing else. |
| `user` | **∅ (no permissions)** | Baseline authenticated principal. **Default role for every new user.** |

`user` exists so a principal can be in the system with **zero inherent access** —
seeing nothing until granted. A plain `user` cannot create labs (`lab:create` is
global-only and they lack it) but can be **made a lab owner** (ownership is the
`owner_id` pointer, not a permission) or **granted per-lab bindings** (directly or via
a group).

**Lab-bindable** (scope = one specific lab):

| Lab role | read | edit | configure | validate | terminal | grant | destroy |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `lab_owner` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `lab_manager` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `lab_operator` | ✅ | — | ✅ | ✅ | ✅ | — | — |
| `lab_viewer` | ✅ | — | — | — | — | — | — |

`lab_manager` holds `grant` but not `destroy`: a manager may bring collaborators onto
the lab but not tear it down — delegation is a management act, destruction isn't.

## Ownership

Labs keep `owner_id` as the **authoritative** owner pointer (display + transfer). The
owner **implicitly** holds the `lab_owner` permission set on their lab — no binding
row — so an owner can never accidentally revoke themselves. Ownership transfer =
reassign `owner_id` (a `lab:grant`-or-admin action). This was chosen over modelling
ownership as an auto-created binding (more uniform, but adds self-revoke foot-guns).

## Anti-escalation rule (delegation safety)

> A delegator may bind a role only if that role's permission set ⊆ the delegator's own
> **effective permissions on that lab**.

Consequences:

- `lab_manager` (no `destroy`) can grant `lab_manager` / `lab_operator` / `lab_viewer`
  but **not** `lab_owner` (which has `destroy`) — no privilege escalation.
- Only `lab_owner` (implicit full set) / `admin` / `global_operator` can mint
  `lab_owner` bindings, i.e. create true co-owners.
- A lab-scoped delegator can never mint a **global** binding — that needs global
  authority (`admin`), so global reach never leaks out of per-lab delegation.

## Authorization algorithm

```
LAB_SCOPED = {read, edit, configure, validate, terminal, destroy, grant}

permissions_for(user, lab) -> set[str]:
    principals = {user} ∪ groups_of(user)
    perms = ∅
    for b in bindings where b.principal ∈ principals:
        if   b.scope == GLOBAL:   perms |= role(b).permissions
        elif b.scope == lab.id:   perms |= (role(b).permissions ∩ LAB_SCOPED)
    if user.id == lab.owner_id:   perms |= LAB_OWNER_PERMS
    return perms

permissions_global(user) -> set[str]:            # global-only checks ignore any lab
    = union of role permissions over the user's + groups' GLOBAL bindings
```

Two guard families replace v1's single `require(...)`:

- `require_global(perm)` — `lab:create`, `user:manage`, `group:manage`.
- `require_lab(perm)` — resolves the lab from the `{name}` path param, then checks
  `permissions_for(user, lab)`. Every per-lab route switches to this.

## Schema

```
groups         (id, name UNIQUE, created_at)
group_members  (group_id, user_id)                       -- M2M; users ∈ 0..N groups
role_bindings  (id,
                principal_type ENUM('user','group'),
                principal_id   UUID,
                role_name      TEXT,                      -- code-defined role
                scope_type     ENUM('global','lab'),
                lab_id         UUID NULL,                 -- set iff scope_type='lab'
                granted_by     UUID, granted_at,          -- audit
                UNIQUE(principal_type, principal_id, role_name, scope_type, lab_id))
```

- **`user_roles` is replaced** by `role_bindings` with `scope_type='global'` — one
  uniform binding mechanism. Migration converts each `user_roles` row to a global
  binding.
- `roles` / `permissions` / `role_permissions` stay; `seed_rbac` also records each
  role's allowed scopes (in code, like the permission mappings).
- `lab_id` FK is `ON DELETE CASCADE` — soft-deleted labs keep the row (record
  survives destroy), hard removal would drop stale bindings.

## Enforcement impact (the sharp edges)

- **`GET /labs` must filter.** v1 returns everything. v2: labs where the caller is
  owner, holds a global `lab:read`, or holds a lab-scoped read binding (direct or via
  a group). A query change, not just a guard.
- **`/events` SSE** currently gates one global `lab:read` and relays *all* labs. It
  must filter the distilled stream to labs the connection's principal can read, or
  scoping leaks through live events. The per-event `lab` field is already parsed, so
  this is a filter over a readable-lab set resolved at connect (re-resolved on a TTL,
  since bindings can change during a long-lived stream).
- **Deploy** (`lab:create`, global) sets `owner_id = caller` — unchanged, but that is
  now what bootstraps the owner's implicit rights.
- **Terminal WS** moves from a global `lab:terminal` check to `require_lab`.
- **Lab detail payload** should carry the caller's effective permission set for that
  lab, so the frontend gates buttons without recomputing.

## New API surface

```
# Groups (group:manage)
GET/POST/DELETE  /groups , /groups/{id}
PUT              /groups/{id}/members            # set membership

# Bindings on a lab (lab:grant on that lab, or admin)
GET    /labs/{name}/grants                       # who has what on this lab
POST   /labs/{name}/grants  {principal, role}    # grant lab-scoped role to user/group
DELETE /labs/{name}/grants/{id}
PUT    /labs/{name}/owner   {user}               # transfer ownership

# Global bindings (user:manage)
GET/POST/DELETE  /grants                          # global role bindings
```

`POST /labs/{name}/grants` enforces the anti-escalation rule: the requested role's
permissions must be ⊆ the caller's effective permissions on the lab, and the role must
be lab-bindable.

---

# Phased implementation plan

Each phase is shippable and gated (ruff + basedpyright strict + pytest for
backend/runner; typecheck + build for frontend). Commit in small logical units per
phase. No phase leaves the app in a broken auth state.

## Phase A — model + resolver (no behavior change yet)

Introduce the data model and the resolver **behind the existing guards**, so the
system still authorizes exactly as v1 until Phase B flips the guards.

- `auth/permissions.py`: add `LAB_EDIT`, `LAB_GRANT`, `GROUP_MANAGE`; redefine
  `lab:create` to the "new lab" meaning; add `LAB_SCOPED` / `GLOBAL_ONLY` sets; add
  the v2 role catalog with per-role allowed scopes; keep v1 names importable during
  transition.
- `db/models.py`: `Group`, `group_members`, `RoleBinding`. Keep `user_roles` for now.
- Migration `0008_rbac_scoped_bindings`: create `groups`, `group_members`,
  `role_bindings`; **backfill** each `user_roles` row → a global `role_bindings` row;
  keep `user_roles` (dropped in Phase E once nothing reads it).
- `auth/service.py`: `permissions_for(user, lab)` + `permissions_global(user)` +
  group resolution. Unit-tested against hand-built fixtures.
- `bootstrap.py`: `seed_rbac` seeds the v2 roles + scopes; every existing user with no
  explicit role gets the `user` role; ensure `admin` still bootstraps.

**Gate:** new resolver unit tests green; existing suite green (guards unchanged).

## Phase B — scoped guards on read/write paths

Flip enforcement to per-lab.

- `auth/dependencies.py`: `require_global(perm)` and `require_lab(perm)` (resolves the
  `{name}` path param → lab → `permissions_for`). 404-vs-403 policy: unknown lab →
  404; known lab without permission → 403.
- `api/labs.py`, `api/terminal.py`: swap each route's `require(...)` for the right
  family. `lab:create` → `require_global`; all per-lab routes → `require_lab`.
- **`GET /labs` filtering** and **lab-detail effective-perms** in the payload.
- **`/events`** readable-lab filtering (resolved at connect, TTL-refreshed).

**Gate:** endpoint tests assert owner/manager/operator/viewer/global_* each see and do
exactly their slice; a `user` with no grants sees no labs.

## Phase C — grants + groups API

- `services/rbac_store.py`: CRUD for bindings and groups (errors-as-values), enforcing
  the anti-escalation rule and lab-bindable/global-bindable constraints.
- `api/grants.py`, `api/groups.py`: the endpoints above.
- `api/users.py`: expose group assignment; default-role handling.
- `PUT /labs/{name}/owner` ownership transfer.

**Gate:** anti-escalation covered (manager can't grant owner; lab delegator can't mint
global; role must be lab-bindable); group membership affects effective permissions.

## Phase D — frontend

- `lib/api.ts`: groups, grants, ownership-transfer clients + zod schemas; lab-detail
  effective-perms.
- Lab detail **"Access"** panel (list/add/remove grants, transfer owner) shown when
  the caller holds `lab:grant`; action buttons gate on the per-lab perm set.
- Admin **Groups** screen (CRUD + membership); `/users` gains group assignment.

**Gate:** `pnpm typecheck` + `pnpm build`; manual walk-through of owner-delegates-to-a-
group, member-of-group-sees-lab.

## Phase E — cleanup

- Drop `user_roles` (migration) once nothing references it.
- Remove the v1 `require(...)` shim and any transition aliases.
- Docs: fold the final surface into CLAUDE.md's backend section.

## Decisions made during implementation

- **404 vs 403** for a lab the caller can't read → **404** (existence hidden); 403
  only once `lab:read` is held. In `require_lab`.
- **Events readable-set TTL** → **30s** (`_READABLE_TTL_SECONDS` in `api/events.py`).
- **Group deletion** → cascade-deletes the group's bindings (`rbac_store.delete_group`).

## Deltas from the original plan (as built)

- **`GET /principals`** (new, `api/directory.py`): a minimal id+name directory of
  users and groups for the grant picker, available to any authenticated caller — a lab
  owner holding only `lab:grant` can't call the `user:manage`/`group:manage` endpoints,
  but still needs to name a grantee.
- **Ownership transfer is stricter than "lab:grant-or-admin"**: it requires the caller
  to be **owner-equivalent** (hold the full `lab_owner` set on the lab), matching the
  anti-escalation rule for granting `lab_owner` — otherwise a manager could bypass it.
- **`LabSummary` also carries `permissions`** (not just `LabDetail`), so the labs list
  gates per-row actions correctly; resolved in one grant load via
  `effective_permissions_bulk`.
- **The `roles`/`permissions` DB tables are retained but vestigial** — seeded from the
  catalog for possible introspection; authorization resolves from the code catalog, and
  role listings are served from it via `GET /roles`.
- **One migration only** (`0008`): user global roles were converted to bindings and
  `user_roles` dropped in the same step (the plan's Phase A/E split was collapsed since
  everything shipped together).

## Migration note (existing deployments)

Users bound to a pre-v2 role that no longer exists in the catalog (`operator`,
`viewer`) keep a global binding to that name, which now resolves to **no permissions**
(unknown roles are inert). Re-assign them to a v2 role after upgrading. Fresh installs
and the bootstrap `admin` are unaffected.
