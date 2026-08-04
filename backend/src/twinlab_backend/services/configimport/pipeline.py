"""The import pipeline: sources in, the definition factory's output out.

parse -> infer -> bucket-split -> emit skeleton -> dry netlab create (the
same validation a PUT runs; it also yields the expanded topology the
interface map joins on, by PINNED address) -> rewrite carry -> assemble.
Pure orchestration; every failure is a typed problem the API maps onto its
422 slugs.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

import yaml

from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services.configimport.classify import BucketSplit, split_buckets
from twinlab_backend.services.configimport.emit import (
    carry_relpath,
    emit_definition,
    quarantine_relpath,
    sanitize_node_name,
)
from twinlab_backend.services.configimport.inference import (
    Inference,
    NodeSource,
    infer,
    is_mgmt_vrf,
)
from twinlab_backend.services.configimport.ios import parse_ios
from twinlab_backend.services.configimport.model import (
    Note,
    ParsedSource,
    ParseError,
    QuarantineClass,
)
from twinlab_backend.services.configimport.rewrite import (
    rewrite_ios,
    rewrite_vyos,
    wrap_raw,
)
from twinlab_backend.services.configimport.vyos import parse_vyos
from twinlab_backend.services.netlab import ClabArtifacts, create_clab_topology

_PARSERS: dict[str, Callable[[str], Result[ParsedSource, ParseError]]] = {
    "iol": parse_ios,
    "vyos": parse_vyos,
}


def import_capable_devices() -> frozenset[str]:
    """The devices with a parser — the catalog's `config_import` flag."""
    return frozenset(_PARSERS)


@dataclass(frozen=True, slots=True)
class ImportSourceSpec:
    device: str
    content: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class QuarantineOut:
    reason: QuarantineClass
    content: str


@dataclass(frozen=True, slots=True)
class NetworkImportResult:
    definition: str
    custom_config: dict[str, str]
    interface_map: dict[str, dict[str, str]]
    name_map: dict[str, str]
    quarantine: dict[str, list[QuarantineOut]]
    warnings: list[Note]


@dataclass(frozen=True, slots=True)
class NodeImportResult:
    fragment: str
    config: str
    interfaces: dict[str, str | None]
    quarantine: list[QuarantineOut]
    warnings: list[Note]


type ImportProblemCode = Literal[
    "unsupported_device", "config_unparseable", "duplicate_node", "netlab_invalid"
]


@dataclass(frozen=True, slots=True)
class ImportProblem:
    code: ImportProblemCode
    message: str
    stderr: str = ""


def _parse_one(spec: ImportSourceSpec, label: str) -> Result[ParsedSource, ImportProblem]:
    parser = _PARSERS.get(spec.device)
    if parser is None:
        return Err(
            ImportProblem(
                "unsupported_device", f"{label}: device {spec.device!r} is not import-capable"
            )
        )
    parsed = parser(spec.content)
    if isinstance(parsed, Err):
        return Err(ImportProblem("config_unparseable", f"{label}: {parsed.error.message}"))
    return parsed


def _interface_map(
    inference: Inference, artifacts: ClabArtifacts, warnings: list[Note]
) -> dict[str, dict[str, str]]:
    """source interface -> netlab NOS-side ifname, joined on the pinned
    addresses (the skeleton pinned every inferred endpoint, so the join is
    total; a miss is a named warning, not a silent gap)."""
    by_address: dict[tuple[str, str], str] = {}
    for link in artifacts.links:
        for endpoint in link.endpoints:
            if endpoint.ipv4 is not None:
                by_address[(endpoint.node, endpoint.ipv4)] = endpoint.ifname

    result: dict[str, dict[str, str]] = {}
    for link in inference.links:
        for endpoint in link.endpoints:
            ifname = by_address.get((endpoint.node, endpoint.ipv4))
            if ifname is None:
                warnings.append(
                    Note(
                        endpoint.node,
                        f"interface {endpoint.interface} ({endpoint.ipv4}) has no expanded-"
                        "topology counterpart; its carried references stay unrewritten",
                    )
                )
                continue
            result.setdefault(endpoint.node, {})[endpoint.interface] = ifname

    for node, pin in inference.loopbacks.items():
        loopback = artifacts.node_facts.get(node, {}).get("loopback")
        ifname = (
            cast("dict[str, object]", loopback).get("ifname")
            if isinstance(loopback, dict)
            else None
        )
        if isinstance(ifname, str):
            result.setdefault(node, {})[pin.interface] = ifname
    return result


