# Acquisition checklist — what the maintainer needs to obtain (strand 17.1)

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

## 5. Cisco — needs a decision from you first

**The open question:** the CML SEULA licenses the reference-platform images for use *inside
CML*. Extracting them for containerlab is common community practice but formally outside it
(https://developer.cisco.com/docs/modeling-labs/vm-images-for-cml-labs/,
https://www.cisco.com/c/dam/en_us/about/doing_business/legal/seula/Cisco-Modeling-Labs-SEULA.pdf).
Twinlab already runs Cisco IOL from that same source, so a position has effectively been
taken — but it should be a stated one, because it decides everything below.

- **CML-Free** (https://developer.cisco.com/docs/modeling-labs/cml-free/) — free, single user;
  ships **IOL, IOL-L2 and ASAv** refplat images. Cheapest way to add ASAv and more IOL
  versions.
- **CML Personal, $199/yr** (https://developer.cisco.com/docs/modeling-labs/reference-platforms-and-images/)
  — unlocks **IOSv, IOSv-L2, CSR1000v, Catalyst 8000v and Nexus 9300v**: five platforms for one
  purchase, and the only realistic route to n9kv.
- **XRd Control Plane** — https://software.cisco.com/downloads, needs a **service contract**
  entitlement (https://xrdocs.io/virtual-routing/tutorials/2022-08-22-xrd-images-where-can-one-get-them).
  Native container, light (~2 GB). Worth asking whoever holds a Cisco contract.

## 6. Nokia — the existing client ask

Already tracked in `docs/nokia-sros.md`: SR OS vSIM is blocked on a customer qcow2 + license.
**Add SR-SIM to the same ask** — Nokia's modern replacement, a *native container* (no KVM), so
it is materially easier to operate than vSIM
(https://documentation.nokia.com/sr/25-7/7x50-shared/srsim-installation-setup/obtaining-the-sr-sim-software.html).
It needs a 1-year subscription license file mounted at `/nokia/license/license.txt`.

## 7. Juniper cRPD / cSRX — low effort, now unblocked

Both deliver config through a `netlab-config.sh` bind, which the `LAB_FILES_DIR` work fixed, so
they are worth a trial now.

- cRPD free trial — https://www.juniper.net/us/en/dm/crpd-free-trial.html → download via
  https://support.juniper.net/support/downloads/?p=crpdtrial
- cSRX 60-day trial — https://www.juniper.net/us/en/dm/csrx-container-firewall-free-trial.html

---

## Already in hand — nothing needed from you

VyOS, Cisco IOL, linux, Nokia SR Linux (parallel branch), FRR, bird, dnsmasq, kind, and
MikroTik CHR 7.16.2 (built from the free vmdk at
`~/devel/vrnetlab-work/vrnetlab/mikrotik/routeros/`).

Free and unblocked, no account needed — I can take these whenever you want them:
**Extreme EXOS** (qcow2s published openly at https://github.com/extremenetworks/Virtual_EXOS)
and **OpenBSD** (vrnetlab builds from the free install image).

## When something arrives

Hand me the file or tell me it is on the host and I will build it, probe it through Twinlab
(deploy → config push → protocol state → the link/facts surfaces), record the evidence in
`results.md`, and — per your standing call that everything tested and supported gets
admitted — do the three-part admission: catalog, kmods/hostprep, and the runner's Ansible
collection for that platform's transport.
