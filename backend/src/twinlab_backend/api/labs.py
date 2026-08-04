"""Lab lifecycle endpoints.

Deploy is the netlab->containerlab handoff: generate the containerlab topology
from the netlab definition and deploy it through clab-api. Config push is
delegated to the netlab-runner sidecar (`netlab initial` over Ansible), which
owns device-specific configuration. A stable lab name is injected into the
definition so create/deploy/configure all target the same containers.

A lab is a durable record: its definition is stored on deploy and reused on
configure (the caller never resupplies it), and survives destroy. List/get merge
that stored record with live node state read from clab-api. This HTTP boundary
maps typed errors to status codes.
"""

import re
import shutil
import uuid
from http import HTTPStatus
from pathlib import Path as FsPath
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from twinlab_backend.api.jobs import SessionFactory, job_out, spawn_job
from twinlab_backend.api.templates import published_lab_summary
from twinlab_backend.api_errors import ApiError
from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import CurrentUserDep, require_global, require_lab
from twinlab_backend.auth.service import effective_permissions_bulk, effective_permissions_for
from twinlab_backend.db.models import Lab
from twinlab_backend.deps import (
    BuiltinLibraryDep,
    ClabClientDep,
    HostPrepDep,
    NetworkTemplatesDep,
    RunnerClientDep,
    SessionDep,
    SettingsDep,
)
from twinlab_backend.models import (
    BuiltinTemplateOut,
    ConfigTimeStatus,
    ConfigureRequest,
    ConfigureResponse,
    ContainerState,
    CreateLabRequest,
    CustomConfigResponse,
    DeployLabRequest,
    DeployResponse,
    DestroyResponse,
    Duration,
    JobOut,
    LabActionResponse,
    LabDetail,
    LabFactsResponse,
    LabLayoutResponse,
    LabLink,
    LabLinksResponse,
    LabNodeState,
    LabStatus,
    LabSummary,
    LabTemplateSet,
    LayoutGroupStyle,
    LayoutPosition,
    LinkEndpoint,
    LinkOperState,
    NetemImpairment,
    NetemSetRequest,
    NetworkTemplateSummary,
    NodeAction,
    NodeConfigResult,
    NodeInterface,
    NodeInterfaces,
    NodeLogsResponse,
    Principal,
    PutLayoutRequest,
    RuntimeActionResult,
    RuntimeActionsReport,
    RuntimeActionsRequest,
    SaveConfigResponse,
    SuiteReport,
    TestSuite,
    TestSuitesResponse,
    UpdateCustomConfigRequest,
    UpdateDefinitionRequest,
    UpdateTestSuitesRequest,
)
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services import job_store, lab_store
from twinlab_backend.services.clab_api import (
    ClabApiClient,
    ClabApiError,
    DeployedLab,
    NodeInfo,
    bare_mgmt_ip,
)
from twinlab_backend.services.clab_api import NetemImpairment as ClabNetemImpairment
from twinlab_backend.services.clab_api import NodeInterfaces as ClabNodeInterfaces
from twinlab_backend.services.clab_api import NodeLogs as ClabNodeLogs
from twinlab_backend.services.configimport import diff as configimport_diff
from twinlab_backend.services.custom_config import BuiltinLibrary
from twinlab_backend.services.device_catalog import LOCAL_ONLY_DEVICES, image_reference
from twinlab_backend.services.host_prep import HostPrepClient
from twinlab_backend.services.mgmt_subnet import MgmtSubnetError, allocate_subnet
from twinlab_backend.services.netlab import (
    ClabArtifacts,
    TopologyLink,
    create_clab_topology,
    find_unsupported_directives,
    read_message,
    read_mgmt_subnet,
    rewrite_generated_binds,
    serialize_links,
    set_lab_name,
    set_mgmt_subnet,
    strip_generated_binds,
)
from twinlab_backend.services.runner_client import ConfigureReport, RunnerClient, RunnerError
from twinlab_backend.services.validation import (
    NodeExecutor,
    NodeFacts,
    check_suite_templates,
    run_config_time_suites,
    run_suite,
)

router = APIRouter(prefix="/labs", tags=["labs"])

# Lab names come from netlab (e.g. tmpXXXX). Constrain the path segment to a
# tight charset with a leading alphanumeric so it can't become "." / ".." or
# otherwise reshape the URL sent to clab-api.
LabName = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
# Node names come from the definition (e.g. r1); same tight, path-safe charset.
NodeName = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
# Suite names come from the stored suites; same tight, path-safe charset.
SuiteName = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
# Whole-lab power controls clab-api exposes natively (POST /labs/{lab}/{action}).
LifecycleAction = Literal["start", "stop", "restart"]
# Per-node controls. clab-api adds pause/unpause on top of the lab-level set;
# they share the /nodes/{node}/{action} path, so node_action handles them as-is.
# The vocabulary itself lives in models.py (contract delta 24): the batch items
# and this path param must never drift apart.
# Lab-level freeze verbs. clab-api has no whole-lab pause, so these fan out over
# the lab's nodes (see `_lab_freeze`); non-atomic by nature.
FreezeAction = Literal["pause", "unpause"]


def _named_definition(definition: str, name: str) -> str:
    named = set_lab_name(definition, name)
    if isinstance(named, Err):
        raise ApiError(422, "netlab_invalid", named.error.message)
    return named.value


# Bounded retries when an auto-allocated subnet is raced by a concurrent create;
# each retry excludes the winner (now committed), so a handful always converges.
_ALLOCATE_ATTEMPTS = 8


async def _resolve_mgmt_subnet(
    named_definition: str, name: str, existing_subnet: str | None, db: AsyncSession, pool: str
) -> tuple[str, str]:
    """Decide a lab's management subnet and bake it into its definition, returning
    `(definition_with_mgmt, subnet)`. Precedence: an explicit `addressing.mgmt.ipv4`
    in the definition wins (intent is honored); else the record's existing subnet
    is reused (stable across redeploys); else a free /24 is allocated from `pool`.
    Takes the existing subnet as a plain value (not the ORM row) so it stays
    correct across the reservation retry loop's rollbacks."""
    explicit = read_mgmt_subnet(named_definition)
    if explicit is not None:
        subnet = explicit
    elif existing_subnet is not None:
        subnet = existing_subnet
    else:
        allocated = allocate_subnet(pool, await lab_store.used_mgmt_subnets(db))
        if isinstance(allocated, Err):
            raise _mgmt_subnet_failed(allocated.error)
        subnet = allocated.value

    injected = set_mgmt_subnet(named_definition, subnet, network_name=f"{name}_mgmt")
    if isinstance(injected, Err):
        raise _netlab_failed(injected.error.message, injected.error.stderr)
    return injected.value, subnet


def _config_time_status(config_time_ok: bool | None) -> ConfigTimeStatus:
    # DB representation is bool|None; the wire vocabulary is the tri-state.
    if config_time_ok is None:
        return "not_run"
    return "passed" if config_time_ok else "failed"


def _owner_principal(lab: Lab) -> Principal | None:
    return None if lab.owner is None else Principal(id=lab.owner.id, name=lab.owner.username)


def _lab_scoped(permissions: list[str]) -> list[str]:
    # Contract delta 10: per-lab permissions are masked to the lab-scoped set;
    # global-only perms ride on /auth/me.
    return [p for p in permissions if p in perms.LAB_SCOPED_PERMISSIONS]


def _to_models(report: ConfigureReport) -> list[NodeConfigResult]:
    return [
        NodeConfigResult(node=n.node, status=n.status, changed=n.changed, failed=n.failed)
        for n in report.nodes
    ]


def _container_state(node: NodeInfo) -> ContainerState:
    # clab-api passes docker's state through; validate against docker's
    # vocabulary (contract delta 3). An unknown state means our model of
    # clab-api is wrong — surface it loudly rather than mapping best-effort.
    match node.state:
        case "created" | "running" | "paused" | "restarting" | "removing" | "exited" | "dead":
            return node.state
        case _:
            raise ApiError(
                502,
                "upstream_error",
                f"unexpected container state {node.state!r} for '{node.container_name}'",
            )


def _to_node_state(node: NodeInfo) -> LabNodeState:
    # clab reports the mgmt address as CIDR; expose the bare IP so the UI can
    # build an `ssh <ip>` command without every consumer stripping the mask.
    mgmt_ip = bare_mgmt_ip(node.ipv4_address)
    return LabNodeState(
        name=node.node_name,
        container=node.container_name,
        image=node.image,
        state=_container_state(node),
        mgmt_ip=mgmt_ip,
    )


def _lab_status(lab: Lab) -> LabStatus:
    match lab.status:
        case "created" | "deploying" | "deployed" | "destroyed":
            return lab.status
        case _:
            raise ApiError(
                500, "internal_error", f"lab '{lab.name}' has invalid status {lab.status!r}"
            )


def _definition_drifted(lab: Lab) -> bool | None:
    """Delta 19: exact text comparison of the stored definition against the
    deployed snapshot. PUT normalizes the stored text (YAML re-dump with
    name/subnet re-pinned), so cosmetic edits — comments, formatting —
    normalize away and never flag drift; only changes surviving normalization
    do. None when nothing is running (status != "deployed") or the snapshot is
    unknown (a lab deployed before the column existed)."""
    if lab.status != lab_store.STATUS_DEPLOYED or lab.deployed_definition is None:
        return None
    return lab.definition != lab.deployed_definition


def lab_summary(
    lab: Lab, live: dict[str, tuple[NodeInfo, ...]], permissions: list[str]
) -> LabSummary:
    live_nodes = live.get(lab.name, ())
    return LabSummary(
        name=lab.name,
        status=_lab_status(lab),
        owner=_owner_principal(lab),
        created_at=lab.created_at,
        updated_at=lab.updated_at,
        nodes=len(live_nodes),
        # Counted on the raw passthrough (an off-vocabulary state simply isn't
        # "running") so one odd node can't 502 the whole listing.
        nodes_running=sum(1 for node in live_nodes if node.state == "running"),
        config_time_status=_config_time_status(lab.config_time_ok),
        definition_drifted=_definition_drifted(lab),
        permissions=_lab_scoped(permissions),
    )


