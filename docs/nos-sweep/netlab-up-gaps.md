# `netlab up` / `netlab down` parity gaps — full audit (2026-08-04)

Analysis input to ROADMAP item 17, strand 17.2. Supersedes the 2026-07-31 three-gap list: those
three are confirmed and still real, but the list was incomplete — the inline-deploy bind loss is
wider than "FRR config scripts" (it silently breaks `/etc/hosts` on the *supported* `linux`
device today), and three smaller silent-ignore surfaces (CLI/plugin up-hooks, OVS bridge type,
topology `message`) were not on it. One factual correction to the old ROADMAP 17.2 text is
flagged under gap 1. Decisions are the maintainer's; options are listed, none chosen here.

Installed netlab: **networklab 26.7** in BOTH venvs (`backend/.venv` and `netlab-runner/.venv`,
`lib/python3.13/site-packages/netsim/`; `netlab-runner/uv.lock` pins the same sdist). All
`netsim/` file:line references below are into
`netlab-runner/.venv/lib/python3.13/site-packages/netsim/`.

---

## Gap 1 — `tc:` link/interface impairment silently dropped

**(a) What netlab does.**
- Schema: `tc` is a first-class **link attribute** — `defaults/attributes.yml:71-78`:
  `delay: time`, `jitter: time` (milliseconds when rendered), `loss`, `corrupt`, `duplicate`,
  `reorder` (float 0–100 %), `rate` (int ≥ 1, passed verbatim to `tc … netem rate`).
  **Seven knobs.**
- Placement: link-level `tc` propagates to every attached interface (link attributes propagate
  unless listed in `link_no_propagate` — `defaults/attributes.yml:88` lists only
  `prefix, interfaces, gateway`; propagation at `augment/links.py:272-274, 913-925`). A
  per-endpoint `<node>.tc` on a link entry lands on that one interface. Either way the expanded
  topology's node interfaces carry `intf.tc`.
- Application: `netlab up` applies it **after container start** — `cli/up.py:396-397` (gated by
  `defaults.tc.enable`, default true), which iterates node interfaces with `tc`
  (`providers/__init__.py:368-373`) and calls the clab provider's `set_tc`
  (`providers/clab/__init__.py:141-153`):
  `sudo ip netns exec <container> tc qdisc add|change dev <clab-ifname> root netem …` via
  `tc_netem_set` (`providers/__init__.py:395-433`; delay+jitter always rendered together as
  `delay Xms Yms`).
- Runtime counterpart: a whole `netlab tc` CLI exists (`cli/tc.py` — enable/disable/show/set
  against the snapshot), i.e. netlab treats topology `tc:` as a *baseline* the CLI can later
  override.

**(b) What Twinlab does.** Silently dropped. The PUT's dry `netlab create` validates `tc:` as
legal schema; the deploy job (`backend/src/twinlab_backend/api/labs.py:973-1035`) never reads it;
no other backend reference (grepped). The builder's extras-passthrough even round-trips `tc:`
faithfully as link extras — it survives editing and does nothing. Twinlab's own netem surface is
the per-interface netem routes + the delta-24 batch, REPLACE semantics, applied through clab-api
(`backend/src/twinlab_backend/models.py:563-582`,
`backend/src/twinlab_backend/services/clab_api.py:104-115`).

**Correction to the pre-audit ROADMAP 17.2:** it said tc is "the same seven knobs as our netem
API". Not so: netlab has **seven** (delay, jitter, loss, corrupt, duplicate, reorder, rate);
Twinlab's netem API has **five** (delay, jitter, loss, rate, corruption — clab-api's netem set
has no duplicate/reorder). `duplicate` and `reorder` are **not expressible** over the existing
clab-api netem path.

**(c) Blast radius.** Any definition carrying `tc:` deploys with no impairment —
definition-is-source-of-truth violated with zero signal. Affects all devices equally (host-side
qdisc). Also note: netem qdiscs die with the container, so a node `restart` (Twinlab power verb)
silently loses whatever impairment was applied — a `tc:`-as-baseline feature would need
reapply-on-restart to stay truthful, which is exactly the baseline-vs-runtime question.

