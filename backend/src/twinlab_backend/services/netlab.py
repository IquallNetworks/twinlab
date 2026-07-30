"""netlab adapter (topology generation only).

The backend uses netlab as a *generator*: `netlab create` turns a declarative
definition into a containerlab topology, which is then deployed through clab-api.
Config push lives in the netlab-runner sidecar (`netlab initial`), not here.
`netlab up` remains forbidden. The subprocess call is the boundary — the one
place `try`/`except` lives; every outcome is a typed result.

Lab identity: a lab needs a *stable* name so the deployed containers
(`clab-<name>-<node>`) and the runner's regenerated inventory agree. We inject
that name into the definition before generating, so create/deploy/configure all
share it.
"""

import copy
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, Field, ValidationError

from twinlab_backend.result import Err, Ok, Result

# A custom-config template relpath (mirrors the models/runner contract): relative,
# traversal-free, `.j2`. `netlab create` validates that every template a
# definition's `config:` references exists, so the fileset must be written into
# the workdir before create — not just at config-push time.
_TEMPLATE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]*\.j2$")

# The parsed containerlab topology (name, topology.nodes/links, ...). The
# clab-api server wants it as a JSON object, so we hand back parsed data rather
# than raw YAML.
type ClabTopology = dict[str, object]

# netlab writes per-node bind sources under this relative dir (e.g.
# `node_files/pe1/ifstate` for cisco_iol). Twinlab deploys the topology inline
# and ships no working-directory files, so binds pointing here can't be honored.
_GENERATED_BIND_PREFIX = "node_files/"

# `netlab create` writes the containerlab topology under this fixed name in its
# working directory (the clab provider's default output file); the expanded
# (post-transform) topology is dumped alongside it via `-o json:nodefault=`.
_CLAB_OUTPUT = "clab.yml"
_EXPANDED_OUTPUT = "expanded.json"
_CREATE_TIMEOUT_SECONDS = 120


@dataclass(frozen=True, slots=True)
class NetlabError:
    message: str
    stderr: str


# --------------------------------------------------------------------------- #
# The link table (contract delta 14)
#
# The expanded topology's `links[]` is the LOGICAL link list — a LAN is one
# link with N endpoints, not clab.yml's per-member bridge fan-out. The two
# public shapes below are the persistable extract (stored on the lab record as
# JSONB, served by GET /labs/{name}/links); they carry no live state.
# --------------------------------------------------------------------------- #


class TopologyLinkEndpoint(BaseModel):
    node: str  # short netlab node name
    ifname: str  # netlab/NOS-side interface name (e.g. "Ethernet0/1")
    ifindex: int  # netlab interface index
    # The container-side interface name (`clab.name` when the kind renames,
    # else ifname) — the same resolution netsim's own netem code uses.
    clab_name: str
    ipv4: str | None  # CIDR; None when unnumbered/L2-only
    ipv6: str | None


class TopologyLink(BaseModel):
    index: int  # netlab linkindex — stable within a definition version
    name: str | None  # user-set link name only
    type: str  # netlab's vocabulary, passthrough (not a rendering signal)
    prefix_ipv4: str | None
    prefix_ipv6: str | None
    bandwidth: int | None
    mtu: int | None
    endpoints: list[TopologyLinkEndpoint]


# Boundary models for the expanded-topology JSON (unknown keys ignored).
# Address fields can be True (unnumbered) or an int (netlab prefix shorthand);
# only a concrete string is an address we can serve — see _address().


class _ExpandedPrefix(BaseModel):
    ipv4: str | bool | int | None = None
    ipv6: str | bool | int | None = None


class _ExpandedLinkInterface(BaseModel):
    node: str
    ifname: str
    ifindex: int
    ipv4: str | bool | int | None = None
    ipv6: str | bool | int | None = None


class _ExpandedLink(BaseModel):
    linkindex: int
    type: str
    name: str | None = None
    # False on L2-only links, absent when unaddressed.
    prefix: _ExpandedPrefix | bool | None = None
    bandwidth: int | None = None
    mtu: int | None = None
    interfaces: list[_ExpandedLinkInterface] = Field(default_factory=list)


class _ExpandedNodeInterfaceClab(BaseModel):
    name: str | None = None


class _ExpandedNodeInterface(BaseModel):
    ifname: str
    ifindex: int
    clab: _ExpandedNodeInterfaceClab | None = None


class _ExpandedNode(BaseModel):
    interfaces: list[_ExpandedNodeInterface] = Field(default_factory=list)


class _ExpandedTopology(BaseModel):
    links: list[_ExpandedLink] = Field(default_factory=list)
    nodes: dict[str, _ExpandedNode] = Field(default_factory=dict)


def _address(value: str | bool | int | None) -> str | None:
    """Only a concrete string is a servable address (True = unnumbered, int =
    netlab prefix shorthand — both mean "no address here")."""
    return value if isinstance(value, str) else None


