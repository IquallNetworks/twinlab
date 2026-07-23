# Twinlab

Twinlab generates reproducible simulated network topologies from a declarative definition. It layers
on [Containerlab](https://containerlab.dev/) (driven through [netlab](https://netlab.tools/)) so
engineers can describe nodes, links, and services declaratively, then deploy reproducible labs for
digital-twin and network-automation testing. Deploy is driven through clab-api; config push is
delegated to netlab (`netlab initial`). `netlab up` is never used.

## Architecture

A `docker compose` stack (project `twinlab`):

```
frontend (Vite/React) --/api/v1--> backend (FastAPI)
                                   backend --netlab create--> clab.yml --deploy--> clab-api (containerlab)
                                   backend --configure--> netlab-runner --netlab initial (ansible/docker)--> nodes
                                   backend --> postgres (users, roles, sessions)
```

| Service | What it is |
|---------|-----------|
| `frontend/` | Vite + React + TypeScript (pnpm), shadcn/ui + TanStack (Query/Router/Form) + zod. Login, user management, and lab management. Dev server proxies `/api/v1` to the backend. See [`frontend/README.md`](frontend/README.md). |
| `backend/` | FastAPI (uv). Runs `netlab create`, deploys the topology through the clab-api server (piped inline), and delegates config push to the netlab-runner. See [`backend/README.md`](backend/README.md). |
| `netlab-runner/` | Config-push sidecar: `netlab initial` over Ansible's `docker` connection. netlab (MIT) + ansible-core + community.docker (GPLv3) + the docker CLI; needs the Docker socket, no host network. |
| `clab-api` | [srl-labs/clab-api-server](https://github.com/srl-labs/clab-api-server) (Apache-2.0). Host-coupled: runs on the host network with the Docker socket + PAM databases mounted, and deploys lab nodes as sibling containers. |
| `postgres` | Backs the RBAC store (users, roles, permissions, sessions) and the durable lab records (definition + status). |

## Quick start

```bash
cp .env.example .env            # then fill in the values
docker compose up -d --build
```

- Frontend — http://localhost:5173 (port and public URL configurable via
  `FRONTEND_PORT` / `DEPLOYMENT_URL` in `.env`)
- Backend health — http://localhost:8000/api/v1/health
- clab-api — http://localhost:8090

## End-to-end lab deploy

The clab-api server authenticates a **real host user** (via the mounted `/etc/passwd`+`/etc/shadow`)
that must be in the `clab_api` group. Create a throwaway one **before** bringing the stack up
(`useradd` rewrites `/etc/passwd` by rename, which can stale a running container's file mount):

```bash
# 1. Groups clab-api expects, then a temporary user (docker group so containerlab
#    ops never hit a socket-perm wall; real shell so PAM auth works).
sudo groupadd -f clab_api && sudo groupadd -f clab_admins
sudo useradd --create-home --shell /bin/bash --groups clab_api,clab_admins,docker twinlab-e2e
PW=$(openssl rand -base64 18); echo "twinlab-e2e:$PW" | sudo chpasswd; echo "password: $PW"

# 2. Put twinlab-e2e / $PW into .env (CLAB_API_USERNAME / CLAB_API_PASSWORD),
#    set CLAB_API_JWT_SECRET=$(openssl rand -hex 32), then:
docker pull ghcr.io/sysoleg/vyos-container:latest    # node image for device: vyos
docker compose up -d --build

# 3. Lab routes require auth (see below). Log in as the bootstrap admin first.
curl -s http://localhost:8000/api/v1/health/ready     # expect database + clab_api = ok
curl -s -c jar.txt -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$BOOTSTRAP_ADMIN_USERNAME\",\"password\":\"$BOOTSTRAP_ADMIN_PASSWORD\"}"

# 4. Drive the flow: netlab definition -> netlab create -> clab-api deploy.
#    Add "configure": true to also push config after deploy (via the netlab-runner:
#    `netlab initial`); the response reports per-node status. The response's
#    lab_name is the lab's stable identity (a top-level `name:` in the definition,
#    or a generated tl-<hex> when absent).
curl -s -b jar.txt http://localhost:8000/api/v1/labs \
  -H 'Content-Type: application/json' \
  -d '{"definition":"provider: clab\ndefaults.device: vyos\nmodule: [ospf]\nnodes: [r1, r2]\nlinks: [r1-r2]\n","configure":true}'
docker ps --filter name=clab-                         # confirm the nodes are up

# List labs (durable records merged with live node state), or inspect one:
curl -s -b jar.txt http://localhost:8000/api/v1/labs
curl -s -b jar.txt http://localhost:8000/api/v1/labs/<lab_name>

# Re-push config to an already-deployed lab at any time. The definition is not
# resupplied — the one stored at deploy is reused, so a re-push can't drift:
curl -s -b jar.txt -X POST http://localhost:8000/api/v1/labs/<lab_name>/configure
```

> Config push is delegated to netlab, so any platform netlab supports can be
> configured; **VyOS** is what's verified end-to-end today. netlab drives Ansible
> over the `docker` connection (exec into nodes by container name via the socket),
> so it needs no management-network reachability or SSH.

> The `docker` group is root-equivalent — fine for a throwaway account you delete afterwards.
> If clab-api was already running when you created the user, recreate it:
> `docker compose up -d --force-recreate clab-api`.

Teardown:

```bash
docker compose down
sudo userdel --remove twinlab-e2e
sudo groupdel clab_api clab_admins    # only if nothing else uses them
```

## Authentication & RBAC

The backend has its own users and role-based access control, backed by Postgres
(separate from the clab-api host user above). Login issues an opaque,
server-revocable session token in a `Secure httpOnly` cookie.

- `POST /api/v1/auth/login` `{username, password}` → sets the session cookie.
- `POST /api/v1/auth/logout` → revokes the session and clears the cookie.
- `GET /api/v1/auth/me` → current identity, roles, and effective permissions.
- `POST/GET /api/v1/users`, `PUT /api/v1/users/{id}/roles` → user management
  (requires `user:manage`).

Seeded roles → permissions:

| Role | Permissions |
|------|-------------|
| `admin` | `lab:create`, `lab:configure`, `lab:destroy`, `lab:read`, `user:manage` |
| `operator` | `lab:create`, `lab:configure`, `lab:destroy`, `lab:read` |
| `viewer` | `lab:read` |

Lab routes are guarded by permission:

- `lab:read` — `GET /api/v1/labs`, `GET /api/v1/labs/{name}`, `GET
  /api/v1/labs/{name}/nodes/{node}/logs`, `GET /api/v1/labs/{name}/interfaces`.
- `lab:create` — `POST /api/v1/labs` (deploy), `PUT /api/v1/labs/{name}` (edit the
  stored definition), `POST /api/v1/labs/{name}/redeploy`.
- `lab:configure` — `POST /api/v1/labs/{name}/configure`, the node/lab
  `start|stop|restart` actions, and `POST /api/v1/labs/{name}/save`.
- `lab:destroy` — `DELETE /api/v1/labs/{name}`.

Editing the definition (`PUT`) is validated by a dry `netlab create` and re-pins
the lab's name, then takes effect on the next redeploy; redeploy rebuilds from the
stored definition (clab-api `reconfigure`) so a running lab can be rebuilt or a
destroyed one brought back. Power control, logs, interfaces, and save operate on
live clab-api state, not the definition. On first startup, when the users table is
empty, a bootstrap admin is created from `BOOTSTRAP_ADMIN_USERNAME` /
`BOOTSTRAP_ADMIN_PASSWORD`.

## Development

Per-project gates (run inside each directory):

- **backend** / **netlab-runner** — `uv run ruff format . && uv run ruff check .`, `uv run basedpyright`, `uv run pytest`.
- **frontend** — `pnpm typecheck`, `pnpm build`.
