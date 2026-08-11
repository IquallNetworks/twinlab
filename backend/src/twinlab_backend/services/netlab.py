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
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, Field, ValidationError

from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services.device_catalog import IMAGE_PINS

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
# `node_files/pe1/ifstate` for cisco_iol). Twinlab deploys the topology inline,
# so relative binds only work when the tree is materialized on the host-shared
# lab-files directory and rewritten absolute (`rewrite_generated_binds`); with
# no such directory configured they are stripped instead.
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
    # The host bridge netlab assigns to shared segments (`name[0:10]_linkindex`).
    # Assigned even to some 2-endpoint links; only 3+ endpoints make the clab
    # provider actually reference it (see _host_bridges). Absent on p2p.
    bridge: str | None = None
    node_count: int
    # Link-level clab attributes; only `external_bridge` (KEY presence, netlab's
    # own check) matters here — it marks `bridge` as externally managed.
    clab: dict[str, object] = Field(default_factory=dict)


class _ExpandedNodeInterfaceClab(BaseModel):
    name: str | None = None


class _ExpandedNodeInterface(BaseModel):
    ifname: str
    ifindex: int
    clab: _ExpandedNodeInterfaceClab | None = None


class _ExpandedNode(BaseModel):
    device: str
    module: list[str] = Field(default_factory=list)
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


# --------------------------------------------------------------------------- #
# Host preparation (what `netlab up` would do to the host before starting)
#
# Twinlab never runs `netlab up`, so its clab pre-start work — creating the
# host bridges shared segments need, modprobing kernel modules — is derived
# here and executed by the hostprep sidecar around deploy/destroy.
# --------------------------------------------------------------------------- #

# Mirrored from netlab's clab provider defaults (providers/clab.yml `kmods`
# and the per-device `clab.kmods` extras): the kernel modules `netlab up`
# would modprobe before starting containers, keyed by netlab module. A device
# *participates* iff its device data carries a `kmods` key — VM/emulator kinds
# (cisco_iol, ...) have none, their dataplane runs inside the image. A `?`
# suffix marks a module netlab treats as optional (failure tolerated).
# test_netlab.py cross-checks this mirror against the installed netlab, so an
# upgrade that changes the map fails a test instead of silently drifting.
PROVIDER_KMODS: dict[str, tuple[str, ...]] = {
    "lag": ("bonding",),
    "mpls": ("mpls-router", "mpls-iptunnel"),
    "sr": ("mpls-router", "mpls-iptunnel"),
    "vxlan": ("vxlan", "udp_tunnel", "ip6_udp_tunnel"),
    "vrf": ("vrf",),
}
DEVICE_KMODS: dict[str, dict[str, tuple[str, ...]]] = {
    "vyos": {},
    "linux": {},
    "frr": {"initial": ("vrf?",)},
    "cumulus": {},
    "cumulus_nvue": {"initial": ("ebtables",)},
    "cisco8000v": {"initial": ("openvswitch",)},
}


@dataclass(frozen=True, slots=True)
class KernelModule:
    name: str
    # Mirrors netlab's `?` suffix: an optional module's load failure is
    # tolerated; a required one failing must fail the deploy (the lab's
    # dataplane silently won't work without it).
    required: bool


def _host_bridges(expanded: _ExpandedTopology) -> tuple[str, ...]:
    """The host bridges this topology needs pre-created. Exactly netlab's own
    filter (clab provider `list_bridges`): bridge assigned AND more than two
    endpoints AND not `clab.external_bridge` (an external bridge is someone
    else's to manage). netlab assigns `bridge` to some 2-endpoint links too
    (e.g. host-to-host), but renders those as plain veth pairs."""
    return tuple(
        sorted(
            {
                link.bridge
                for link in expanded.links
                if link.bridge is not None
                and link.node_count > 2
                and "external_bridge" not in link.clab
            }
        )
    )


def _kernel_modules(expanded: _ExpandedTopology) -> tuple[KernelModule, ...]:
    """The kernel modules this topology needs loaded, from each participating
    node's device x netlab modules (netlab iterates `initial` + the node's
    modules over the merged provider/device map). A module needed as required
    by any node is required overall."""
    needed: dict[str, bool] = {}
    for node in expanded.nodes.values():
        device_extras = DEVICE_KMODS.get(node.device)
        if device_extras is None:
            continue  # non-participating device: no kmods key in its defaults
        merged = {**PROVIDER_KMODS, **device_extras}
        for module in ("initial", *node.module):
            for kmod in merged.get(module, ()):
                name = kmod.removesuffix("?")
                required = not kmod.endswith("?")
                needed[name] = needed.get(name, False) or required
    return tuple(KernelModule(name, required) for name, required in sorted(needed.items()))