def lab_detail(lab: Lab, nodes: tuple[NodeInfo, ...], permissions: list[str]) -> LabDetail:
    return LabDetail(
        name=lab.name,
        status=_lab_status(lab),
        definition=lab.definition,
        deployed_definition=lab.deployed_definition,
        definition_drifted=_definition_drifted(lab),
        owner=_owner_principal(lab),
        created_at=lab.created_at,
        updated_at=lab.updated_at,
        nodes=[_to_node_state(n) for n in nodes],
        config_time_status=_config_time_status(lab.config_time_ok),
        permissions=_lab_scoped(permissions),
        template_published=lab.template_published,
        message=read_message(lab.definition) if lab.definition is not None else None,
    )


def _load_suites(raw: dict[str, object] | None) -> dict[str, TestSuite]:
    """Parse a lab's stored suites back into the schema. The stored JSON was
    validated on write, so a parse failure here is a corrupt row (a real error),
    not a caller mistake."""
    if not raw:
        return {}
    return {name: TestSuite.model_validate(spec) for name, spec in raw.items()}


def _test_suites_response(lab: Lab) -> TestSuitesResponse:
    last = lab.last_validation or {}
    return TestSuitesResponse(
        test_suites=_load_suites(lab.test_suites),
        last_validation={name: SuiteReport.model_validate(rep) for name, rep in last.items()},
        config_time_status=_config_time_status(lab.config_time_ok),
    )


def _runner_executor(
    runner: RunnerClient, definition: str, templates: dict[str, str]
) -> NodeExecutor:
    """Bind a lab's definition to the runner's `netlab exec` as a NodeExecutor:
    (node, command) -> stdout. netlab picks the per-NOS transport (docker/ssh), so
    validation stays NOS-agnostic; the definition (stable name + mgmt subnet baked
    in) lets the runner rebuild the matching inventory. `templates` is the lab's
    custom-config fileset — the inventory's `netlab create` validates any `config:`
    reference, so a lab using custom config needs them here too."""

    async def execute(node: str, command: str, interactive: bool) -> Result[str, str]:
        result = await runner.exec_command(
            definition, node, command, templates, interactive=interactive
        )
        if isinstance(result, Err):
            return Err(result.error.message)
        return Ok(result.value)

    return execute


async def _node_facts_for(db: AsyncSession, lab: Lab, library: BuiltinLibrary) -> NodeFacts:
    """The lab's fact namespace (delta 17), from the record's cache — lazily
    regenerated from the stored definition when the cache predates the column.
    Callers guarantee `lab.definition` is set."""
    stored = _stored_node_facts(lab)
    if stored is not None:
        return stored
    if lab.definition is None:  # callers pre-check; defensive for typing
        raise ApiError(409, "no_definition", f"lab '{lab.name}' has no stored definition yet")
    artifacts = await run_in_threadpool(
        create_clab_topology, lab.definition, _config_fileset(library, lab)
    )
    if isinstance(artifacts, Err):
        # Unexpected — the stored definition passed its PUT-time dry run.
        raise _netlab_failed(artifacts.error.message, artifacts.error.stderr)
    facts = artifacts.value.node_facts
    _ = await lab_store.set_node_facts(db, lab.name, dict(facts))
    return facts


async def _run_config_time(
    runner: RunnerClient,
    db: AsyncSession,
    lab: Lab,
    definition: str,
    library: BuiltinLibrary,
    *,
    skip: bool,
) -> tuple[Literal["configured", "validation_failed"], list[SuiteReport] | None]:
    """Run the lab's config-time suites after a successful config push. Returns
    `(status, reports)`: `configured` when they pass — or are skipped, or none
    exist — and `validation_failed` when any fails. On a real run it persists the
    per-suite results and the config-time gate (so a failed config is unambiguous
    on the record); a skip leaves the prior gate untouched and reports nothing."""
    suites = _load_suites(lab.test_suites)
    if skip or not any(s.stage == "config-time" for s in suites.values()):
        return "configured", None
    executor = _runner_executor(runner, definition, _config_fileset(library, lab))
    facts = await _node_facts_for(db, lab, library)
    reports = await run_config_time_suites(executor, facts, suites)
    ok = all(r.ok for r in reports)
    stored: dict[str, object] = {r.suite: r.model_dump(mode="json") for r in reports}
    _ = await lab_store.record_validation(
        db, lab.name, stored, config_time_ok=ok, set_config_time=True
    )
    return ("configured" if ok else "validation_failed"), reports


def _logs_response(logs: ClabNodeLogs, node_name: str) -> NodeLogsResponse:
    return NodeLogsResponse(node=node_name, container=logs.container_name, logs=logs.logs)


def _short_node_name(container: str, lab_name: str) -> str:
    # clab-api keys interfaces by container name; the API exposes SHORT node
    # names (contract delta 6). Containerlab names containers clab-<lab>-<node>.
    prefix = f"clab-{lab_name}-"
    if not container.startswith(prefix):
        raise ApiError(502, "upstream_error", f"unexpected container name '{container}'")
    return container.removeprefix(prefix)


def _interfaces_response(
    nodes: tuple[ClabNodeInterfaces, ...], lab_name: str
) -> list[NodeInterfaces]:
    return [
        NodeInterfaces(
            node=_short_node_name(n.node_name, lab_name),
            interfaces=[
                NodeInterface(
                    name=i.name,
                    alias=i.alias,
                    ifindex=i.ifindex,
                    mac=i.mac,
                    mtu=i.mtu,
                    state=i.state,
                    kind=i.kind,
                )
                for i in n.interfaces
            ],
        )
        for n in nodes
    ]


_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)(us|ms|s)$")


def _parse_duration(raw: str, *, interface: str) -> Duration | None:
    """clab-api reports netem durations as tc strings ("50ms"; empty or zero =
    unshaped). Translate to the structured {value, unit} pair (contract delta
    7); an unrecognized format is a loud upstream error."""
    if raw == "":
        return None
    matched = _DURATION_RE.match(raw)
    if matched is None:
        raise ApiError(502, "upstream_error", f"unexpected netem duration {raw!r} on '{interface}'")
    value = float(matched.group(1))
    if value == 0:
        return None
    match matched.group(2):
        case "us" | "ms" | "s" as unit:
            return Duration(value=value, unit=unit)
        case _:  # unreachable: the regex only admits the three units
            raise ApiError(502, "upstream_error", f"unexpected netem unit in {raw!r}")


def _duration_string(duration: Duration | None) -> str | None:
    # clab-api's wire wants tc strings; :g drops a trailing .0 ("50ms", "0.5ms").
    return None if duration is None else f"{duration.value:g}{duration.unit}"


def _netem_model(impairment: ClabNetemImpairment) -> NetemImpairment:
    return NetemImpairment(
        interface=impairment.interface,
        delay=_parse_duration(impairment.delay, interface=impairment.interface),
        jitter=_parse_duration(impairment.jitter, interface=impairment.interface),
        loss=impairment.loss,
        rate=impairment.rate,
        corruption=impairment.corruption,
    )


async def _resolve_container(clab: ClabApiClient, lab_name: str, node_name: str) -> str:
    """Map a short node name to its clab container name via a live inspect. netem
    is keyed by container (not the short node name clab-api's node routes accept),
    so we resolve it from live state rather than reconstructing clab's naming."""
    inspected = await clab.inspect(lab_name)
    if isinstance(inspected, Err):
        raise _clab_action_failed(inspected.error)
    for node in inspected.value:
        if node.node_name == node_name:
            return node.container_name
    raise ApiError(404, "node_not_found", f"node '{node_name}' not found in lab '{lab_name}'")


def _user_fileset(lab: Lab) -> dict[str, str]:
    """A lab's stored user templates as a {relpath: source} fileset. Values were
    validated as strings on write; a non-string is a corrupt row and dropped."""
    raw = lab.custom_config or {}
    return {path: content for path, content in raw.items() if isinstance(content, str)}


def _config_fileset(library: BuiltinLibrary, lab: Lab) -> dict[str, str]:
    """The custom-config fileset shipped to the runner for a configure: the whole
    built-in library plus the lab's user templates. Collisions are prevented at
    write time (a user path may not shadow a built-in), so the merge is safe;
    netlab renders only the templates the definition's `config:` references."""
    return library.fileset | _user_fileset(lab)


def link_oper_state(states: list[str | None]) -> LinkOperState:
    """Roll a link's endpoint interface states up into the derived link state
    (contract delta 14): all "up" -> up; all known-not-up -> down; a mix of
    known states -> degraded; any unknown endpoint -> unknown."""
    if not states or any(state is None for state in states):
        return "unknown"
    if all(state == "up" for state in states):
        return "up"
    if all(state != "up" for state in states):
        return "down"
    return "degraded"


def merge_links(
    stored: list[TopologyLink],
    inventory: dict[str, list[NodeInterface]] | None,
    impairments: dict[str, list[NetemImpairment]],
) -> LabLinksResponse:
    """Assemble the link-table response: the stored logical links overlaid with
    live per-interface state and active impairment. `inventory` is keyed by
    SHORT node name; None means live state could not be resolved (lab not
    deployed / inventory unavailable) -> live=False, every state unknown. An
    endpoint is matched against its node's inventory by name OR alias (a
    renaming kind like cisco_iol advertises the NOS name as the alias);
    matched endpoints report the live container-side name."""
    links: list[LabLink] = []
    for link in stored:
        endpoints: list[LinkEndpoint] = []
        for endpoint in link.endpoints:
            live = None
            if inventory is not None:
                live = next(
                    (
                        candidate
                        for candidate in inventory.get(endpoint.node, [])
                        if endpoint.clab_name in (candidate.name, candidate.alias)
                    ),
                    None,
                )
            interface = live.name if live is not None else endpoint.clab_name
            impairment = next(
                (
                    entry
                    for entry in impairments.get(endpoint.node, [])
                    if entry.interface == interface
                ),
                None,
            )
            endpoints.append(
                LinkEndpoint(
                    node=endpoint.node,
                    interface=interface,
                    ifname=endpoint.ifname,
                    ifindex=endpoint.ifindex,
                    ipv4=endpoint.ipv4,
                    ipv6=endpoint.ipv6,
                    state=live.state if live is not None else None,
                    impairment=impairment,
                )
            )
        links.append(
            LabLink(
                index=link.index,
                name=link.name,
                type=link.type,
                prefix_ipv4=link.prefix_ipv4,
                prefix_ipv6=link.prefix_ipv6,
                bandwidth=link.bandwidth,
                mtu=link.mtu,
                oper_state=link_oper_state([e.state for e in endpoints]),
                endpoints=endpoints,
            )
        )
    return LabLinksResponse(links=links, live=inventory is not None)


