"""The deployable-device catalog (contract delta 18).

The device SET is policy — the tested platforms of CLAUDE.md's Current State
(vyos, iol) plus the linux host device; widening it is a maintainer decision
that starts with testing (the NOS sweep), never a quiet edit here. Each
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
    ),
    CatalogDeviceSpec(
        device="iol",
        label="Cisco IOL",
        role="router",
        modules=(
            "bfd",
            "bgp",
            "dhcp",
            "eigrp",
            "evpn",
            "gateway",
            "isis",
            "mpls",
            "ospf",
            "ripv2",
            "routing",
            "sr",
            "srv6",
            "vlan",
            "vrf",
            "vxlan",
        ),
        image="vrnetlab/cisco_iol:17.16.01a",
    ),
    CatalogDeviceSpec(
        device="linux",
        label="Linux host",
        role="host",
        modules=("lag", "routing", "vlan"),
        image="python:3.13-alpine",
    ),
)


def image_reference(image: str) -> str:
    """Docker-normalized repo:tag for presence matching: an untagged name
    means ":latest". Only the segment after the last "/" can carry a tag —
    a ":" before it is a registry port, not a tag separator."""
    last_segment = image.rsplit("/", 1)[-1]
    return image if ":" in last_segment else f"{image}:latest"
