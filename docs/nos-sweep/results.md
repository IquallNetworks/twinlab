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
| Extreme EXOS, OpenBSD | not started | — | — | — | — | wave 1 remainder |

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