def _stored_links(lab: Lab) -> list[TopologyLink] | None:
    """Parse the lab's cached link table; None = absent or unreadable (a shape
    change since it was written) — both healed by regeneration."""
    if lab.links is None:
        return None
    raw = lab.links.get("links")
    if not isinstance(raw, list):
        return None
    try:
        return [TopologyLink.model_validate(item) for item in cast("list[object]", raw)]
    except ValidationError:
        return None


def _stored_node_facts(lab: Lab) -> dict[str, dict[str, object]] | None:
    """The lab's cached fact namespace; None = absent (rows predating the
    column) — healed by regeneration. Values are raw netlab node dicts
    (delta 17: provisional, unpinned), so only the outer shape is checked."""
    if lab.node_facts is None:
        return None
    facts: dict[str, dict[str, object]] = {}
    for name, data in lab.node_facts.items():
        if not isinstance(data, dict):
            return None
        facts[name] = cast("dict[str, object]", data)
    return facts


async def _live_link_state(
    clab: ClabApiClient, lab: Lab, links: list[TopologyLink]
) -> tuple[dict[str, list[NodeInterface]] | None, dict[str, list[NetemImpairment]]]:
    """Best-effort live overlay for the link table. Upstream failures degrade
    (None inventory -> live=False; a node's failed netem show -> no impairment
    data) rather than failing the read — the table itself is stored data."""
    if lab.status != lab_store.STATUS_DEPLOYED:
        return None, {}
    inventory_result = await clab.interfaces(lab.name)
    if isinstance(inventory_result, Err):
        return None, {}
    try:
        converted = _interfaces_response(inventory_result.value, lab.name)
    except ApiError:
        # An unexpected container name 502s the /interfaces route (the loud
        # path); here an unreadable inventory just means "not live".
        return None, {}
    inventory = {entry.node: entry.interfaces for entry in converted}
    # One inspect resolves every endpoint container at once (netem is keyed by
    # container name).
    endpoint_nodes = {endpoint.node for link in links for endpoint in link.endpoints}
    inspected = await clab.inspect(lab.name)
    if isinstance(inspected, Err):
        return inventory, {}
    containers = {
        node.node_name: node.container_name
        for node in inspected.value
        if node.node_name in endpoint_nodes and node.state == "running"
    }

    # The netem shows run SEQUENTIALLY: clab-api serializes netem per lab — a
    # concurrent call gets 409 "busy with netem operation", so a fan-out would
    # defeat itself and quietly degrade to "no data" (implementation finding).
    impairments: dict[str, list[NetemImpairment]] = {}
    for node, container in containers.items():
        shown = await clab.show_netem(container)
        if isinstance(shown, Err):
            impairments[node] = []
            continue
        try:
            impairments[node] = [_netem_model(entry) for entry in shown.value]
        except ApiError:
            # A malformed tc duration 502s the per-node netem route (the loud
            # path); here it must not take down the whole table.
            impairments[node] = []
    return inventory, impairments


def _custom_config_response(library: BuiltinLibrary, lab: Lab) -> CustomConfigResponse:
    return CustomConfigResponse(
        builtin=[
            BuiltinTemplateOut(name=t.name, description=t.description, files=t.files)
            for t in library.templates
        ],
        custom_config=_user_fileset(lab),
    )


async def _push_config(
    runner: RunnerClient, definition: str, templates: dict[str, str]
) -> Result[ConfigureReport, ApiError]:
    report = await runner.configure(definition, templates)
    if isinstance(report, Err):
        return Err(_runner_failed(report.error))
    return Ok(report.value)


async def _live_detail(lab: Lab, clab: ClabApiClient, permissions: list[str]) -> LabDetail:
    """Merge a stored lab record with its live node state from clab-api. A lab not
    currently deployed (inspect 404) simply has no live nodes; any other clab-api
    failure is surfaced as 502."""
    inspected = await clab.inspect(lab.name)
    if isinstance(inspected, Ok):
        nodes = inspected.value
    elif inspected.error.status_code == HTTPStatus.NOT_FOUND:
        nodes = ()
    else:
        raise ApiError(502, "upstream_error", inspected.error.message)
    return lab_detail(lab, nodes, permissions)


async def _generate_topology(
    definition: str, templates: dict[str, str], node_files_target: FsPath | None = None
) -> Result[ClabArtifacts, ApiError]:
    """Run `netlab create` (off the event loop — blocking subprocess work) and
    map a failure onto the error envelope. `templates` is the custom-config
    fileset the definition may reference — `netlab create` validates those
    exist. `node_files_target` (deploy only) materializes the generated
    `node_files/` tree for the bind rewrite. Returns the ApiError as a value so
    the caller can restore lab state before re-raising, rather than unwinding
    through an exception."""
    artifacts = await run_in_threadpool(
        create_clab_topology, definition, templates, node_files_target
    )
    if isinstance(artifacts, Err):
        return Err(_netlab_failed(artifacts.error.message, artifacts.error.stderr))
    return Ok(artifacts.value)


async def _prepare_host(
    db: AsyncSession, hostprep: HostPrepClient | None, lab_name: str, artifacts: ClabArtifacts
) -> ApiError | None:
    """Host preparation before the clab deploy — `netlab up`'s pre-start work,
    done through the hostprep sidecar: create the host bridges multi-access
    links need and load the kernel modules the topology's devices ask for.
    No-op when the topology needs nothing, so a stack without the sidecar
    still deploys every such lab. Returned (not raised) so the caller restores
    the lab status first."""
    bridges = list(artifacts.host_bridges)
    modules = [module.name for module in artifacts.kernel_modules]
    if not bridges and not modules:
        return None
    if hostprep is None:
        return ApiError(
            503,
            "hostprep_unavailable",
            "this topology needs host preparation (bridges/kernel modules) "
            "but no hostprep sidecar is configured",
        )
    if bridges:
        # Bridge names truncate the lab name to 10 chars, so two labs sharing
        # a prefix (and a linkindex) would share a bridge — silently
        # cross-wiring their segments in netlab's own workflow. The persisted
        # claims let Twinlab refuse loudly instead.
        owners = await lab_store.bridge_owners(db, exclude_lab=lab_name)
        taken = sorted(bridge for bridge in bridges if bridge in owners)
        if taken:
            return ApiError(
                409,
                "bridge_conflict",
                f"host bridge(s) {', '.join(taken)} belong to another lab — lab names "
                "sharing their first 10 characters collide on bridge names; rename one lab",
            )
        # Claim BEFORE creating, so cleanup always knows what may exist.
        _ = await lab_store.set_host_bridges(db, lab_name, bridges)
        ensured = await hostprep.ensure_bridges(bridges)
        if isinstance(ensured, Err):
            return ApiError(502, "hostprep_failed", ensured.error.message)
        conflicts = [o for o in ensured.value if o.status == "not_bridge"]
        if conflicts:
            names = ", ".join(o.name for o in conflicts)
            return ApiError(
                409,
                "bridge_conflict",
                f"host interface(s) {names} already exist and are not bridges",
            )
        failures = [o for o in ensured.value if o.status not in ("created", "existed")]
        if failures:
            detail = "; ".join(f"{o.name}: {o.detail}" for o in failures)
            return ApiError(502, "hostprep_failed", f"could not create host bridge(s): {detail}")
    if modules:
        loaded = await hostprep.load_modules(modules)
        if isinstance(loaded, Err):
            return ApiError(502, "hostprep_failed", loaded.error.message)
        required = {module.name for module in artifacts.kernel_modules if module.required}
        # Only required modules fail the deploy (netlab's own `?` semantics):
        # without them the lab's dataplane silently wouldn't work.
        missing = [o for o in loaded.value if not o.ok and o.name in required]
        if missing:
            detail = "; ".join(f"{o.name}: {o.detail}" for o in missing)
            return ApiError(
                502,
                "kernel_module_missing",
                f"required kernel module(s) failed to load: {detail}",
            )
    return None


async def _prune_stale_bridges(
    db: AsyncSession,
    hostprep: HostPrepClient | None,
    lab_name: str,
    previous: list[str],
    needed: tuple[str, ...],
) -> None:
    """After a successful (re)deploy: drop bridges claimed by an earlier
    definition version that the fresh topology no longer needs (clab has
    rewired the lab, so their veths are gone). Never fails the deploy — a
    bridge that can't be deleted stays on the claim so the next destroy
    retries it; the claim always lists exactly what may exist on the host."""
    if not previous and not needed:
        return
    stale = sorted(set(previous) - set(needed))
    kept: list[str] = []
    if stale:
        if hostprep is None:
            kept = stale
        else:
            pruned = await hostprep.delete_bridges(stale)
            if isinstance(pruned, Err):
                kept = stale
            else:
                kept = [o.name for o in pruned.value if o.status not in ("deleted", "absent")]
    claim = sorted({*needed, *kept})
    _ = await lab_store.set_host_bridges(db, lab_name, claim if claim else None)


