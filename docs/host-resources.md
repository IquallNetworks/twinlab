# Host resources (contract delta 30)

**Status: implemented 2026-08-11.** Closes the scope question the ROADMAP's Phase 6 item 9
parked ("full observability stack vs. lightweight Docker-API stats") in favour of the second
answer, and deliberately leaves the first parked.

## The problem

A lab is a claim on a finite machine, and nothing in the API said what was left. "Is there room
for this lab?" and "what is this lab costing me?" were answerable only by ssh-ing to the host and
running `free`, `df` and `docker stats` by hand. A deploy that failed because the host was
already full looked, from the API, exactly like a deploy that failed for any other reason.

## What was built

Three resources, split by **where the data lives and what it costs to read** — not by subject
matter. Collapsing them into one endpoint would have made the cheap, always-available reading as
slow and as fragile as the expensive one.

| Resource | Source | Cost | Gate |
| --- | --- | --- | --- |
| `GET /host` | the backend's own `/proc`, sampled on a 5s timer | instant | any authenticated user |
| `GET /host/docker` | the Docker Engine API, via the netlab-runner | ~1s+ | any authenticated user |
| `GET /labs/{name}/usage` | clab-api inspect + the runner's per-container stats | ~1s | `lab:read` |

Plus one step: a deploy job records **`host_resources`** as its FIRST step. That step's value is
entirely retrospective — a deploy that went wrong is often a deploy that started on a host with
nothing left, and that is only answerable afterwards if the reading was written down at the time.

## Decisions

**No mount, no privilege, no sidecar for the machine's own figures.** `/proc/stat`,
`/proc/meminfo` and `/proc/loadavg` are not namespaced by Docker, so the backend container reads
the HOST's values there. Verified live: the backend reports `total_bytes: 33563410432` and 8
cores, byte-identical to the host's own `free -b` and `nproc`. The node_exporter convention of
bind-mounting `/proc` at `/host/proc` would have been more explicit but bought nothing here, and
a bind plus a settings key is real surface.

**Disk is the exception**, because `statvfs` genuinely needs the filesystem in the backend's
mount namespace. So `disks` reports only what the backend has: today the host-shared
`LAB_FILES_DIR`, which is already bind-mounted same-path. The daemon's data root is reported by
name (`DockerUsage.root_dir`) but not measured — the backend does not mount `/var/lib/docker`,
and mounting it to read one number was not worth the coupling.

**The runner reads the Docker Engine API, not the `docker` CLI** — a departure from every other
Docker read in that sidecar (`docker image ls` for the catalog). `docker stats` and `docker
system df` emit only human-formatted sizes ("41.2MiB / 62.7GiB", "24.42GB"), so a byte count
parsed back out of them would be invented precision. The API serves raw integers. The cost is a
~20-line stdlib unix-socket HTTP client (`netlab-runner/src/netlab_runner/docker_api.py`); the
alternative was adding httpx to the runner for one GET.

**Unmeasured is not zero.** A stopped container answers `stats` with HTTP 200 and an empty
payload. Reporting that as 0% CPU would claim an idle node where there is no running one, so
every measure on `NodeUsage` is nullable and a non-running node carries none of them — the same
distinction `image_present: None` draws in the device catalog. Its `state` says which case a
reader is looking at.

**`live` reports the MEASURES, not the nodes.** A runner outage still leaves the node rows (they
come from clab-api), so `LabUsage.live=false` with populated rows reads as "unmeasured", never as
"idle". An undeployed lab is `live=false` with no rows, which is data rather than an error: a lab
with no containers legitimately costs nothing.

**`GET /host/docker` 503s rather than degrading.** This breaks the link table's "upstream
failures degrade, never 5xx" rule on purpose: the link table has the stored definition to fall
back on, and this has nothing. Zeros would be a lie, and a nullable-everything shape would be a
worse one.

**Percentages are host-relative.** `NodeUsage.cpu_percent` is Docker's own formula — the
container's share of total system CPU time scaled by core count — so a node pinning two cores
reads 200%. Live-verified against a busy-loop container: 101% on an 8-core host.

**Reclaimable matches what the operator sees.** The four disk rows are computed to agree with
`docker system df` exactly, including its quirks: images charge only their UNSHARED bytes as
reclaimable, and shared build-cache records count toward size but not toward reclaim. Verified
against a live host (images 24.42 GB / 22.47 GB reclaimable, volumes 3.445 GB, build cache
21.13 GB / 9.373 GB — identical on both sides).

**One sample at startup.** `psutil.cpu_percent` measures the window since its own previous call,
so the first call would report a since-boot average. The lifespan primes it with one blocking
0.2s sample before the app serves, and the timer takes over — so `GET /host` is never serving a
fabricated first reading. A failed sample KEEPS the previous snapshot rather than clearing it;
`sampled_at` already tells a reader how stale the value is.

## Deliberately NOT built

**Time series, retention, alerting, dashboards, a Prometheus exposition.** This is an
instantaneous reading. If history is ever picked up, the collector here is what it would read
from, and `services/host_metrics.py` is a serialization boundary away from an exporter.

One thing to settle BEFORE that work starts: **Grafana has been AGPL-3.0 since v8**. It is
OSI-approved but sits awkwardly against the rule that everything Twinlab ships or requires must
be Apache-2.0-compatible. cAdvisor and Prometheus are Apache-2.0; Perses and VictoriaMetrics are
the Apache-licensed dashboard side. That is a maintainer decision, not an implementation detail.

**Per-lab rollups on `GET /labs`.** The fleet list would then pay a per-container sampling cost
on every render. Usage stays opt-in, per lab.

**A capacity gate on deploy.** The `host_resources` step records what the host had; it does not
refuse. Refusing needs a per-lab cost ESTIMATE (which netlab does not give us — node `cpu`/
`memory` are libvirt-only and inert under clab), and a wrong estimate that blocks a deploy is
worse than no estimate at all.