**(d) Options.**
- **Honor at deploy**: after `mark_deployed`, apply impairments derived from the expanded
  topology (the raw `node_facts` already carry `intf.tc`; the typed `_ExpandedLinkInterface` in
  `backend/src/twinlab_backend/services/netlab.py:102-108` would need the field) through the
  existing netem executor — attractive (impairment reproducible-by-definition), but forces the
  **baseline-vs-runtime design**: does netem GET distinguish baseline from override? does
  clearing an interface revert to baseline or to clean? is baseline reapplied on node restart
  and redeploy? Same question as the shelved scenario item's snapshot-restore cleanup (ROADMAP
  16.5) — settle once for both. Sub-decision: `duplicate`/`reorder` can't ride clab-api netem —
  support 5/7 and reject the other two loudly, or add a second channel (the runner already has
  the netns privileges to run raw `tc`, at the cost of a second impairment path to keep
  coherent).
- **Reject at PUT** (422 or a named warning): cheapest honest option; loses the reproducibility
  win.
- **Strip-with-warning**: keeps deploys working, still not source-of-truth.
- **Out of scope**: hard to defend given the netem API already exists.

---

## Gap 2 — `tools:` silently dropped

**(a) What netlab does.** `netlab up` starts side containers per topology `tools:` entry —
`cli/up.py:303-343` (`start_external_tools`), commands resolved from `netsim/tools/*.yml`
(`cli/external_commands.py:243-268, 294-321`). Shipped tools: **graphite, suzieq, nuts, nso,
edgeshark**. Each is a `docker run` attached to the lab's mgmt docker network
(`{sys.docker_net}` = `--network=<addressing.mgmt._network>`, `external_commands.py:301-302`),
several mounting **workdir files that `netlab create` generates** (graphite's
`graphite-default.json`, suzieq's `./suzieq` inventory, nuts' `./nuts`). `netlab down` stops
them (`cli/down.py:147-157`) and `--cleanup` removes their data (`down.py:89-95`).

**(b) What Twinlab does.** Silently dropped. Valid netlab schema, so the PUT's dry create
accepts it; nothing in the backend references tools (grepped); the lab deploys without them and
nothing says so.

**(c) Blast radius.** Users importing existing netlab topologies that rely on
graphite/suzieq/edgeshark observability get nothing, silently. Supporting them is per-tool work:
config-file generation lives in the create workdir Twinlab throws away, lifecycle must ride
deploy/destroy, and each tool has its own port publishing and volumes. The mgmt-network
attachment at least maps cleanly onto Twinlab's per-lab `_network`.

**(d) Options.** Reject at PUT (422, named slug) · strip-with-warning (deploy proceeds, warning
on the job/lab) · declare out-of-scope in docs (the standing recommendation — but *explicitly*,
i.e. paired with one of the first two so it is never silent) · support (heavy, per-tool
integrations; if ever, graphite/suzieq first as pure side containers).

---

## Gap 3 — no pre-flight image check

**(a) What netlab does.** `cli/up.py:378` → `providers.validate_images`
(`providers/__init__.py:321-325`) → clab `validate_node_image`
(`providers/clab/__init__.py:113-121`) → `utils.validate_docker_image`
(`providers/clab/utils.py:36-67`): `docker image ls` per image; missing with **no build recipe**
→ friendly *info* ("We'll try to download…" — docker pulls at deploy); missing with a **build
recipe** (`build:` in device clab data, e.g. netlab/bird) → **hard error** with
`netlab clab build <device>` hints. The nuance: netlab only hard-blocks images that *cannot* be
pulled.

**(b) What Twinlab does.** No deploy-time check. The deploy job pipes `topologyContent` and a
missing image surfaces as a clab-api failure → job error `502 upstream_error` carrying
clab-api's message (`backend/src/twinlab_backend/api/labs.py:1012-1018, 1944-1946`) — late and
opaque. The **visibility** half is already solved since delta 18: the runner serves
`GET /images` (`netlab-runner/src/netlab_runner/app.py:71-77`, `runner.py:153-166`) and the
backend owns matching policy (untagged → `:latest`,
`backend/src/twinlab_backend/services/device_catalog.py:87-90`), feeding the catalog's
best-effort `image_present`/`live`.