def import_network(
    specs: list[ImportSourceSpec],
) -> Result[NetworkImportResult, ImportProblem]:
    sources: list[NodeSource] = []
    name_map: dict[str, str] = {}
    warnings: list[Note] = []
    seen: set[str] = set()
    for index, spec in enumerate(specs):
        label = spec.name or f"source #{index + 1}"
        parsed = _parse_one(spec, label)
        if isinstance(parsed, Err):
            return parsed
        hostname = parsed.value.hostname
        raw_name = spec.name if spec.name is not None else hostname
        if raw_name is None:
            return Err(
                ImportProblem(
                    "config_unparseable",
                    f"{label}: the config names no hostname and no `name` override was given",
                )
            )
        node = sanitize_node_name(raw_name)
        if node in seen:
            return Err(
                ImportProblem("duplicate_node", f"two sources resolve to node name {node!r}")
            )
        seen.add(node)
        if hostname is not None:
            name_map[hostname] = node
        warnings.extend(Note(node, message) for message in parsed.value.warnings)
        sources.append(NodeSource(node=node, device=spec.device, parsed=parsed.value))

    inference = infer(sources)
    warnings.extend(inference.notes)

    per_node_addresses: dict[str, dict[str, str]] = {source.node: {} for source in sources}
    for link in inference.links:
        for endpoint in link.endpoints:
            per_node_addresses[endpoint.node][endpoint.interface] = endpoint.ipv4
    for node, pin in inference.loopbacks.items():
        per_node_addresses[node][pin.interface] = pin.ipv4

    splits: dict[str, BucketSplit] = {
        source.node: split_buckets(
            source.parsed,
            device=source.device,
            modeled_addresses=per_node_addresses[source.node],
            mgmt_interfaces=inference.mgmt_interfaces.get(source.node, frozenset()),
            mgmt_vrfs=inference.mgmt_vrfs.get(source.node, frozenset()),
        )
        for source in sources
    }

    carry_nodes = frozenset(node for node, split in splits.items() if split.carried)
    definition = emit_definition(sources, inference, carry_nodes)

    # The dry create only checks that referenced templates EXIST; content
    # lands after the rewrite, which needs this run's expanded topology.
    placeholder = {carry_relpath(node): "placeholder\n" for node in carry_nodes}
    created = create_clab_topology(definition, placeholder or None)
    if isinstance(created, Err):
        return Err(ImportProblem("netlab_invalid", created.error.message, created.error.stderr))

    interface_map = _interface_map(inference, created.value, warnings)

    custom_config: dict[str, str] = {}
    quarantine: dict[str, list[QuarantineOut]] = {}
    for source in sources:
        split = splits[source.node]
        mapping = interface_map.get(source.node, {})
        if split.carried:
            all_lines = tuple(line for block in split.carried for line in block.lines)
            rewriter = rewrite_vyos if source.device == "vyos" else rewrite_ios
            rewritten, notes = rewriter(all_lines, mapping, source.node)
            warnings.extend(notes)
            custom_config[carry_relpath(source.node)] = wrap_raw("\n".join(rewritten))
        if split.quarantined:
            quarantine[source.node] = [
                QuarantineOut(block.reason, "\n".join(block.lines)) for block in split.quarantined
            ]
            text = "\n".join(line for block in split.quarantined for line in block.lines)
            custom_config[quarantine_relpath(source.node)] = wrap_raw(text)

    return Ok(
        NetworkImportResult(
            definition=definition,
            custom_config=custom_config,
            interface_map=interface_map,
            name_map=name_map,
            quarantine=quarantine,
            warnings=warnings,
        )
    )


def import_node(device: str, content: str) -> Result[NodeImportResult, ImportProblem]:
    """The single-node granularity: a stampable fragment plus its carry.
    No peers -> no inference -> the carry keeps SOURCE interface names (the
    contract QUIRK); the fragment models the device and the loopback pin."""
    parsed = _parse_one(ImportSourceSpec(device=device, content=content), "the config")
    if isinstance(parsed, Err):
        return parsed
    source = parsed.value

    warnings = [Note(None, message) for message in source.warnings]
    mgmt_interfaces = frozenset(
        interface.name for interface in source.interfaces if is_mgmt_vrf(interface.vrf)
    )
    mgmt_vrfs = frozenset(
        interface.vrf
        for interface in source.interfaces
        if interface.vrf is not None and is_mgmt_vrf(interface.vrf)
    )
    pin = next(
        (
            interface
            for interface in source.interfaces
            if interface.loopback and interface.ipv4 is not None
        ),
        None,
    )
    modeled_addresses = {pin.name: pin.ipv4} if pin is not None and pin.ipv4 is not None else {}
    split = split_buckets(
        source,
        device=device,
        modeled_addresses=modeled_addresses,
        mgmt_interfaces=mgmt_interfaces,
        mgmt_vrfs=mgmt_vrfs,
    )

    fragment: dict[str, object] = {"device": device}
    if pin is not None and pin.ipv4 is not None:
        fragment["loopback"] = {"ipv4": pin.ipv4}

    interfaces = {
        interface.name: interface.ipv4
        for interface in source.interfaces
        if not interface.loopback and interface.name not in mgmt_interfaces
    }
    if split.carried and interfaces:
        warnings.append(
            Note(
                None,
                "carried config keeps the SOURCE interface names — wire the node's "
                "links first, then review the carry against the lab's names",
            )
        )
    carry_text = "\n".join(line for block in split.carried for line in block.lines)
    return Ok(
        NodeImportResult(
            fragment=yaml.safe_dump(fragment, sort_keys=False),
            config=wrap_raw(carry_text) if carry_text else "",
            interfaces=interfaces,
            quarantine=[
                QuarantineOut(block.reason, "\n".join(block.lines)) for block in split.quarantined
            ],
            warnings=warnings,
        )
    )
