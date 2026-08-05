# Admitting a platform — the checklist

Widening Twinlab's supported device set is **a maintainer decision that starts with testing**
(CLAUDE.md), and it is never a catalog edit: a device can deploy perfectly and still be
unsupportable because its container is named wrong, its transport has no Ansible collection, or
its config push needs the internet.

This is the procedure, in the order you actually do it, with the failure signature for each
trap — the signatures are the expensive part, because most of them surface as something that
*looks* like a broken device and is not. Evidence per platform lives in `results.md`.

---

## 0. What "supported" means

A platform is admitted when, through Twinlab's own API:

- `PUT` accepts a definition naming it (the dry `netlab create` is the first gate),
- `POST /deploy` with `configure: true` reaches `status="configured"`,
- the protocol it is there to run actually comes up (OSPF adjacency is the usual proof),
- `GET /labs/{name}` lists every node with live state, and `GET /links` resolves every
  endpoint with `oper_state: up`,
- `DELETE ?remove=true` tears it down and leaves nothing behind.

Anything less is recorded in `results.md` as a denial with its reason. A denial is a real
deliverable — three of the platforms probed so far are denials.

## 1. Obtain the image

- Free pulls and `netlab clab build <device>` (the daemon tier) need nothing.
- vrnetlab platforms are built locally from a vendor download; images are **used, never
  redistributed**.
- **The tag you build is rarely the tag netlab defaults to.** vrnetlab built
  `mikrotik_routeros:7.16.2` while netlab 26.07 expects `:7.21.4`, so probe definitions need an
  explicit `image:`. Decide deliberately which one the catalog should carry.
- Set `local_only` in the catalog for anything that cannot be pulled from a public registry —
  proprietary (iol), vrnetlab-built (routeros7), or netlab-built (bird, dnsmasq). It makes a
  missing image a fast, friendly deploy failure instead of a docker pull that will never work.

## 2. Probe it

Deploy a two-node lab of the platform through the API, with `configure: true`, and check the
list in §0. Then check the traps below.

**When something fails, get the output the API swallows.** The job result carries a summary,
not `netlab initial`'s stdout. Reproduce it where the runner does:

```bash
docker compose exec -T netlab-runner sh -c 'mkdir -p /tmp/p && cat > /tmp/p/topology.yml' < def.yml
docker compose exec -T netlab-runner sh -c 'cd /tmp/p && netlab create topology.yml && netlab initial'
```

That is exactly what `/configure` does in a TemporaryDirectory, so the output is the real one.

## 3. The traps, with their signatures

### Container naming — the one that cannot be worked around

containerlab must name the node `clab-<lab>-<node>`. Twinlab's live-state merge, netem, logs
and the terminal all resolve containers by that convention.

> **Signature:** the node is missing from `GET /labs/{name}`'s node list and its links report
> `oper_state: "unknown"`, while `docker ps` clearly shows it running.

`kind` fails here — `k8s-kind` names the container `<node>-control-plane` — and is why it is
not admitted despite deploying and configuring fine.

### The Ansible collection for its transport

`netlab-runner/Dockerfile` installs **one collection per transport**. Docker-exec platforms
(vyos, frr, linux, the daemons) need none; `network_cli` and friends do — `cisco.ios` for IOL,
`community.routeros` for CHR, `arista.eos` for cEOS, `junipernetworks.junos` for Junos,
`fortinet.fortios` for FortiGate.

> **Signature:** `[ERROR]: Task failed: network os <x> is not supported` plus `UNREACHABLE!`
> per node — *after* netlab logged `[CREATED] r1: initial,ospf`. The config was rendered fine;
> only the push had nowhere to go.

Collections are GPL-3.0-or-later, the same process-boundary aggregation already documented for
ansible-core. No new licensing question, but confirm it the same way each time.

### The connection plugin

ansible-core 2.21 removed `paramiko` outright. netlab still names it for `openbsd`, `srlinux`
and `sros` under the clab provider.

> **Signature:** `[ERROR]: Task failed: the connection plugin 'paramiko' was not found`, again
> after the config rendered.

Fix it in `netlab-runner/netlab-defaults.yml` (`/etc/netlab/defaults.yml` in the image), which
netlab merges over its packaged device data so the override lands in
`group_vars/<device>/topology.json` at create time. Pick the replacement per device — a plain
host wants `ssh`, a network OS more likely `ansible.netcommon.libssh`.