def _extract_links(expanded: _ExpandedTopology) -> Result[list[TopologyLink], NetlabError]:
    """Map the expanded topology's logical links onto the persistable shape,
    joining each endpoint to its container-side interface name through the
    node-level interface table — the only place `clab.name` lives."""
    container_names: dict[tuple[str, int], str] = {
        (node_name, interface.ifindex): (
            interface.clab.name
            if interface.clab is not None and interface.clab.name is not None
            else interface.ifname
        )
        for node_name, node in expanded.nodes.items()
        for interface in node.interfaces
    }

    links: list[TopologyLink] = []
    for link in expanded.links:
        endpoints: list[TopologyLinkEndpoint] = []
        for attachment in link.interfaces:
            clab_name = container_names.get((attachment.node, attachment.ifindex))
            if clab_name is None:
                return Err(
                    NetlabError(
                        f"link {link.linkindex}: endpoint {attachment.node}:{attachment.ifname}"
                        " is missing from the node interface table",
                        "",
                    )
                )
            endpoints.append(
                TopologyLinkEndpoint(
                    node=attachment.node,
                    ifname=attachment.ifname,
                    ifindex=attachment.ifindex,
                    clab_name=clab_name,
                    ipv4=_address(attachment.ipv4),
                    ipv6=_address(attachment.ipv6),
                )
            )
        prefix = link.prefix if isinstance(link.prefix, _ExpandedPrefix) else None
        links.append(
            TopologyLink(
                index=link.linkindex,
                name=link.name,
                type=link.type,
                prefix_ipv4=_address(prefix.ipv4) if prefix is not None else None,
                prefix_ipv6=_address(prefix.ipv6) if prefix is not None else None,
                bandwidth=link.bandwidth,
                mtu=link.mtu,
                endpoints=endpoints,
            )
        )
    return Ok(links)


@dataclass(frozen=True, slots=True)
class ClabArtifacts:
    """What Twinlab keeps from one `netlab create` run: the containerlab
    topology (deployed inline through clab-api) and the logical link table
    (persisted on the lab record)."""

    topology: ClabTopology
    links: list[TopologyLink]


def serialize_links(links: list[TopologyLink]) -> dict[str, object]:
    """The JSONB payload stored on the lab record's `links` column."""
    return {"links": [link.model_dump() for link in links]}


def read_lab_name(definition: str) -> str | None:
    """Return the definition's top-level `name:`, or None if absent/unparseable."""
    try:
        parsed: Any = yaml.safe_load(definition)
    except yaml.YAMLError:
        return None
    if isinstance(parsed, dict):
        name = cast("dict[str, object]", parsed).get("name")
        if isinstance(name, str):
            return name
    return None


def set_lab_name(definition: str, name: str) -> Result[str, NetlabError]:
    """Return the definition with its top-level `name:` set to `name`, so a lab's
    identity is stable across create/deploy/configure."""
    try:
        parsed: Any = yaml.safe_load(definition)
    except yaml.YAMLError as exc:
        return Err(NetlabError(f"could not parse definition: {exc}", ""))
    if not isinstance(parsed, dict):
        return Err(NetlabError("definition is not a mapping", ""))

    definition_map = cast("dict[str, object]", parsed)
    definition_map["name"] = name
    return Ok(yaml.safe_dump(definition_map, sort_keys=False))


def read_mgmt_subnet(definition: str) -> str | None:
    """Return the definition's `addressing.mgmt.ipv4` (the management subnet), or
    None if unset/unparseable. Lets the deploy path honor an explicitly-chosen
    subnet instead of allocating one."""
    try:
        parsed: Any = yaml.safe_load(definition)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    addressing = cast("dict[str, object]", parsed).get("addressing")
    if not isinstance(addressing, dict):
        return None
    mgmt = cast("dict[str, object]", addressing).get("mgmt")
    if not isinstance(mgmt, dict):
        return None
    ipv4 = cast("dict[str, object]", mgmt).get("ipv4")
    return ipv4 if isinstance(ipv4, str) else None


def set_mgmt_subnet(definition: str, subnet: str, network_name: str) -> Result[str, NetlabError]:
    """Pin the lab's management subnet (`addressing.mgmt.ipv4`) and give it a
    distinct Docker network (`addressing.mgmt._network`) so concurrent labs don't
    share one mgmt bridge. `_network` is only set when absent, honoring an
    explicit choice; other `addressing.mgmt` keys are preserved."""
    try:
        parsed: Any = yaml.safe_load(definition)
    except yaml.YAMLError as exc:
        return Err(NetlabError(f"could not parse definition: {exc}", ""))
    if not isinstance(parsed, dict):
        return Err(NetlabError("definition is not a mapping", ""))

    definition_map = cast("dict[str, object]", parsed)
    addressing = definition_map.setdefault("addressing", {})
    if not isinstance(addressing, dict):
        return Err(NetlabError("addressing is not a mapping", ""))
    addressing_map = cast("dict[str, object]", addressing)
    mgmt = addressing_map.setdefault("mgmt", {})
    if not isinstance(mgmt, dict):
        return Err(NetlabError("addressing.mgmt is not a mapping", ""))
    mgmt_map = cast("dict[str, object]", mgmt)

    mgmt_map["ipv4"] = subnet
    mgmt_map.setdefault("_network", network_name)
    return Ok(yaml.safe_dump(definition_map, sort_keys=False))


