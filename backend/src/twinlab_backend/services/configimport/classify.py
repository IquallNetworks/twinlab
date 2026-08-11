"""The three-bucket split: every stanza line lands in exactly one bucket.

MODELED lines are what the thin skeleton makes netlab regenerate — the
hostname and each modeled interface's primary address (plus its stanza
header when nothing else in the stanza survives). QUARANTINED stanzas are
the platform rule lists below — config referencing the production
environment rather than the network's own behavior — plus every
management-VRF interface stanza and (IOS) mgmt-VRF routes/definitions.
Everything else is CARRIED verbatim.

The rule lists are code, not contract: the four classes are pinned
(`QUARANTINE_CLASSES`), the line lists may grow. Routing policy, ACLs, QoS
and non-mgmt VRFs are NEVER quarantined — they carry and apply.

Per-platform behaviour is a `ClassifySpec` record, never a branch: `split_buckets`
reads the spec it is handed and knows no device names. The specs live here rather
than in each platform's module so the pinned classes can be audited across
platforms side by side — `auth` must mean the same thing everywhere.
"""

import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from twinlab_backend.services.configimport.model import (
    ParsedSource,
    QuarantineClass,
    Stanza,
)

# (class, stanza-key prefix): a stanza whose key starts with the prefix is
# quarantined under the class.
type KeyRule = tuple[QuarantineClass, tuple[str, ...]]

# How a platform's interface stanza carries its identity — the one genuine
# syntactic axis in this module:
#   "flat"  — every line is an independent command (VyOS `set …`). Consuming a
#             modeled address just drops that line; there is no header.
#   "block" — an indented body under a header line (IOS `interface Gi0/0`). The
#             header is carried while any child survives and modeled when the
#             address was the stanza's only content.
type StanzaForm = Literal["flat", "block"]

# The regex matching the ONE line the skeleton models for an interface, built
# from (interface name, pinned CIDR).
type AddressPattern = Callable[[str, str], re.Pattern[str]]

# Structural quarantine beyond the key rules, given the source's mgmt VRFs.
type MgmtRule = Callable[[Stanza, frozenset[str]], QuarantineClass | None]


@dataclass(frozen=True, slots=True)
class ClassifySpec:
    """Everything `split_buckets` needs to know about one platform's syntax.

    Adding a platform is a new value of this record — never a new branch, and
    never an `else` that silently means an existing platform."""

    quarantine_rules: tuple[KeyRule, ...]
    address_pattern: AddressPattern
    stanza_form: StanzaForm
    # None where the platform expresses management scope only through interface
    # VRF membership, which `split_buckets` already handles generically.
    mgmt_rule: MgmtRule | None = None


_IOS_RULES: tuple[KeyRule, ...] = (
    ("auth", ("aaa",)),
    ("auth", ("tacacs",)),
    ("auth", ("tacacs-server",)),
    ("auth", ("radius",)),
    ("auth", ("radius-server",)),
    ("auth", ("username",)),
    ("auth", ("enable",)),
    ("auth", ("crypto",)),
    ("auth", ("line",)),
    ("auth", ("ip", "ssh")),
    ("telemetry", ("ntp",)),
    ("telemetry", ("snmp-server",)),
    ("telemetry", ("logging",)),
    ("telemetry", ("flow", "exporter")),
    ("hardware", ("version",)),
    ("hardware", ("boot",)),
    ("hardware", ("boot-start-marker",)),
    ("hardware", ("boot-end-marker",)),
    ("hardware", ("license",)),
    ("hardware", ("platform",)),
    ("hardware", ("hw-module",)),
    ("hardware", ("redundancy",)),
    ("hardware", ("diagnostic",)),
)

_VYOS_RULES: tuple[KeyRule, ...] = (
    ("auth", ("system", "login")),
    ("auth", ("service", "ssh")),
    ("telemetry", ("system", "ntp")),
    ("telemetry", ("system", "syslog")),
    ("telemetry", ("system", "sflow")),
    ("telemetry", ("service", "snmp")),
    ("hardware", ("system", "console")),
)

_IOS_MGMT_ROUTE_RE = re.compile(r"^ip route vrf (\S+)\s")


@dataclass(frozen=True, slots=True)
class CarriedBlock:
    lines: tuple[str, ...]
    interface: str | None  # set for interface stanzas — the rewrite target


@dataclass(frozen=True, slots=True)
class QuarantinedBlock:
    reason: QuarantineClass
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BucketSplit:
    modeled: tuple[str, ...]
    carried: tuple[CarriedBlock, ...]
    quarantined: tuple[QuarantinedBlock, ...]


