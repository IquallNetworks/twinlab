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
        image="ghcr.io/sysoleg/vyos-container",
        local_only=False,
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


def image_reference(image: str) -> str:
    """Docker-normalized repo:tag for presence matching: an untagged name
    means ":latest". Only the segment after the last "/" can carry a tag —
    a ":" before it is a registry port, not a tag separator."""
    last_segment = image.rsplit("/", 1)[-1]
    return image if ":" in last_segment else f"{image}:latest"