async def _release_host_bridges(
    db: AsyncSession, hostprep: HostPrepClient | None, lab_name: str
) -> None:
    """Destroy-time cleanup of the lab's claimed host bridges (the teardown is
    already done and recorded when this runs). Raises on anything left behind:
    a bridge leaked on the host is an operator problem to surface, never to
    swallow — the claim stays on the record, so a redeploy (idempotent ensure)
    or a later delete retries it."""
    lab = await lab_store.get_lab(db, lab_name, include_deleted=True)
    bridges = list(lab.host_bridges or []) if lab else []
    if not bridges:
        return
    if hostprep is None:
        raise ApiError(
            503,
            "hostprep_unavailable",
            f"lab claims host bridge(s) {', '.join(bridges)} but no hostprep sidecar "
            "is configured to remove them",
        )
    deleted = await hostprep.delete_bridges(bridges)
    if isinstance(deleted, Err):
        raise ApiError(502, "hostprep_failed", deleted.error.message)
    leftovers = [o for o in deleted.value if o.status not in ("deleted", "absent")]
    if leftovers:
        detail = "; ".join(
            f"{o.name}: {o.status}" + (f" ({o.detail})" if o.detail else "") for o in leftovers
        )
        raise ApiError(409, "bridge_conflict", f"could not remove host bridge(s): {detail}")
    _ = await lab_store.set_host_bridges(db, lab_name, None)


def image_preflight_report(
    artifacts: ClabArtifacts, present: frozenset[str]
) -> tuple[list[str], list[str]]:
    """The deploy image pre-flight's findings as `(fatal, warnings)` — pure so
    it unit-tests without a runner. Fatal = a missing image whose device the
    catalog marks local-only (never pullable, the deploy is IMPOSSIBLE);
    warning = missing but pullable (docker pulls at deploy). Devices outside
    the catalog count as pullable — unknown is not a reason to block."""
    fatal: list[str] = []
    warnings: list[str] = []
    inner = artifacts.topology.get("topology")
    nodes = cast("dict[str, object]", inner).get("nodes") if isinstance(inner, dict) else None
    if not isinstance(nodes, dict):
        return ([], [])
    for name, node in cast("dict[str, object]", nodes).items():
        image = cast("dict[str, object]", node).get("image") if isinstance(node, dict) else None
        if not isinstance(image, str) or image_reference(image) in present:
            continue
        facts = artifacts.node_facts.get(name)
        device = facts.get("device") if facts is not None else None
        if isinstance(device, str) and device in LOCAL_ONLY_DEVICES:
            fatal.append(f"node '{name}' needs image {image} (device {device})")
        else:
            warnings.append(
                f"image {image} for node '{name}' is not on the host; "
                "the deploy will try to pull it"
            )
    return (fatal, warnings)


async def _image_preflight(runner: RunnerClient, artifacts: ClabArtifacts) -> ApiError | list[str]:
    """Deploy's first job step (up-parity gap 3, decision 2026-08-04): reject
    only an impossible deploy. Missing + local-only device → fail fast with a
    friendly error instead of clab-api's late opaque 502; missing + pullable →
    proceed, the warning rides the deploy result; runner unreachable → proceed
    (the check must never add a failure mode of its own)."""
    listed = await runner.list_images()
    if isinstance(listed, Err):
        return ["image pre-flight skipped: netlab-runner unreachable"]
    fatal, warnings = image_preflight_report(artifacts, listed.value)
    if fatal:
        return ApiError(
            409,
            "image_missing",
            "image(s) not on the host and not publicly pullable: "
            + "; ".join(fatal)
            + " — load them on the host, then redeploy",
        )
    return warnings


async def _finish_deploy(
    deployed: DeployedLab,
    definition: str,
    runner: RunnerClient,
    db: AsyncSession,
    lab: Lab,
    library: BuiltinLibrary,
    *,
    configure: bool,
    skip_config_time: bool,
    warnings: list[str],
) -> DeployResponse:
    """Shared tail of deploy and redeploy: optionally push config, then run the
    config-time suites and build the response. Raises on a config-push failure; a
    config-time validation failure is reported (status `validation_failed`), not
    raised — the lab stays deployed. `warnings` are the image pre-flight's
    non-fatal findings, carried onto every outcome."""
    nodes = [n.node_name for n in deployed.nodes]
    # Always wait for the devices to actually be ready (NOS booted, accepting
    # SSH/console) before reporting the deploy done — even without a config push.
    # IOL/IOS keeps booting ~60-90s after its container is up, so a bare deploy
    # that returned immediately would hand back nodes that reject connections.
    templates = _config_fileset(library, lab)
    ready = await runner.ready(definition, templates)
    if isinstance(ready, Err):
        raise _ready_failed(ready.error)
    if not configure:
        return DeployResponse(
            status="deployed", lab_name=deployed.name, nodes=nodes, warnings=warnings
        )
    pushed = await _push_config(runner, definition, templates)
    if isinstance(pushed, Err):
        raise pushed.error
    report = pushed.value
    configuration = _to_models(report)
    if not report.succeeded:
        # The push RAN; a per-node failure is data, not an HTTP error (contract
        # delta 9). The gate doesn't run on a failed push.
        return DeployResponse(
            status="config_failed",
            lab_name=deployed.name,
            nodes=nodes,
            configuration=configuration,
            validation=None,
            warnings=warnings,
        )
    status, validation = await _run_config_time(
        runner, db, lab, definition, library, skip=skip_config_time
    )
    return DeployResponse(
        status=status,
        lab_name=deployed.name,
        nodes=nodes,
        configuration=configuration,
        validation=validation,
        warnings=warnings,
    )


@router.post("", status_code=201, dependencies=[Depends(require_global(perms.LAB_CREATE))])
async def create_lab(
    request: CreateLabRequest,
    db: SessionDep,
    user: CurrentUserDep,
    settings: SettingsDep,
) -> LabDetail:
    # The lifecycle split's cheap create: a bare record (status `created`, no
    # definition, nothing deployed) with the lab's mgmt /24 allocated up front —
    # so the slow deploy path carries no reservation machinery. The caller
    # becomes the owner. Authoring (PUT definition/suites/templates) and deploy
    # are separate verbs.
    for _ in range(_ALLOCATE_ATTEMPTS):
        allocated = allocate_subnet(
            settings.mgmt_subnet_pool, await lab_store.used_mgmt_subnets(db)
        )
        if isinstance(allocated, Err):
            raise _mgmt_subnet_failed(allocated.error)
        created = await lab_store.create_lab(db, request.name, allocated.value, user.id)
        if isinstance(created, Lab):
            granted = sorted(await effective_permissions_for(db, user, created))
            return lab_detail(created, (), granted)
        if created.reason == "name_taken":
            raise ApiError(409, "lab_exists", f"lab '{request.name}' already exists")
        # subnet_taken: raced by a concurrent create — the winner is excluded
        # from the next allocation round.
    raise ApiError(503, "mgmt_subnet_exhausted", "could not reserve a free mgmt subnet")


@router.put("/{lab_name}", dependencies=[Depends(require_lab(perms.LAB_EDIT))])
async def update_lab_definition(
    lab_name: LabName,
    request: UpdateDefinitionRequest,
    clab: ClabClientDep,
    db: SessionDep,
    settings: SettingsDep,
    library: BuiltinLibraryDep,
    user: CurrentUserDep,
) -> LabDetail:
    # Editing a lab's definition is authoring the topology, so it takes lab:create.
    # The lab's name is fixed by the record and re-pinned here, so the edit can't
    # rename (and orphan) the lab; its mgmt subnet is likewise re-pinned so an edit
    # keeps the same mgmt network (unless the edit names its own). The running lab
    # is untouched until a redeploy; we validate the new definition by generating
    # from it and reject a broken one.
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")

    # Legal netlab keys Twinlab decided to reject rather than silently ignore
    # (up-parity decisions, docs/nos-sweep/): the dry create below would accept
    # them and the deploy would quietly not honor them.
    unsupported = find_unsupported_directives(request.definition)
    if unsupported:
        raise ApiError(
            422,
            "unsupported_directive",
            "the definition uses netlab features Twinlab does not honor: "
            + ", ".join(directive.key for directive in unsupported),
            {"directives": [{"key": d.key, "reason": d.reason} for d in unsupported]},
        )

    definition = _named_definition(request.definition, lab_name)
    definition, mgmt_subnet = await _resolve_mgmt_subnet(
        definition, lab_name, lab.mgmt_subnet, db, settings.mgmt_subnet_pool
    )
    # Validate against the same fileset a deploy would ship (built-ins + the lab's
    # stored user templates), since netlab create checks the `config:` references.
    validated = await run_in_threadpool(
        create_clab_topology, definition, _config_fileset(library, lab)
    )
    if isinstance(validated, Err):
        raise _netlab_failed(validated.error.message, validated.error.stderr)

    updated = await lab_store.update_definition(
        db,
        lab_name,
        definition,
        mgmt_subnet,
        serialize_links(validated.value.links),
        dict(validated.value.node_facts),
    )
    if isinstance(updated, lab_store.LabStoreError):
        if updated.reason == "subnet_taken":
            raise ApiError(409, "mgmt_subnet_taken", f"mgmt subnet {mgmt_subnet} is already in use")
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    # `updated_at` has a server-side onupdate, so the UPDATE expires it; refresh it
    # in this async context before rendering, or reading it in lab_detail triggers a
    # sync lazy-load (MissingGreenlet) outside a greenlet.
    await db.refresh(updated, ["updated_at"])
    granted = sorted(await effective_permissions_for(db, user, updated))
    return await _live_detail(updated, clab, granted)


async def _submit_job(
    db: AsyncSession,
    lab_id: uuid.UUID,
    lab_name: str,
    kind: str,
    params: dict[str, object],
    user_id: uuid.UUID,
) -> job_store.Job | ApiError:
    """Take the lab's job mutex by inserting the running row (409 `job_in_flight`
    with the holder in extras when another job is running), then prune old
    history. Takes plain values, not the Lab row: a losing submit ROLLS BACK the
    session, expiring every instance in it — touching the ORM row afterwards
    would trip an expired-attribute load."""
    submitted = await job_store.submit_job(db, lab_id, kind, params, user_id)
    if isinstance(submitted, job_store.JobStoreError):
        # The running job is by construction the newest (a later submit would
        # have been rejected); name it so the caller can poll or wait it out.
        holder = await job_store.list_jobs(db, lab_id, limit=1)
        extras: dict[str, object] = (
            {"job_id": str(holder[0].id), "kind": holder[0].kind} if holder else {}
        )
        return ApiError(
            409, "job_in_flight", f"another job is already running on '{lab_name}'", extras
        )
    await job_store.prune_finished(db, lab_id)
    return submitted


