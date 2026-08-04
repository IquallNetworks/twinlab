"""Cisco IOS boundary parser: running-config text → the normalized model.

netutils' IOSConfigParser (Apache-2.0) supplies the structural parent/child
line tree; the semantic extraction on top is ours. A stanza is one top-level
line plus its children, verbatim — leading whitespace preserved, so the carry
re-applies byte-exact. Dump FRAMING — the `Building configuration…` /
`Current configuration…` banner and the trailing `end` — is not config and
has no representation (the VyOS brace-comment equivalent); everything else,
`version` and `boot-start-marker` included, stays for the bucket split.
"""

import ipaddress
import re

from netutils.config.parser import IOSConfigParser

from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services.configimport.model import (
    ParsedSource,
    ParseError,
    SourceInterface,
    Stanza,
)

# Dump framing (not config): dropped like the trailing `end`.
_FRAMING_PREFIXES = ("Building configuration", "Current configuration")

_LOOPBACK_RE = re.compile(r"^Loopback\d+$", re.IGNORECASE)

# Interface families the lab cannot realize as a veth endpoint: their config
# rides the carry with a warning. Anything else carrying an address is a
# realizable LINK endpoint — including Serial (the link maps onto a lab
# ethernet; serial-specific lines stay in the carry and fail honestly).
_UNINFERABLE_PREFIXES = (
    "Port-channel",
    "Vlan",
    "Tunnel",
    "BVI",
    "BDI",
    "Dialer",
    "Virtual-",
    "Group-Async",
    "NVI",
    "Cellular",
)

_IP_ADDRESS_RE = re.compile(r"^\s*ip address (\S+) (\S+)(\s+secondary)?\s*$")
_VRF_RE = re.compile(r"^\s*(?:ip )?vrf forwarding (\S+)\s*$")
_SHUTDOWN_RE = re.compile(r"^\s*shutdown\s*$")


def _primary_cidr(ip: str, mask: str, name: str, warnings: list[str]) -> str | None:
    try:
        return str(ipaddress.IPv4Interface(f"{ip}/{mask}"))
    except ValueError:
        warnings.append(f"interface {name}: unparseable address {ip} {mask}; treated as unnumbered")
        return None


def _interface_facts(name: str, children: list[str], warnings: list[str]) -> SourceInterface | None:
    """The inferable facts of one interface stanza, or None (with a warning)
    for an interface the lab cannot realize."""
    if "." in name:
        warnings.append(f"subinterface {name} is not inferred; its config rides the carry")
        return None
    if name.startswith(_UNINFERABLE_PREFIXES):
        warnings.append(
            f"interface {name} cannot be realized in the lab; its config rides the carry"
        )
        return None

    ipv4: str | None = None
    vrf: str | None = None
    shutdown = False
    for child in children:
        address = _IP_ADDRESS_RE.match(child)
        if address is not None:
            if address.group(3) is None and ipv4 is None:
                ipv4 = _primary_cidr(address.group(1), address.group(2), name, warnings)
            continue
        vrf_match = _VRF_RE.match(child)
        if vrf_match is not None:
            vrf = vrf_match.group(1)
            continue
        if _SHUTDOWN_RE.match(child) is not None:
            shutdown = True
    return SourceInterface(
        name=name,
        ipv4=ipv4,
        vrf=vrf,
        shutdown=shutdown,
        loopback=_LOOPBACK_RE.match(name) is not None,
    )


def parse_ios(content: str) -> Result[ParsedSource, ParseError]:
    """Parse an IOS running-config dump into the facts model."""
    try:
        config_lines = IOSConfigParser(content).config_lines
    except Exception as exc:  # netutils raises assorted errors on malformed input
        return Err(ParseError(f"could not parse IOS config: {exc}"))

    # Group into (top-level line, children) stanzas, in source order.
    blocks: list[tuple[str, list[str]]] = []
    for line in config_lines:
        if line.parents:
            if not blocks:
                return Err(ParseError(f"orphaned child line {line.config_line[:80]!r}"))
            blocks[-1][1].append(line.config_line)
            continue
        top = line.config_line
        if top == "end" or top.startswith(_FRAMING_PREFIXES):
            continue
        blocks.append((top, []))

    hostname: str | None = None
    interfaces: list[SourceInterface] = []
    stanzas: list[Stanza] = []
    warnings: list[str] = []
    for top, children in blocks:
        lines = (top, *children)
        if top.startswith("hostname "):
            hostname = top.removeprefix("hostname ").strip()
            stanzas.append(Stanza(lines=lines, kind="hostname", key=("hostname",)))
            continue
        if top.startswith("interface "):
            name = top.removeprefix("interface ").strip()
            facts = _interface_facts(name, children, warnings)
            if facts is not None:
                interfaces.append(facts)
            stanzas.append(
                Stanza(lines=lines, kind="interface", key=("interface", name), interface=name)
            )
            continue
        stanzas.append(Stanza(lines=lines, kind="other", key=tuple(top.split()[:2])))

    if hostname is None and not any(s.kind == "interface" for s in stanzas):
        return Err(ParseError("does not look like an IOS config (no hostname, no interfaces)"))
    return Ok(
        ParsedSource(
            hostname=hostname,
            interfaces=tuple(interfaces),
            stanzas=tuple(stanzas),
            warnings=tuple(warnings),
        )
    )
