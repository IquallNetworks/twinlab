"""VyOS boundary parser: both dump formats → the normalized facts model.

`show configuration commands` yields flat `set …` lines; `show configuration`
yields the brace tree. Both normalize to the SET form — VyOS's own
equivalence — and the completeness invariant is defined over that
normalization (config comments in the brace form have no set-form
representation and are the one thing normalization does not keep).

Pure code; the only `try`/`except` wraps tokenization. Quoting is preserved
verbatim in stanza lines (the carry re-applies them as-is) and stripped only
where a VALUE is inspected (addresses, hostnames).
"""

import shlex

from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services.configimport.model import (
    ParsedSource,
    ParseError,
    SourceInterface,
    Stanza,
    StanzaKind,
)

# Interface types under `interfaces` the importer can realize in a lab:
# ethernet joins link inference; loopback/dummy pin as loopbacks (VyOS labs
# use dummies as extra loopbacks). Everything else — bonding, bridge, tunnel,
# vti, wireguard, … — cannot exist in the lab's veth world, so its config
# rides the carry with a warning.
_ETHERNET = "ethernet"
_LOOPBACK_TYPES = frozenset({"loopback", "dummy"})

_HOSTNAME_KEY = ("system", "host-name")


def _unquote(token: str) -> str:
    """A set-command value token with its (matching) quotes stripped."""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        return token[1:-1]
    return token


def _tokenize(line: str) -> Result[list[str], ParseError]:
    try:
        # posix=False keeps quote characters in the tokens, so re-joining a
        # path reproduces the source spelling verbatim.
        return Ok(shlex.split(line, posix=False))
    except ValueError as exc:
        return Err(ParseError(f"could not tokenize {line!r}: {exc}"))


def _brace_to_paths(lines: list[str]) -> Result[list[tuple[str, ...]], ParseError]:
    """The brace tree as flat set-paths (leaf lines appended to their section
    stack). Comment blocks (`/* … */`) are skipped — they have no set-form
    representation."""
    paths: list[tuple[str, ...]] = []
    stack: list[tuple[str, ...]] = []
    for line in lines:
        if line.startswith(("/*", "//")):
            continue
        if line == "}":
            if not stack:
                return Err(ParseError("unbalanced '}' in brace-format config"))
            section = stack.pop()
            # An empty section is still config (VyOS: `loopback lo { }`):
            # keep it as a bare path so nothing vanishes in normalization.
            prefix = tuple(token for part in stack for token in part) + section
            if not any(path[: len(prefix)] == prefix for path in paths):
                paths.append(prefix)
            continue
        if line.endswith("{"):
            tokens = _tokenize(line[:-1].strip())
            if isinstance(tokens, Err):
                return tokens
            if not tokens.value:
                return Err(ParseError("brace-format section with no name"))
            stack.append(tuple(tokens.value))
            continue
        tokens = _tokenize(line)
        if isinstance(tokens, Err):
            return tokens
        flat = tuple(token for part in stack for token in part)
        paths.append(flat + tuple(tokens.value))
    if stack:
        return Err(ParseError("unbalanced '{' in brace-format config"))
    return Ok(paths)


def _set_form_paths(lines: list[str]) -> Result[list[tuple[str, ...]], ParseError]:
    paths: list[tuple[str, ...]] = []
    for line in lines:
        if line != "set" and not line.startswith("set "):
            return Err(ParseError(f"expected a `set` command, got {line[:80]!r}"))
        tokens = _tokenize(line[4:])
        if isinstance(tokens, Err):
            return tokens
        if not tokens.value:
            return Err(ParseError("bare `set` with no path"))
        paths.append(tuple(tokens.value))
    return Ok(paths)


def _group_key(path: tuple[str, ...]) -> tuple[str, ...]:
    """The stanza a set-path classifies under. Interfaces group per interface;
    `system`/`service` split one level deeper (host-name vs login vs ntp are
    different buckets); everything else groups by its top word."""
    match path:
        case ("interfaces", iftype, name, *_):
            return ("interfaces", iftype, _unquote(name))
        case (("system" | "service") as top, second, *_):
            return (top, second)
        case (top, *_):
            return (top,)
        case _:  # unreachable: the tokenizers reject empty paths
            return path


def _interface_facts(
    key: tuple[str, ...], paths: list[tuple[str, ...]], warnings: list[str]
) -> SourceInterface | None:
    """The inferable facts of one interface stanza, or None (with a warning)
    for a type the lab cannot realize."""
    _, iftype, name = key
    if iftype != _ETHERNET and iftype not in _LOOPBACK_TYPES:
        warnings.append(
            f"interface type {iftype} ({name}) cannot be realized in the lab; "
            "its config rides the carry"
        )
        return None

    ipv4: str | None = None
    vrf: str | None = None
    shutdown = False
    vifs_warned: set[str] = set()
    for path in paths:
        match path[3:]:
            case ("vif" | "vif-s", raw_vif, *_):
                vif_id = _unquote(raw_vif)
                if vif_id not in vifs_warned:
                    vifs_warned.add(vif_id)
                    warnings.append(
                        f"VLAN subinterface {name} vif {vif_id} is not inferred; "
                        "its config rides the carry"
                    )
            case ("address", raw_value):
                value = _unquote(raw_value)
                if ipv4 is None and "/" in value and "." in value.split("/", 1)[0]:
                    ipv4 = value
            case ("vrf", raw_value):
                vrf = _unquote(raw_value)
            case ("disable",):
                shutdown = True
            case _:
                pass
    return SourceInterface(
        name=name,
        ipv4=ipv4,
        vrf=vrf,
        shutdown=shutdown,
        loopback=iftype in _LOOPBACK_TYPES,
    )


def parse_vyos(content: str) -> Result[ParsedSource, ParseError]:
    """Parse a VyOS config dump (either format) into the facts model."""
    lines = [stripped for raw in content.splitlines() if (stripped := raw.strip())]
    if not lines:
        return Err(ParseError("no configuration lines found"))

    # Format detection is by the FIRST line: `show configuration commands`
    # output is set commands throughout, the brace form opens with a section.
    is_brace = lines[0] != "set" and not lines[0].startswith("set ")
    if is_brace and not any(line.endswith("{") for line in lines):
        return Err(ParseError("not a VyOS config: neither `set` commands nor a brace tree"))
    paths = _brace_to_paths(lines) if is_brace else _set_form_paths(lines)
    if isinstance(paths, Err):
        return paths
    if not paths.value:
        return Err(ParseError("no configuration paths found"))

    grouped: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for path in paths.value:
        grouped.setdefault(_group_key(path), []).append(path)

    hostname: str | None = None
    interfaces: list[SourceInterface] = []
    stanzas: list[Stanza] = []
    warnings: list[str] = []
    for key, group in grouped.items():
        kind: StanzaKind = "other"
        interface: str | None = None
        if key == _HOSTNAME_KEY:
            kind = "hostname"
            for path in group:
                if len(path) == 3:
                    hostname = _unquote(path[2])
        elif key[0] == "interfaces" and len(key) == 3:
            kind = "interface"
            interface = key[2]
            facts = _interface_facts(key, group, warnings)
            if facts is not None:
                interfaces.append(facts)
        stanzas.append(
            Stanza(
                lines=tuple("set " + " ".join(path) for path in group),
                kind=kind,
                key=key,
                interface=interface,
            )
        )
    return Ok(
        ParsedSource(
            hostname=hostname,
            interfaces=tuple(interfaces),
            stanzas=tuple(stanzas),
            warnings=tuple(warnings),
        )
    )