async def _deploy_job(
    session_factory: SessionFactory,
    clab: ClabApiClient,
    runner: RunnerClient,
    hostprep: HostPrepClient | None,
    library: BuiltinLibrary,
    lab_name: str,
    *,
    lab_files_dir: str,
    previous_status: str,
    configure: bool,
    skip_config_time: bool,
) -> DeployResponse:
    """The deploy operation, run inside a job task: fresh session, lab re-fetched.
    Generate -> prepare the host (bridges/kernel modules via hostprep) -> clab
    deploy. A failure up to and including the clab deploy restores the pre-deploy
    status before re-raising; failures past mark_deployed (readiness, config
    push) leave the lab deployed."""
    async with session_factory() as db:
        lab = await lab_store.get_lab(db, lab_name)
        if lab is None or lab.definition is None:
            # Unreachable via the API (the mutex holds and pre-checks passed at
            # submit) — typed anyway so a corrupt row fails the job loudly.
            raise ApiError(409, "no_definition", f"lab '{lab_name}' lost its definition")
        definition = lab.definition
        previous_bridges = list(lab.host_bridges or [])
        lab_dir = FsPath(lab_files_dir) / lab_name if lab_files_dir else None
        generated = await _generate_topology(
            definition,
            _config_fileset(library, lab),
            node_files_target=lab_dir / "node_files" if lab_dir is not None else None,
        )
        if isinstance(generated, Err):
            _ = await lab_store.set_status(db, lab_name, previous_status)
            raise generated.error
        artifacts = generated.value
        preflight = await _image_preflight(runner, artifacts)
        if isinstance(preflight, ApiError):
            _ = await lab_store.set_status(db, lab_name, previous_status)
            raise preflight
        image_warnings = preflight
        prep_failed = await _prepare_host(db, hostprep, lab_name, artifacts)
        if prep_failed is not None:
            _ = await lab_store.set_status(db, lab_name, previous_status)
            raise prep_failed
        # We deploy inline (topologyContent). With a lab-files directory the
        # node_files/ tree was just materialized there, so point the generated
        # binds at it — absolute, the same path dockerd mounts from and clab-api
        # pre-flights in. Without one, fall back to dropping them (kinds that
        # regenerate their files tolerate it; bind-dependent config doesn't).
        shippable = (
            rewrite_generated_binds(artifacts.topology, str(lab_dir))
            if lab_dir is not None
            else strip_generated_binds(artifacts.topology)
        )
        deployed = await clab.deploy(shippable, reconfigure=True)
        if isinstance(deployed, Err):
            # Bridges created above are left in place (harmless when idle, and
            # possibly still wired mid-overwrite): the claim keeps them
            # tracked, and the next deploy or destroy reconciles.
            _ = await lab_store.set_status(db, lab_name, previous_status)
            raise _deploy_failed(deployed.error.message)
        await _prune_stale_bridges(db, hostprep, lab_name, previous_bridges, artifacts.host_bridges)
        # The deploy's own `netlab create` just produced the link table and the
        # fact namespace — refresh both stored caches (free backfill for rows
        # predating the columns).
        _ = await lab_store.set_links(db, lab_name, serialize_links(artifacts.links))
        _ = await lab_store.set_node_facts(db, lab_name, dict(artifacts.node_facts))
        _ = await lab_store.mark_deployed(db, lab_name, deployed_definition=definition)
        return await _finish_deploy(
            deployed.value,
            definition,
            runner,
            db,
            lab,
            library,
            configure=configure,
            skip_config_time=skip_config_time,
            warnings=image_warnings,
        )


@router.post(
    "/{lab_name}/deploy", status_code=202, dependencies=[Depends(require_lab(perms.LAB_EDIT))]
)
async def deploy_lab(
    lab_name: LabName,
    http_request: Request,
    clab: ClabClientDep,
    runner: RunnerClientDep,
    hostprep: HostPrepDep,
    db: SessionDep,
    library: BuiltinLibraryDep,
    settings: SettingsDep,
    user: CurrentUserDep,
    request: DeployLabRequest | None = None,
) -> JobOut:
    # THE deploy verb (lifecycle split): build the lab from its stored
    # definition + suites + custom config — fresh if created/destroyed,
    # overwrite-in-place if running (clab reconfigure). The caller never
    # resupplies the definition. 202 + the running job (contract delta 12);
    # the body is optional (a bare deploy).
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    if lab.definition is None:
        raise ApiError(409, "no_definition", f"lab '{lab_name}' has no stored definition yet")

    body = request if request is not None else DeployLabRequest()
    lab_id = lab.id  # captured before submit: a losing submit expires the row
    previous_status = lab.status
    params: dict[str, object] = {
        "configure": body.configure,
        "skip_config_time_checks": body.skip_config_time_checks,
        # Private bookkeeping (stripped from the echo): what a failed deploy —
        # or the restart sweep — restores the lab's status to.
        "_previous_status": previous_status,
    }
    job = await _submit_job(db, lab_id, lab_name, "deploy", params, user.id)
    if isinstance(job, ApiError):
        raise job
    # Display status only — the job row is the lock.
    _ = await lab_store.set_status(db, lab_name, lab_store.STATUS_DEPLOYING)

    session_factory: SessionFactory = http_request.app.state.session_factory

    async def work() -> DeployResponse:
        return await _deploy_job(
            session_factory,
            clab,
            runner,
            hostprep,
            library,
            lab_name,
            lab_files_dir=settings.lab_files_dir,
            previous_status=previous_status,
            configure=body.configure,
            skip_config_time=body.skip_config_time_checks,
        )

    spawn_job(http_request, job, lab_name, work)
    return job_out(job, lab_name)


@router.get("")
async def list_labs(clab: ClabClientDep, db: SessionDep, user: CurrentUserDep) -> list[LabSummary]:
    # The catalog is filtered to what the caller may read: a global lab:read sees
    # everything; otherwise only owned labs and labs granted to them (directly or via
    # a group). A user with no grants gets an empty list — no blanket read guard.
    # Per-lab permissions are resolved in one grant load and carried on each row so
    # the list can gate per-row actions correctly.
    labs = await lab_store.list_labs(db)
    perms_by_lab = await effective_permissions_bulk(db, user, labs)
    visible = [lab for lab in labs if perms.LAB_READ in perms_by_lab[lab.id]]
    # Live node state is best-effort enrichment; if clab-api is unreachable the
    # durable catalog still lists, with node counts of 0.
    live_result = await clab.list_labs()
    live = live_result.value if isinstance(live_result, Ok) else {}
    return [lab_summary(lab, live, sorted(perms_by_lab[lab.id])) for lab in visible]


@router.get("/{lab_name}", dependencies=[Depends(require_lab(perms.LAB_READ))])
async def get_lab(
    lab_name: LabName, clab: ClabClientDep, db: SessionDep, user: CurrentUserDep
) -> LabDetail:
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    granted = sorted(await effective_permissions_for(db, user, lab))
    return await _live_detail(lab, clab, granted)


async def _configure_job(
    session_factory: SessionFactory,
    runner: RunnerClient,
    library: BuiltinLibrary,
    lab_name: str,
    *,
    skip_config_time: bool,
) -> ConfigureResponse:
    """The configure operation, run inside a job task. A push that couldn't run
    raises (fails the job); one that ran with per-node failures is data
    (contract delta 9) — the job succeeds with status `config_failed`."""
    async with session_factory() as db:
        lab = await lab_store.get_lab(db, lab_name)
        if lab is None or lab.definition is None:
            raise ApiError(409, "no_definition", f"lab '{lab_name}' lost its definition")
        definition = lab.definition
        pushed = await _push_config(runner, definition, _config_fileset(library, lab))
        if isinstance(pushed, Err):
            raise pushed.error
        report = pushed.value
        configuration = _to_models(report)
        if not report.succeeded:
            return ConfigureResponse(
                status="config_failed",
                lab_name=lab_name,
                configuration=configuration,
                validation=None,
            )
        status, validation = await _run_config_time(
            runner, db, lab, definition, library, skip=skip_config_time
        )
        return ConfigureResponse(
            status=status, lab_name=lab_name, configuration=configuration, validation=validation
        )


@router.post(
    "/{lab_name}/configure",
    status_code=202,
    dependencies=[Depends(require_lab(perms.LAB_CONFIGURE))],
)
async def configure_nodes(
    lab_name: LabName,
    http_request: Request,
    runner: RunnerClientDep,
    db: SessionDep,
    library: BuiltinLibraryDep,
    user: CurrentUserDep,
    request: ConfigureRequest | None = None,
) -> JobOut:
    # The definition is the lab's stored source of truth; the caller does not
    # resupply it. Config rendering is deterministic, so it reproduces the
    # intended per-node config. After the push, the lab's config-time suites run
    # (unless skipped) to gate "config done". 202 + the running job; the body is
    # optional (a bare configure keeps the default: run the checks).
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    if lab.definition is None:
        raise ApiError(409, "no_definition", f"lab '{lab_name}' has no stored definition yet")

    skip = request.skip_config_time_checks if request is not None else False
    lab_id = lab.id  # captured before submit: a losing submit expires the row
    job = await _submit_job(
        db, lab_id, lab_name, "configure", {"skip_config_time_checks": skip}, user.id
    )
    if isinstance(job, ApiError):
        raise job

    session_factory: SessionFactory = http_request.app.state.session_factory

    async def work() -> ConfigureResponse:
        return await _configure_job(
            session_factory, runner, library, lab_name, skip_config_time=skip
        )

    spawn_job(http_request, job, lab_name, work)
    return job_out(job, lab_name)


# --- Test suites: declared assertions run against the live lab. Read/author with
# lab:read / lab:create; run on demand with lab:validate (the automatic config-time
# run rides lab:configure, inside configure). ---


@router.get("/{lab_name}/test-suites", dependencies=[Depends(require_lab(perms.LAB_READ))])
async def get_test_suites(lab_name: LabName, db: SessionDep) -> TestSuitesResponse:
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    return _test_suites_response(lab)


