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

from twinlab_backend.services.configimport.inference import Inference, NodeSource

# Link-attribute words netlab reads off a dict-form link entry: a node whose
# sanitized name collided with one would corrupt the emitted links.
_RESERVED_NODE_NAMES = frozenset(
    {"prefix", "type", "name", "bridge", "interfaces", "mtu", "bandwidth", "gateway", "role"}
)

_INVALID_NAME_CHARS = re.compile(r"[^A-Za-z0-9_]")


def sanitize_node_name(hostname: str) -> str:
    """A netlab-safe node name: alphanumerics and underscores only (hyphens
    and dots are the builder's gated territory, and netlab mangles them in
    identifier contexts), first char alphanumeric, 64 max. The applied
    rename lands in the import's name map."""
    cleaned = _INVALID_NAME_CHARS.sub("_", hostname)
    if not cleaned or not cleaned[0].isalnum():
        cleaned = f"n{cleaned}"
    if cleaned.lower() in _RESERVED_NODE_NAMES:
        cleaned = f"n_{cleaned}"
    return cleaned[:64]


def carry_relpath(node: str) -> str:
    """The custom-config fileset path of a node's carry template (the
    contract's `imported/<node>.j2`; netlab accepts the subdir reference —
    verified live)."""
    return f"imported/{node}.j2"


def quarantine_relpath(node: str) -> str:
    """The UNATTACHED quarantine file's fileset path."""
    return f"imported/{node}.quarantine.j2"


def emit_definition(
    sources: list[NodeSource], inference: Inference, carry_nodes: frozenset[str]
) -> str:
    """The thin skeleton as netlab YAML. `carry_nodes` are the nodes whose
    carry template is non-empty — only they get a `config:` reference
    (netlab create validates that referenced templates exist)."""
    nodes: dict[str, object] = {}
    for source in sources:
        node: dict[str, object] = {"device": source.device}
        loopback = inference.loopbacks.get(source.node)
        if loopback is not None:
            node["loopback"] = {"ipv4": loopback.ipv4}
        if source.node in carry_nodes:
            node["config"] = [carry_relpath(source.node)]
        nodes[source.node] = node

    links: list[dict[str, object]] = []
    for link in inference.links:
        entry: dict[str, object] = {
            endpoint.node: {"ipv4": endpoint.ipv4} for endpoint in link.endpoints
        }
        entry["prefix"] = link.network
        links.append(entry)

    doc: dict[str, object] = {"provider": "clab", "nodes": nodes}
    if links:
        doc["links"] = links
    return yaml.safe_dump(doc, sort_keys=False)