**(c) Blast radius.** Every new NOS the sweep adds multiplies this; proprietary images (IOL and
kin) are never pullable, so today their absence is exactly the opaque-502 case.

**(d) Options** (only deploy-time semantics remain undecided): hard-block at submit when the
image is known absent — simple, but *wrong* for publicly pullable images unless paired with
pullability knowledge (the catalog could carry "local-only" per device — the sweep is the
natural source) · warn-and-continue: pre-check, attach a warning, let clab-api try — opaque
failure becomes "we told you first" · degraded check (runner unreachable) must not block —
mirror the catalog's honesty. Out-of-scope is not really available given "never silent" and the
sweep's needs.

---

## Gap 4 — inline deploy loses netlab's generated file artifacts (NEW scope; supersedes "FRR only")

**(a) What netlab does.** `netlab create` writes per-node files under `node_files/` and wires
them into containers via clab **binds**: device `config_templates` become binds
(`providers/clab/binds.py:51-78` — `node_files/<node>/<src>` or shared
`node_files/-shared-<src>`), daemon `daemon_config`/`_node_config` files join the same list
(`binds.py:28-46`), and `startup`-mode templates would set
`clab.startup-config: node_files/<node>/startup.partial.config` (`providers/clab/configs.py:69-72`).
At config time, `sh`-mode entries are **executed inside the container from the bind-mounted
path** (`configs.py:100-146`: `docker exec <c> /etc/config/NN-<mod>.sh`), `cp_sh` is `docker cp`
first, `ns` runs host-side via `ip netns exec`.

**(b) What Twinlab does.** Deploys inline (`topologyContent`) and ships no workdir, so the
backend strips every bind whose source starts `node_files/`
(`backend/src/twinlab_backend/services/netlab.py:44, 507-540`); absolute binds are kept. The
strip touches **only `binds`** — a relative `startup-config` path would pass through
unsatisfiable (no shipped device triggers it by default today, but it's a latent hole worth a
guard).

**(c) Blast radius — precise per-device consequences (netlab 26.7):**

| Device / class | Artifact lost | Effect under Twinlab |
|---|---|---|
| **vyos** (supported) | none — `/lib/modules:/lib/modules` is absolute (`devices/vyos.yml:104-105`), kept | works (clab-api is host-coupled) |
| **cisco IOL** (supported) | `ifstate` bind (`devices/iol.yml:15-16`) stripped | safe — kind regenerates (proven) |
| **linux** (supported) | shared `/etc/hosts` template (`devices/linux.yml:67-68`) stripped | **lab nodes lose the all-nodes /etc/hosts — inter-node resolution *by name* silently absent.** Live today on a supported device; previously unrecorded (blackbox uses IPs) |
| **frr** | `sh`-mode config scripts (`devices/frr.yml:39,44`) **and** the `daemons` file bind (`frr.yml:50-51`) stripped | daemons never enabled *and* config push impossible — the known casualty is actually two distinct losses; plus the hosts file |
| **crpd, csrx, iosxr** | `netlab-config.sh:sh` binds (`crpd.yml:32-34`, `csrx.yml:33-35`, `iosxr.yml:28-29`) | same class as FRR — config push cannot work inline |
| **cumulus** | `/etc/network/interfaces` + hosts binds (`cumulus.yml:20-22`) | initial interface config lost |
| **srlinux** | hosts bind (`srlinux.yml:58-59`) | name resolution only — matches the nokia/ finding that SR Linux works |
| **all daemons** (bird, dnsmasq, kind, netscaler — `netsim/daemons/`) | entire config delivery is `daemon_config` file binds + `sh` mode | broken by construction inline |
| **eos** (opt-in `sh`) | default config is Ansible | unaffected by default |
| `config_mode: [startup]` devices (arubacx, dellos10, ios, junos) | would use relative `startup-config` if ever driven that way | latent — see (b) |

`ns`-mode is already handled by the runner's netns config path; `cp_sh` survives inline. This
table is the critical input to the NOS sweep: any device whose clab config path is bind-delivered
`sh` scripts or daemon config files **cannot** be supported without a file channel.

