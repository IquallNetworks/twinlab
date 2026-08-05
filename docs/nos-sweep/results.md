# NOS sweep — probe results (strand 17.1)

Evidence for admission decisions. **Admission is the maintainer's call** (CLAUDE.md: widening
the supported set starts with testing, not a catalog edit).

> **Standing rule, 2026-08-04: everything probed green gets admitted.** FRR, MikroTik CHR,
> bird and dnsmasq joined the catalog on this evidence; `kind` did not (reason below). Later
> platforms follow the same rule as their probes land.

Probe protocol per platform: obtain the image → `POST /labs` → `PUT` the definition (the dry
`netlab create` is the first gate) → `POST /deploy` with `configure: true` → poll the job →
check protocol state on the device → check Twinlab's own surfaces (`/interfaces`, `/links`,
`/facts`) → destroy with `remove=true`.

## Host readiness (2026-08-04)

`/dev/kvm` present, VMX **and nested virt enabled** (`kvm_intel.nested=Y`), 31 GB RAM (27
free), 148 GB disk free, user in `docker` + `clab_admins`. So the vrnetlab/KVM kinds are
runnable here, including the vJunos class once those images are obtained (they cannot run
inside a nested VM — this host is bare metal, so that constraint does not bite).

## Results

| Platform | Image obtained | Deploy | Config push | Protocol | Twinlab surfaces | Verdict |
|---|---|---|---|---|---|---|
| **MikroTik CHR** (`routeros7`) | `vrnetlab/mikrotik_routeros:7.16.2`, built locally from the free `chr-7.16.2.vmdk` | OK | OK once the runner ships `community.routeros` — see below | **OSPF Full both ways**, addressing exactly as netlab expanded it (10.1.0.1/30 ↔ .2/30, loopbacks 10.0.0.x/32) | interfaces / links / facts all correct | **ADMITTED** — re-probed green on a rebuilt stack |
| **bird** (daemon tier) | `netlab/bird:latest`, `netlab clab build bird` | OK | OK (`status="configured"`) | **OSPF Full/PtP both ways** | links `up`, addresses correct | **ADMITTED** |
| **FRR** | `quay.io/frrouting/frr:10.6.1` | OK | OK | OSPF Full (probed 2026-08-04, gap-4 verification) | — | **ADMITTED** |
| **dnsmasq** (daemon tier) | `netlab/dnsmasq:latest`, built | OK | OK (`status="configured"`) | dnsmasq running as PID 1 from `/etc/dnsmasq.conf`; addressing applied and the peer pings | links `up` | **ADMITTED** (the `dhcp` module path itself is untested — it needs a dhcp-capable client, i.e. IOL) |
| **kind** (k8s host role) | `kindest/node:v1.34.3`, pulled | OK (needs `plugin: [kind]` in the definition, which netlab says loudly) | OK | node reachable from the linux peer | **BROKEN**: container is named `k1-control-plane`, not `clab-<lab>-<node>`, so the live-state merge cannot see it — absent from the lab's node list, link `oper_state` "unknown" | **NOT admitted** — destroy does clean it up |
| **Extreme EXOS** | `vrnetlab/extreme_exos:32.7.2.19` and `:33.1.1.31`, both built from the free GitHub qcow2s | OK (containers run) | **NEVER REACHED** — SSH never opens | — | link table correct; nodes running | **NOT admitted** — see below |
| **OpenBSD** | `vrnetlab/openbsd_openbsd:7.7` (the version netlab targets) — `:7.9` is what `make download` fetches and it fails earlier | OK — both nodes boot and pass readiness | **FAILS** — netlab asks for a connection plugin ansible removed; with that overridden, the config script then hangs | — | links `up`, addresses correct | **NOT admitted** — got much further on 7.7; see below |

## The finding that generalizes: the runner ships one Ansible collection per platform

`netlab-runner/Dockerfile` installs exactly `community.docker cisco.ios ansible.netcommon`.
CHR's config push failed with

```
[ERROR]: Task failed: network os routeros is not supported
fatal: [r1]: UNREACHABLE! => ... "unreachable": true
```

— netlab rendered the config fine (`[CREATED] r1: initial,ospf`), Ansible simply had no
`community.routeros`. Installing it in the running container made the same `netlab initial`
succeed (`ok=16 changed=2` per node) and brought OSPF up.

**So admitting a NOS is three coordinated changes, not one:**

1. `services/device_catalog.py` `SUPPORTED_DEVICES` (+ `local_only`, `config_import`) and the
   frontend's `use-device-catalog.ts` static fallback;
2. backend `DEVICE_KMODS` **and** hostprep's fixed module allowlist together (the drift guard
   only covers the netlab side);
3. **the runner's Ansible collection for that platform's transport** — `community.routeros`
   for CHR, `arista.eos` for cEOS, `junipernetworks.junos` for the Junos family,
   `cisco.nxos`, `fortinet.fortios`, … Devices on the docker-exec transport (vyos, frr,
   linux, daemons) need none, which is why this has not bitten before.

Licensing note for that step: Ansible collections are GPL-3.0-or-later, the same aggregation
already documented for ansible-core + community.docker (separate processes, nothing linked).
No new licensing question, but each addition should be confirmed the same way.

`community.routeros` is now in `netlab-runner/Dockerfile`, and CHR was **re-probed on a
freshly built stack** — deploy, config push and OSPF Full both ways, with no hand-patched
container involved.

## Other observations