@dataclass(frozen=True, slots=True)
class ClabArtifacts:
    """What Twinlab keeps from one `netlab create` run: the containerlab
    topology (deployed inline through clab-api), the logical link table
    (persisted on the lab record), the per-node fact namespace test-suite
    templates render against (contract delta 17 — netlab's RAW node dicts,
    deliberately unpinned until a pre-v1.0 pinning decision), and the host
    preparation the deploy needs (bridges created / kernel modules loaded
    via the hostprep sidecar)."""

    topology: ClabTopology
    links: list[TopologyLink]
    node_facts: dict[str, dict[str, object]]
    host_bridges: tuple[str, ...]
    kernel_modules: tuple[KernelModule, ...]


def serialize_links(links: list[TopologyLink]) -> dict[str, object]:
    """The JSONB payload stored on the lab record's `links` column."""
    return {"links": [link.model_dump() for link in links]}


def _extract_node_facts(raw_expanded: object) -> Result[dict[str, dict[str, object]], NetlabError]:
    """The expanded topology's `nodes` as RAW dicts — the template fact
    namespace. Shape-checked only one level deep (a node's data must be a
    mapping); everything below is netlab's to define."""
    if not isinstance(raw_expanded, dict):
        return Err(NetlabError(f"{_EXPANDED_OUTPUT} was not a mapping", ""))
    nodes = cast("dict[str, object]", raw_expanded).get("nodes", {})
    if not isinstance(nodes, dict):
        return Err(NetlabError(f"{_EXPANDED_OUTPUT} `nodes` was not a mapping", ""))
    facts: dict[str, dict[str, object]] = {}
    for name, data in cast("dict[str, object]", nodes).items():
        if not isinstance(data, dict):
            return Err(NetlabError(f"{_EXPANDED_OUTPUT} node {name!r} was not a mapping", ""))
        facts[name] = cast("dict[str, object]", data)
    return Ok(facts)


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


def read_message(definition: str) -> str | None:
    """The definition's top-level `message:` — the author's "how to use this
    lab" note `netlab up` would print after configuring (up-parity gap 7:
    surfaced on LabDetail instead of silently dropped). None if
    absent/unparseable/not a string."""
    try:
        parsed: Any = yaml.safe_load(definition)
    except yaml.YAMLError:
        return None
    if isinstance(parsed, dict):
        message = cast("dict[str, object]", parsed).get("message")
        if isinstance(message, str):
            return message
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


