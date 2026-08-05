# NOS availability & acquisition matrix (2026-08-04)

> **Superseded in part, 2026-08-05.** Every Cisco row that depends on the CML reference-platform
> set — iol/ioll2, iosv/iosvl2, csr, cat8000v, nxos, asav — is now **out of scope**: the
> maintainer settled the SEULA question against extracting those images, so **IOL was withdrawn
> from the supported set** and the CML-Free / CML Personal routes are off the acquisition list.
> The Cisco rows that survive are `iosxr` (XRd) and `cisco8000v`, which ship under separate
> entitlements. Nokia `srsim` is **parked** (25.x-only, so it cannot run the client's releases,
> plus an annual subscription licence). The matrix below is left as the dated research it was —
> see `results.md`, `acquisition-checklist.md` and ROADMAP 17.1 / item 20 for what holds now.

Research input to ROADMAP item 17, strand 17.1. Installed netlab: **26.07** (read from
`netlab-runner/.venv/.../site-packages/netsim/`). Candidate set = netlab 26.07 devices with a
`clab` provider section, cross-checked against containerlab's kinds list
(https://containerlab.dev/manual/kinds/). Devices netlab supports only under libvirt/external
(sonic, routeros v6) are out of scope (appendix). VM-based kinds must be built with
**srl-labs/vrnetlab** (https://github.com/srl-labs/vrnetlab — the containerlab fork; the old
`hellt/vrnetlab` now lives under the srl-labs org; upstream `vrnetlab/vrnetlab` images do NOT
work with containerlab, per https://containerlab.dev/manual/vrnetlab/).

**Bind-risk column**: derived locally from each device YAML's `clab.node.config_templates`
(these become `node_files/*` binds, which Twinlab's inline deploy strips) — cross-referenced
with the known FRR failure (see `netlab-up-gaps.md` gap 4). "proven" = already running under
Twinlab despite a bind.

## Matrix

| netlab device | clab kind | Class | Image source | vrnetlab build? | KVM? | RAM/node (approx) | netlab support quality | Bind risk (inline deploy) | Multi-version |
|---|---|---|---|---|---|---|---|---|---|
| vyos | linux (native ctr) | FREE PULL | `ghcr.io/sysoleg/vyos-container` (rolling) | no | no | ~0.5–1 GB | full (Twinlab-tested) | low — `/lib/modules` host bind, proven working | limited: rolling tags; VyOS Stream qcow quarterly (vyos.net/get/stream) |
| frr | linux (native ctr) | FREE PULL | `quay.io/frrouting/frr:10.6.1` (any tag) | no | no | ~0.1 GB | full in netlab; **known broken in Twinlab** | **HIGH — `/etc/frr/daemons` + hosts binds (the proven failure)** | excellent: quay tags back many majors |
| srlinux | nokia_srlinux | FREE PULL | `ghcr.io/nokia/srlinux` | no | no | ~2 GB | full (proven on twinlab-nokia branch) | low — hosts bind only, proven | excellent: all releases public on ghcr |
| linux / daemons (bird, dnsmasq) | linux | FREE PULL / local `netlab clab build` | `python:3.13-alpine`; `netlab/bird`, `netlab/dnsmasq` built locally (`build: true`) | no | no | tiny | full / daemon-tier | linux: proven; bird/dnsmasq deliver daemon config via binds — untested risk | n/a (bird `sw_version` pinned in netlab, 2.19.1) |
| kind (k8s) | k8s-kind | FREE PULL | `kindest/node:v1.34.3` (Docker Hub) | no | no | ~1–2 GB | daemon-tier, host role | `daemon_config` binds (`/tmp/kind`) — risk | good (kindest tags) |
| cumulus / cumulus_nvue | cvx | FREE PULL (dated) | `networkop/cx:4.4.0` / `cx:5.3.0` (Docker Hub) | no | no | ~0.5–1 GB | **netlab caveat: "out-of-date and not supported"** | HIGH — `/etc/network/interfaces` bind (cumulus) | frozen; newer VX now behind NVIDIA support contract / NVIDIA Air (see flags) |
| eos (cEOS) | ceos | FREE REG | arista.com → Support → Software Download → cEOS-lab `.tar.xz`, `docker import` | no | no | ~2 GB | full | none — SSH (network_cli) push to /mnt/flash | excellent: long back-catalog of 4.2x releases |
| iol / ioll2 | cisco_iol | FREE REG (CML-Free) / CML paid — **SEULA: CML-only use** | CML refplat ISO (`iol`/`ioll2` .bin) → vrnetlab | yes (no VM — IOL is a binary) | no | ~0.75–1 GB | full (Twinlab-tested) | low — `ifstate.cfg` bind stripped, proven tolerable | per CML refplat release |
| iosv / iosvl2 | cisco_vios | ENTITLEMENT (CML) | CML refplat → vrnetlab `vios`/`viosl2` | yes | yes | ~1 GB | good | none | per CML release (15.x — legacy, frozen) |
| csr | cisco_csr1000v | ENTITLEMENT (CML/CCO) | CML refplat qcow2 → vrnetlab | yes | yes | ~4 GB | good | none | CML releases |
| cat8000v | cisco_c8000v | ENTITLEMENT (CML/CCO) | CML refplat qcow2 → vrnetlab | yes | yes | ~4–5 GB | good | none | CML releases (17.x train) |
| nxos (N9300v) | cisco_n9kv | ENTITLEMENT (CML/CCO) | CML refplat qcow2 → vrnetlab | yes | yes | ~8–10 GB | good | none | CML releases |
| asav | cisco_asav | FREE REG (CML-Free includes ASAv) | CML(-Free) refplat qcow2 → vrnetlab | yes | yes | ~2 GB | firewall-tier | none | CML releases |
| iosxr (XRd) | cisco_xrd | ENTITLEMENT (CCO + service contract) | software.cisco.com XRd Control Plane tarball (docker image inside) | no | no | ~2 GB / 1 vCPU | full | **HIGH — config via `netlab-config.sh` bind (FRR-pattern)** | XR releases on CCO |
| cisco8000v (8201 emulator) | cisco_c8000 | ENTITLEMENT (Cisco account team) | Cisco 8000 emulator tarball, local docker build | no (own build scripts) | yes | heavy (>10 GB, unconfirmed) | niche | none known | with entitlement |
| crpd | juniper_crpd | FREE TRIAL REG | Juniper support downloads (`crpdtrial`) + free trial license | no | no | ~0.25–2 GB | good | **HIGH — config via `netlab-config.sh` bind (FRR-pattern)** | versions on portal (needs account) |
| csrx | juniper_csrx | FREE TRIAL REG (60-day) | juniper.net cSRX free trial; Agile licensing after | no | no | ~1–2 GB | minimal | **HIGH — same sh-script bind pattern** | limited |
| vjunos-router | juniper_vjunosrouter | FREE (download, no license) | support.juniper.net/support/downloads/?p=vjunos-router (qcow2) | yes | yes | ~5 GB / 4 vCPU | full | none — Junos netconf/SSH push | several releases (23.x–25.x) |
| vjunos-switch | juniper_vjunosswitch | FREE (download, no license) | support.juniper.net/support/downloads/?p=vjunos-switch | yes | yes | ~5 GB / 4 vCPU; ~15 min boot | full | none | several releases |
| vptx (vJunosEvolved) | juniper_vjunosevolved | FREE (download, no license) | juniper.net vJunos labs page → vJunosEvolved qcow2 | yes | yes | ~8 GB / 4 vCPU | full | none | several releases |
| vsrx | vr-vsrx | REG + eval (30-day) / paid | Juniper account, vSRX eval qcow2 | yes | yes | ~4 GB / 2 vCPU | best effort | none | limited |
| vmx | vr-vmx | CONTRACT (legacy, effectively EOL) | Juniper contract download (18.x-era qcow) | yes | yes | ~6–8 GB | best effort | none | poor |
| sros (vSIM) | vr-sros | CONTRACT — **known blocked on client qcow2 + license** (docs/nokia-sros.md) | Nokia customer portal | yes | yes | ~4–6 GB | best effort | none | with license, any release |
| srsim (SR-SIM) | nokia_srsim | CONTRACT-ish — Nokia portal + **1-year subscription license** | Nokia portal `srsim.tar.xz`, `docker image load`; license mounted at `/nokia/license/license.txt` | no — **native container** | no | ~4–8 GB (unconfirmed) | full | none | with license |
| routeros7 (CHR) | vr-ros | FREE (free license tier: 1 Mbit/s per-interface cap) | mikrotik.com/download/chr → `chr.vmdk` → vrnetlab | yes | yes | ~0.5 GB | minimal | none | excellent: full version archive on mikrotik.com |
| dellos10 | vr-ftosv | ENTITLEMENT (Dell Digital Locker) | Dell Digital Locker OS10 virtualization zip → vrnetlab | yes | yes | ~4 GB (unconfirmed) | niche | none | poor |
| arubacx | vr-aoscx | FREE REG (Aruba Support Portal account) | ASP → AOS-CX Switch Simulator OVA (extract vmdk) → vrnetlab | yes | yes | ~4 GB (unconfirmed) | best effort | none | several OVA releases (10.07–10.13) |
| exos | linux (VM-in-ctr) | FREE PULL (GitHub!) | github.com/extremenetworks/Virtual_EXOS qcow2 → vrnetlab (`build: true`) | yes | yes | ~1 GB (unconfirmed) | minimal | none | good: 32.x/33.x qcow2s in repo |
| fortios | fortinet_fortigate | FREE REG (FortiCare) + eval license (feature-limited) | support.fortinet.com FGVM64-KVM "New deployment" zip → vrnetlab | yes | yes | ~2 GB | minimal | none — **httpapi transport (unique)** | 7.x versions with account; <7.2.0 had 15-day eval |
| openbsd | openbsd | FREE | vrnetlab `openbsd` builds from freely downloadable install image | yes | yes | ~0.5–1 GB | host-role | none | any OpenBSD release |
| netscaler | linux (native ctr) | FREE-ish (Citrix CPX express) | `netlab/netscaler` local build (`build: true`) over Citrix CPX container | no | no | ~1 GB | niche | none known | limited |

Transport-diversity note (from each device's `group_vars` locally): docker-exec (vyos, frr,
cumulus, linux, daemons), network_cli/SSH (eos, ios family incl. IOL, nxos, asav, arubacx,
dellos10, exos, routeros7, XR family), netconf (all Junos VMs), httpapi (fortios — the only
one), paramiko+gNMI vars (srlinux, sros/srsim). cRPD/cSRX/XRd use sh-scripts-over-bind — the
same mechanism the FRR gap analysis covers.

## Per-class acquisition instructions

### FREE PUBLIC PULL (no account)
- **FRR** — `docker pull quay.io/frrouting/frr:<tag>`. Blocked by the daemons-file bind until
  the inline-deploy gap is solved.
- **Nokia SR Linux** — `docker pull ghcr.io/nokia/srlinux[:tag]`; all versions public
  (https://github.com/nokia/srlinux-container-image).
- **VyOS** — `ghcr.io/sysoleg/vyos-container` (https://github.com/sysoleg/vyos-container);
  rolling only — LTS images are paid/subscription since 1.4, VyOS Stream quarterly
  (https://vyos.net/get/stream/).
- **Extreme EXOS** — qcow2s published openly at https://github.com/extremenetworks/Virtual_EXOS;
  build with srl-labs/vrnetlab.
- **Cumulus VX (dated)** — `networkop/cx:4.4.0` / `5.3.0` (https://github.com/networkop/cx);
  netlab marks both "out-of-date and not supported".
- **MikroTik CHR** — https://mikrotik.com/download/chr (`chr.vmdk`, full version archive),
  build via srl-labs/vrnetlab `routeros`; free license = 1 Mbit/s per-interface upload cap
  (https://help.mikrotik.com/docs/spaces/ROS/pages/18350234/Cloud+Hosted+Router+CHR).
- **OpenBSD** — vrnetlab builds from the free install image (containerlab `openbsd` kind).
- **bird / dnsmasq / kind / netscaler** — `netlab clab build <device>` (daemons/`build: true`),
  `kindest/node` from Docker Hub.

### FREE WITH REGISTRATION
- **Arista cEOS** — free arista.com account (**corporate email required** per netlab docs
  https://netlab.tools/labs/ceos/) → Support → Software Download → `cEOS64-lab-<ver>.tar.xz` →
  `docker import`. Long version back-catalog → best multi-version platform.
- **Juniper vJunos-switch / vJunos-router / vJunosEvolved** — free downloads, no license
  (https://www.juniper.net/us/en/dm/vjunos-labs.html;
  https://support.juniper.net/support/downloads/?p=vjunos-switch and `?p=vjunos-router`);
  containerlab docs even say no account needed. srl-labs/vrnetlab build; KVM; 5–8 GB/node;
  **cannot run nested inside a VM** (vJunos deployment caveat).
- **Cisco via CML-Free** — free single-user CML
  (https://developer.cisco.com/docs/modeling-labs/cml-free/) ships refplat images for **IOL,
  IOL-L2, ASAv** (5-node limit applies to CML itself, not to the image files). **Licensing
  caveat**: the CML SEULA licenses refplat images for use *within CML only*
  (https://developer.cisco.com/docs/modeling-labs/vm-images-for-cml-labs/) — extracting them
  for containerlab is common community practice but formally outside the SEULA. Maintainer
  call; Twinlab already runs IOL, so the position taken there extends here.
- **Fortinet FortiGate** — free FortiCare account → support.fortinet.com → FGVM64 KVM "New
  deployment" qcow2 → vrnetlab `fortigate`
  (https://containerlab.dev/manual/kinds/fortinet_fortigate/). Permanent eval license is
  feature/capacity-limited
  (https://docs.fortinet.com/document/fortigate-private-cloud/7.6.0/kvm-administration-guide/504166/fortigate-vm-evaluation-license).
- **Juniper cRPD** — free trial: https://www.juniper.net/us/en/dm/crpd-free-trial.html,
  download via https://support.juniper.net/support/downloads/?p=crpdtrial (account required).
  Native container, tiny — but bind-blocked config path today.
- **Juniper cSRX** — 60-day free trial
  (https://www.juniper.net/us/en/dm/csrx-container-firewall-free-trial.html); same bind caveat.
- **Aruba AOS-CX** — AOS-CX Switch Simulator OVA from the Aruba Support Portal (ASP account;
  latest 10.13.1000, Jan 2024 —
  https://airheads.hpe.com/discussion/latest-aruba-aos-cx-simulator-release); extract vmdk,
  vrnetlab `aoscx`. Whether a bare free ASP account suffices is unconfirmed.

### VENDOR ENTITLEMENT / PAID / CONTRACT
- **CML Personal ($199/yr, sales run ~$149)** — unlocks IOSv, IOSv-L2, CSR1000v, Catalyst
  8000v, Nexus 9300v refplat images
  (https://developer.cisco.com/docs/modeling-labs/reference-platforms-and-images/, price via
  https://www.netpilot.io/blog/cisco-cml-cost). Same SEULA caveat as above. One $199 spend
  covers five additional Cisco platforms.
- **Cisco XRd Control Plane** — CCO download, needs a service contract entitlement
  (https://xrdocs.io/virtual-routing/tutorials/2022-08-22-xrd-images-where-can-one-get-them,
  https://software.cisco.com/downloads). Native container, light — but FRR-pattern bind risk.
- **Cisco 8000 emulator** — via Cisco account team only
  (https://containerlab.dev/manual/kinds/c8000/).
- **Nokia SR-SIM** — Nokia customer portal + 1-year subscription license
  (https://documentation.nokia.com/sr/25-7/7x50-shared/srsim-installation-setup/obtaining-the-sr-sim-software.html);
  native container (no KVM) — the modern replacement for vSIM; same client-ask as SR OS vSIM
  (docs/nokia-sros.md).
- **Nokia SR OS vSIM (vr-sros)** — known blocked on client qcow2 + license.
- **Juniper vSRX** — account + 30-day eval or paid; **vMX** — legacy contract download, skip
  (vJunos-router is its free successor).
- **Dell OS10** — Dell Digital Locker, entitlement required
  (https://www.dell.com/community/Networking-General/Download-OS10-simulation/m-p/7859478);
  low value per effort.
- **Cumulus VX current** — NVIDIA re-published images ~March 2026 but behind a support
  contract; otherwise NVIDIA Air (hosted) only
  (https://blog.ipspace.net/2025/06/cumulus-linux-gone/,
  https://www.nvidia.com/en-in/networking/ethernet-switching/cumulus-vx/download/).

### EFFECTIVELY UNOBTAINABLE (for this project, today)
- vMX (practically), current Cumulus VX without a contract, Dell OS10 without Dell
  entitlement, Cisco 8000 emulator without an account-team relationship.

## Recommended acquisition order

Already in hand: VyOS, Cisco IOL, linux, SR Linux (parallel branch — fold in).

1. **Wave 1 — free pulls, no paperwork (days):** MikroTik CHR (vrnetlab starter — smallest KVM
   image, exercises the whole vrnetlab+KVM pipeline cheaply), Extreme EXOS (GitHub qcow2),
   OpenBSD, bird/dnsmasq (`netlab clab build`), kind. FRR and Cumulus only after the bind gap
   has an answer — free but currently dead on arrival through inline deploy.
2. **Wave 2 — registrations (a week, mostly waiting on accounts):** **Arista cEOS first** —
   highest coverage per effort: native container (no KVM), full netlab support, network_cli
   transport, deepest multi-version catalog for mixed-version topologies. Then the **vJunos
   trio** (free, full netlab support, netconf transport, but 5–8 GB/node + KVM + no-nested-virt
   — plan host capacity), **FortiGate eval** (the only httpapi transport), **CML-Free** (extra
   IOL versions + ASAv — surface the SEULA question to the maintainer once), **Aruba CX** (ASP
   account), **cRPD/cSRX trials** (park until the bind gap closes).
3. **Wave 3 — entitlements (weeks, needs budget/asks):** CML Personal $199 (IOSv, CSR,
   cat8000v, n9kv — four platforms, one purchase), XRd via whoever holds a Cisco service
   contract (bind-gap-dependent), Nokia SR-SIM added to the existing SR OS client ask (native
   container — easier to operate than vSIM), Dell OS10 / Cisco 8000 only if a client
   relationship supplies them.

**Diversity math:** Wave 1+2 alone covers native-container + VM-in-container + IOL-binary boot
mechanisms; docker-exec, network_cli, netconf, httpapi and gNMI-capable transports; four
interface-naming schemes — with cEOS, SR Linux, FRR (when unblocked) and CHR providing deep
multi-version pull-ability for large mixed-version topologies.

**Operational notes:** vrnetlab kinds need `/dev/kvm` on the clab-api host and images are built
locally (`git clone srl-labs/vrnetlab && make` per platform — images never distributed,
consistent with the licensing stance); vJunos-class nodes boot in ~10–15 min (blackbox timeouts
must stretch); nested-virt hosts can't run vJunos at all; 5-node mixed-VM labs want ~32 GB RAM
headroom.

## Key local findings (beyond acquisition)

- **Three more platforms share FRR's bind-dependent config path** — XRd, cRPD, and cSRX all
  deliver config via a `netlab-config.sh` shipped as a `config_templates` bind
  (`netsim/devices/iosxr.yml`, `crpd.yml`, `csrx.yml`), and cumulus binds
  `/etc/network/interfaces`. These are acquisition-worthy but will fail Twinlab's inline deploy
  exactly like FRR until that gap is solved — see `netlab-up-gaps.md` gap 4. IOL's
  `ifstate.cfg` bind and SR Linux/linux `hosts` binds are the proven-tolerable cases.
- bird/dnsmasq/kind daemons also deliver config through binds — untested risk.

## Flags — where 2026 reality may differ / unconfirmed

- Cumulus VX "re-published behind support contract as of March 2026" comes from one search
  summary; verify before relying on it.
- cEOS corporate-email-only registration is netlab-docs-sourced; may have changed.
- vJunos "no account needed" is containerlab-docs-sourced; Juniper's portal may still ask for
  one (free either way).
- CML-Free image set/limits checked against DevNet docs at CML 2.10; SEULA interpretation is
  ours, not legal advice.
- RAM figures marked "unconfirmed" (SR-SIM, EXOS, Dell OS10, Aruba CX, cisco8000v) were not
  verifiable from fetched pages.
- Dell OS10 downloadability without entitlement varies by account; community threads conflict.
- cSRX/cRPD trial terms may have shifted under the HPE-Juniper merger.

## Appendix — out of scope

**netlab devices without clab support (26.07):** `sonic` (libvirt/external only — containerlab
has free `sonic-vs` images, but netlab can't drive SONiC under clab, so it's blocked
netlab-side), `routeros` (v6, libvirt only), `junos`/`ios`/`xr` (meta parents),
`none`/`unknown` (test stubs).

**Containerlab kinds with no netlab device:** PAN-OS, Huawei VRP, Check Point CloudGuard,
IPInfusion OcNOS, Cisco FTDv/cat9kv/xrv9k, 6WIND VSR, Arrcus, FD.io VPP, RARE/freeRtr,
OpenWrt, SONiC-vs, and traffic generators (Keysight ixia-c-one — free pull, a future blackbox
traffic source; Ostinato). Juniper's new **cJunosEvolved** (containerized Junos Evolved, free
from the vJunos download area per its 2025 deployment guide) has no netlab device yet — a watch
item for future netlab releases.

Sources: [containerlab kinds](https://containerlab.dev/manual/kinds/),
[netlab platforms](https://netlab.tools/platforms/),
[srl-labs/vrnetlab](https://github.com/srl-labs/vrnetlab),
[vrnetlab manual](https://containerlab.dev/manual/vrnetlab/),
[netlab cEOS guide](https://netlab.tools/labs/ceos/),
[vJunos labs page](https://www.juniper.net/us/en/dm/vjunos-labs.html),
[vJunos-switch downloads](https://support.juniper.net/support/downloads/?p=vjunos-switch),
[XRd image sourcing (xrdocs)](https://xrdocs.io/virtual-routing/tutorials/2022-08-22-xrd-images-where-can-one-get-them),
[Nokia SR-SIM obtaining](https://documentation.nokia.com/sr/25-7/7x50-shared/srsim-installation-setup/obtaining-the-sr-sim-software.html),
[clab SR OS/SR-SIM kind](https://containerlab.dev/manual/kinds/sros/),
[MikroTik CHR](https://help.mikrotik.com/docs/spaces/ROS/pages/18350234/Cloud+Hosted+Router+CHR)
+ [download](https://mikrotik.com/download/chr),
[FortiGate eval license](https://docs.fortinet.com/document/fortigate-private-cloud/7.6.0/kvm-administration-guide/504166/fortigate-vm-evaluation-license)
+ [clab fortinet kind](https://containerlab.dev/manual/kinds/fortinet_fortigate/),
[cRPD trial](https://www.juniper.net/us/en/dm/crpd-free-trial.html),
[cSRX trial](https://www.juniper.net/us/en/dm/csrx-container-firewall-free-trial.html),
[CML-Free](https://developer.cisco.com/docs/modeling-labs/cml-free/),
[CML VM image policy](https://developer.cisco.com/docs/modeling-labs/vm-images-for-cml-labs/),
[CML SEULA](https://www.cisco.com/c/dam/en_us/about/doing_business/legal/seula/Cisco-Modeling-Labs-SEULA.pdf),
[CML pricing](https://www.netpilot.io/blog/cisco-cml-cost),
[Virtual_EXOS](https://github.com/extremenetworks/Virtual_EXOS),
[Cumulus gone (ipSpace)](https://blog.ipspace.net/2025/06/cumulus-linux-gone/),
[Cumulus VX download page](https://www.nvidia.com/en-in/networking/ethernet-switching/cumulus-vx/download/),
[networkop/cx](https://github.com/networkop/cx),
[AOS-CX simulator thread](https://airheads.hpe.com/discussion/latest-aruba-aos-cx-simulator-release),
[Dell OS10 thread](https://www.dell.com/community/Networking-General/Download-OS10-simulation/m-p/7859478),
[clab c8000 kind](https://containerlab.dev/manual/kinds/c8000/),
[clab cisco_iol kind](https://containerlab.dev/manual/kinds/cisco_iol/),
[clab vJunos-switch kind](https://containerlab.dev/manual/kinds/vr-vjunosswitch/),
[clab cEOS kind](https://containerlab.dev/manual/kinds/ceos/),
[nokia/srlinux-container-image](https://github.com/nokia/srlinux-container-image),
[sysoleg/vyos-container](https://github.com/sysoleg/vyos-container),
[VyOS Stream](https://vyos.net/get/stream/).