@router.put("/{lab_name}/test-suites", dependencies=[Depends(require_lab(perms.LAB_EDIT))])
async def put_test_suites(
    lab_name: LabName, request: UpdateTestSuitesRequest, db: SessionDep
) -> TestSuitesResponse:
    # Authoring a lab's tests is authoring the lab, so it takes lab:edit (like
    # editing the definition). Suites are stored on the record, not in the netlab
    # definition, and take effect on the next validation run.
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    # Delta 17: templates are syntax-checked always, and dry-rendered per target
    # node when the lab has facts (a definition). A suite authored before the
    # definition passes on syntax alone; a later run surfaces render problems as
    # per-check errors.
    problems = check_suite_templates(request.test_suites, _stored_node_facts(lab))
    if problems:
        raise ApiError(
            422,
            "template_invalid",
            "test-suite template(s) failed to render",
            {"problems": problems},
        )
    stored: dict[str, object] = {
        name: suite.model_dump(mode="json") for name, suite in request.test_suites.items()
    }
    updated = await lab_store.update_test_suites(db, lab_name, stored)
    if isinstance(updated, lab_store.LabStoreError):
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    return _test_suites_response(updated)


async def _suite_run_job(
    session_factory: SessionFactory,
    runner: RunnerClient,
    library: BuiltinLibrary,
    lab_name: str,
    suite: str,
) -> SuiteReport:
    """The on-demand suite run, inside a job task. The result is persisted
    (updating just this suite's last run) but the config-time gate is left
    untouched: a manual run isn't a configure."""
    async with session_factory() as db:
        lab = await lab_store.get_lab(db, lab_name)
        if lab is None:
            raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
        target = _load_suites(lab.test_suites).get(suite)
        if target is None:
            raise ApiError(404, "suite_not_found", f"lab '{lab_name}' has no suite '{suite}'")
        definition = lab.definition
        if definition is None:
            raise ApiError(409, "no_definition", f"lab '{lab_name}' has no stored definition yet")
        executor = _runner_executor(runner, definition, _config_fileset(library, lab))
        facts = await _node_facts_for(db, lab, library)
        report = await run_suite(executor, facts, suite, target)
        _ = await lab_store.record_validation(
            db,
            lab_name,
            {suite: report.model_dump(mode="json")},
            config_time_ok=None,
            set_config_time=False,
        )
        return report


@router.post(
    "/{lab_name}/test-suites/{suite}/run",
    status_code=202,
    dependencies=[Depends(require_lab(perms.LAB_VALIDATE))],
)
async def run_test_suite(
    lab_name: LabName,
    suite: SuiteName,
    http_request: Request,
    runner: RunnerClientDep,
    db: SessionDep,
    library: BuiltinLibraryDep,
    user: CurrentUserDep,
) -> JobOut:
    # Run one suite on demand — any stage; a config-time suite can be re-run
    # here too. 202 + the running job (a run's worst case is the sum of every
    # test's `wait`). Pre-checks are synchronous: unknown lab/suite 404.
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    if _load_suites(lab.test_suites).get(suite) is None:
        raise ApiError(404, "suite_not_found", f"lab '{lab_name}' has no suite '{suite}'")
    if lab.definition is None:  # the runner needs the inventory to exec anywhere
        raise ApiError(409, "no_definition", f"lab '{lab_name}' has no stored definition yet")

    lab_id = lab.id  # captured before submit: a losing submit expires the row
    job = await _submit_job(db, lab_id, lab_name, "suite_run", {"suite": suite}, user.id)
    if isinstance(job, ApiError):
        raise job

    session_factory: SessionFactory = http_request.app.state.session_factory

    async def work() -> SuiteReport:
        return await _suite_run_job(session_factory, runner, library, lab_name, suite)

    spawn_job(http_request, job, lab_name, work)
    return job_out(job, lab_name)


# --- Custom-config templates: the seam for config netlab doesn't model (MPLS-TE,
# IP SLA, QoS, …). Built-in templates are shipped read-only; user templates are
# per-lab. Read with lab:read, author with lab:create (like test-suite authoring).
# Both tiers ride the config push (built-ins always, user templates when stored). ---


@router.get("/{lab_name}/custom-config", dependencies=[Depends(require_lab(perms.LAB_READ))])
async def get_custom_config(
    lab_name: LabName, library: BuiltinLibraryDep, db: SessionDep
) -> CustomConfigResponse:
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    return _custom_config_response(library, lab)


@router.put("/{lab_name}/custom-config", dependencies=[Depends(require_lab(perms.LAB_EDIT))])
async def put_custom_config(
    lab_name: LabName,
    request: UpdateCustomConfigRequest,
    library: BuiltinLibraryDep,
    db: SessionDep,
) -> CustomConfigResponse:
    # Authoring a lab's templates is authoring the lab, so it takes lab:create
    # (like editing the definition or suites). A user template may not shadow a
    # built-in. Stored on the record; applied on the next configure/redeploy.
    fileset = dict(request.custom_config)
    collision = library.collision(fileset)
    if collision is not None:
        raise _builtin_collision(collision)
    updated = await lab_store.update_custom_config(db, lab_name, dict(fileset))
    if isinstance(updated, lab_store.LabStoreError):
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    return _custom_config_response(library, updated)


# --- Config-diff (contract delta 22): the import-fidelity proof. Stateless —
# the sources ride the request (a lab never remembers its import origin) and
# the interface map is recomputed by joining the sources' addresses against
# the RUNNING configs collected over the exec transport. Informational, never
# a gate. lab:validate: it execs on nodes, the suite-run class. ---


class DiffSourceIn(BaseModel):
    node: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=64)]
    content: Annotated[str, StringConstraints(min_length=1, max_length=512 * 1024)]
    # Delta 23: explicit source-if -> lab-if entries that override/extend the
    # address-join recompute. An L2-linked interface carries no address on
    # either side, so the join cannot see it — the client feeds back the map
    # the import returned, and the diff stays stateless.
    interface_map: dict[str, str] | None = None


class ConfigDiffRequest(BaseModel):
    sources: list[DiffSourceIn] = Field(min_length=1, max_length=64)


class NodeConfigDiffOut(BaseModel):
    node: str
    matched: int
    missing: list[str]
    extra: list[str]
    quarantined: int


class ConfigDiffReportOut(BaseModel):
    nodes: list[NodeConfigDiffOut]


@router.post("/{lab_name}/config-diff", dependencies=[Depends(require_lab(perms.LAB_VALIDATE))])
async def config_diff(
    lab_name: LabName,
    request: ConfigDiffRequest,
    runner: RunnerClientDep,
    library: BuiltinLibraryDep,
    db: SessionDep,
) -> ConfigDiffReportOut:
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    if lab.definition is None:
        raise ApiError(409, "no_definition", f"lab '{lab_name}' has no stored definition yet")
    if lab.status != "deployed":
        raise ApiError(409, "lab_not_running", f"lab '{lab_name}' is not deployed")

    facts = await _node_facts_for(db, lab, library)
    devices: dict[str, str] = {}
    for source in request.sources:
        node_facts = facts.get(source.node)
        device = node_facts.get("device") if node_facts is not None else None
        if not isinstance(device, str):
            raise ApiError(422, "unknown_node", f"lab '{lab_name}' has no node '{source.node}'")
        if device not in configimport_diff.DUMP_COMMANDS:
            raise ApiError(
                422,
                "unsupported_device",
                f"node '{source.node}' is a {device}, which is not import-capable",
            )
        devices[source.node] = device

    definition = lab.definition
    templates = _config_fileset(library, lab)
    # Sequential on purpose: the runner serializes inventory work per lab, and
    # the validation gate's parallelization is itself parked (ROADMAP item 10).
    results: list[NodeConfigDiffOut] = []
    for source in request.sources:
        device = devices[source.node]
        collected = await runner.exec_command(
            definition, source.node, configimport_diff.DUMP_COMMANDS[device], templates
        )
        if isinstance(collected, Err):
            raise ApiError(
                502,
                "exec_failed",
                f"could not collect node '{source.node}': {collected.error.message}",
            )
        diffed = configimport_diff.diff_node(
            source.node, device, source.content, collected.value, source.interface_map
        )
        if isinstance(diffed, Err):
            raise ApiError(422, "config_unparseable", f"node '{source.node}': {diffed.error}")
        results.append(
            NodeConfigDiffOut(
                node=diffed.value.node,
                matched=diffed.value.matched,
                missing=diffed.value.missing,
                extra=diffed.value.extra,
                quarantined=diffed.value.quarantined,
            )
        )
    return ConfigDiffReportOut(nodes=results)


# --- Topology layout (contract delta 19): ONE shared manual arrangement per
# lab, replacing the frontend's per-browser localStorage. The ids are opaque
# presentation data; validation is shape-only (the request model bounds key
# count/length and requires finite floats). PUT rides lab:edit — arranging the
# shared layout is authoring: only the Build tab edits topology or arrangement
# (maintainer's call 2026-08-03), other canvases are read/operate-only. ---


def _layout_response(lab: Lab) -> LabLayoutResponse:
    # Stored JSON was shape-validated on write, so a parse failure here is a
    # corrupt row (a real error), not a caller mistake — same rule as suites.
    raw = lab.layout or {}
    positions_raw = raw.get("positions")
    groups_raw = raw.get("groups")
    positions = cast("dict[str, object]", positions_raw) if isinstance(positions_raw, dict) else {}
    groups = cast("dict[str, object]", groups_raw) if isinstance(groups_raw, dict) else {}
    return LabLayoutResponse(
        positions={key: LayoutPosition.model_validate(pos) for key, pos in positions.items()},
        groups={key: LayoutGroupStyle.model_validate(style) for key, style in groups.items()},
    )


@router.get("/{lab_name}/layout", dependencies=[Depends(require_lab(perms.LAB_READ))])
async def get_layout(lab_name: LabName, db: SessionDep) -> LabLayoutResponse:
    # Deliberately NOT 409-gated on a definition (unlike links/facts): an empty
    # layout is honest, not a lie — the layout is an independent presentational
    # sub-resource.
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    return _layout_response(lab)


