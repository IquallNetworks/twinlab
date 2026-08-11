"""Skeleton emission: the thin netlab definition.

Deliberately minimal (docs/config-import.md): nodes, inferred links with
PINNED addressing (endpoint CIDRs and the link prefix — address fidelity is
the point of a twin), first-loopback pins, and carry template references —
and NO protocol modules: netlab regenerates only interface/IP config,
everything else rides the carry verbatim, so the loss surface stays the
interface map plus the quarantine list. No `name:` and no mgmt addressing —
the receiving lab's PUT pins both, as for any authored definition.
"""

import re

import yaml

from twinlab_backend.services.configimport.wiring import NodeSource, Wiring

# Link-attribute words netlab reads off a dict-form link entry: a node whose
# sanitized name collided with one would corrupt the emitted links.
_RESERVED_NODE_NAMES = frozenset(
    {"prefix", "type", "name", "bridge", "interfaces", "mtu", "bandwidth", "gateway", "role"}
)

_INVALID_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]")
# netlab validates node names as identifiers (must_be_id): a leading letter or
# underscore, then letters/digits/underscore/hyphen, MAX_NODE_ID_LENGTH (16)
# characters. A name outside it fails the dry `netlab create` the import runs,
# so the sanitizer has to land inside it — hyphens included, since they are
# legal here (the emitted links are dict-form, never the terse `a-b` spelling
# that would re-split a hyphenated name). The leading underscore netlab would
# also accept is NOT taken: node names travel through the API's `_Name` (the
# netem and power routes), which starts at an alphanumeric.
NODE_NAME_MAX = 16


def sanitize_node_name(hostname: str) -> str:
    """A netlab-safe node name: letters, digits, underscores and hyphens, a
    leading letter, 16 characters max. Only what the twin cannot carry is
    rewritten — a hyphenated hostname keeps its hyphens. Every applied rename
    lands in the import's name map."""
    cleaned = _INVALID_NAME_CHARS.sub("_", hostname)
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"n{cleaned}"
    # Reserved words are all far shorter than the cap, so truncating last
    # cannot reintroduce one.
    if cleaned.lower() in _RESERVED_NODE_NAMES:
        cleaned = f"n_{cleaned}"
    return cleaned[:NODE_NAME_MAX]


def carry_relpath(node: str) -> str:
    """Where the `imported` record's node variant materializes (delta 27) —
    the path netlab's per-node lookup resolves `config: [imported]` to, and
    the path the dry create's placeholder must occupy. Byte-identical to the
    pre-record carry path, so definitions from before the remodel (direct
    `config: [imported/<node>.j2]` references) keep resolving."""
    return f"imported/{node}.j2"


def emit_definition(
    sources: list[NodeSource], topology: Wiring, carry_nodes: frozenset[str]
) -> str:
    """The thin skeleton as netlab YAML. `carry_nodes` are the nodes whose
    carry template is non-empty — only they reference the `imported` template
    (the NAME form: netlab resolves it per node to `imported/<node>.j2`, and
    its create-time validation walks the same lookup — both directions proven
    live 2026-08-07, delta 27)."""
    nodes: dict[str, object] = {}
    for source in sources:
        node: dict[str, object] = {"device": source.device}
        loopback = topology.loopbacks.get(source.node)
        if loopback is not None:
            node["loopback"] = {"ipv4": loopback.ipv4}
        if source.node in carry_nodes:
            node["config"] = ["imported"]
        nodes[source.node] = node

    links: list[dict[str, object]] = []
    for link in topology.links:
        # An unaddressed endpoint MUST spell `ipv4: false`: left bare, netlab
        # invents an address for it (live-proven — and not even from the
        # pinned prefix), which is exactly the silent invention import must
        # never emit. An all-unaddressed wire pins `prefix: false` the same
        # way, yielding a real unaddressed veth pair.
        entry: dict[str, object] = {
            endpoint.node: {"ipv4": endpoint.ipv4 if endpoint.ipv4 is not None else False}
            for endpoint in link.endpoints
        }
        entry["prefix"] = link.network if link.network is not None else False
        links.append(entry)

    doc: dict[str, object] = {"provider": "clab", "nodes": nodes}
    if links:
        doc["links"] = links
    return yaml.safe_dump(doc, sort_keys=False)