> **Do not** try this from a topology `groups:` entry: netlab writes device defaults into
> `group_vars/<device>/`, and Ansible resolves same-precedence groups **alphabetically**, so an
> overriding group only wins when its name sorts after the device's (`bsd` loses to `openbsd`;
> `zz_bsd` wins). That is a trap, not a mechanism.

### Boot time vs the readiness budget

`netlab initial --ready` bounds itself: each node gets `netlab_check_retries ×
netlab_check_delay` seconds and nodes are polled concurrently, so the command's runtime is the
**largest** per-node budget — routeros7 250s, exos 400s, junos 300s, iosxr 600s. The runner's
subprocess timeout (900s) is a backstop that must stay above all of them.

> **Signature:** `could not run netlab initial --ready: Command [...] timed out after N
> seconds` — OUR timeout, not netlab's. netlab's own giving-up looks different and names the
> node: `SSH server on node r1 (device exos) is not ready after 400.6 seconds`.

If a platform's budget approaches the backstop, raise the backstop — never let our timeout
truncate a wait netlab was willing to make.

### Does its config push need the internet?

netlab's `linux/packages.j2` installs whatever `netlab_linux_packages` lists and the image
lacks, so a platform can silently depend on egress **and DNS from inside the lab node**.

> **Signature:** `apk add`/`apt-get` output in the config-script results, ending in
> `temporary error (try again later)` or `unable to select packages`, and a
> `<node> Failed: initial` line.

FRR is the only admitted platform in this state (see the parked item in ROADMAP 17.1). The
lasting fix is an image that already carries the packages — the script only installs what is
missing — not making the lab's DNS work.

### Whether the platform is a VM in a container

vrnetlab kinds wrap qemu, so `GET /labs/{name}/interfaces` reports the **wrapper's** netns
(`br-mgmt`, `tap0`, `tap1`, `eth1`), never the router's own names. `GET /links` is unaffected
and is the surface to use: it joins the container-side name with the NOS-side `ifname` and
netlab's addresses. netem targets the container-side veth, which is the correct shaping point
anyway. This is a documented caveat, not a blocker.

### Plugins the device requires

Some devices need a netlab plugin named in the definition (`kind` needs `plugin: [kind]`).

> **Signature:** the `PUT` is rejected with `netlab_invalid` and netlab says so plainly:
> `MissingDependency in kind: Device kind (node k1) requires "kind" plugin to work properly`.

That one is honest and self-correcting; no action beyond documenting it for users.

## 4. The coordinated changes

Once probed green, admission is **four** edits that must land together:

1. **`backend/.../services/device_catalog.py`** — a `CatalogDeviceSpec` with `modules` and
   `image` mirrored from the installed netlab (`netlab show module-support --format yaml`, and
   the device's `clab.image`), `role`, and `local_only`. Two drift guards will check the mirror
   for you; note that netlab splits its catalog between `devices/` and `daemons/`.
2. **`frontend/src/lib/device-catalog.ts`** — the static fallback list used until `GET /catalog`
   resolves. Its `modules` are the server matrix intersected with `BUILDER_MODULES`.
3. **`backend/.../services/netlab.py` `DEVICE_KMODS` AND `hostprep/.../host.py`'s allowlist** —
   together. The drift guard only covers the netlab side, so a module allowed in one and not
   the other fails at deploy.
4. **`netlab-runner/Dockerfile`** — the Ansible collection for its transport, and
   `netlab-defaults.yml` if it needs a connection override.

## 5. Tests and docs

- **`blackbox/tests/test_catalog.py`** asserts the exact supported set — update it, or the
  suite fails honestly.
- Consider a `deploy`-marked test if the platform adds a capability worth pinning. The
  mixed-NOS test is the model: it pairs **VyOS + bird** precisely because both configure with
  no egress. A test must never depend on the lab node reaching the internet.
- Note any new image prerequisite in `blackbox/README.md` — the suite must be runnable
  elsewhere.
- **`CLAUDE.md`**'s supported-platforms paragraph, `results.md`, and the ROADMAP 17.1 record.

## 6. Verification gate

Backend `ruff format` + `ruff check` + basedpyright + pytest; frontend `pnpm typecheck` +
`pnpm build` + `pnpm check:build-doc`; **the full blackbox suite against a rebuilt stack** —
rebuilt matters: a collection installed by hand into a running container proves nothing about
what a fresh stack does. Then re-probe the platform on that rebuilt stack.