- **vrnetlab kinds report the WRAPPER's interfaces.** `GET /labs/{name}/interfaces` on CHR
  lists `br-mgmt`, `tap0`, `tap1`, `eth0`, `eth1` — the container that wraps the qemu VM, not
  the router's `ether1..n`. `GET /links` is unaffected and is the surface to use: it joins the
  container-side name (`eth1`) with the NOS-side `ifname` (`ether2`) and netlab's addresses.
  netem targets the container-side veth, which is the correct shaping point anyway.
- **MikroTik download URLs** are not linked from the JS-driven download page; the direct form
  `https://download.mikrotik.com/routeros/<ver>/chr-<ver>.vmdk.zip` works (unzip → drop the
  `.vmdk` in `mikrotik/routeros/` → `make docker-image`). The free CHR license caps each
  interface at 1 Mbit/s, which is irrelevant for control-plane testing.
- **srl-labs/vrnetlab naming** differs from netlab's default: netlab 26.07 expects
  `vrnetlab/mikrotik_routeros:7.21.4`, the build produced `:7.16.2`, so the definition needs
  an explicit `image:`. Expect the same for every vrnetlab platform — the version we build is
  rarely the version netlab defaults to.
- A definition naming an uncataloged device deploys fine through the API and the Build tab
  falls back to text mode, exactly as designed — the probe never needed a catalog edit.

## Wave-1 negatives, with their evidence

Both are honest denials, which is what a sweep is for. Neither is a Twinlab defect.

### Extreme EXOS — the vrnetlab launcher never finishes bootstrap

Tried **two** versions (32.7.2.19 and 33.1.1.31, both on vrnetlab's tested list); identical
behaviour. The container runs and qemu forwards port 22, but SSH resets the connection because
EXOS's sshd is never enabled — the launcher wedges before it gets there:

```
launch  INFO  Running bootstrap_config()
* EXOS-VM.3 # unconfigure vlan Mgmt ipaddress
Error: VLAN Mgmt does not have primary address!
* EXOS-VM.4 # configure iproute add default 10.0.0.2 vr VR-Mgmt
* EXOS-VM.5 # vrnetlab  INFO  waiting for '#' on serial console      <-- stuck here indefinitely
```

netlab then correctly fails the deploy at its own readiness budget. Revisit only if EXOS
becomes strategically interesting — netlab rates its support "minimal".

### OpenBSD — credentials don't match, and startup is flaky

Two independent problems in one 2-node probe:

1. One node died: `qemu-system-x86_64: -cdrom /cloud_init.iso: Could not open ... No such file
   or directory` → `QemuBroken: Unable to connect to qemu monitor on port 4000`. The other node
   booted cleanly ("Startup complete in 0:00:56"), so this is a race or a per-container
   generation failure in the image, not a host limit.
2. The node that DID boot rejects netlab's credentials (`admin`/`admin`, from
   `netsim/devices/openbsd.yml`) — "Permission denied". netlab targets
   `vrnetlab/openbsd_openbsd:7.7`; the current `make download` fetches a 7.9 cloud image whose
   cloud-init sets up a different login.

Retry is cheap if wanted: pin the 7.7 image netlab expects, or override the credentials in the
definition's group_vars.

### FRR: its config push needs egress FROM THE LAB NODE — and why THIS host has none

Found while building the mixed-NOS blackbox test. netlab's FRR initial script includes
`linux/packages.j2`, which installs `netlab_linux_packages` (gnupg, curl) whenever the binaries
are missing — and the official `quay.io/frrouting/frr` image ships neither. So every FRR
config push runs `apk add gnupg curl` inside the node.

**Why it fails on this host, exactly.** containerlab sets each lab node's DNS explicitly —
`docker inspect` shows `HostConfig.DNS` populated and the node's `/etc/resolv.conf` carries
`# Overrides: [nameservers]`. It fills that from the host's `/etc/resolv.conf`, dropping
addresses it considers unusable for a lab. This host's IPv4 resolvers are `100.72.3.105` and
`100.72.3.101` — inside **100.64.0.0/10, the CGNAT range** — so both are dropped, leaving only
the two IPv6 nameservers. Lab nodes are IPv4-only, so every lookup SERVFAILs. A plain
`docker run` container on the SAME clab mgmt network resolves fine, because Docker's own
resolver keeps all four upstreams; only clab-created nodes are affected.

So this is not transient and not a Twinlab defect — it is the interaction of a CGNAT resolver
with containerlab's DNS propagation. But it does mean **FRR's config push is the only admitted
platform that is not hermetic** (vyos/bird/dnsmasq/linux/iol/CHR all configure with no egress).
It is why the mixed-NOS blackbox test deliberately pairs **VyOS + bird**: a test must not depend
on the lab node reaching the internet.

**Removing the dependency is proven to work.** `linux/packages.j2` only installs what is
missing (`which gpg`, `which curl`), so an image that already carries them skips the install
entirely. A two-line probe image —

```dockerfile
FROM quay.io/frrouting/frr:10.6.1
RUN apk add --no-cache gnupg curl
```

— deploys and configures **`status="configured"` with OSPF Full both ways on this host, with
DNS still broken**. That makes FRR hermetic like the rest, and it is the same class of thing
netlab already does for the daemon tier (`netlab clab build bird`). The cost is that the
catalog's `image` would no longer be netlab's default, which the drift guard asserts — so it
needs a deliberate decision, not a quiet edit.