**(d) Options.**
- **A file-shipping channel**: the runner already regenerates `node_files/` in its own workdir
  and holds the docker socket — a pre-configure `docker cp` of each stripped bind target
  (generalizing netlab's own `cp_sh`) would restore most of this class without touching
  clab-api. Cost: a second config-delivery mechanism to keep faithful.
- **Targeted fix for `/etc/hosts` only**: small, self-contained, benefits supported devices
  today (content derivable from the expanded topology; push via runner exec/cp post-deploy).
- **Reject/flag at the catalog boundary**: the sweep's supported-matrix marks bind-dependent
  devices unsupported; extend the same honesty to PUT/deploy warnings.
- **Out-of-scope declaration** per device class (daemons especially).
- Independent small guard either way: strip (or refuse) a relative `startup-config` in
  `strip_generated_binds` so it can never leak inline.

---

## Gap 5 — up/down CLI hooks and plugin hooks never run (NEW)

**(a)** `netlab up`/`down` run registered hooks at every phase: shell hooks from
`defaults.netlab.up.<hook>` / `defaults.netlab.down.<hook>` and plugin
`pre_shell_*`/`post_shell_*` hooks (`cli/_hooks.py:25-68`; call sites `cli/up.py:368, 388, 399`,
`cli/down.py:169, 187, 212, 219`). **(b)** Topology *transformation* plugin hooks DO run (inside
`netlab create`); the up/down CLI-time hooks never run. Silent. **(c)** Niche — and the flip
side is that arbitrary shell from a stored definition executing on the backend host would be a
security hole in a multi-user server, so *not* running them is almost certainly correct; the
issue is only silence. **(d)** Reject the keys at PUT · warn and ignore · document out-of-scope
with the security rationale. "Support" is realistically off the table for shell hooks.

---

## Gap 6 — OVS bridge type ignored (NEW)

**(a)** `defaults.providers.clab.bridge_type: ovs-bridge` (default `bridge`,
`providers/clab.yml:22`) switches multi-access-link bridge creation to Open vSwitch
(`providers/clab/labops.py:15-16, 65-80`; `netlab down` destroys them
`clab/__init__.py:62-68`). **(b)** hostprep creates **Linux bridges only**
(`hostprep/src/hostprep/host.py`); a definition selecting `ovs-bridge` validates, deploys, and
silently gets Linux bridges. **(c)** Small: hostprep's `group_fwd_mask 65528` already covers
LACP/LLDP/STP forwarding for common cases; behavior differs only at the margins (IGMP snooping,
OpenFlow experiments). **(d)** Reject the key at PUT · warn-and-proceed · out-of-scope
declaration. Supporting OVS in hostprep means shipping and privileging `ovs-vsctl` in the
sidecar — real cost for marginal gain.

---

## Gap 7 — topology `message` never surfaced (NEW, minor)

**(a)** After initial config, `netlab up` prints the topology's `message` (`cli/up.py:263-265`)
— lab authors use it for "how to use this lab" notes. **(b)** Twinlab drops it silently.
**(c)** Cosmetic; matters most for imported community topologies and the template library.
**(d)** Surface it on `LabDetail`/deploy-job result · ignore-and-document. Rejecting seems
disproportionate.

---

## `netlab down` specifically — Twinlab's destroy path vs `cli/down.py`

Walked `run` → `stop_all` → `stop_provider_lab` end to end
(`cli/down.py:189-225, 159-187, 100-116`):

- **Stop external tools** (`down.py:147-157`) + tool data cleanup (`89-95`) — the down-side of
  gap 2; nothing else.
- **clab workload stop**: `containerlab destroy --cleanup` ↔ clab-api destroy — covered.
- **Bridge teardown**: clab `post_stop_lab` (`providers/clab/__init__.py:62-68`) ↔ hostprep
  delete at destroy with confirmed-gone / claim-retained-on-failure semantics
  (`backend/src/twinlab_backend/api/labs.py:780-801`) — covered, and Twinlab is strictly *safer*
  (netlab never checks attached ports).
- **Kernel modules**: neither side unloads — parity by design.
- **`--cleanup` file removal, snapshot/lock/status-registry cleanup** — N/A; Twinlab's workdirs
  are ephemeral tempdirs and lab state is the DB.
- **down CLI hooks** — gap 5.

**`netlab down` adds no gap beyond 2 and 5.**

---

## Walked and confirmed covered / not applicable

- **Host bridges + kernel modules** (clab `pre_start_lab`, `providers/clab/__init__.py:53-60`;
  `labops.py:96-148`): hostprep + backend policy. `_host_bridges`
  (`services/netlab.py:251-267`) matches netlab's own filter (`providers/clab/utils.py:14-20`,
  incl. `external_bridge`); the kmods mirror (`netlab.py:225-239`) matches
  `providers/clab.yml:24-29` + per-device `clab.kmods`, with a drift-guard test. Sweep note:
  widening the device set requires extending `DEVICE_KMODS` *and* hostprep's fixed module
  allowlist together — the drift-guard only catches the netlab side.