@router.put("/{lab_name}/layout", dependencies=[Depends(require_lab(perms.LAB_EDIT))])
async def put_layout(
    lab_name: LabName, request: PutLayoutRequest, db: SessionDep
) -> LabLayoutResponse:
    # Full REPLACE ({} clears): the writer always sends the complete current
    # arrangement, so replace semantics prune stale ids naturally.
    serialized: dict[str, object] = {
        "positions": {key: pos.model_dump() for key, pos in request.positions.items()},
        "groups": {key: style.model_dump() for key, style in request.groups.items()},
    }
    updated = await lab_store.set_layout(db, lab_name, serialized)
    if isinstance(updated, lab_store.LabStoreError):
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    return _layout_response(updated)


# The publish toggle (contract delta 21). Guard order matters: require_lab
# first, so a caller who can't even read the lab gets the existence-hiding 404
# before the global template:manage check can say 403.
@router.put(
    "/{lab_name}/template",
    dependencies=[
        Depends(require_lab(perms.LAB_READ)),
        Depends(require_global(perms.TEMPLATE_MANAGE)),
    ],
)
async def set_lab_template(
    lab_name: LabName,
    request: LabTemplateSet,
    db: SessionDep,
    library: NetworkTemplatesDep,
) -> NetworkTemplateSummary | None:
    """Publish this lab's stored definition into the network collection as a
    LIVE template, or withdraw it. lab:read suffices beside template:manage —
    publishing changes the LIBRARY, not the lab. Returns the resulting entry,
    None once withdrawn. Re-publishing just updates the description."""
    if request.published:
        lab = await lab_store.get_lab(db, lab_name)
        if lab is None:
            raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
        if lab.definition is None:
            raise ApiError(409, "no_definition", f"lab '{lab_name}' has no definition to publish")
        if lab_name in library.names:
            raise ApiError(409, "name_taken", f"'{lab_name}' is a builtin template name")
    updated = await lab_store.set_template_publication(
        db, lab_name, published=request.published, description=request.description
    )
    if isinstance(updated, lab_store.LabStoreError):
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    return published_lab_summary(updated) if request.published else None


async def _destroy_job(
    session_factory: SessionFactory,
    clab: ClabApiClient,
    hostprep: HostPrepClient | None,
    lab_name: str,
    *,
    lab_files_dir: str,
    remove: bool,
) -> DestroyResponse:
    """The destroy operation, inside a job task. The submit pre-check already
    required a running lab for a plain destroy; a teardown-404 here (torn down
    in the race window) still fails the job with `lab_not_running`. Claimed
    host bridges are released AFTER the record is updated: the teardown really
    happened either way, and on a cleanup failure the job fails loudly with the
    claim kept for a retry."""
    async with session_factory() as db:
        result = await clab.destroy(lab_name)
        if isinstance(result, Err):
            not_found = result.error.status_code == HTTPStatus.NOT_FOUND
            # A not-running lab is fatal for a plain destroy, but expected when
            # deleting one that's already down. Other upstream failures are 502.
            if not remove or not not_found:
                if not_found:
                    raise ApiError(409, "lab_not_running", f"lab '{lab_name}' is not running")
                raise ApiError(502, "upstream_error", result.error.message)
            teardown_detail = "lab was not running"
        else:
            teardown_detail = result.value

        if lab_files_dir:
            # The materialized node_files tree is a regenerable cache the next
            # deploy fully replaces — best-effort removal, no claim semantics
            # to protect (unlike host bridges).
            await run_in_threadpool(
                shutil.rmtree, FsPath(lab_files_dir) / lab_name, ignore_errors=True
            )

        if remove:
            deleted = await lab_store.soft_delete(db, lab_name)
            if isinstance(deleted, lab_store.LabStoreError):
                # Absent or already deleted — nothing to remove from the catalog.
                raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
            await _release_host_bridges(db, hostprep, lab_name)
            return DestroyResponse(status="deleted", detail=teardown_detail)

        # Retain the definition, flip status. not_found (deployed out-of-band) is fine.
        _ = await lab_store.mark_destroyed(db, lab_name)
        await _release_host_bridges(db, hostprep, lab_name)
        return DestroyResponse(status="destroyed", detail=teardown_detail)


@router.delete(
    "/{lab_name}", status_code=202, dependencies=[Depends(require_lab(perms.LAB_DESTROY))]
)
async def destroy_lab(
    lab_name: LabName,
    http_request: Request,
    clab: ClabClientDep,
    hostprep: HostPrepDep,
    db: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
    remove: bool = False,
) -> JobOut:
    """Tear down the running lab — 202 + the running destroy job. Default
    (`remove=false`) keeps the record, flipping it to `destroyed` (redeployable)
    — and so requires the lab to be up: a fast live-state pre-check makes that a
    synchronous 409 at submit (404 stays reserved for existence-hiding, contract
    delta 11). With `remove=true` it also soft-deletes the record (hidden from
    the catalog, row kept — the job itself stays pollable); teardown is then
    best-effort, so a lab that isn't running is fine."""
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")

    if not remove:
        # Pre-accept the "must be running" rule; the job tolerates the small
        # TOCTOU window (a teardown race fails the job with the same code).
        inspected = await clab.inspect(lab_name)
        if isinstance(inspected, Err):
            if inspected.error.status_code == HTTPStatus.NOT_FOUND:
                raise ApiError(409, "lab_not_running", f"lab '{lab_name}' is not running")
            raise ApiError(502, "upstream_error", inspected.error.message)

    lab_id = lab.id  # captured before submit: a losing submit expires the row
    job = await _submit_job(db, lab_id, lab_name, "destroy", {"remove": remove}, user.id)
    if isinstance(job, ApiError):
        raise job

    session_factory: SessionFactory = http_request.app.state.session_factory

    async def work() -> DestroyResponse:
        return await _destroy_job(
            session_factory,
            clab,
            hostprep,
            lab_name,
            lab_files_dir=settings.lab_files_dir,
            remove=remove,
        )

    spawn_job(http_request, job, lab_name, work)
    return job_out(job, lab_name)


# --- Runtime control & observability (operate on live clab-api state, not the
# stored definition). Power control and save mutate the running lab, so they take
# lab:configure; logs and interfaces are read-only (lab:read). ---


# Netem link impairment (POST set/reset mutate → lab:configure; GET show → lab:read).
# These are keyed by container + interface; the node's container is resolved live.
# Declared BEFORE the `{action}` node route so the static `netem` segment isn't
# captured by the NodeAction path param (which would 422 instead of matching here).
@router.get(
    "/{lab_name}/nodes/{node_name}/netem",
    dependencies=[Depends(require_lab(perms.LAB_READ))],
)
async def show_node_netem(
    lab_name: LabName, node_name: NodeName, clab: ClabClientDep
) -> list[NetemImpairment]:
    container = await _resolve_container(clab, lab_name, node_name)
    result = await clab.show_netem(container)
    if isinstance(result, Err):
        raise _clab_action_failed(result.error)
    return [_netem_model(i) for i in result.value]


@router.post(
    "/{lab_name}/nodes/{node_name}/netem",
    dependencies=[Depends(require_lab(perms.LAB_CONFIGURE))],
)
async def set_node_netem(
    lab_name: LabName, node_name: NodeName, request: NetemSetRequest, clab: ClabClientDep
) -> LabActionResponse:
    container = await _resolve_container(clab, lab_name, node_name)
    applied = await _netem_once(clab, container, request)
    if isinstance(applied, Err):
        raise applied.error
    return LabActionResponse(message=applied.value)


@router.post(
    "/{lab_name}/nodes/{node_name}/{action}",
    dependencies=[Depends(require_lab(perms.LAB_CONFIGURE))],
)
async def node_lifecycle(
    lab_name: LabName, node_name: NodeName, action: NodeAction, clab: ClabClientDep
) -> LabActionResponse:
    applied = await _power_once(clab, lab_name, node_name, action)
    if isinstance(applied, Err):
        raise applied.error
    return LabActionResponse(message=applied.value)


# One executor per verb, shared by the single route and the batch (contract
# delta 24): a standalone verb IS a batch of one. Errors come back as values —
# the single routes raise at the edge, the batch records them as data.
async def _netem_once(
    clab: ClabApiClient, container: str, request: NetemSetRequest
) -> Result[str, ApiError]:
    # REPLACE semantics (contract delta 7): clear the interface first, then
    # apply exactly what the body states — the result is the complete desired
    # impairment regardless of prior shaping, and a body with no impairments
    # is a plain clear (subsuming the removed /netem/reset endpoint).
    cleared = await clab.reset_netem(container, request.interface)
    if isinstance(cleared, Err):
        return Err(_clab_action_failed(cleared.error))
    impairments = (request.delay, request.jitter, request.loss, request.rate, request.corruption)
    if all(value is None for value in impairments):
        return Ok(cleared.value)
    result = await clab.set_netem(
        container,
        request.interface,
        delay=_duration_string(request.delay),
        jitter=_duration_string(request.jitter),
        loss=request.loss,
        rate=request.rate,
        corruption=request.corruption,
    )
    if isinstance(result, Err):
        return Err(_clab_action_failed(result.error))
    return Ok(result.value)


async def _power_once(
    clab: ClabApiClient, lab_name: str, node_name: str, action: NodeAction
) -> Result[str, ApiError]:
    result = await clab.node_action(lab_name, node_name, action)
    if isinstance(result, Err):
        return Err(_clab_action_failed(result.error))
    return Ok(result.value)


