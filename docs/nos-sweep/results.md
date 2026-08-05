# NOS sweep — probe results (strand 17.1)

Evidence for admission decisions. **Admission is the maintainer's call** (CLAUDE.md: widening
the supported set starts with testing, not a catalog edit).

> **Standing rule, 2026-08-04: everything probed green gets admitted.** FRR, MikroTik CHR,
> bird and dnsmasq joined the catalog on this evidence; `kind` did not (reason below). Later
> platforms follow the same rule as their probes land.
>
> **The rule is about behaviour, and behaviour is not the only gate (2026-08-05).** Cisco IOL
> probed green throughout and was still WITHDRAWN, because its only legitimate image source is
> Cisco's CML reference-platform set and Cisco licenses those images for use inside CML only.
> A platform must clear **both** bars — it works, *and* we may legitimately run its image
> here. See "Cisco IOL — withdrawn on licensing" below; the decision, its full framing and the
> post-v1.0 revisit are ROADMAP 17.1 and item 20.

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
| **dnsmasq** (daemon tier) | `netlab/dnsmasq:latest`, built | OK | OK (`status="configured"`) | dnsmasq running as PID 1 from `/etc/dnsmasq.conf`; addressing applied and the peer pings | links `up` | **ADMITTED** (the `dhcp` module path itself is untested — it needs a dhcp-capable client, and the admitted set no longer has one: IOL was the candidate) |
| **kind** (k8s host role) | `kindest/node:v1.34.3`, pulled | OK (needs `plugin: [kind]` in the definition, which netlab says loudly) | OK | node reachable from the linux peer | **BROKEN**: container is named `k1-control-plane`, not `clab-<lab>-<node>`, so the live-state merge cannot see it — absent from the lab's node list, link `oper_state` "unknown" | **NOT admitted** — destroy does clean it up |
| **Extreme EXOS** | `vrnetlab/extreme_exos:32.7.2.19` and `:33.1.1.31`, both built from the free GitHub qcow2s | OK (containers run) | **NEVER REACHED** — SSH never opens | — | link table correct; nodes running | **NOT admitted** — see below |
| **OpenBSD** | `vrnetlab/openbsd_openbsd:7.7` (the version netlab targets) — `:7.9` is what `make download` fetches and it fails earlier | OK — both nodes boot and pass readiness | **FAILS** — netlab asks for a connection plugin ansible removed; with that overridden, the config script then hangs | — | links `up`, addresses correct | **NOT admitted** — got much further on 7.7; see below |
| **Cisco IOL** (`iol`) | `vrnetlab/cisco_iol:17.16.01a`, from the CML refplat set | OK | OK (`network_cli` over SSH, once the runner shipped `cisco.ios`) | OSPF Full, LDP operational, VPNv4 Established; MPLS L3VPN end to end | interfaces / links (the `Ethernet0/1` ↔ `eth1` alias join) / facts all correct; suite 25/25 incl. interactive VRF pings | **WITHDRAWN 2026-08-05 — licensing, not behaviour**; see below |

## The finding that generalizes: the runner ships one Ansible collection per platform

At the time of the probe `netlab-runner/Dockerfile` installed exactly
`community.docker cisco.ios ansible.netcommon` (`cisco.ios` left with IOL on 2026-08-05).
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

**A fourth step surfaced 2026-08-05, from the same transport fact:** a `network_cli` platform
also needs an entry in the runner's `_NETMIKO_DEVICE_TYPES`, or `interactive: true` test cases
return `no interactive CLI driver for network_os '<x>'`. CHR was admitted without one — the
gap was found while withdrawing IOL and closed with `routeros: mikrotik_routeros`. The failure
is a clean typed error rather than a wrong driver, which is exactly why it went unnoticed:
nothing else in the probe protocol exercises interactive mode.

**A fifth step surfaced later the same day** (the TextFSM path — see the mixed-NOS section
below), so the count in this dated finding is superseded: the standing procedure is **up to
five** coordinated changes, and `admitting-a-platform.md` is the authoritative list. This
section is kept as the evidence for how the generalization was reached.

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
platform that is not hermetic** (vyos/bird/dnsmasq/linux/CHR all configure with no egress).
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

### Cisco IOL — withdrawn on licensing

**The only platform so far removed from the supported set after passing every behavioural
test.** IOL probed green on everything the protocol asks for: deploy, `network_cli` config push
over SSH, OSPF Full, LDP operational, VPNv4 Established, a full MPLS L3VPN, the
`Ethernet0/1` ↔ `eth1` alias join in the link table, facts, and 25/25 on its device-keyed suite
including interactive VRF pings through the netmiko channel. None of that is in doubt and none
of it is why it left.

