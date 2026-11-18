# Resource limits: labs that slow down instead of taking the host over

**Status: implemented 2026-11-17; boot waves turned off by default the same day.** Deployment settings and host setup only: the API contract is
unchanged, and so is every lab definition.

## The problem

On a host shared with unrelated workloads, deploying a lab sometimes took the whole machine: the
kernel's OOM killer ended **other** processes. Twinlab set no limit anywhere — not on lab nodes,
not on its own services — so a lab could take memory and CPU until the host ran out.

The maintainer's constraint: **labs should be slowed down, not killed.**

## What was measured

On an 8-core, 31 GiB host, sampling cgroup v2 counters and PSI every 0.5s through deploy and
configure of the 7-node MPLS L3VPN topology (`examples/mpls-l3vpn.yml`, and its IOL sibling).
"Used" is `MemTotal − MemAvailable`, so reclaimable page cache is not counted.

| | VyOS | Cisco IOL |
|---|---|---|
| Memory per node | ~430 MiB peak, ~330 steady | ~225 MiB |
| Lab total | 2.3 GiB, building over ~30s | 1.55 GiB, **in one step within ~10s** |
| Boot CPU | **5–6 of 8 cores for ~30s, 60–75% CPU pressure, load 53** | under half a core |
| netlab-runner peak (config push) | 287 MiB | **797 MiB** |

Three findings shaped the design:

- **The two platforms stress opposite resources.** VyOS boot is a CPU burst (a full init per
  node); IOL allocates its memory at once. A fix for one resource alone would have passed on one
  platform and failed on the other.
- **Running labs are quiet.** After configure both labs sat flat; the spikes are deploy-time.
- **The runner grows with node count on `network_cli` platforms.** Ansible keeps one persistent
  connection process per SSH-configured node, about 110 MiB each on IOL. That memory sits in a
  Twinlab SERVICE, not in a lab, so a limit on lab nodes alone would miss it.

## What was built

### 1. Lab nodes in one cgroup — `LAB_CGROUP_PARENT`

The backend places every node under one parent cgroup by setting containerlab's `cgroup-parent`
(Docker's `--cgroup-parent`) on the generated topology's `defaults` and on every node, and drops
any a kind or group names: the limit is host policy, so a definition must not escape it. netlab
rejects `clab.cgroup-parent` at node, group and device level today, so this guards against its
attribute list growing rather than a known path. On a systemd host the value
is a slice, e.g. `twinlab-labs.slice`; the operator puts the limits on the slice. Unset = Docker's
default placement, i.e. no grouping. A slice name or an absolute cgroup path is validated at load,
since anything else would fail every deploy at the daemon.

This needs **clab-api v0.7.0 or newer** (containerlab ≥ 0.79 added `cgroup-parent`); the stack
moved from v0.5.0 to v0.10.0 for it.

### 2. Twinlab's services in a sibling slice — `SERVICES_CGROUP_PARENT`

Compose places every Twinlab service under the same kind of parent, e.g.
`twinlab-services.slice`. systemd names nest on the dash, so `twinlab-labs.slice` and
`twinlab-services.slice` are both children of `twinlab.slice`, and **one limit on `twinlab.slice`
covers labs and services together**.

### 3. Staggered boot — `BOOT_WAVE_SIZE`, `BOOT_WAVE_INTERVAL_SECONDS` (off by default)

Deploy can give the nodes a containerlab `startup-delay` so they boot in waves, for example 2
nodes 10 seconds apart, in definition order. A node whose definition already sets
`clab.startup-delay` keeps it and takes no slot. It shipped on by default and was turned **off**
the same day, for the reason in [Waves stall every other lab](#waves-stall-every-other-lab):
`BOOT_WAVE_INTERVAL_SECONDS` defaults to 0, and setting it turns waves on. The
deploy job's `clab_deploy_started` step says when a lab boots in waves, so a slower deploy
explains itself.

On the VyOS lab, the stagger turned one 30-second saturation into four short spikes:

| Run | Peak lab CPU | CPU pressure | Deploy → nodes ready |
|---|---|---|---|
| All at once | ~6 cores | 60–75%, sustained | 30s |
| containerlab `max-workers=1` | ~6 cores | ~60%, sustained | 28s |
| **Waves of 2, 10s apart** | ~4.4 cores | spikes of 28–50%, ~5% between | 41s |

`max-workers` was measured and rejected: it serializes container *creation*, but each node starts
booting the moment its container is up, so the boots still overlap.

The cost grows with the lab: the last wave starts `(ceil(N/2) − 1) × 10` seconds after the first,
and clab-api's deploy call stays open meanwhile. Twinlab's deploy timeout is 600s, so with waves
of 2, 10s apart, a lab of roughly 110 nodes would reach it. clab-api's own containerlab timeout
(5 minutes by default with Docker) does not cut a delayed deploy short: one with a single node
delayed 310s succeeded.

#### Waves stall every other lab

Found after shipping, while trying clab-api's newer endpoints. Since v0.7.0 (commit `a24ac2d`,
"serialize containerlab shared link state", the same release that brought containerlab 0.79 and
`cgroup-parent`), clab-api holds **one process-wide lock**, `containerlabMu`, for the whole of a
deploy, destroy, apply, node lifecycle action or save, and the calls that read a lab (inspect,
the lab list, links, interfaces, netem show) take it too. v0.5.0 and v0.6.0 took it only while
constructing containerlab's object. Twinlab uses one clab-api account for every lab, so the lock
is fleet-wide.

A `startup-delay` is slept inside the deploy call, so waves hold that lock for
`(waves − 1) × interval`. Without waves a 3-node FRR deploy call lasted ~0.7s; with two waves it
lasted 10.7s, and the 7-node VyOS lab holds it for ~30s. Measured with a second lab deploying a
node delayed by a fixed time:

| Delay | What the other lab saw |
|---|---|
| 45s | Twinlab's reads hit their 30s clab-api timeout: lab detail and interfaces answered **502**, the list, links and usage came back without live state |
| 60s | inspect, links, interfaces and netem show waited ~57s; a node restart ~59s |
| 310s | a node stop waited 4m40s, then failed with a 500 (`context deadline exceeded`) |

The lock fixes a real race over containerlab's shared link state, and no release has
`cgroup-parent` without it. Waves done outside the deploy call were considered and rejected:
deploying a subset and growing the lab with `apply` would hot-plug links into nodes that have
already started, and a vrnetlab VM (CHR) only sees the interfaces present when its container
starts. So waves stay available for hosts where one lab deploys at a time, and the host
protection that costs nothing is the slice's `CPUWeight`, which makes a boot burst yield to other
work only under contention.

## Host setup

Twinlab cannot create the limits itself: they are host configuration, done once, as root.

```sh
# Limits on the parent slice cover labs AND services. Pick MemoryHigh from what
# the host can spare for Twinlab after its other workloads.
sudo systemctl set-property twinlab.slice MemoryHigh=16G CPUWeight=20
```

Then set, in `.env`:

```sh
LAB_CGROUP_PARENT=twinlab-labs.slice
SERVICES_CGROUP_PARENT=twinlab-services.slice
```

- **`MemoryHigh`, not `MemoryMax`.** Above `MemoryHigh` the kernel reclaims and throttles the
  slice; it never kills. `MemoryMax` is the OOM line, and setting it brings back node kills —
  confined to Twinlab, but kills. Docker's own `--memory` (containerlab's per-node `memory`) is a
  `memory.max` too, which is why per-node limits were not used.