def _key_rule(rules: tuple[KeyRule, ...], stanza: Stanza) -> QuarantineClass | None:
    for reason, prefix in rules:
        if stanza.key[: len(prefix)] == prefix:
            return reason
    return None


def _ios_address_re(interface: str, cidr: str) -> re.Pattern[str]:
    """The IOS line the skeleton models: the primary `ip address` spelled
    with a dotted mask (matched within the interface's own stanza, so the
    name itself is not part of the pattern)."""
    _ = interface
    parsed = ipaddress.IPv4Interface(cidr)
    ip, mask = str(parsed.ip), str(parsed.network.netmask)
    return re.compile(rf"^\s*ip address {re.escape(ip)} {re.escape(mask)}\s*$")


def _vyos_address_re(interface: str, cidr: str) -> re.Pattern[str]:
    return re.compile(
        rf"^set interfaces \S+ {re.escape(interface)} address ['\"]?{re.escape(cidr)}['\"]?$"
    )


def split_buckets(
    parsed: ParsedSource,
    *,
    spec: ClassifySpec,
    modeled_addresses: dict[str, str],
    mgmt_interfaces: frozenset[str],
    mgmt_vrfs: frozenset[str],
) -> BucketSplit:
    """Assign every stanza (or line within an interface stanza) to a bucket.
    `modeled_addresses` maps interface name -> the primary CIDR the skeleton
    pins (link endpoints, stubs, the loopback pin); an interface absent from
    it keeps its address line in the carry."""
    modeled: list[str] = []
    carried: list[CarriedBlock] = []
    quarantined: list[QuarantinedBlock] = []
    for stanza in parsed.stanzas:
        if stanza.kind == "hostname":
            modeled.extend(stanza.lines)
            continue
        if stanza.kind == "interface" and stanza.interface is not None:
            if stanza.interface in mgmt_interfaces:
                quarantined.append(QuarantinedBlock(reason="mgmt", lines=stanza.lines))
                continue
            cidr = modeled_addresses.get(stanza.interface)
            if cidr is None:
                carried.append(CarriedBlock(lines=stanza.lines, interface=stanza.interface))
                continue
            pattern = spec.address_pattern(stanza.interface, cidr)
            kept = [line for line in stanza.lines if pattern.match(line) is None]
            taken = [line for line in stanza.lines if pattern.match(line) is not None]
            modeled.extend(taken)
            if spec.stanza_form == "flat" or not kept:
                if kept:
                    carried.append(CarriedBlock(lines=tuple(kept), interface=stanza.interface))
                continue
            # A block stanza's header line survives the address match by
            # construction (the pattern matches an address line only), so
            # `kept` is non-empty here for every real block platform; the
            # guard above keeps an empty one from unpacking.
            header, *children = kept
            if children:
                carried.append(CarriedBlock(lines=(header, *children), interface=stanza.interface))
            else:
                modeled.append(header)
            continue
        # Non-interface stanzas: rule lists, then the platform's own structural
        # management rule (IOS mgmt-VRF routes and definitions).
        reason = _key_rule(spec.quarantine_rules, stanza)
        if reason is None and spec.mgmt_rule is not None:
            reason = spec.mgmt_rule(stanza, mgmt_vrfs)
        if reason is not None:
            quarantined.append(QuarantinedBlock(reason=reason, lines=stanza.lines))
        else:
            carried.append(CarriedBlock(lines=stanza.lines, interface=None))
    return BucketSplit(
        modeled=tuple(modeled), carried=tuple(carried), quarantined=tuple(quarantined)
    )


def _ios_mgmt_reason(stanza: Stanza, mgmt_vrfs: frozenset[str]) -> QuarantineClass | None:
    """Mgmt-VRF routes and the VRF definition itself belong to the source's
    OOB plane, which the lab replaces."""
    if not mgmt_vrfs:
        return None
    if stanza.key == ("ip", "route"):
        match = _IOS_MGMT_ROUTE_RE.match(stanza.lines[0])
        if match is not None and match.group(1) in mgmt_vrfs:
            return "mgmt"
    if stanza.key == ("vrf", "definition") and any(
        stanza.lines[0] == f"vrf definition {vrf}" for vrf in mgmt_vrfs
    ):
        return "mgmt"
    return None


# The per-platform specs. Defined last so they can name the rules and helpers
# above; assembled into the full importer records in `platforms.py`.
IOS_CLASSIFY = ClassifySpec(
    quarantine_rules=_IOS_RULES,
    address_pattern=_ios_address_re,
    stanza_form="block",
    mgmt_rule=_ios_mgmt_reason,
)

VYOS_CLASSIFY = ClassifySpec(
    quarantine_rules=_VYOS_RULES,
    address_pattern=_vyos_address_re,
    stanza_form="flat",
)