# A static segment beside the other static lab POSTs (deploy, configure, save,
# start/stop/restart) — no {action} path param exists at lab level to capture it.
@router.post("/{lab_name}/actions", dependencies=[Depends(require_lab(perms.LAB_CONFIGURE))])
async def apply_runtime_actions(
    lab_name: LabName, request: RuntimeActionsRequest, clab: ClabClientDep
) -> RuntimeActionsReport:
    """Apply many netem impairments and node power events in one request
    (contract delta 24). Items run SEQUENTIALLY in request order and execution
    CONTINUES past a failure: a 2xx means the batch ran, and each item's
    outcome is index-aligned in the report. Deliberately NOT a transaction —
    no rollback, no isolation against a concurrent single verb."""
    # ONE inspect resolves every netem item's container (netem is keyed by
    # container, the node routes by short name — the clab-api naming quirk), the
    # same trick the link table uses instead of N per-item resolves. Container
    # names survive stop/start, so a power item can't invalidate this map.
    containers: dict[str, str] = {}
    resolve_error: ApiError | None = None
    if any(item.kind == "netem" for item in request.actions):
        inspected = await clab.inspect(lab_name)
        if isinstance(inspected, Err):
            # Netem items cannot run without the map; power items take the short
            # name and are unaffected, so they still get their turn.
            resolve_error = _clab_action_failed(inspected.error)
        else:
            containers = {node.node_name: node.container_name for node in inspected.value}

    results: list[RuntimeActionResult] = []
    for item in request.actions:
        if item.kind == "power":
            applied = await _power_once(clab, lab_name, item.node, item.action)
        elif resolve_error is not None:
            applied = Err(resolve_error)
        elif (container := containers.get(item.node)) is None:
            applied = Err(
                ApiError(404, "node_not_found", f"node '{item.node}' not found in lab '{lab_name}'")
            )
        else:
            applied = await _netem_once(clab, container, item)
        if isinstance(applied, Err):
            results.append(
                RuntimeActionResult(
                    ok=False, code=applied.error.code, message=applied.error.message
                )
            )
        else:
            results.append(RuntimeActionResult(ok=True, message=applied.value))
    return RuntimeActionsReport(results=results)


# Lab-level power controls use explicit action segments (not a `{action}` path
# param) so they sit unambiguously beside the other static POST routes under
# `/{lab_name}/` — configure, redeploy, save — with no variable segment able to
# shadow them.
@router.post("/{lab_name}/start", dependencies=[Depends(require_lab(perms.LAB_CONFIGURE))])
async def start_lab(lab_name: LabName, clab: ClabClientDep) -> LabActionResponse:
    return await _lab_lifecycle(clab, lab_name, "start")


@router.post("/{lab_name}/stop", dependencies=[Depends(require_lab(perms.LAB_CONFIGURE))])
async def stop_lab(lab_name: LabName, clab: ClabClientDep) -> LabActionResponse:
    return await _lab_lifecycle(clab, lab_name, "stop")


@router.post("/{lab_name}/restart", dependencies=[Depends(require_lab(perms.LAB_CONFIGURE))])
async def restart_lab(lab_name: LabName, clab: ClabClientDep) -> LabActionResponse:
    return await _lab_lifecycle(clab, lab_name, "restart")


# clab-api has no whole-lab pause, so freeze/unfreeze fan out over the nodes.
@router.post("/{lab_name}/pause", dependencies=[Depends(require_lab(perms.LAB_CONFIGURE))])
async def pause_lab(lab_name: LabName, clab: ClabClientDep) -> LabActionResponse:
    return await _lab_freeze(clab, lab_name, "pause")


@router.post("/{lab_name}/unpause", dependencies=[Depends(require_lab(perms.LAB_CONFIGURE))])
async def unpause_lab(lab_name: LabName, clab: ClabClientDep) -> LabActionResponse:
    return await _lab_freeze(clab, lab_name, "unpause")


@router.post("/{lab_name}/save", dependencies=[Depends(require_lab(perms.LAB_CONFIGURE))])
async def save_lab_config(lab_name: LabName, clab: ClabClientDep) -> SaveConfigResponse:
    result = await clab.save_config(lab_name)
    if isinstance(result, Err):
        raise _clab_action_failed(result.error)
    return SaveConfigResponse(message=result.value.message, output=result.value.output)


@router.get(
    "/{lab_name}/nodes/{node_name}/logs", dependencies=[Depends(require_lab(perms.LAB_READ))]
)
async def node_logs(
    lab_name: LabName, node_name: NodeName, clab: ClabClientDep, tail: int = 200
) -> NodeLogsResponse:
    # 200 lines is a sane display default; large enough to be useful, small enough
    # not to ship a whole boot log by accident. Callers widen it via ?tail=.
    # clab-api's logs endpoint matches on the container name (not the short node
    # name the action endpoints accept), so resolve it from live state first.
    container = await _resolve_container(clab, lab_name, node_name)
    result = await clab.node_logs(lab_name, container, tail=str(tail))
    if isinstance(result, Err):
        raise _clab_action_failed(result.error)
    return _logs_response(result.value, node_name)


@router.get("/{lab_name}/interfaces", dependencies=[Depends(require_lab(perms.LAB_READ))])
async def lab_interfaces(
    lab_name: LabName, clab: ClabClientDep, node: str | None = None
) -> list[NodeInterfaces]:
    # The `node` filter takes the SHORT name, like the response keys (contract
    # delta 6); filtered here rather than upstream so we don't depend on
    # clab-api's filter matching semantics.
    result = await clab.interfaces(lab_name)
    if isinstance(result, Err):
        raise _clab_action_failed(result.error)
    inventory = _interfaces_response(result.value, lab_name)
    if node is None:
        return inventory
    return [entry for entry in inventory if entry.node == node]


@router.get("/{lab_name}/links", dependencies=[Depends(require_lab(perms.LAB_READ))])
async def lab_links(
    lab_name: LabName, clab: ClabClientDep, db: SessionDep, library: BuiltinLibraryDep
) -> LabLinksResponse:
    """The lab's logical link table with derived oper state (contract delta 14):
    served from the record's cached extract, lazily regenerated from the stored
    definition when the cache predates the column."""
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    if lab.definition is None:
        # An empty table would be indistinguishable from a definition with no
        # links; a bare created record has nothing to derive from.
        raise ApiError(
            409, "no_definition", f"lab '{lab_name}' has no definition to derive links from"
        )
    stored = _stored_links(lab)
    if stored is None:
        artifacts = await run_in_threadpool(
            create_clab_topology, lab.definition, _config_fileset(library, lab)
        )
        if isinstance(artifacts, Err):
            # Unexpected — the stored definition passed its PUT-time dry run.
            raise _netlab_failed(artifacts.error.message, artifacts.error.stderr)
        stored = artifacts.value.links
        _ = await lab_store.set_links(db, lab_name, serialize_links(stored))
    inventory, impairments = await _live_link_state(clab, lab, stored)
    return merge_links(stored, inventory, impairments)


@router.get("/{lab_name}/facts", dependencies=[Depends(require_lab(perms.LAB_READ))])
async def lab_facts(
    lab_name: LabName, db: SessionDep, library: BuiltinLibraryDep
) -> LabFactsResponse:
    """The per-node fact namespace suite templates render against (contract
    delta 17): served from the record's cached extract, lazily regenerated from
    the stored definition when the cache predates the column."""
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    if lab.definition is None:
        raise ApiError(
            409, "no_definition", f"lab '{lab_name}' has no definition to derive facts from"
        )
    return LabFactsResponse(nodes=await _node_facts_for(db, lab, library))


async def _lab_lifecycle(
    clab: ClabApiClient, lab_name: str, action: LifecycleAction
) -> LabActionResponse:
    result = await clab.lab_action(lab_name, action)
    if isinstance(result, Err):
        raise _clab_action_failed(result.error)
    return LabActionResponse(message=result.value)


async def _lab_freeze(
    clab: ClabApiClient, lab_name: str, action: FreezeAction
) -> LabActionResponse:
    """Pause/unpause every node in a lab. clab-api has no whole-lab pause, so we
    fan out over the nodes. This is non-atomic on purpose (the locked roadmap
    decision): we report which nodes failed rather than rolling the rest back."""
    inspected = await clab.inspect(lab_name)
    if isinstance(inspected, Err):
        raise _clab_action_failed(inspected.error)
    nodes = inspected.value
    if not nodes:
        raise ApiError(409, "lab_not_running", f"lab '{lab_name}' has no running nodes")
    failed = [
        node.node_name
        for node in nodes
        if isinstance(await clab.node_action(lab_name, node.node_name, action), Err)
    ]
    if failed:
        raise ApiError(
            502, "upstream_error", f"{action} failed on: {', '.join(failed)}", {"nodes": failed}
        )
    verb = "paused" if action == "pause" else "unpaused"
    return LabActionResponse(message=f"{verb} {len(nodes)} node(s)")


def _clab_action_failed(error: ClabApiError) -> ApiError:
    # An unknown lab/node surfaces as 404; anything else is an upstream failure.
    if error.status_code == HTTPStatus.NOT_FOUND:
        return ApiError(404, "clab_not_found", error.message)
    return ApiError(502, "upstream_error", error.message)


def _mgmt_subnet_failed(error: MgmtSubnetError) -> ApiError:
    # A misconfigured pool is a server config error (500); an exhausted pool is a
    # capacity limit the operator can raise (503) — neither is the caller's fault.
    if error.reason == "invalid_pool":
        return ApiError(500, "mgmt_pool_invalid", error.message)
    return ApiError(503, "mgmt_subnet_exhausted", error.message)


def _builtin_collision(relpath: str) -> ApiError:
    # A user template path uses a built-in's reserved namespace; a built-in is
    # non-deletable and cannot be shadowed. 409 so the caller renames its template.
    return ApiError(
        409, "builtin_template_shadowed", f"template path '{relpath}' shadows a built-in template"
    )


def _netlab_failed(message: str, stderr: str) -> ApiError:
    return ApiError(422, "netlab_invalid", message, {"stderr": stderr})


def _deploy_failed(message: str) -> ApiError:
    return ApiError(502, "upstream_error", message)


def _ready_failed(error: RunnerError) -> ApiError:
    # A bad definition is the caller's fault (422); otherwise the nodes didn't come
    # up in time — the lab is deployed but not usable yet (502, retry the deploy).
    if error.reason == "bad_definition":
        return ApiError(422, "netlab_invalid", error.message)
    return ApiError(502, "nodes_not_ready", error.message)


def _runner_failed(error: RunnerError) -> ApiError:
    # A bad definition is the caller's fault; anything else is an upstream failure.
    if error.reason == "bad_definition":
        return ApiError(422, "netlab_invalid", error.message)
    return ApiError(502, "config_push_failed", error.message)
