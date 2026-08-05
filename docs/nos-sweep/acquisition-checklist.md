# Acquisition checklist — what the maintainer needs to obtain (strand 17.1)

> **PARKED TO AFTER v1.0 (2026-08-05, maintainer's call) — ROADMAP item 21.** Nothing on this
> list gates the release any more. v1.0 ships on the six platforms already tested and admitted
> (VyOS, FRR, MikroTik CHR, bird, dnsmasq, linux); strand 17.1's remaining v1.0 work is the
> large mixed-NOS topology over that set, which needs nothing from anyone. This file stays the
> actionable detail — every URL, account cost, build path and what each platform unlocks — so
> the post-v1.0 pickup is a matter of reading it, not re-researching it. The ordering below is
> still the agreed priority.

Actionable form of `nos-availability.md`. Everything here needs a human: an account, an
acceptance of terms, or a purchase. **Images are used, never redistributed** — every build is
local, consistent with Twinlab's licensing stance.

Ordering rationale: cEOS first (most coverage per unit of effort), then the free-but-heavy
Junos family, then the ones that unlock a transport or a version spread we have no other
source for.

---

## 1. Arista cEOS — do this one first

- **Register:** https://www.arista.com/en/login (free account; netlab's guide says a corporate
  email is required — https://netlab.tools/labs/ceos/)
- **Download:** Support → Software Download → *cEOS-lab* → `cEOS64-lab-<version>.tar.xz`
- **Get 2–3 versions**, e.g. a current 4.3x plus one or two older 4.2x — cEOS has the deepest
  back-catalog of anything on the list and is what makes a mixed-*version* topology possible.
- **Install:** `docker import cEOS64-lab-<ver>.tar.xz ceos:<ver>` (no vrnetlab, no KVM)
- **Why first:** native container, full netlab support, `network_cli` transport (so it also
  exercises the runner-collection path with `arista.eos`), ~2 GB/node.

## 2. Juniper vJunos family — free, no license, but heavy

- **Download (account may not even be required):**
  - vJunos-router — https://support.juniper.net/support/downloads/?p=vjunos-router
  - vJunos-switch — https://support.juniper.net/support/downloads/?p=vjunos-switch
  - vJunosEvolved — https://www.juniper.net/us/en/dm/vjunos-labs.html
- **Build:** `srl-labs/vrnetlab` (already cloned at `~/devel/vrnetlab-work/vrnetlab`), drop the
  qcow2 in the matching directory, `make docker-image`
- **Cost:** 5–8 GB RAM and 4 vCPU *per node*, ~15-minute boots. This host has 31 GB and
  nested virt is enabled, so it can run them — a 3-node vJunos lab is roughly the ceiling.
- **Unlocks:** the netconf transport (collection `junipernetworks.junos`).

## 3. Fortinet FortiGate — the only httpapi transport

- **Register:** https://support.fortinet.com (free FortiCare account)
- **Download:** FortiGate-VM → *FGVM64* → **KVM** → "New deployment" zip → extract the qcow2
- **Build:** vrnetlab `fortinet/fortigate`
- **Note:** the permanent evaluation license is feature- and capacity-limited
  (https://docs.fortinet.com/document/fortigate-private-cloud/7.6.0/kvm-administration-guide/504166/fortigate-vm-evaluation-license)
  — fine for a transport probe.

## 4. Aruba AOS-CX

- **Register:** Aruba Support Portal (https://asp.arubanetworks.com) — whether a bare free
  account suffices is unconfirmed; that is part of what this step establishes.
- **Download:** AOS-CX Switch Simulator OVA (latest is 10.13.1000), extract the vmdk
- **Build:** vrnetlab `aruba/aoscx`

## 5. Cisco — CLOSED for now (decided 2026-08-05)

**Nothing to obtain here.** The CML licensing question was answered: Cisco licenses its
reference-platform images for use *inside CML only*
(https://developer.cisco.com/docs/modeling-labs/vm-images-for-cml-labs/,
https://www.cisco.com/c/dam/en_us/about/doing_business/legal/seula/Cisco-Modeling-Labs-SEULA.pdf),
and the maintainer took the conservative stance — so **Cisco IOL was withdrawn from the
supported set**, and everything gated behind that licence is off the list:

- ~~**CML-Free**~~ — would have added ASAv and extra IOL *versions* (the mixed-version case).
- ~~**CML Personal, $199/yr**~~ — would have added IOSv, IOSv-L2, CSR1000v, Catalyst 8000v and
  Nexus 9300v.

Revisiting the stance is a **post-v1.0** item (ROADMAP item 20); if it reverses, this section
comes back as written above and IOL re-admission is largely a revert.

**Still open, because it is NOT under the CML SEULA:**

- **XRd Control Plane** — https://software.cisco.com/downloads, needs a **service contract**
  entitlement (https://xrdocs.io/virtual-routing/tutorials/2022-08-22-xrd-images-where-can-one-get-them).
  Native container, light (~2 GB), no KVM. Worth asking whoever holds a Cisco contract — this
  is the one Cisco platform the licensing decision does not block.
- **Cisco 8000 emulator** — Cisco account team only; heavy, low value per effort.

## 6. Nokia — PARKED for now (decided 2026-08-05)

SR OS vSIM stays blocked on a customer qcow2 + licence (`nokia/docs/nokia-sros.md`), and
**SR-SIM was considered and parked rather than added to the ask**. Two reasons: it is 25.x-era
only, so it cannot run the releases the client actually holds (TiMOS 22.10.R3 / 24.10.R7), and
its licence is an **annual subscription** mounted at `/nokia/license/license.txt` — no licence
means the container will not boot, and expiry reboots it
(https://documentation.nokia.com/sr/25-7/7x50-shared/srsim-installation-setup/obtaining-the-sr-sim-software.html).
That is a recurring obligation, not a one-time file, which is worth naming before recommending
it.

Kept here because it stays the better long-term Nokia target: SR-SIM is a *native container*
(no KVM, no vrnetlab wrapper), which deletes the top SR OS risk — vrnetlab wires its datapath
with tc `mirred` filters on the very interfaces Twinlab writes netem to. Probe the
**integrated** (pizza-box) chassis first if it is ever picked up; the distributed ones are one
CPM container plus an IOM container per line card sharing a netns, i.e. several containers per
netlab node.

**The free Nokia win, also parked:** SR Linux needs no acquisition at all
(`ghcr.io/nokia/srlinux`, no account, no licence) and is already proven end to end on the
parallel `nokia/` tree. Admitting it on `dev` is runner plumbing only — that tree's
`nokia.grpc`/`nokia.srlinux` collections, `grpcio`/`protobuf`, and
`PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` have never been ported here.

## 7. Juniper cRPD / cSRX — low effort, now unblocked

Both deliver config through a `netlab-config.sh` bind, which the `LAB_FILES_DIR` work fixed, so
they are worth a trial now.

- cRPD free trial — https://www.juniper.net/us/en/dm/crpd-free-trial.html → download via
  https://support.juniper.net/support/downloads/?p=crpdtrial
- cSRX 60-day trial — https://www.juniper.net/us/en/dm/csrx-container-firewall-free-trial.html

---

## Already in hand — nothing needed from you

VyOS, linux, FRR, bird, dnsmasq, kind, MikroTik CHR 7.16.2 (built from the free vmdk at
`~/devel/vrnetlab-work/vrnetlab/mikrotik/routeros/`), and Nokia SR Linux (parallel branch).
The IOL image is on the host too, but is no longer used — the platform was withdrawn on
licensing (§5).

Free and unblocked, no account needed — I can take these whenever you want them:
**Extreme EXOS** (qcow2s published openly at https://github.com/extremenetworks/Virtual_EXOS)
and **OpenBSD** (vrnetlab builds from the free install image). Both currently sit as parked
negatives in `results.md`.

## When something arrives

Hand me the file or tell me it is on the host and I will build it, probe it through Twinlab
(deploy → config push → protocol state → the link/facts surfaces), record the evidence in
`results.md`, and — per your standing call that everything tested and supported gets
admitted — run the full admission in `admitting-a-platform.md`: catalog + frontend fallback,
kmods/hostprep, the runner's Ansible collection (plus a netmiko `device_type` if its transport
is SSH), and a connection override if netlab names a plugin ansible no longer ships.

**Two bars, not one** (2026-08-05): a platform must work *and* its image must be one we may
legitimately run here. IOL cleared the first and failed the second.