- **`CPUWeight` below the default 100** makes labs yield to other processes under contention
  only; with idle cores they still run at full speed. CPU limits never kill.
- **The host needs swap.** Throttling works by paging lab memory out. Without swap the kernel
  cannot reclaim anonymous memory, and a slice over `MemoryHigh` stalls instead of slowing.
  Check with `swapon --show`.
- `set-property` writes a drop-in under `/etc/systemd/system.control/`, which persists across
  reboots and applies whenever Docker recreates the slice (slices are created on demand when the
  first container lands in them, and vanish when the last one leaves).
  `sudo systemctl revert twinlab.slice` removes it.
- If `systemd-oomd` runs on the host, check that no `ManagedOOM*` policy covers `twinlab.slice`;
  oomd kills whole cgroups under pressure, which is the opposite of the goal.

Verified on the 31 GiB host with `MemoryHigh=1.5G CPUWeight=20` on the labs slice, against a VyOS
lab that wants 2.3 GiB: redeployed from scratch it stayed at ~1.45 GiB with ~950 MiB in swap,
`memory.events` counted ~8,000 throttle events and **0 OOM kills**, all 7 nodes configured, and
its own suites passed (17/17 convergence, 2/2 reachability). Boot took 43s instead of 41s and the
config push 2m25s instead of 2m15s. Applied to an already running lab, the limit pushed it down
within seconds with no restarts.

## Deliberately not done

- **Per-node memory limits.** Every Docker memory limit is a kill line, which the constraint
  rules out.
- **A deploy-time admission check** (refuse a lab that will not fit the slice's headroom). It
  needs a per-device memory estimate, and it would change the API (a new refusal). Parked until
  the slice proves insufficient.
- **The slice on `GET /host`.** Reporting the slice's usage and limit next to the machine's is a
  contract change; parked with the admission check, which would consume it.
- **Capping the runner's Ansible `forks`.** netlab sets none, so Ansible's default of 5 applies.
  The runner's memory is bounded by the services slice now; revisit if config push on large
  `network_cli` labs gets throttled hard.
