"""The normalized facts model every platform parser produces.

A parsed source config is an ordered sequence of verbatim STANZAS — blocks
that classify as one unit — plus the extracted structural facts (hostname,
interfaces) that link inference and the three-bucket split consume. Every
normalized source line lives in exactly one stanza, so assigning buckets
per stanza (or per line within one) preserves the completeness invariant —
modeled, carried and quarantined together partition the source — by
construction.

Normalization caveat, deliberate: for VyOS the invariant is defined over the
flat set-command form — `show configuration commands` output IS that form,
and the brace format converts to it by VyOS's own equivalence. IOS stanzas
keep the source lines verbatim.
"""

from dataclasses import dataclass, field
from typing import Literal

# Where a line can land (contract delta 22): modeled config is consumed into
# the skeleton (netlab regenerates it natively — it must never also ride the
# carry), carried config applies verbatim via custom-config, quarantined
# config is kept visible but unattached by default.
type Bucket = Literal["modeled", "carried", "quarantined"]

# The pinned quarantine classes (the contract's QUARANTINE_CLASSES).
type QuarantineClass = Literal["mgmt", "auth", "telemetry", "hardware"]

type StanzaKind = Literal["hostname", "interface", "other"]


@dataclass(frozen=True, slots=True)
class SourceInterface:
    """One INFERABLE interface as the source config declares it. Interface
    types the importer cannot realize in a lab (bonds, bridges, tunnels, …)
    are deliberately absent — their config rides the carry with a warning."""

    name: str
    ipv4: str | None  # primary IPv4 CIDR; None = unnumbered/DHCP/L2-only
    vrf: str | None  # VRF membership — feeds mgmt-VRF quarantine detection
    shutdown: bool
    loopback: bool


@dataclass(frozen=True, slots=True)
class Stanza:
    """A verbatim block of normalized source lines that classifies as one
    unit. `key` is the platform's structural key for classification (VyOS:
    the set-path prefix the block groups under; IOS: the first word of the
    top-level line)."""

    lines: tuple[str, ...]
    kind: StanzaKind
    key: tuple[str, ...]
    interface: str | None = None  # kind == "interface" only


@dataclass(frozen=True, slots=True)
class ParsedSource:
    """One source config, parsed: the facts inference needs plus the stanza
    sequence the bucket split consumes. `warnings` are parse-level fidelity
    notes (a VLAN subinterface that will not be inferred, an uninferable
    interface type) — never silent, never fatal."""

    hostname: str | None
    interfaces: tuple[SourceInterface, ...]
    stanzas: tuple[Stanza, ...]
    warnings: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class ParseError:
    """The source could not be parsed at all (422 `config_unparseable`)."""

    message: str


@dataclass(frozen=True, slots=True)
class Note:
    """One import warning: a named fidelity hazard, never silent, never
    fatal. `node` is None for network-level notes."""

    node: str | None
    message: str
