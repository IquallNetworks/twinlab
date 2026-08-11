"""The fidelity diff: prove an import, don't trust it (delta 22).

Compares a node's SOURCE config against its RUNNING config collected from
the lab, both normalized through the same parsers the importer uses. The
interface map is recomputed statelessly by joining the two sides' pinned
addresses (a lab never remembers its import origin); quarantined source
lines are excluded from comparison (counted); the source hostname is
excluded by construction (the lab node's name intentionally differs).
Line membership is compared stripped — indentation is presentation.

`extra` (running lines with no source counterpart) is expected noise —
the lab's own baseline, defaults the NOS materializes — and stays
informational. The report is never a gate.
"""

from dataclasses import dataclass

from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services.configimport.classify import split_buckets
from twinlab_backend.services.configimport.platforms import PLATFORMS
from twinlab_backend.services.configimport.wiring import is_mgmt_vrf

# The dump command per import-capable device, derived from the platform table
# so it cannot drift from the parser set — a platform that can be imported can
# be diffed, by construction. See `PlatformImporter.dump_command` for why the
# spelling is the device's own CLI.
DUMP_COMMANDS: dict[str, str] = {
    device: platform.dump_command for device, platform in PLATFORMS.items()
}


@dataclass(frozen=True, slots=True)
class NodeDiffData:
    node: str
    matched: int
    missing: list[str]
    extra: list[str]
    quarantined: int


def diff_node(
    node: str,
    device: str,
    source_content: str,
    running_output: str,
    interface_map: dict[str, str] | None = None,
) -> Result[NodeDiffData, str]:
    platform = PLATFORMS.get(device)
    if platform is None:
        return Err(f"device {device!r} is not import-capable")
    source = platform.parse(source_content)
    if isinstance(source, Err):
        return Err(f"source config: {source.error.message}")
    running = platform.parse(running_output)
    if isinstance(running, Err):
        return Err(f"running config: {running.error.message}")

    # The comparable set: everything but the hostname (modeled_addresses is
    # empty, so address lines stay comparable — address fidelity IS the
    # point) and the quarantine (kept as a count).
    mgmt_interfaces = frozenset(
        interface.name for interface in source.value.interfaces if is_mgmt_vrf(interface.vrf)
    )
    mgmt_vrfs = frozenset(
        interface.vrf
        for interface in source.value.interfaces
        if interface.vrf is not None and is_mgmt_vrf(interface.vrf)
    )
    split = split_buckets(
        source.value,
        spec=platform.classify,
        modeled_addresses={},
        mgmt_interfaces=mgmt_interfaces,
        mgmt_vrfs=mgmt_vrfs,
    )
    quarantined = sum(len(block.lines) for block in split.quarantined)

    # Recompute the interface map: join the two sides on their addresses.
    running_by_address = {
        interface.ipv4: interface.name
        for interface in running.value.interfaces
        if interface.ipv4 is not None
    }
    mapping: dict[str, str] = {}
    for interface in source.value.interfaces:
        if interface.ipv4 is None:
            continue
        counterpart = running_by_address.get(interface.ipv4)
        if counterpart is not None:
            mapping[interface.name] = counterpart
    # Caller-supplied entries WIN (delta 23): an L2-linked interface carries
    # no address on either side, so the join above cannot see it — the client
    # feeds back the map the import returned. The diff stays stateless.
    if interface_map is not None:
        mapping.update(interface_map)

    source_lines = tuple(line for block in split.carried for line in block.lines)
    rewritten, _ = platform.rewrite(source_lines, mapping, node)

    running_lines = [line for stanza in running.value.stanzas for line in stanza.lines]
    running_set = {line.strip() for line in running_lines}
    source_set = {line.strip() for line in rewritten}

    missing = [line for line in rewritten if line.strip() not in running_set]
    matched = len(rewritten) - len(missing)
    extra = [line for line in running_lines if line.strip() not in source_set]
    return Ok(
        NodeDiffData(
            node=node, matched=matched, missing=missing, extra=extra, quarantined=quarantined
        )
    )
