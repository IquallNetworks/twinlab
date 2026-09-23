# 1. Install

From nothing to a sign-in page, on one Linux host.

## What you need

**Linux.** Twinlab's lab layer drives Linux kernel networking directly through
containerlab, so there is no other host it runs on. This is not a packaging gap
that a container fixes.

**Docker, with the `docker compose` plugin.** The stack runs as seven compose
services, and lab nodes run as further containers beside them on the same
daemon.

**A host user account** for the containerlab API server to authenticate as. The
next section creates it.

**Node images**, but only for the platforms you intend to use. See
[Node images](#node-images).

### Sizing

Measured on this project's own host, so treat these as a floor rather than a
recommendation.

| What | Memory |
| --- | --- |
| The stack itself, all seven services | about 270 MB |
| One VyOS node, idle | about 350 MB |
| The 7-node `mpls-l3vpn` example, running OSPF, LDP and MP-BGP | about 2.4 GB |

Node images dominate disk use, not Twinlab itself. A full set of the six
supported platforms costs roughly 5 GB, and VyOS alone accounts for 2.7 GB.

## The clab-api host user

The containerlab API server authenticates a real host account. It validates
credentials against the host's `/etc/passwd` and `/etc/shadow`, both of which
the stack mounts into it. So the account must exist before the stack starts.

Create it first. `useradd` rewrites `/etc/passwd` by renaming the file, which
leaves a container that already mounted it holding the old copy. A running
clab-api therefore cannot see an account you add later.

```bash
sudo groupadd -f clab_api && sudo groupadd -f clab_admins
# A real shell, so PAM authentication works. The docker group keeps
# containerlab away from a socket-permission wall.
sudo useradd --create-home --shell /bin/bash \
  --groups clab_api,clab_admins,docker twinlab-host
PW=$(openssl rand -base64 18); echo "twinlab-host:$PW" | sudo chpasswd; echo "password: $PW"
```

Keep that password. It goes into `.env` in the next step.

**The `docker` group is root-equivalent.** Anyone who can reach the Docker
socket can start a privileged container and own the host. For a throwaway lab
host that is a reasonable trade. For a permanent one, grant it deliberately.

If clab-api was already running when you created the account, give it the new
`/etc/passwd`:

```bash
docker compose up -d --force-recreate clab-api
```

## Configuration

```bash
cp .env.example .env
```

`.env.example` documents every variable. These are the ones with no usable
default:

| Variable | What it is |
| --- | --- |
| `CLAB_API_USERNAME` / `CLAB_API_PASSWORD` | the host account from the previous step |
| `CLAB_API_JWT_SECRET` | `openssl rand -hex 32` |
| `JUMP_TOKEN` | `openssl rand -hex 32`, shared by the SSH jump host and the backend |
| `HOSTPREP_TOKEN` | `openssl rand -hex 32`, shared by the backend and the host-preparation sidecar |
| `POSTGRES_PASSWORD` | any value |
| `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` / `BOOTSTRAP_ADMIN_EMAIL` | Twinlab's first administrator. Every user has an email |
| `OIDC_SECRET_KEY` | `openssl rand -base64 32 \| tr '+/' '-_'`, the key that encrypts sign-in providers' client secrets |
| `FRONTEND_BASE_PATH` | the path the UI is served under. **Empty** serves it at the origin root |

The stack refuses to start without `JUMP_TOKEN`, `HOSTPREP_TOKEN` and
`OIDC_SECRET_KEY`. That is deliberate: none has a default, so no deployment can
ship a secret that is published in this repository. It also refuses to start
without `BOOTSTRAP_ADMIN_EMAIL` or without `FRONTEND_BASE_PATH`. An empty base path is a real
value ("the root"). An unset one is a mistake, because the backend builds the
URLs it sends browsers to from it.

Three more are worth reading before you start, because moving them later is
disruptive:

- **`LAB_FILES_DIR`** (default `/var/lib/twinlab/lab-files`) is a host directory
  where deploy materializes the per-node files netlab generates, so lab
  containers can bind-mount them. Twinlab uses that same path verbatim on the
  host, inside the backend, and inside clab-api. Pick one and leave it alone
  while a lab is running.
- **`MGMT_SUBNET_POOL`** (default `10.77.0.0/16`) is where each lab's management
  `/24` comes from. Change it only if that range collides with a route on the
  host.
- **`FRONTEND_PORT`** is the published UI port. Behind HTTPS, also set
  `SESSION_COOKIE_SECURE=true` so the session cookie is Secure-only.
  (`DEPLOYMENT_URL` only matters under the development override
  `compose.dev.yaml`, whose dev server rejects unknown `Host` headers.)
  A fronting proxy that routes a subpath — `https://host/twinlab` — to this
  stack needs **`FRONTEND_BASE_PATH=/twinlab`**: the base is baked into the
  frontend image, so changing it is an `up -d --build`. The proxy passes URIs
  through unchanged and must forward WebSocket upgrades (`Upgrade` +
  `Connection` headers).
- **`PUBLIC_ORIGIN`** (unset by default) is the origin browsers reach Twinlab at:
  scheme, host and port, no path, for example `https://twinlab.example.com`.
  Signing in through an external identity provider needs it, because providers
  redirect back to `${PUBLIC_ORIGIN}${FRONTEND_BASE_PATH}/api/v1/auth/oidc/<provider>/callback`.
  Leave it unset if you only use Twinlab's own passwords. See
  [Access](07-access.md#signing-in-through-an-identity-provider).

## Node images

Twinlab never distributes images. You fetch them yourself, and only for the
platforms you intend to use. A stack with no images still starts, and a lab of
`linux` nodes needs one 70 MB pull.

You cannot simply pull four of the six supported platforms, so read the notes.

| Device | Image the catalog expects | How you get it |
| --- | --- | --- |
| `linux` | `python:3.13-alpine` | pull |
| `frr` | `quay.io/frrouting/frr:10.6.1` | pull |
| `vyos` | `twinlab/vyos:2026.05.30-0046-rolling` | pull by digest, then tag locally |
| `bird` | `netlab/bird:latest` | netlab builds it |
| `dnsmasq` | `netlab/dnsmasq:latest` | netlab builds it |
| `routeros7` | `vrnetlab/mikrotik_routeros:7.21.4` | build from a MikroTik download |

### The two straight pulls

```bash
docker pull python:3.13-alpine
docker pull quay.io/frrouting/frr:10.6.1
```

### VyOS

VyOS needs a local tag, because its registry publishes exactly one tag:
`:latest`, a rolling nightly that upstream rebuilds whenever it likes. A lab
that pulls `:latest` is not reproducible. So Twinlab pins a digest and gives it
a tag that names the version inside.

```bash
docker pull ghcr.io/sysoleg/vyos-container@sha256:dc8d4233b2b7e9e94d96fd8d10a40a6b256c5d1aec1c960e02cdf835ca68fe50
docker tag ghcr.io/sysoleg/vyos-container@sha256:dc8d4233b2b7e9e94d96fd8d10a40a6b256c5d1aec1c960e02cdf835ca68fe50 \
  twinlab/vyos:2026.05.30-0046-rolling
```

The tag must match the catalog exactly. It is a local name, so nothing can pull
it for you if you get it wrong.

### bird and dnsmasq

netlab builds these two itself. Run the build inside the netlab-runner
container, which already has netlab and reaches the host's Docker daemon. The
image then lands where lab nodes need it:

```bash
docker compose exec netlab-runner netlab clab build bird
docker compose exec netlab-runner netlab clab build dnsmasq
```

This needs the stack up, so do it after [Start the stack](#start-the-stack).
`netlab clab build --list` shows what else netlab can build.

### MikroTik RouterOS 7 (CHR)

The longest path, and the only one with a trap.

MikroTik publishes the CHR disk image free. Build a container from it with
[srl-labs/vrnetlab](https://github.com/srl-labs/vrnetlab):

```bash
# 1. Download and unpack the version you want.
curl -O https://download.mikrotik.com/routeros/7.16.2/chr-7.16.2.vmdk.zip
unzip chr-7.16.2.vmdk.zip

# 2. Drop the .vmdk into vrnetlab's mikrotik/routeros/ directory, then:
cd vrnetlab/mikrotik/routeros && make docker-image
```

**The trap: the tag you build is almost never the tag the catalog expects.** The
catalog names `vrnetlab/mikrotik_routeros:7.21.4`, and your build carries
whatever version you downloaded. When they differ, set the image explicitly on
the node. Use the **Image override** field on the node's Advanced tab
([page 3](03-build-tab.md)), or `image:` in the YAML. Expect this for any
vrnetlab-built platform.

The free CHR license limits each interface to 1 Mbit/s. That does not matter for
control-plane testing, which is what these labs do.

### What happens when an image is missing

Deploy checks images before it starts, and reacts differently depending on
whether docker could ever fetch the image:

- **`vyos`, `routeros7`, `bird` and `dnsmasq` fail immediately**, with a job
  error of `image_missing`. No registry has them, so a wait for a pull would
  only turn a clear error into a confusing one later.
- **`linux` and `frr` only warn.** Deploy continues and docker pulls the image,
  so the first deploy is slow rather than broken.

If the netlab-runner is unreachable, Twinlab skips the check rather than
blocking the deploy.

## Start the stack

```bash
docker compose up -d --build
```

| What | Where |
| --- | --- |
| Web UI | `http://localhost:5173` (`FRONTEND_PORT`) |
| API | the same origin, under `/api/v1` |
| SSH jump host | port 2222 (`JUMP_PORT`) |

The backend port is not published. The frontend container proxies `/api/v1` to
it, which is why the session cookie needs no cross-origin handling.

Two services do sit on host ports, on **every interface**: clab-api on 8090 and
the host-preparation sidecar on 8091 (both run on the host network, so compose
cannot scope their binding). Both are authenticated — host PAM credentials and
a shared token — but they are privileged services, and nothing outside this
machine ever needs them. On a host other people can reach, firewall both ports.

Check that it came up:

```bash
curl -s http://localhost:5173/api/v1/health/ready
{"status":"ready","checks":{"database":"ok","clab_api":"ok"}}
```

A `clab_api` check that is not `ok` almost always means the host account. Go
back to [The clab-api host user](#the-clab-api-host-user).

## Sign in

Open the web UI and sign in as `BOOTSTRAP_ADMIN_USERNAME`.

Twinlab creates that account on first startup, and only while the users table is
empty. It is not a fixed back door. Once you have other administrators you can
delete it like any other account, and changing `BOOTSTRAP_ADMIN_PASSWORD` later
does nothing.

The dashboard opens empty, with one user and no labs. [Page 2](02-first-lab.md)
builds the first lab, and until it lands the root README walks the same path
over the API.

## Upgrading

```bash
git pull
docker compose up -d --build
```

The backend runs `alembic upgrade head` before it serves anything, so database
migrations are part of starting up and need no separate step.

**Check `.env` against `.env.example` first.** A release can add a required
variable, and the stack refuses to start until it is set. The provider sign-in
release added three: `BOOTSTRAP_ADMIN_EMAIL`, `OIDC_SECRET_KEY` and
`FRONTEND_BASE_PATH` (empty keeps the UI at the root). Its migration gives every
existing account a display name equal to its username and a placeholder email,
`<username>@users.invalid`. The Users page flags those placeholders until an
administrator sets real addresses.

**Deployed labs survive.** Lab nodes are not part of the compose project. They
are sibling containers on the host daemon, so stopping or rebuilding the stack
leaves them running.

Twinlab reconciles the gap on startup instead of pretending nothing happened. It
marks a job that was still running when the backend stopped as failed, with the
code `backend_restart`, instead of leaving it pending forever. A lab stuck
mid-deploy returns to a usable state.

Two things to know about restarting during a long operation:

- The lab containers keep whatever state they reached. A deploy interrupted
  halfway leaves a half-deployed lab, and the failed job says how far it got.
- Redeploying from the stored definition is the way back. See [page
  4](04-operating.md).

## Starting over

To wipe Twinlab's own state — users, labs, definitions, jobs:

```bash
docker compose down -v
```

**Destroy your labs first.** That command removes the database, but not the lab
containers, because they belong to the host daemon. Without the database Twinlab
no longer knows those labs exist, and you are left cleaning up by hand:

```bash
docker ps --filter name='^clab-'          # what is still running
sudo containerlab destroy --all           # if you have containerlab on the host
```

`LAB_FILES_DIR` also survives, and deploy regenerates its contents per lab, so
you can clear it while nothing is running.
