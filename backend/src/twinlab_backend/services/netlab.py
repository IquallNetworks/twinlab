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

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from twinlab_backend.result import Err, Ok, Result

# The parsed containerlab topology (name, topology.nodes/links, ...). The
# clab-api server wants it as a JSON object, so we hand back parsed data rather
# than raw YAML.
type ClabTopology = dict[str, object]

# `netlab create` writes the containerlab topology under this fixed name in its
# working directory (the clab provider's default output file).
_CLAB_OUTPUT = "clab.yml"
_CREATE_TIMEOUT_SECONDS = 120


@dataclass(frozen=True, slots=True)
class NetlabError:
    message: str
    stderr: str


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


def create_clab_topology(definition: str) -> Result[ClabTopology, NetlabError]:
    """Run `netlab create` on a netlab definition and return the generated
    containerlab topology as parsed data. The definition must state each node's
    `device` and the `provider` — Twinlab never defaults those."""
    with tempfile.TemporaryDirectory() as workdir:
        source = Path(workdir) / "topology.yml"
        _ = source.write_text(definition)

        try:
            proc = subprocess.run(
                ["netlab", "create", source.name],
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
        except OSError as exc:
            return Err(NetlabError(f"netlab create produced no {_CLAB_OUTPUT}: {exc}", proc.stderr))

    try:
        parsed: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return Err(NetlabError(f"could not parse {_CLAB_OUTPUT}: {exc}", proc.stderr))

    if not isinstance(parsed, dict):
        return Err(NetlabError(f"{_CLAB_OUTPUT} was not a mapping", proc.stderr))
    return Ok(cast("ClabTopology", parsed))
