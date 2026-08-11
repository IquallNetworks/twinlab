# Twinlab

Twinlab generates **reproducible simulated network topologies from a declarative definition**. It
is a layer over [Containerlab](https://containerlab.dev/), driven through
[netlab](https://netlab.tools/), that lets you describe nodes, links, services and the tests that
validate them declaratively, then deploy that description as a running lab — a digital twin for
validating configurations, orchestration workflows, service provisioning and operational
procedures before they touch production.

The definition is the sole source of truth for a lab. The same definition always produces the same
environment.

```
  frontend (React) ─┐
                    ├─ /api/v1 ─► backend ─┬─► netlab create ─► containerlab topology
  twinlab-client ───┘                      │
                                           ├─► clab-api      ─► lab containers (host daemon)
                                           ├─► hostprep      ─► host bridges + kernel modules
                                           └─► netlab-runner ─► netlab initial ─► node config
```

netlab is used strictly as a **generator and configurator**, never as a deployer: `netlab create`
produces the topology, `netlab initial` pushes config. **`netlab up` is never used** — it `sudo`s
and fuses deploy and config into one opaque step, which would break both the reproducibility seam
and the clab-api deploy boundary.

## What you get

- **A lab from a definition** — author netlab YAML by hand, or build it on a **visual canvas** with
  a full-syntax text escape hatch, and deploy it as a durable, redeployable record.
- **Two more ways in** — a **template library** (built-in topologies plus labs published from your
  own fleet, and reusable node fragments) and **config import**, which turns real device
  configurations into a twin: per-platform parsers, wiring you declare, pinned addressing, verbatim
  carry of everything not modeled, and quarantine for what must not be applied.
- **Declarative validation** — test suites stored on the lab and run as a render → execute → parse
  → assert pipeline. All data, no user code: commands and expectations are Jinja2 templates
  rendered per node against netlab's own facts; parsing is JSON or TextFSM; assertions are
  substring, regex, or a structured comparison over parsed output. A suite can gate the config push
  or run on demand.
- **Runtime control and observability** — per-node and whole-lab power, config save, container
  logs, an interface inventory, a logical link table with live operational state, **netem link
  impairment** to shape a degraded network, and batch actions that stage a whole condition in one
  request.
- **Live surfaces** — a Server-Sent Events stream of container and job activity, and a WebSocket
  terminal into any node.
- **Host resources** — what the machine has left (CPU, load, memory, disk), what the container
  daemon is holding and how much of it is reclaimable, and what each lab's nodes cost right now.
  Every deploy records the host's state as its first step, so a deploy that failed on a full
  machine still says so afterwards.
- **Access control that delegates** — scoped RBAC over users and groups, API keys, and an SSH jump
  host that makes a deployed lab reachable — and Ansible-ready — with plain `ssh -J`.

## Requirements

- **Linux.** The lab layer drives Linux kernel networking directly; Twinlab is not designed for
  any other host.
- **Docker** with the `docker compose` plugin.
- **A host user in the `clab_api` group** — clab-api authenticates a real PAM user (see
  [First run](#first-run)).
- **Node images** for the platforms you intend to use. Images are used, never distributed.

## First run

### 1. The clab-api host user

clab-api validates credentials against the host's `/etc/passwd` + `/etc/shadow` (both mounted into
it), so it needs a real account in the `clab_api` group. Create it **before** bringing the stack
up — `useradd` rewrites `/etc/passwd` by rename, which can stale a running container's mount.

```bash
sudo groupadd -f clab_api && sudo groupadd -f clab_admins
# A real shell so PAM auth works; the docker group so containerlab never hits a
# socket-permission wall. That group is root-equivalent — fine for a throwaway
# account, a deliberate grant for a permanent one.
sudo useradd --create-home --shell /bin/bash --groups clab_api,clab_admins,docker twinlab-host
PW=$(openssl rand -base64 18); echo "twinlab-host:$PW" | sudo chpasswd; echo "password: $PW"
```

If clab-api was already running when you created the user:
`docker compose up -d --force-recreate clab-api`.

### 2. Configuration

```bash
cp .env.example .env
```

Every variable is documented in `.env.example`. The ones you must fill in:

| Variable | What it is |
| --- | --- |
| `CLAB_API_USERNAME` / `CLAB_API_PASSWORD` | the host user from step 1 |
| `CLAB_API_JWT_SECRET` | `openssl rand -hex 32` |
| `JUMP_TOKEN`, `HOSTPREP_TOKEN` | `openssl rand -hex 32` each — the stack refuses to start without them, so no deployment can ship a well-known secret |
| `POSTGRES_PASSWORD` | any value |
| `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` | Twinlab's first admin, created on first startup only, when the users table is empty |

`LAB_FILES_DIR` (default `/var/lib/twinlab/lab-files`) is a **host-shared** directory where deploy
materializes netlab's generated per-node files so lab containers can bind-mount them. The same
path is used verbatim on the host and inside the backend and clab-api containers — pick one and
don't move it while labs are deployed.

### 3. Up

```bash
# VyOS is PINNED to an exact upstream build (the registry publishes only a
# rolling :latest, so reproducibility needs a digest): pull it by digest and
# tag it with the VyOS version it contains. The catalog expects this tag —
# bumping the pin means updating the digest+tag here AND in
# backend/src/twinlab_backend/services/device_catalog.py.
docker pull ghcr.io/sysoleg/vyos-container@sha256:dc8d4233b2b7e9e94d96fd8d10a40a6b256c5d1aec1c960e02cdf835ca68fe50
docker tag ghcr.io/sysoleg/vyos-container@sha256:dc8d4233b2b7e9e94d96fd8d10a40a6b256c5d1aec1c960e02cdf835ca68fe50 \
  twinlab/vyos:2026.05.30-0046-rolling

docker compose up -d --build
```

- **Web UI** — http://localhost:5173 (`FRONTEND_PORT`)
- **API** — same origin, under `/api/v1`: the frontend container proxies it. The backend port is
  *not* published by default.
- **SSH jump host** — port 2222 (`JUMP_PORT`)

```bash
curl -s http://localhost:5173/api/v1/health/ready
# {"status":"ready","checks":{"database":"ok","clab_api":"ok"}}
```

Sign in as the bootstrap admin and the UI will walk you through creating a lab. The rest of this
section does the same over HTTP.

## Your first lab, over the API

The lifecycle is **create → author → deploy**, three separate steps.

```bash
API=http://localhost:5173/api/v1

# Log in (an opaque, server-revocable session cookie; an API key works too).
curl -s -c jar.txt -X POST $API/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"..."}'

# 1. CREATE a bare record. The name is the lab's durable identity: it keys every
#    /labs/{name} route, is pinned into the definition as netlab's topology name,
#    and prefixes the lab's containers. It is therefore a netlab identifier —
#    a leading letter, then letters/digits/dash/underscore, 16 characters max.
#    This also reserves the lab's management /24 from MGMT_SUBNET_POOL.
curl -s -b jar.txt -X POST $API/labs -H 'Content-Type: application/json' \
  -d '{"name":"demo"}'

# 2. AUTHOR its definition. Validated by a dry `netlab create`; the lab's name and
#    management subnet are re-pinned into the stored text.
curl -s -b jar.txt -X PUT $API/labs/demo -H 'Content-Type: application/json' \
  -d '{"definition":"provider: clab\ndefaults.device: linux\nnodes: [h1, h2]\nlinks: [h1-h2]\n"}'

# 3. DEPLOY from the stored definition. Returns 202 and a RUNNING job.
curl -s -b jar.txt -X POST $API/labs/demo/deploy -H 'Content-Type: application/json' \
  -d '{"configure":true}'
# {"id":"019fd74a-…","lab_name":"demo","kind":"deploy","status":"running",…}

# 4. Poll the job (or watch GET /events) until it is terminal.
curl -s -b jar.txt $API/labs/demo/jobs/019fd74a-…
# {"status":"succeeded","result":{"status":"configured","nodes":["h1","h2"],…}}

docker ps --filter name=clab-demo          # the nodes
curl -s -b jar.txt $API/labs/demo          # record + live node state + mgmt IPs
```

Tear it down. `DELETE` also submits a job; `?remove=true` additionally drops the record and
releases its subnet, whereas a plain destroy leaves a `destroyed` record you can redeploy from the
same definition.

```bash
curl -s -b jar.txt -X DELETE "$API/labs/demo?remove=true"
```

The definition is never resupplied — deploy, configure and redeploy all read the stored one, so a
re-push cannot drift from what was authored.

### Worked examples

| File | What it is |
| --- | --- |
| [`examples/mpls-l3vpn.yml`](examples/mpls-l3vpn.yml) | A VyOS MPLS L3VPN core: 4 PE + 3 P, OSPF area 0, LDP, MP-BGP VPNv4. Paired with `mpls-l3vpn.test-suites.json`. |
| [`examples/campus-lan.yml`](examples/campus-lan.yml) | Multi-access LAN segments, a stub link, named links, explicit bandwidth/MTU — the shapes a point-to-point topology never reaches. |
| [`examples/mixed-nos.yml`](examples/mixed-nos.yml) | Every supported platform in one lab, in a full OSPF mesh, so each cross-vendor pairing is proven by one deploy. `mixed-nos.test-suites.json` asserts it. |

## Concepts worth knowing up front

**Long operations are async jobs.** Deploy, configure, destroy and test-suite runs return `202`
with a running job. Pre-accept checks stay synchronous, so a `4xx` still means "rejected"; a
*failed job* means "ran and could not complete". One running job per lab is the operation mutex —
a concurrent submit of any kind is `409 job_in_flight`. Jobs persist, list per-lab and across the
fleet, and a backend restart fails orphaned jobs honestly rather than wedging the lab.

**Every non-2xx wears one error envelope** — `{code, message, extras}` — with stable code slugs
(`lab_not_found`, `permission_denied`, `netlab_invalid`, `job_in_flight`, …).

**A lab is a durable record.** Its definition, test suites, custom-config templates and topology
layout live on it and survive destroy.

**Live state is separate from the definition.** Power control, logs, the interface inventory, the
link table and netem impairment all read and act on running containers, not on the stored text. A
`drifted` flag tells you when the two have diverged.

**Authentication and RBAC.** Two credentials — opaque session cookies and `Authorization: Bearer`
API keys — resolved by one shared path across HTTP routes, the SSE stream and the terminal
handshake. Permissions are **lab-scoped** (`lab:read`, `lab:edit`, `lab:configure`, `lab:validate`,
`lab:terminal`, `lab:destroy`, `lab:grant`) or **global-only** (`lab:create`, `user:manage`,
`group:manage`, `template:manage`). A *binding* ties a user or group to a role at a scope — global,
or one specific lab — so an owner can delegate on their own lab without an admin. Roles:
`admin`, `global_operator`, `global_viewer`, `creator` and `user` bind globally; `lab_owner`,
`lab_manager`, `lab_operator` and `lab_viewer` bind to a lab. The full model is
[`docs/rbac-v2.md`](docs/rbac-v2.md).

**SSH into nodes** through the jump host. Register a public key on your account (or have the
server generate a pair), then add the hop to `~/.ssh/config`:

```
Host twinlab-jump
  HostName localhost
  Port 2222
  User jump
  IdentityFile ~/.ssh/<your-registered-key>
  IdentitiesOnly yes
```

```bash
ssh -J twinlab-jump vyos@10.77.0.101
```

To reach nodes by name instead, the lab's Nodes tab hands out ready-made aliases (one per node,
`<node>.<lab>`) to paste beneath that block:

```
Host r1.mylab
  HostName 10.77.0.101
  User vyos
  ProxyJump twinlab-jump
```

```bash
ssh r1.mylab
```

The alias is resolved on *your* machine and `HostName` stays the management address, so the jump
host still receives the IP — which is what it authorizes. sshd matches its `permitopen`
restrictions literally, performing no name lookup, so a name the server was never told about
would be refused however well it resolves.

Use the config block (or an explicit `ProxyCommand`) rather than a bare `ssh -J` with `-i`:
command-line identity options do **not** apply to the jump hop, which is its own implicit
connection, so the connection dies there with "Permission denied (publickey)". Access is resolved
live against the backend on every connection — the key is authorized only for the management IPs
of labs you hold `lab:terminal` on, and revoking a key, a grant or a user bites immediately. A
deployed lab is Ansible-ready over the same path.

## Supported NOS platforms

**VyOS, FRR and MikroTik RouterOS 7 (CHR)**, plus the **bird** and **dnsmasq** daemons and
**`linux`** as the host/endpoint device. This is the *tested* set, not a wish list: all six stand
up together in `examples/mixed-nos.yml`, reach OSPF Full on every cross-vendor pairing and forward
end to end, with a test suite that asserts it. Per-platform evidence is in
[`docs/nos-sweep/results.md`](docs/nos-sweep/results.md).

A definition naming any other netlab device is not rejected — it edits as text and may even deploy
— but nothing about it is promised, and the visual builder will not offer it. Cisco IOL works but
is deliberately **not** admitted: its only legitimate image source is Cisco's CML
reference-platform set, licensed for use inside CML only.

## The Python client

[`client/`](client/) is `twinlab-client`, the distributable async Python client for the whole API —
every wire shape a frozen dataclass, every method a coroutine, any non-2xx raising
`TwinlabApiError` with the envelope. It ships `py.typed`.

```python
async with TwinlabClient("http://localhost:5173") as client:
    await client.login("admin", "...")
    await client.create_lab("demo")
    await client.update_definition("demo", open("lab.yml").read())

    job = await client.deploy_lab("demo", configure=True)
    done = await client.wait_job("demo", job.id, timeout=900)
    print(done.status, done.result)
```

The stack itself is not distributed — Twinlab is deployed from this repository with
`docker compose`.

## Repository layout

The compose stack (project `twinlab`) is seven services:

| Service | What it is |
| --- | --- |
| [`frontend/`](frontend/) | Vite + React + TypeScript (pnpm), shadcn/ui on Tailwind v4 with the TanStack family. Dashboard, routed lab tabs, a guided visual topology builder with a full-syntax text escape hatch, live canvas, jobs center, per-node connect/terminal surfaces, account management. Proxies `/api/v1` to the backend. |
| [`backend/`](backend/) | FastAPI (uv, Python 3.14). Owns the lab lifecycle, jobs, RBAC, validation, config import and the template library; runs `netlab create`, deploys through clab-api, delegates config push to the runner. |
| [`netlab-runner/`](netlab-runner/) | Config-push sidecar: `netlab initial` over Ansible's `docker` connection, plus host-side `ip netns exec` scripts for plain-container nodes. Holds the Docker socket; no host network. |
| [`hostprep/`](hostprep/) | The one component allowed to touch host network devices: creates the Linux bridges multi-access links need and loads kernel modules. A dumb, stateless executor behind a token — all policy stays in the backend. |
| [`jump/`](jump/) | Stock OpenSSH sshd. One forwarding-only account; per-key access resolved live by `AuthorizedKeysCommand` against the backend. |
| `clab-api` | [srl-labs/clab-api-server](https://github.com/srl-labs/clab-api-server) (Apache-2.0). Host-coupled — host network and PID, Docker socket and PAM databases mounted — and deploys lab nodes as sibling containers. |
| `postgres` | The RBAC store and the durable lab records, via SQLAlchemy async + Alembic. Migrations run in the backend entrypoint. |

Three projects sit beside the stack, none of them a service:

| Project | What it is |
| --- | --- |
| [`client/`](client/) | `twinlab-client` — the distributable async Python client. |
| [`blackbox/`](blackbox/) | The contract's enforcement: 163 tests driving a live stack through the client only, including real containerlab deploys behind a `deploy` marker. |
| [`e2e/`](e2e/) | The browser layer's: 58 Playwright specs driving the real frontend against a dedicated stack that every run resets to an empty backend. |

## Documentation

[`docs/guide/`](docs/guide/) is the **operator guide**, for running Twinlab rather than changing it:
install, your first lab, a reference for every Build tab setting, operating a running lab, test
suites, config import, access and SSH, and troubleshooting indexed by error code.

**A running stack serves it at `/docs`**, linked from the header and the command palette, so the
documentation always matches the version you are running. Its
[Install](docs/guide/01-install.md) page is the fuller version of
[First run](#first-run) above, and the only place that documents how to obtain a node image for
each of the six supported platforms.

The rest of [`docs/`](docs/) is design records, written for people changing the code:
`twinlab_client_shape.py` is the reviewed API contract, and `rbac-v2.md`, `config-import.md`,
`fact-namespace.md`, `frontend-rework.md`, `host-resources.md`, `operator-guide-plan.md` and
`nos-sweep/` cover the rest. [`ROADMAP.md`](ROADMAP.md) records what is shipped, deferred and why.

## Development

Quality gates, run inside each project directory:

| Project | Gates |
| --- | --- |
| `backend/`, `client/`, `netlab-runner/`, `hostprep/` | `uv run ruff format .` · `uv run ruff check .` · `uv run basedpyright` (strict) · `uv run pytest` |
| `frontend/` | `pnpm typecheck` · `pnpm build` · `pnpm check:build-doc` |
| `blackbox/` | `uv run pytest` against a live stack (see its README) |
| `e2e/` | `pnpm typecheck` · `pnpm test` (resets and drives its own stack) |

"Done" means every gate is green. Contributions follow the conventions in
[`CLAUDE.md`](CLAUDE.md) — errors as values rather than exceptions, sparing defaults, small
commits, and no dependency added without checking that its license is OSI-approved and
Apache-2.0-compatible.

## License

Apache-2.0 — see [`LICENSE`](LICENSE). **Twinlab is fully open source, and so is everything it
ships:** every dependency, bundled tool and reference platform carries an OSI-approved license
compatible with Apache-2.0.