def strip_record_pins(definition: str) -> Result[str, NetlabError]:
    """The inverse of set_lab_name/set_mgmt_subnet, for REUSE of a stored
    definition: remove the record-keyed pins — top-level `name:` and
    `addressing.mgmt.ipv4`/`_network` — so serving it as a network template
    yields something another lab can instantiate. The receiving PUT re-pins
    its own record's name and subnet; left in place, the source lab's explicit
    mgmt subnet wins there and the PUT 409s `mgmt_subnet_taken` for as long as
    the source lab exists. Other `addressing.mgmt` keys survive; mappings the
    strip empties are dropped rather than left as clutter."""
    try:
        parsed: Any = yaml.safe_load(definition)
    except yaml.YAMLError as exc:
        return Err(NetlabError(f"could not parse definition: {exc}", ""))
    if not isinstance(parsed, dict):
        return Err(NetlabError("definition is not a mapping", ""))

    definition_map = cast("dict[str, object]", parsed)
    _ = definition_map.pop("name", None)
    addressing = definition_map.get("addressing")
    if isinstance(addressing, dict):
        addressing_map = cast("dict[str, object]", addressing)
        mgmt = addressing_map.get("mgmt")
        if isinstance(mgmt, dict):
            mgmt_map = cast("dict[str, object]", mgmt)
            _ = mgmt_map.pop("ipv4", None)
            _ = mgmt_map.pop("_network", None)
            if not mgmt_map:
                _ = addressing_map.pop("mgmt")
        if not addressing_map:
            _ = definition_map.pop("addressing")
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
    definition: str,
    templates: dict[str, str] | None = None,
    node_files_target: Path | None = None,
) -> Result[ClabArtifacts, NetlabError]:
    """Run `netlab create` on a netlab definition and return the generated
    containerlab topology plus the logical link table. The definition must state
    each node's `device` and the `provider` — Twinlab never defaults those.
    `templates` is the custom-config fileset the definition may reference
    (built-in + user); netlab validates their existence at create time, so they
    are written into the workdir first. Omit it for a definition with no custom
    config. `node_files_target` (the deploy path only) materializes the
    generated `node_files/` tree there — full replace, permissions preserved —
    so `rewrite_generated_binds` can point the topology's binds at it instead
    of stripping them."""
    with tempfile.TemporaryDirectory() as workdir:
        source = Path(workdir) / "topology.yml"
        _ = source.write_text(definition)
        written = _write_templates(Path(workdir), templates or {})
        if written is not None:
            return Err(written)
        # Image pins (device_catalog.IMAGE_PINS): netlab reads a
        # `topology-defaults.yml` beside the topology and merges it over its
        # device data, so the pinned image lands in the emitted clab topology
        # for EVERY create — dry validation, deploy, links/facts backfill —
        # with nothing for a definition to know. An explicit node `image:`
        # still wins (node data beats defaults).
        pins = {
            "devices": {device: {"clab": {"image": image}} for device, image in IMAGE_PINS.items()}
        }
        _ = (Path(workdir) / "topology-defaults.yml").write_text(yaml.safe_dump(pins))

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

        if node_files_target is not None:
            materialized = _materialize_node_files(Path(workdir) / "node_files", node_files_target)
            if materialized is not None:
                return Err(materialized)

    try:
        parsed: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return Err(NetlabError(f"could not parse {_CLAB_OUTPUT}: {exc}", proc.stderr))

    if not isinstance(parsed, dict):
        return Err(NetlabError(f"{_CLAB_OUTPUT} was not a mapping", proc.stderr))

    try:
        raw_doc: Any = json.loads(raw_expanded)
        expanded = _ExpandedTopology.model_validate(raw_doc)
    except (json.JSONDecodeError, ValidationError) as exc:
        return Err(NetlabError(f"could not parse {_EXPANDED_OUTPUT}: {exc}", proc.stderr))

    links = _extract_links(expanded)
    if isinstance(links, Err):
        return Err(links.error)
    node_facts = _extract_node_facts(raw_doc)
    if isinstance(node_facts, Err):
        return Err(node_facts.error)
    return Ok(
        ClabArtifacts(
            topology=cast("ClabTopology", parsed),
            links=links.value,
            node_facts=node_facts.value,
            host_bridges=_host_bridges(expanded),
            kernel_modules=_kernel_modules(expanded),
        )
    )


@dataclass(frozen=True, slots=True)
class UnsupportedDirective:
    key: str
    reason: str


def _flatten_paths(value: object, prefix: tuple[str, ...]) -> list[tuple[tuple[str, ...], object]]:
    """Every (path, value) in a definition, with dotted keys split — netlab
    treats `defaults.netlab.up:` and nested `defaults: {netlab: {up:`
    identically, so the checks below must too. Lists are descended as well
    (`tc:` lives on `links:` entries), their indices riding the path as `[i]`
    components so a rejected key can name the entry it came from."""
    entries: list[tuple[tuple[str, ...], object]] = []
    if isinstance(value, dict):
        for key, member in cast("dict[object, object]", value).items():
            if not isinstance(key, str):
                continue
            path = prefix + tuple(key.split("."))
            entries.append((path, member))
            entries.extend(_flatten_paths(member, path))
    elif isinstance(value, list):
        for index, member in enumerate(cast("list[object]", value)):
            entries.extend(_flatten_paths(member, (*prefix, f"[{index}]")))
    return entries


def _display_path(path: tuple[str, ...]) -> str:
    """Dotted key for a message, list indices glued on: `links[1].tc`."""
    rendered = ""
    for part in path:
        rendered += part if part.startswith("[") or not rendered else f".{part}"
    return rendered


# netlab's seven `tc:` knobs (defaults/attributes.yml). A `tc` key is impairment
# only when it carries one of them — `defaults.tc.enable` is netlab's global
# switch for a step we never run, and a NODE may legitimately be named `tc`,
# which makes `tc:` on a link entry an endpoint rather than an attribute.
_TC_KNOBS = frozenset({"delay", "jitter", "loss", "corrupt", "duplicate", "reorder", "rate"})


def _tc_impairment_key(path: tuple[str, ...], value: object) -> str | None:
    if path[-1] == "tc":
        knobbed = isinstance(value, dict) and any(
            key in _TC_KNOBS for key in cast("dict[object, object]", value)
        )
        return _display_path(path) if knobbed else None
    if len(path) >= 2 and path[-2] == "tc" and path[-1] in _TC_KNOBS:
        return _display_path(path[:-1])  # report the `tc` key, not each knob
    return None