def _write_templates(workdir: Path, templates: dict[str, str]) -> NetlabError | None:
    """Write custom-config templates into the create workdir so `netlab create`'s
    validation of `config:` references passes. Paths are already validated upstream
    (pydantic for user templates, trusted literals for built-ins); this rejects an
    unsafe path defensively rather than trusting the caller."""
    for relpath, content in templates.items():
        if not _TEMPLATE_PATH.match(relpath) or ".." in Path(relpath).parts:
            return NetlabError(f"unsafe template path: {relpath!r}", "")
        target = workdir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = target.write_text(content)
    return None


def create_clab_topology(
    definition: str, templates: dict[str, str] | None = None
) -> Result[ClabArtifacts, NetlabError]:
    """Run `netlab create` on a netlab definition and return the generated
    containerlab topology plus the logical link table. The definition must state
    each node's `device` and the `provider` — Twinlab never defaults those.
    `templates` is the custom-config fileset the definition may reference
    (built-in + user); netlab validates their existence at create time, so they
    are written into the workdir first. Omit it for a definition with no custom
    config."""
    with tempfile.TemporaryDirectory() as workdir:
        source = Path(workdir) / "topology.yml"
        _ = source.write_text(definition)
        written = _write_templates(Path(workdir), templates or {})
        if written is not None:
            return Err(written)

        try:
            proc = subprocess.run(
                # Any `-o` REPLACES netlab's default output set, so `provider`
                # (clab.yml) must be requested back — and `config` must come
                # FIRST: the clab provider validates binds against the
                # node_files/ that the config output writes (verified: without
                # it, create fails on "File node_files/... does not exist").
                # The default set's `pickle` is dropped — never read here.
                [
                    "netlab",
                    "create",
                    source.name,
                    "-o",
                    "config",
                    "-o",
                    "provider",
                    "-o",
                    f"json:nodefault={_EXPANDED_OUTPUT}",
                ],
                cwd=workdir,
                # netlab keeps global state under ~/.netlab and its mkdir isn't
                # concurrency-safe: two creates racing to first-create it makes one
                # fail. Point HOME at the per-call workdir so each invocation gets
                # its own ~/.netlab and concurrent deploys can't collide.
                env={**os.environ, "HOME": workdir},
                capture_output=True,
                text=True,
                timeout=_CREATE_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return Err(NetlabError(message=f"could not run netlab: {exc}", stderr=""))

        if proc.returncode != 0:
            return Err(NetlabError(message="netlab create failed", stderr=proc.stderr))

        try:
            raw = (Path(workdir) / _CLAB_OUTPUT).read_text()
            raw_expanded = (Path(workdir) / _EXPANDED_OUTPUT).read_text()
        except OSError as exc:
            return Err(NetlabError(f"netlab create output missing: {exc}", proc.stderr))

    try:
        parsed: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return Err(NetlabError(f"could not parse {_CLAB_OUTPUT}: {exc}", proc.stderr))

    if not isinstance(parsed, dict):
        return Err(NetlabError(f"{_CLAB_OUTPUT} was not a mapping", proc.stderr))

    try:
        expanded = _ExpandedTopology.model_validate(json.loads(raw_expanded))
    except (json.JSONDecodeError, ValidationError) as exc:
        return Err(NetlabError(f"could not parse {_EXPANDED_OUTPUT}: {exc}", proc.stderr))

    links = _extract_links(expanded)
    if isinstance(links, Err):
        return Err(links.error)
    return Ok(ClabArtifacts(topology=cast("ClabTopology", parsed), links=links.value))


def strip_generated_binds(topology: ClabTopology) -> ClabTopology:
    """Drop per-node binds whose source is a netlab-generated `node_files/*` path.

    Twinlab deploys the topology inline (clab-api `topologyContent`) and ships no
    working-directory files, so such a bind can't be satisfied on the clab-api
    host — clab-api rejects the deploy with "failed to verify bind path". The
    containerlab kind regenerates what it needs from the topology itself (e.g.
    cisco_iol's `ifstate`), so dropping these binds is safe. A node left with no
    binds loses the now-empty `binds` key. Returns a new topology; the input is
    not mutated."""
    result = copy.deepcopy(topology)
    inner = result.get("topology")
    if not isinstance(inner, dict):
        return result
    nodes = cast("dict[str, object]", inner).get("nodes")
    if not isinstance(nodes, dict):
        return result
    for node in cast("dict[str, object]", nodes).values():
        if not isinstance(node, dict):
            continue
        node_map = cast("dict[str, object]", node)
        binds = node_map.get("binds")
        if not isinstance(binds, list):
            continue
        kept = [
            bind
            for bind in cast("list[object]", binds)
            if not (isinstance(bind, str) and bind.startswith(_GENERATED_BIND_PREFIX))
        ]
        if kept:
            node_map["binds"] = kept
        else:
            del node_map["binds"]
    return result
