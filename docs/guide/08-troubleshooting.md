# 8. When something fails

Indexed by the code Twinlab gives you, so you can search for what you actually
saw.

## How to read an error

Every failure carries three things:

- a **code**, a stable slug such as `no_definition`. This page indexes them.
- a **message**, written for a person.
- **extras**, sometimes. This is where the underlying tool's own output goes,
  and it is usually where the real answer is.

`netlab_invalid` is the clearest example. The message says netlab refused the
definition. The extras carry netlab's stderr, which says *why*.

### Refused, or failed?

Two different things, and telling them apart saves time.

- **Refused.** Twinlab rejected the request before doing anything. Nothing
  changed. You get an HTTP error immediately.
- **Failed job.** The operation started and could not finish. It may have
  changed something part way, and the job's step log says how far it got.

Long operations — deploy, configure, destroy, suite runs — check what they can
up front and then run as jobs. So a `4xx` from one of those still means
"rejected", and a failed job means "ran, and stopped".

## Before it deploys

**`netlab_invalid`** (422) — netlab refused the definition. Read the extras, not
the message. This is the most common save failure and the answer is always in
netlab's own words.

**`unsupported_directive`** (422) — a legal netlab key that Twinlab deliberately
does not honour. Twinlab refuses it rather than ignoring it quietly. [Page
9](09-definition-reference.md) lists them and says why Twinlab refuses each one.

**`no_definition`** (409) — the lab record exists, and nobody authored it yet.
Build or paste a definition first. This is the expected state of a brand-new
lab.

**`lab_exists`** (409) / **`name_taken`** (409) — the name is in use. Note that
a soft-deleted lab releases its name, so this can also mean a lab you deleted is
still finishing.

**`lab_not_found`** (404) — either the lab does not exist, or you cannot read
it. Twinlab does not distinguish the two on purpose, so a 404 is not proof of
absence.

**`mgmt_subnet_exhausted`** (503) — the management pool has no free `/24` left.
Every lab holds one, including destroyed labs, so this usually means old records
to clean up rather than a pool that is genuinely too small. Delete labs you will
not redeploy, or widen `MGMT_SUBNET_POOL`.

**`mgmt_subnet_taken`** (409), **`mgmt_pool_invalid`** (500) — a collision in
the pool, and a malformed `MGMT_SUBNET_POOL` respectively.

## While deploying

**`image_missing`** — a node image is not on the host and no registry can
supply it. This is a job failure, and it is the pre-flight doing its job: for
`vyos`, `routeros7`, `bird` and `dnsmasq` there is nothing to pull, so failing
now beats failing obscurely later. [Page 1](01-install.md) has the per-platform
table.

**`bridge_conflict`** (409) — two labs whose names share their first ten
characters would use the same host bridge for a LAN segment. Bridge names
truncate the lab name, so netlab itself would cross-wire the two labs. Twinlab
refuses instead. Rename one lab.

**`hostprep_unavailable`** (503) — the host-preparation sidecar is not
answering. Labs that need no host bridges and no kernel modules still deploy, so
this only blocks multi-access topologies.

**`hostprep_failed`** (502), **`kernel_module_missing`** (502) — host
preparation ran and could not do the job. These are host problems, not lab
problems. A missing kernel module means the host does not have it.

**`job_in_flight`** (409) — the lab already has a running job. One operation per
lab, whatever kind. Wait for the Last-operation badge.

**`nodes_not_ready`** (502) — the containers deployed but did not come up in
time.

**`clab_api_error`** (502), **`clab_not_found`** (404), **`upstream_error`**
(502) — the containerlab layer refused or failed. The extras carry its own
message.

**`lab_not_running`** (409) — you asked for something that needs live
containers, and there are none. Destroy is the usual one.

## Configuration and validation

**`config_push_failed`** (502) — the push could not run at all.

**A push that ran and failed on some nodes is not an error.** It is a success
with `config_failed` and per-node detail, because the operation worked and the
finding is the news. Look at the per-node results.

**`validation_failed`** — a config-time suite gated the configure and did not
pass. The lab deployed. Something in it did not converge, and the suite results
say which assertion.

**`template_invalid`** (422), **`invalid_template`** (422) — a suite or
custom-config template that will not render or does not have the right shape.
The message names the suite, the test and the field.

**`exec_failed`** (502) — a command could not run on a node.

## Import

**`unsupported_device`** (422) — no parser for that platform.
[Page 6](06-config-import.md) lists what Twinlab can import, which is a narrower
set than what it can deploy.

**`config_unparseable`** (422) — the parser could not read the configuration.

**`duplicate_node`** (422) — two hostnames collide after truncation to 16
characters. Name one of them yourself in the wizard.

**`wiring_invalid`** (422) — a wiring entry names an unknown node or interface,
wires an interface twice, makes a self-link, uses a loopback or management
endpoint, or has fewer than two endpoints.

**`wiring_conflict`** (422) — a wire's endpoints are in different subnets.
Usually a mask typo. Both wiring errors name the offending entry.

## Permissions and sessions

**`not_authenticated`** (401) — no valid session or API key.

**`invalid_credentials`** (401, 403) — wrong username or password, or a
deactivated account.

**`permission_denied`** (403) — you signed in, and you lack the permission. Page
7 explains which one you need.

**`grant_escalation`** (403) — you tried to grant more than you hold. You cannot
give away access you do not have.

**`role_not_lab_bindable`** (422) — you tried to bind a global-only role to one
lab. [Page 7](07-access.md) has the two role tables.

**`last_admin`** (409) — you cannot deactivate or delete the only active
administrator.

**`invalid_public_key`**, **`unsupported_key_type`**,
**`key_already_registered`** — SSH key registration. Fingerprints are globally
unique, so the last one means somebody already registered that key.

## Jobs that ended by themselves

**`backend_restart`** and **`backend_shutdown`** — the backend stopped while the
job was running, so Twinlab failed the job honestly rather than leaving it
pending forever.

This does not touch the lab containers, which are not part of the stack. A lab
left mid-deploy comes back to a usable state, and a redeploy is the way forward.
[Page 1](01-install.md) covers restarts.

## Problems with no error code

The ones that actually cost time, because nothing tells you anything.

**SSH fails with "Permission denied (publickey)".** If you used `ssh -J` with
`-i`, the jump hop never saw your key, and the message names the wrong host.
[Page 7](07-access.md).

**The lab says `deployed` but nothing works yet.** Containers are up and the job
is still pushing configuration. Wait for the Last-operation badge.
[Page 2](02-first-lab.md).

**A test returns empty output and fails.** The command probably reached the
container's shell instead of the network OS. This is what `mode: cli` is for.
[Page 5](05-test-suites.md).

**Impairment you set is gone.** Setting impairment replaces it. If you set
loss without restating an existing delay, the delay went away.
[Page 4](04-operating.md).

**The activity feed is empty after a reload.** It is session-scoped, with no
server-side history. The jobs list is the durable record.

**A builder control is grey or missing.** Either its key sits in Advanced
properties, or the device cannot do it. The control says which.
[Page 3](03-build-tab.md).

**SSH refuses a node after a redeploy.** New containers mean new host keys.
Clear the stale `known_hosts` entries.

## Getting more detail

In rough order of usefulness:

1. **The job's step log** — how far the operation got, in its own words.
2. **The error's extras** — the real output from netlab or containerlab.
3. **Node logs**, from the Nodes tab.
4. **`curl -s http://localhost:5173/api/v1/health/ready`** — is the stack itself
   healthy?
5. **`docker compose logs backend`** — for a `500 internal_error`, which means a
   bug rather than a usage problem.
