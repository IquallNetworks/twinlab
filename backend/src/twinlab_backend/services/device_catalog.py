"""The deployable-device catalog (contract delta 18).

The device SET is policy — the tested platforms of CLAUDE.md's Current State
(vyos, frr, routeros7 plus the bird and dnsmasq daemons) and the linux
host device; widening it is a maintainer decision that starts with testing
(the NOS sweep — evidence per platform in docs/nos-sweep/results.md), never a
quiet edit here. Narrowing it is one too: Cisco IOL was admitted and then
WITHDRAWN 2026-08-05 on licensing, not on behaviour — it deploys and
configures fine, but its only legitimate source is the CML reference-platform
set, which Cisco licenses for use inside CML only (ROADMAP 17.1). Each
entry's module list and default image are DATA mirrored from the installed
netlab and drift-guarded by tests (the kmods pattern in services/netlab.py),
so catalog reads never pay a netlab subprocess.
"""

from dataclasses import dataclass
from typing import Literal

DeviceRole = Literal["router", "host"]


@dataclass(frozen=True, slots=True)
class CatalogDeviceSpec:
    device: str  # netlab device slug — what a definition's `device:` takes
    label: str
    role: DeviceRole  # "router" = configurable NOS; "host" = plain container
    # netlab config modules the device supports UNDER THE CLAB PROVIDER
    # (netlab's module-support view; a provider-keyed entry without "clab" —
    # e.g. linux dhcp, libvirt-only — does not count).
    modules: tuple[str, ...]
    image: str  # netlab's default clab image (untagged means ":latest")
    # True when the device's image can never be pulled from a public registry:
    # built from a vendor download by vrnetlab (routeros7), or built by netlab
    # itself (`netlab clab build`, the daemons). The deploy image pre-flight
    # (up-parity gap 3) fails fast on a
    # missing local-only image, where a missing pullable one is only a
    # warning — docker pulls at deploy.
    local_only: bool


# The vyos image PIN (maintainer decision 2026-08-07). netlab's default —
# ghcr.io/sysoleg/vyos-container — publishes exactly ONE tag (:latest, a VyOS
# rolling nightly rebuilt upstream at will), so "the same definition always
# produces the same environment" held only until the next upstream rebuild.
# The pin is a LOCAL tag: host setup pulls the exact build by DIGEST and tags
# it (see README "Node images"), the tag names the VyOS version inside, and
# `create_clab_topology` writes the override into every netlab workdir
# (topology-defaults.yml) so netlab emits it into the clab topology. Bumping
# the pin is a deliberate act: pick a new upstream digest, read its
# /etc/os-release version, update BOTH constants and the README commands.
#   Upstream build: ghcr.io/sysoleg/vyos-container
#     @sha256:dc8d4233b2b7e9e94d96fd8d10a40a6b256c5d1aec1c960e02cdf835ca68fe50
_VYOS_PINNED_IMAGE = "twinlab/vyos:2026.05.30-0046-rolling"

# Devices whose deploy image deliberately DIVERGES from netlab's default —
# written into every `netlab create` workdir as topology-defaults.yml. Keys
# are catalog slugs; the drift guard checks these against the catalog specs
# and still watches netlab's own default for upstream moves.
IMAGE_PINS: dict[str, str] = {"vyos": _VYOS_PINNED_IMAGE}

SUPPORTED_DEVICES: tuple[CatalogDeviceSpec, ...] = (
    CatalogDeviceSpec(
        device="vyos",
        label="VyOS",
        role="router",
        modules=(
            "bfd",
            "bgp",
            "evpn",
            "gateway",
            "isis",
            "lag",
            "mpls",
            "ospf",
            "ripv2",
            "routing",
            "vlan",
            "vrf",
            "vxlan",
        ),
        image=_VYOS_PINNED_IMAGE,
        # Local tag by definition — the registry has no such tag to pull, so
        # a missing image must fail the pre-flight fast, not "warn and let
        # docker pull" its way into a late clab-api error.
        local_only=True,
    ),
    CatalogDeviceSpec(
        device="frr",
        label="FRRouting",
        role="router",
        modules=(
            "bfd",
            "bgp",
            "evpn",
            "gateway",
            "isis",
            "lag",
            "mpls",
            "ospf",
            "ripv2",
            "routing",
            "sr",
            "srv6",
            "stp",
            "vlan",
            "vrf",
            "vxlan",
        ),
        image="quay.io/frrouting/frr:10.6.1",
        local_only=False,
    ),
    CatalogDeviceSpec(
        device="routeros7",
        label="MikroTik RouterOS 7 (CHR)",
        role="router",
        modules=("bfd", "bgp", "mpls", "ospf", "vlan", "vrf", "vxlan"),
        image="vrnetlab/mikrotik_routeros:7.21.4",
        local_only=True,
    ),
    CatalogDeviceSpec(
        device="bird",
        label="BIRD routing daemon",
        role="router",
        modules=(
            "bfd",
            "bgp",
            "evpn",
            "gateway",
            "lag",
            "ospf",
            "routing",
            "vlan",
            "vrf",
            "vxlan",
        ),
        image="netlab/bird:latest",
        local_only=True,
    ),
    CatalogDeviceSpec(
        device="dnsmasq",
        label="dnsmasq DHCP/DNS server",
        role="host",
        modules=("dhcp", "lag", "routing", "vlan"),
        image="netlab/dnsmasq:latest",
        local_only=True,
    ),
    CatalogDeviceSpec(
        device="linux",
        label="Linux host",
        role="host",
        modules=("lag", "routing", "vlan"),
        image="python:3.13-alpine",
        local_only=False,
    ),
)

# The pre-flight's fatal set, derived so it can never drift from the catalog.
LOCAL_ONLY_DEVICES: frozenset[str] = frozenset(
    spec.device for spec in SUPPORTED_DEVICES if spec.local_only
)

# The supported slugs, derived for membership checks (a user config-template
# variant's `device` scope must name one — contract delta 27).
CATALOG_DEVICE_SLUGS: frozenset[str] = frozenset(spec.device for spec in SUPPORTED_DEVICES)


def image_reference(image: str) -> str:
    """Docker-normalized repo:tag for presence matching: an untagged name
    means ":latest". Only the segment after the last "/" can carry a tag —
    a ":" before it is a registry port, not a tag separator."""
    last_segment = image.rsplit("/", 1)[-1]
    return image if ":" in last_segment else f"{image}:latest"