**The reason is the image's licence.** IOL is distributed only inside Cisco's CML
reference-platform set, and Cisco states plainly that those images *"are only licensed for use
within Cisco Modeling Labs"* and that *"downloading these VM images and using them outside
Cisco Modeling Labs without a proper license is prohibited"*
([DevNet](https://developer.cisco.com/docs/modeling-labs/vm-images-for-cml-labs/)). Extracting
them for containerlab is common community practice; it is still outside that grant. Note this
is NOT Twinlab's own open-source constraint — Twinlab ships, mirrors and links no images, so
nothing we distribute is affected. It is a question about what the maintainer runs on their own
host while testing, which is why it was theirs to answer.

**The maintainer chose the conservative stance on 2026-08-05**, "for now", with a post-v1.0
item to revisit (ROADMAP item 20). Two things follow that are worth writing down:

- **Withdrawal is the admission procedure in reverse**, and it reaches further than admission
  does: catalog + frontend fallback, the runner's collection, *and* the platform's example, its
  builtin network template, its suite cases, and every doc claim. `DEVICE_KMODS`/hostprep
  needed nothing (iol carries no netlab kmods key). What stayed, deliberately, is every
  mechanism that is device-agnostic and merely happens to cover IOS — the config-import IOS
  parser, the `textfsm`/`cisco_ios` map with Twinlab's own LDP template, and the
  `mpls_te`/`ip_sla` built-ins, which ARE the built-in custom-config library.
- **The dnsmasq `dhcp` module path lost its only candidate client** — STILL OPEN, and the only
  live sweep follow-up from this withdrawal. Under the clab provider `linux` has no `dhcp`
  support (netlab lists it libvirt-only), so nothing in the admitted set can exercise it; it
  needs a future platform that can.
- ~~The example suite lost its second live device flavor, so `textfsm` and
  `compare`-over-parsed-output have no worked example.~~ **CLOSED 2026-08-05** by
  `examples/mixed-nos.test-suites.json`, which restores device-keyed dispatch across FOUR
  flavours plus both parse modes — see the mixed-NOS section below.

**Cisco is not entirely closed.** XRd Control Plane and the Cisco 8000 emulator ship under
separate entitlements, not the CML SEULA, so they stay acquirable independently of this
decision — XRd being the attractive one (native container, ~2 GB, no KVM, needs a Cisco service
contract).

## The mixed-NOS lab: all six admitted platforms in one network (2026-08-05)

The strand's actual goal, and the last of its v1.0 work. Every platform above was probed on its
own two-node topology; this puts all six in ONE network, because a platform that configures fine
alone can still get its interface names, addressing or adjacencies wrong beside another vendor.
Definition: **`examples/mixed-nos.yml`**; suites: **`examples/mixed-nos.test-suites.json`**.

Shape: the four routing platforms (vyos, frr, routeros7, bird) form a **full mesh**, so all six
cross-vendor OSPF pairings are proven by one deploy instead of six labs; plus a three-endpoint
services LAN (vyos + dnsmasq + a linux host, so the hostprep bridge path is in play), a linux
host behind CHR, and a stub. Seven nodes, nine links, three config-push paths at once — Ansible
`docker` (vyos), `network_cli` over SSH (CHR), host-side `ip netns exec` scripts (frr, bird,
dnsmasq, the linux hosts).

**Result: green on the first attempt.** `POST /deploy` with `configure: true` → job `succeeded`,
`status="configured"`, all 7 nodes up.

**One caveat on the images, stated up front because it is the parked FRR item biting.** The
verified run gave `frr1` a locally-built `quay.io/frrouting/frr:10.6.1` + `apk add gnupg curl`
image (the proven fix from the FRR section above). FRR's config push is the only non-hermetic one
in the admitted set, and on this host — CGNAT resolvers, so containerlab propagates no usable
IPv4 nameserver — it cannot succeed on netlab's default image. The COMMITTED example deliberately
keeps netlab's default, because that is the portable choice and works wherever lab nodes have DNS,
with the two-line workaround documented in its header. Every other node ran exactly the image the
example names, CHR's pinned `7.16.2` included. So the example deploys as-written on a normal host
and needs that single override here until the FRR image question is settled.

Evidence:

- **All six adjacencies Full.** Each of the four routers holds exactly three: vyos1 and frr1
  report `Full/-` (FRR), bird1 `Full/PtP`, chr1 `state=Full` ×3.
- **Forwarding end to end.** `host1` on the services LAN reaches `host2` behind CHR — two
  platforms away — plus every router loopback that exists, and the vyos stub on `dum1`.
- **Surfaces correct across four NOS families.** The link table resolves CHR's alias join
  (`chr1:eth1` container-side ↔ `ether2` NOS-side) on every CHR link, all endpoints `up`, the
  3-endpoint LAN is ONE row with three endpoints, and `live=True`. `/interfaces` and `/facts`
  agree per node.
- **netem on all four platforms**, singly and as one **batch** (delta 24) mixing four netem sets
  with a node power event: every item `ok`, impairment surfaced on the right link endpoints, all
  cleared. On CHR this writes to the wrapper container's veth, which is the correct shaping point.
- **The config-time gate works on a mixed lab**: a `configure` ran the `convergence` suite
  automatically, 8/8, and `config_time_status` went `not_run` → `passed`.
- **Suites: 9/9 across four device flavours** (see the next section).

### Two netlab semantics this surfaced — both correct, both worth knowing

Neither is a defect; both are documented in the definition's header so nobody "fixes" them.

1. **bird's links type `lan`, not `p2p`.** netlab types a two-node link `p2p` only when BOTH ends
   are routers, and it classifies the bird daemon `role: host`. So the three bird links expand to
   `lan` /24s while vyos-frr, vyos-chr and frr-chr get p2p /30s. It changes nothing about the
   protocol — netlab still configures OSPF point-to-point on all of them (bird `Full/PtP`, FRR
   `Full/-` with no DR election, CHR `network-type=ptp`) — and a two-endpoint `lan` still renders
   as a direct veth with no bridge. Exactly why Twinlab discriminates on ENDPOINT COUNT and
   treats `type` as a passthrough.
2. **A daemon-role node gets a router ID but no loopback INTERFACE.** bird1 was assigned
   `10.0.0.4` and its neighbours see that ID, but netlab creates the loopback interface only for
   role-router nodes, so `10.0.0.4/32` appears in nobody's OSPF table and pinging it fails —
   correctly, the address exists nowhere. Do not write a check that pings a daemon node's
   router ID.

### Test suites: the worked examples the IOL withdrawal had cost us

The withdrawal left the example suite with one live device flavour, so device-keyed dispatch,
`parse: textfsm` and `compare`-over-parsed-output had no worked example (logged as a sweep
follow-up). `examples/mixed-nos.test-suites.json` restores all three with **four** flavours —
9/9 green live, nothing hardcoded (every router ID and address renders from facts):

- `ospf_adjacency` — ONE test dispatched across FOUR device keys (vyos / frr / routeros7 / bird),
  each asserting three Full adjacencies in its own idiom. Deliberately node-agnostic so one test
  serves all four.
- `ospf_peers_json` — `parse: json` + `compare` on the two FRR-based platforms, naming the two
  peers they have in common (chr1, bird1) so one case is correct for both nodes.
- `ospf_peers_textfsm` — `parse: textfsm` + root-level `list` compare on CHR. RouterOS has no
  JSON output, so it is the platform that genuinely needs TextFSM.
- `fabric_forwarding` — the control plane agreeing is not the data plane working: a ping across
  the fabric.
- `chr_interactive_ping` (runtime suite) — **the first live verification of `interactive: true`
  on CHR**, i.e. of the netmiko `routeros: mikrotik_routeros` entry added 2026-08-05. It had been
  fixed on inspection and never exercised.

### Two more admission gaps, same family as the netmiko one

Found while writing that suite; both fixed (commit "Backend: give RouterOS 7 a TextFSM path…").

1. **`routeros7` was missing from `TEXTFSM_PLATFORMS`**, so `parse: textfsm` on CHR was rejected
   as an authoring error — on the one admitted platform with no JSON alternative. This is the
   third thing CHR's admission missed, after the Ansible collection and the netmiko driver: the
   lesson is not "we forgot" but that **admitting a platform touches more places than the
   catalog**, and the probe protocol exercises none of them.
2. **Mapping the platform is not enough: ntc-templates cannot parse RouterOS 7.** Both its
   `mikrotik_routeros` OSPF-neighbour templates were written for v6 — they require
   `interface=`/`priority=` and v6's field order, where v7 dropped those two, added `area=`,
   moved `router-id=`, and prefixes rows with the flag column. They raise a TextFSM state error
   rather than mis-parsing. So Twinlab packages its own template (the second in
   `services/textfsm_templates/`), indexed for the **`terse`** spelling because plain `print`
   wraps one record over several lines at the terminal width and no line-oriented template can
   follow that. **Expect this per vrnetlab-era platform**: ntc's coverage tracks the release its
   contributor had.

### One bug in Twinlab itself, not in a platform

`_parse_textfsm` caught only `CliTableError` ("no template found") and let **`TextFSMError`**
("template resolved, output does not fit") escape the boundary. `_run_check` is written to expect
a value there — its own comment says *"report the check as broken — never silently fall back to
raw"* — so an escaping exception skipped that and failed the **whole suite run** instead of
marking ONE check `error`. Pre-existing and reachable on any device whose ntc template targets a
different NOS release; the new RouterOS 7 template merely made it cheap to hit. Now translated at
the boundary.

### A stub link read "down" while forwarding — RESOLVED 2026-08-05

Found here, raised as a contract question rather than fixed, then **decided and shipped the same
day.** Worth keeping in full because the diagnosis is the interesting part: every step of the
chain was individually correct.

`customer-drop` (one endpoint, `vyos1:dum1`) read `oper=down` even though `172.16.5.1` pings.

1. **The kernel declines to answer.** Dummy drivers never drive carrier, so the device reports
   `IF_OPER_UNKNOWN` while fully up: `4: dum1: <BROADCAST,NOARP,UP,LOWER_UP> ... state UNKNOWN
   ... dummy`. `IFF_UP` *and* `IFF_LOWER_UP` are both set.
2. clab-api passes the literal string `"unknown"` through as the interface state.
3. `merge_links` stores it on the endpoint — `state=None` means something different, namely that
   Twinlab could not resolve the interface at all.
4. The delta-14 roll-up (`all "up" -> up; all known-not-up -> down; any None -> unknown`)
   classified a *known* value that is not `"up"` as **down**.

**The blast radius was every stub on every supported platform**, via two different realizations
that converge on the same interface type — worth knowing independently of this bug:

| Device | netlab `type` | Interface | clab link | Live state | `kind` |
|---|---|---|---|---|---|
| vyos | `loopback` | `dum1` | **none** — the node configures it itself | `unknown` | `dummy` |
| frr | `stub` | `eth2` | `type: dummy` | `unknown` | `dummy` |
| routeros7 | `stub` | `ether3`→`eth2` | `type: dummy` | `unknown` | `dummy` |
| bird / linux / dnsmasq | `lan` | `eth2` | `type: dummy` | `unknown` | `dummy` |

`campus-lan.yml` carries a stub too, so it was affected as well. Not affected: real links (veth
→ `up`), LANs, undeployed labs (unknown by design), stopped nodes (`None` → unknown, correct).

**Nobody had decided it.** The roll-up's table test has rows for `None`, `"down"` and
`"lowerlayerdown"` — so `None`-vs-known-string was thought about — and no row for the literal
`"unknown"`. The contract had the same gap: its parenthetical listed only resolution failures as
"unknown", so one word was doing two jobs, *"we could not find out"* and *"the device said
unknown"*.

**The fix (maintainer-decided, contract wording amended, no shape change).** Two pure stages:

- Each endpoint classifies up / down / unknown, and **down is now a CLOSED set** — `down`,
  `lowerlayerdown`, `notpresent`. Anything else, including a value we have never seen, reads
  **unknown rather than assumed-down**. That was the maintainer's addition to the original
  proposal and it is the better default in general: claiming a link is down is a strong
  statement, and a wrong one teaches users to ignore the signal.
- Plus the refinement that fixes the stub: operstate is *meaningless* without a carrier, so an
  endpoint whose interface `kind` is carrier-less (`dummy`) and whose state is `"unknown"` reads
  **up**. clab-api already reports `kind` and `merge_links` already holds the matched interface,
  so this cost no new wire field.
- The endpoint `state` passthrough is untouched — only the derived roll-up changed. A consumer
  obligation went into the contract: never read `state != "up"` as down.

The frontend reimplements this rule for LAN spoke styling and got the conservative half; it
cannot do the `kind` refinement (kind is not on the wire) but a spoke belongs to a 3+-endpoint
LAN whose members are always veths, so a dummy cannot appear there.

Verified live: the stub flipped to `up` with its endpoint still reporting raw `"unknown"`, every
other link unchanged, and admin-downing a real link still reads `down` — **both sides drop
together**, which is why `degraded` did not appear and is exactly the veth-pair behaviour the
contract comment already predicted.