- **Provider probes** (`cli/up.py:190-197`; containerlab ≥ 0.75.0, `providers/clab.yml:15-19`):
  the executor is the clab-api container — a compose-stack ops concern, not a per-deploy check;
  failures land in the same `upstream_error` bucket as gap 3.
- **`process_config_sw_check`** (`cli/up.py:370-371`): also runs inside `netlab initial`
  (`cli/initial/deploy.py:166`) — the runner covers it.
- **Initial config deploy**: the runner — including `ns`-mode host-netns scripts — modulo gap
  4's `sh`-mode losses.
- **`clab.exec` / `netlab_start_exec` startup delays** (`providers/clab/utils.py:22-33`): live
  IN the topology content, so inline deploy preserves them.
- **mgmt-IP validation** (`providers/__init__.py:330-363`): runs during `netlab create` —
  Twinlab runs it.
- **`--reload-config`, `--fast-config`, `--snapshot`, `--dry-run`, `--validate`**: CLI
  conveniences; save/reload has a clab-api counterpart (`POST /labs/{name}/save`), validation is
  Twinlab's own suite machinery — deliberate replacements, not gaps.
- **Directory locks, lab-status registry, usage stats** (`up.py:355-362, 380-385, 410-420`):
  replaced by the DB, the per-lab job mutex, and `bridge_conflict`; `HOME=<workdir>` in the
  create subprocess isolates the stats write.
- **Multi-provider topologies** (`up.py:391-394`, libvirt secondary): clab-only by design. A
  `provider: libvirt` definition fails *loudly* today (no `clab.yml` output → "netlab create
  output missing"), and libvirt cannot be secondary under clab in netlab's ordering — no silent
  partial deploy exists.

## Completeness statement

`netsim/cli/up.py` (`run_up`, every call in lines 348–433) and `netsim/cli/down.py` were walked
line by line against the installed netlab 26.7, then every provider hook the clab provider
actually implements (`providers/clab/__init__.py` defines `pre_start_lab`, `post_stop_lab`,
`post_configuration_create`, `node_post_transform`, `validate_node_image`,
`deploy_node_config`, `set_tc`; the `_Provider` base's remaining hooks are empty stubs —
`providers/__init__.py:133-146`), the tools machinery in `cli/external_commands.py`, the tc
machinery (`providers/__init__.py:368-433`, `cli/tc.py`, schema in `defaults/attributes.yml`),
the binds/configs modules (`providers/clab/binds.py`, `configs.py`, `utils.py`, `labops.py`),
and a grep of every shipped device and daemon default (`netsim/devices/*.yml`,
`netsim/daemons/*.yml`) for binds / config_templates / config modes / kmods / start-exec. On the
Twinlab side: the netlab adapter in full (`services/netlab.py`), the deploy job and destroy path
(`api/labs.py`), the hostprep sidecar surface, and the runner's endpoints. Every statement in
`run_up`/`run` is accounted for above as either a numbered gap, a covered item, or an explicit
N/A — so within what netlab 26.7's up/down actually execute for the clab provider, this list is
believed exhaustive.