def find_unsupported_directives(definition: str) -> list[UnsupportedDirective]:
    """Definition keys that are legal netlab schema but that Twinlab REJECTS
    rather than silently ignores (up-parity decisions, docs/nos-sweep/):
    `tools:` side containers never start here, `defaults.netlab.up/down` shell
    hooks never run (arbitrary shell from a stored definition on a multi-user
    server is off the table — only the silence was the bug), an OVS
    `bridge_type` would silently get Linux bridges from hostprep, and link or
    interface `tc:` impairment is applied by `netlab up` alone — a step Twinlab
    replaces (gap 1, rejected for v1.0; the netem API impairs a deployed lab).
    An unparseable or non-mapping definition returns [] — the dry `netlab
    create` stays the syntax authority."""
    try:
        parsed: Any = yaml.safe_load(definition)
    except yaml.YAMLError:
        return []
    if not isinstance(parsed, dict):
        return []
    found: dict[str, UnsupportedDirective] = {}
    for path, value in _flatten_paths(cast("dict[object, object]", parsed), ()):
        if (tc_key := _tc_impairment_key(path, value)) is not None:
            found[tc_key] = UnsupportedDirective(
                tc_key,
                "definition-time `tc:` impairment is not applied — "
                "shape a deployed lab through the netem API",
            )
        elif path[0] == "tools":
            found["tools"] = UnsupportedDirective(
                "tools", "netlab's side-container tools are not started by Twinlab"
            )
        elif path[:3] in (("defaults", "netlab", "up"), ("defaults", "netlab", "down")):
            key = ".".join(path[:3])
            found[key] = UnsupportedDirective(
                key, "up/down shell hooks never run on a multi-user server"
            )
        elif path == ("defaults", "providers", "clab", "bridge_type") and value == "ovs-bridge":
            found["defaults.providers.clab.bridge_type"] = UnsupportedDirective(
                "defaults.providers.clab.bridge_type",
                "OVS bridges are not supported — hostprep creates Linux bridges",
            )
    return sorted(found.values(), key=lambda directive: directive.key)


def _materialize_node_files(source: Path, target: Path) -> NetlabError | None:
    """Replace `target` with the workdir's freshly generated `node_files/` tree
    (permissions preserved — sh-mode config scripts carry their exec bit). A
    topology that generated no files removes any stale tree, so a previous
    deploy's files can never leak into this one. Filesystem I/O is the boundary;
    failures come back typed."""
    try:
        if target.exists():
            shutil.rmtree(target)
        if source.is_dir():
            target.parent.mkdir(parents=True, exist_ok=True)
            _ = shutil.copytree(source, target)
    except OSError as exc:
        return NetlabError(f"could not materialize lab files at {target}: {exc}", "")
    return None


def rewrite_generated_binds(topology: ClabTopology, node_files_parent: str) -> ClabTopology:
    """Point per-node binds at the materialized `node_files/` tree: every bind
    whose source is a relative netlab-generated path gets `node_files_parent`
    (an absolute directory, same path on the host and in the clab-api container
    — see compose) prepended, so dockerd can mount it and clab-api's bind
    pre-flight can see it. A relative `startup-config` is rewritten the same way
    — inline deploy would otherwise ship it unsatisfiable. Everything else is
    untouched; returns a new topology, the input is not mutated."""
    prefix = node_files_parent.rstrip("/")
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
        if isinstance(binds, list):
            node_map["binds"] = [
                f"{prefix}/{bind}"
                if isinstance(bind, str) and bind.startswith(_GENERATED_BIND_PREFIX)
                else bind
                for bind in cast("list[object]", binds)
            ]
        startup = node_map.get("startup-config")
        if isinstance(startup, str) and startup.startswith(_GENERATED_BIND_PREFIX):
            node_map["startup-config"] = f"{prefix}/{startup}"
    return result


def strip_generated_binds(topology: ClabTopology) -> ClabTopology:
    """Drop per-node binds whose source is a netlab-generated `node_files/*` path
    — the fallback when no lab-files directory is configured (LAB_FILES_DIR
    unset; the compose stack always sets it, so this covers hand-rolled setups).

    Twinlab deploys the topology inline (clab-api `topologyContent`); with no
    materialized tree such a bind can't be satisfied on the clab-api host —
    clab-api rejects the deploy with "failed to verify bind path". Dropping is
    tolerable for kinds that regenerate what they need from the topology itself
    (e.g. cisco_iol's `ifstate`) and silently degrades the rest (frr's daemons
    file, the shared /etc/hosts) — which is why the rewrite path above is the
    real fix. A node left with no binds loses the now-empty `binds` key. Returns
    a new topology; the input is not mutated."""
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
