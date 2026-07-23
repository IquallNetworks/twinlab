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

import uuid
from http import HTTPStatus
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import CurrentUserDep, require
from twinlab_backend.db.models import Lab
from twinlab_backend.deps import (
    BuiltinLibraryDep,
    ClabClientDep,
    RunnerClientDep,
    SessionDep,
    SettingsDep,
)
from twinlab_backend.models import (
    BuiltinTemplateOut,
    ConfigureRequest,
    ConfigureResponse,
    CustomConfigResponse,
    DeployRequest,
    DeployResponse,
    DestroyResponse,
    LabActionResponse,
    LabDetail,
    LabNodeState,
    LabSummary,
    NetemImpairment,
    NetemResetRequest,
    NetemSetRequest,
    NodeConfigResult,
    NodeInterface,
    NodeInterfaces,
    NodeLogsResponse,
    RedeployRequest,
    SaveConfigResponse,
    SuiteReport,
    TestSuite,
    TestSuitesResponse,
    UpdateCustomConfigRequest,
    UpdateDefinitionRequest,
    UpdateTestSuitesRequest,
)
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services import lab_store
from twinlab_backend.services.clab_api import (
    ClabApiClient,
    ClabApiError,
    DeployedLab,
    NodeInfo,
)
from twinlab_backend.services.clab_api import NetemImpairment as ClabNetemImpairment
from twinlab_backend.services.clab_api import NodeInterfaces as ClabNodeInterfaces
from twinlab_backend.services.clab_api import NodeLogs as ClabNodeLogs
from twinlab_backend.services.custom_config import BuiltinLibrary
from twinlab_backend.services.mgmt_subnet import MgmtSubnetError, allocate_subnet
from twinlab_backend.services.netlab import (
    create_clab_topology,
    read_mgmt_subnet,
    set_lab_name,
    set_mgmt_subnet,
    strip_generated_binds,
)
from twinlab_backend.services.runner_client import ConfigureReport, RunnerClient, RunnerError
from twinlab_backend.services.validation import NodeExecutor, run_config_time_suites, run_suite

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
NodeAction = Literal["start", "stop", "restart", "pause", "unpause"]
# Lab-level freeze verbs. clab-api has no whole-lab pause, so these fan out over
# the lab's nodes (see `_lab_freeze`); non-atomic by nature.
FreezeAction = Literal["pause", "unpause"]


def _named_definition(definition: str, name: str) -> str:
    named = set_lab_name(definition, name)
    if isinstance(named, Err):
        raise HTTPException(
            status_code=422, detail={"stage": "netlab", "message": named.error.message}
        )
    return named.value


# Bounded retries when an auto-allocated subnet is raced by a concurrent deploy;
# each retry excludes the winner (now committed), so a handful always converges.
_RESERVE_ATTEMPTS = 8


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


async def _reserve_deploy(
    db: AsyncSession,
    name: str,
    named_definition: str,
    existing_subnet: str | None,
    owner_id: uuid.UUID,
    pool: str,
) -> tuple[str, str]:
    """Resolve a mgmt subnet and reserve the lab row (`deploying`) BEFORE the slow
    deploy, so two concurrent deploys can't claim the same /24. Returns
    `(definition_with_mgmt, subnet)`. An auto-allocated subnet raced by another
    deploy is retried; a fixed subnet (explicit in the definition, or the record's
    own) can't be reallocated, so a clash 409s. A concurrent claim on the same
    name also 409s."""
    fixed = read_mgmt_subnet(named_definition) is not None or existing_subnet is not None
    for _ in range(_RESERVE_ATTEMPTS):
        definition, subnet = await _resolve_mgmt_subnet(
            named_definition, name, existing_subnet, db, pool
        )
        reserved = await lab_store.reserve_lab(db, name, definition, subnet, owner_id)
        if isinstance(reserved, Lab):
            return definition, subnet
        if reserved.reason == "name_taken":
            raise HTTPException(
                status_code=409,
                detail={"stage": "labs", "message": f"lab '{name}' is being deployed"},
            )
        if fixed:  # subnet_taken on a subnet we can't reallocate
            raise HTTPException(
                status_code=409,
                detail={"stage": "labs", "message": f"mgmt subnet {subnet} is already in use"},
            )
        # subnet_taken on an auto-allocated /24: retry — the winner is now excluded.
    raise HTTPException(
        status_code=503,
        detail={"stage": "mgmt-subnet", "message": "could not reserve a free mgmt subnet"},
    )


def _to_models(report: ConfigureReport) -> list[NodeConfigResult]:
    return [
        NodeConfigResult(node=n.node, status=n.status, changed=n.changed, failed=n.failed)
        for n in report.nodes
    ]


def _to_node_state(node: NodeInfo) -> LabNodeState:
    # clab reports the mgmt address as CIDR; expose the bare IP so the UI can
    # build an `ssh <ip>` command without every consumer stripping the mask.
    mgmt_ip = node.ipv4_address.split("/", 1)[0]
    return LabNodeState(
        name=node.node_name,
        container=node.container_name,
        image=node.image,
        state=node.state,
        mgmt_ip=mgmt_ip,
    )


def lab_summary(lab: Lab, live: dict[str, tuple[NodeInfo, ...]]) -> LabSummary:
    return LabSummary(
        name=lab.name,
        status=lab.status,
        owner=lab.owner.username if lab.owner is not None else None,
        created_at=lab.created_at,
        updated_at=lab.updated_at,
        nodes=len(live.get(lab.name, ())),
        config_time_ok=lab.config_time_ok,
    )


def lab_detail(lab: Lab, nodes: tuple[NodeInfo, ...]) -> LabDetail:
    return LabDetail(
        name=lab.name,
        status=lab.status,
        definition=lab.definition,
        owner=lab.owner.username if lab.owner is not None else None,
        created_at=lab.created_at,
        updated_at=lab.updated_at,
        nodes=[_to_node_state(n) for n in nodes],
        config_time_ok=lab.config_time_ok,
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
        config_time_ok=lab.config_time_ok,
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

    async def execute(node: str, command: str) -> Result[str, str]:
        result = await runner.exec_command(definition, node, command, templates)
        if isinstance(result, Err):
            return Err(result.error.message)
        return Ok(result.value)

    return execute


async def _run_config_time(
    runner: RunnerClient, db: AsyncSession, lab: Lab, library: BuiltinLibrary, *, skip: bool
) -> tuple[str, list[SuiteReport] | None]:
    """Run the lab's config-time suites after a successful config push. Returns
    `(status, reports)`: `configured` when they pass — or are skipped, or none
    exist — and `validation_failed` when any fails. On a real run it persists the
    per-suite results and the config-time gate (so a failed config is unambiguous
    on the record); a skip leaves the prior gate untouched and reports nothing."""
    suites = _load_suites(lab.test_suites)
    if skip or not any(s.stage == "config-time" for s in suites.values()):
        return "configured", None
    executor = _runner_executor(runner, lab.definition, _config_fileset(library, lab))
    reports = await run_config_time_suites(executor, suites)
    ok = all(r.ok for r in reports)
    stored: dict[str, object] = {r.suite: r.model_dump(mode="json") for r in reports}
    _ = await lab_store.record_validation(
        db, lab.name, stored, config_time_ok=ok, set_config_time=True
    )
    return ("configured" if ok else "validation_failed"), reports


def _logs_response(logs: ClabNodeLogs, node_name: str) -> NodeLogsResponse:
    return NodeLogsResponse(node=node_name, container=logs.container_name, logs=logs.logs)


def _interfaces_response(nodes: tuple[ClabNodeInterfaces, ...]) -> list[NodeInterfaces]:
    return [
        NodeInterfaces(
            node=n.node_name,
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


def _netem_model(impairment: ClabNetemImpairment) -> NetemImpairment:
    return NetemImpairment(
        interface=impairment.interface,
        delay=impairment.delay,
        jitter=impairment.jitter,
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
    raise HTTPException(
        status_code=404,
        detail={
            "stage": "clab-api",
            "message": f"node '{node_name}' not found in lab '{lab_name}'",
        },
    )


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
) -> Result[ConfigureReport, HTTPException]:
    report = await runner.configure(definition, templates)
    if isinstance(report, Err):
        return Err(_runner_failed(report.error))
    return Ok(report.value)


async def _live_detail(lab: Lab, clab: ClabApiClient) -> LabDetail:
    """Merge a stored lab record with its live node state from clab-api. A lab not
    currently deployed (inspect 404) simply has no live nodes; any other clab-api
    failure is surfaced as 502."""
    inspected = await clab.inspect(lab.name)
    if isinstance(inspected, Ok):
        nodes = inspected.value
    elif inspected.error.status_code == HTTPStatus.NOT_FOUND:
        nodes = ()
    else:
        raise HTTPException(
            status_code=502, detail={"stage": "clab-api", "message": inspected.error.message}
        )
    return lab_detail(lab, nodes)


async def _run_deploy(
    definition: str, clab: ClabApiClient, templates: dict[str, str], *, reconfigure: bool
) -> Result[DeployedLab, HTTPException]:
    """Generate the containerlab topology from a netlab definition and deploy it.
    `reconfigure` overwrites a lab of the same name (redeploy). `templates` is the
    custom-config fileset the definition may reference — `netlab create` validates
    those exist, so they must be present even though config push happens later.
    Returns the mapped HTTPException as an error value so the caller can release a
    reservation before re-raising, rather than unwinding through an exception."""
    # netlab create is blocking subprocess work; keep it off the event loop.
    topology = await run_in_threadpool(create_clab_topology, definition, templates)
    if isinstance(topology, Err):
        return Err(_netlab_failed(topology.error.message, topology.error.stderr))
    # We deploy inline (topologyContent) and ship no files, so drop binds netlab
    # points at its generated node_files/* (e.g. cisco_iol's ifstate) — the clab
    # kind regenerates them, and clab-api would otherwise reject the bind path.
    shippable = strip_generated_binds(topology.value)
    deployed = await clab.deploy(shippable, reconfigure=reconfigure)
    if isinstance(deployed, Err):
        return Err(_deploy_failed(deployed.error.message))
    return Ok(deployed.value)


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
) -> DeployResponse:
    """Shared tail of deploy and redeploy: optionally push config, then run the
    config-time suites and build the response. Raises on a config-push failure; a
    config-time validation failure is reported (status `validation_failed`), not
    raised — the lab stays deployed."""
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
        return DeployResponse(status="deployed", lab_name=deployed.name, nodes=nodes)
    pushed = await _push_config(runner, definition, templates)
    if isinstance(pushed, Err):
        raise pushed.error
    report = pushed.value
    configuration = _to_models(report)
    if not report.succeeded:
        raise _config_failed(report.lab_name, configuration)
    status, validation = await _run_config_time(runner, db, lab, library, skip=skip_config_time)
    return DeployResponse(
        status=status,
        lab_name=deployed.name,
        nodes=nodes,
        configuration=configuration,
        validation=validation,
    )


@router.post("", status_code=201, dependencies=[Depends(require(perms.LAB_CREATE))])
async def deploy_lab(
    request: DeployRequest,
    clab: ClabClientDep,
    runner: RunnerClientDep,
    db: SessionDep,
    user: CurrentUserDep,
    settings: SettingsDep,
    library: BuiltinLibraryDep,
) -> DeployResponse:
    name = request.name

    existing = await lab_store.get_lab(db, name)
    if existing is not None and existing.status in (
        lab_store.STATUS_DEPLOYED,
        lab_store.STATUS_DEPLOYING,
    ):
        raise HTTPException(
            status_code=409,
            detail={"stage": "labs", "message": f"lab '{name}' is already deployed"},
        )
    # Reject a user template that shadows a built-in before any side effects.
    if request.custom_config is not None:
        collision = library.collision(dict(request.custom_config))
        if collision is not None:
            raise _builtin_collision(collision)
    # Capture as plain values: the row may be re-fetched across reservation retries.
    created_new = existing is None
    existing_subnet = existing.mgmt_subnet if existing is not None else None

    named_definition = _named_definition(request.definition, name)
    # Reserve the subnet + row (status `deploying`) before the slow deploy, so
    # concurrent deploys can't collide on a /24. The definition (mgmt baked in) is
    # persisted here; configure reuses it.
    definition, _subnet = await _reserve_deploy(
        db, name, named_definition, existing_subnet, user.id, settings.mgmt_subnet_pool
    )

    # netlab create validates the definition's `config:` templates, so ship the
    # built-in library plus the incoming user templates (collision-checked above).
    deploy_templates = library.fileset | dict(request.custom_config or {})
    deployed = await _run_deploy(definition, clab, deploy_templates, reconfigure=False)
    if isinstance(deployed, Err):
        # Deploy failed after the reservation; free it (delete a fresh row, or
        # revert a re-armed destroyed lab) so its subnet and name don't leak.
        await lab_store.release_reservation(db, name, created_new=created_new)
        raise deployed.error
    _ = await lab_store.mark_deployed(db, name)
    # Persist any suites supplied with the deploy before the config-time run reads
    # them; a first deploy+configure can then gate on its own convergence checks.
    if request.test_suites is not None:
        _ = await lab_store.update_test_suites(
            db, name, {n: s.model_dump(mode="json") for n, s in request.test_suites.items()}
        )
    # Store user templates on the record so configure/redeploy reuse them (the
    # caller never resupplies them, like the definition and suites).
    if request.custom_config is not None:
        _ = await lab_store.update_custom_config(db, name, dict(request.custom_config))
    lab = await lab_store.get_lab(db, name)
    if lab is None:  # just deployed and stored; absence would be an internal fault
        raise HTTPException(
            status_code=500, detail={"stage": "labs", "message": f"lab '{name}' vanished"}
        )
    return await _finish_deploy(
        deployed.value,
        definition,
        runner,
        db,
        lab,
        library,
        configure=request.configure,
        skip_config_time=request.skip_config_time_checks,
    )


@router.put("/{lab_name}", dependencies=[Depends(require(perms.LAB_CREATE))])
async def update_lab_definition(
    lab_name: LabName,
    request: UpdateDefinitionRequest,
    clab: ClabClientDep,
    db: SessionDep,
    settings: SettingsDep,
    library: BuiltinLibraryDep,
) -> LabDetail:
    # Editing a lab's definition is authoring the topology, so it takes lab:create.
    # The lab's name is fixed by the record and re-pinned here, so the edit can't
    # rename (and orphan) the lab; its mgmt subnet is likewise re-pinned so an edit
    # keeps the same mgmt network (unless the edit names its own). The running lab
    # is untouched until a redeploy; we validate the new definition by generating
    # from it and reject a broken one.
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
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

    updated = await lab_store.update_definition(db, lab_name, definition, mgmt_subnet)
    if isinstance(updated, lab_store.LabStoreError):
        if updated.reason == "subnet_taken":
            raise HTTPException(
                status_code=409,
                detail={"stage": "labs", "message": f"mgmt subnet {mgmt_subnet} is already in use"},
            )
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )
    # `updated_at` has a server-side onupdate, so the UPDATE expires it; refresh it
    # in this async context before rendering, or reading it in lab_detail triggers a
    # sync lazy-load (MissingGreenlet) outside a greenlet.
    await db.refresh(updated, ["updated_at"])
    return await _live_detail(updated, clab)


@router.post("/{lab_name}/redeploy", dependencies=[Depends(require(perms.LAB_CREATE))])
async def redeploy_lab(
    lab_name: LabName,
    request: RedeployRequest,
    clab: ClabClientDep,
    runner: RunnerClientDep,
    db: SessionDep,
    library: BuiltinLibraryDep,
) -> DeployResponse:
    # Rebuild a lab from its stored definition (as-is, or after a PUT edit). The
    # caller never resupplies it. reconfigure=true overwrites the running lab if
    # present; on a destroyed lab it deploys fresh.
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )

    # Redeploy reuses the stored subnet (baked into the definition), so there's no
    # allocation and no reservation race to guard here.
    deployed = await _run_deploy(
        lab.definition, clab, _config_fileset(library, lab), reconfigure=True
    )
    if isinstance(deployed, Err):
        raise deployed.error
    # Preserve the original owner, definition, and subnet; only flip status.
    _ = await lab_store.mark_deployed(db, lab_name)
    return await _finish_deploy(
        deployed.value,
        lab.definition,
        runner,
        db,
        lab,
        library,
        configure=request.configure,
        skip_config_time=request.skip_config_time_checks,
    )


@router.get("", dependencies=[Depends(require(perms.LAB_READ))])
async def list_labs(clab: ClabClientDep, db: SessionDep) -> list[LabSummary]:
    labs = await lab_store.list_labs(db)
    # Live node state is best-effort enrichment; if clab-api is unreachable the
    # durable catalog still lists, with node counts of 0.
    live_result = await clab.list_labs()
    live = live_result.value if isinstance(live_result, Ok) else {}
    return [lab_summary(lab, live) for lab in labs]


@router.get("/{lab_name}", dependencies=[Depends(require(perms.LAB_READ))])
async def get_lab(lab_name: LabName, clab: ClabClientDep, db: SessionDep) -> LabDetail:
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )
    return await _live_detail(lab, clab)


@router.post("/{lab_name}/configure", dependencies=[Depends(require(perms.LAB_CONFIGURE))])
async def configure_nodes(
    lab_name: LabName,
    runner: RunnerClientDep,
    db: SessionDep,
    library: BuiltinLibraryDep,
    request: ConfigureRequest | None = None,
) -> ConfigureResponse:
    # The definition is the lab's stored source of truth; the caller does not
    # resupply it. Config rendering is deterministic, so it reproduces the
    # intended per-node config. After the push, the lab's config-time suites run
    # (unless skipped) to gate "config done". The body is optional (a bare
    # configure keeps the default: run the checks).
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )

    pushed = await _push_config(runner, lab.definition, _config_fileset(library, lab))
    if isinstance(pushed, Err):
        raise pushed.error
    report = pushed.value
    configuration = _to_models(report)
    if not report.succeeded:
        raise _config_failed(lab_name, configuration)
    skip = request.skip_config_time_checks if request is not None else False
    status, validation = await _run_config_time(runner, db, lab, library, skip=skip)
    return ConfigureResponse(
        status=status, lab_name=lab_name, configuration=configuration, validation=validation
    )


# --- Test suites: declared assertions run against the live lab. Read/author with
# lab:read / lab:create; run on demand with lab:validate (the automatic config-time
# run rides lab:configure, inside configure). ---


@router.get("/{lab_name}/test-suites", dependencies=[Depends(require(perms.LAB_READ))])
async def get_test_suites(lab_name: LabName, db: SessionDep) -> TestSuitesResponse:
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )
    return _test_suites_response(lab)


@router.put("/{lab_name}/test-suites", dependencies=[Depends(require(perms.LAB_CREATE))])
async def put_test_suites(
    lab_name: LabName, request: UpdateTestSuitesRequest, db: SessionDep
) -> TestSuitesResponse:
    # Authoring a lab's tests is authoring the lab, so it takes lab:create (like
    # editing the definition). Suites are stored on the record, not in the netlab
    # definition, and take effect on the next validation run.
    stored: dict[str, object] = {
        name: suite.model_dump(mode="json") for name, suite in request.test_suites.items()
    }
    updated = await lab_store.update_test_suites(db, lab_name, stored)
    if isinstance(updated, lab_store.LabStoreError):
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )
    return _test_suites_response(updated)


@router.post(
    "/{lab_name}/test-suites/{suite}/run",
    dependencies=[Depends(require(perms.LAB_VALIDATE))],
)
async def run_test_suite(
    lab_name: LabName,
    suite: SuiteName,
    runner: RunnerClientDep,
    db: SessionDep,
    library: BuiltinLibraryDep,
) -> SuiteReport:
    # Run one suite on demand — any stage; a config-time suite can be re-run here
    # too. The result is persisted (updating just this suite's last run) but the
    # config-time gate is left untouched: a manual run isn't a configure.
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )
    target = _load_suites(lab.test_suites).get(suite)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail={"stage": "labs", "message": f"lab '{lab_name}' has no suite '{suite}'"},
        )
    executor = _runner_executor(runner, lab.definition, _config_fileset(library, lab))
    report = await run_suite(executor, suite, target)
    _ = await lab_store.record_validation(
        db,
        lab_name,
        {suite: report.model_dump(mode="json")},
        config_time_ok=None,
        set_config_time=False,
    )
    return report


# --- Custom-config templates: the seam for config netlab doesn't model (MPLS-TE,
# IP SLA, QoS, …). Built-in templates are shipped read-only; user templates are
# per-lab. Read with lab:read, author with lab:create (like test-suite authoring).
# Both tiers ride the config push (built-ins always, user templates when stored). ---


@router.get("/{lab_name}/custom-config", dependencies=[Depends(require(perms.LAB_READ))])
async def get_custom_config(
    lab_name: LabName, library: BuiltinLibraryDep, db: SessionDep
) -> CustomConfigResponse:
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )
    return _custom_config_response(library, lab)


@router.put("/{lab_name}/custom-config", dependencies=[Depends(require(perms.LAB_CREATE))])
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
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )
    return _custom_config_response(library, updated)


@router.delete("/{lab_name}", dependencies=[Depends(require(perms.LAB_DESTROY))])
async def destroy_lab(
    lab_name: LabName, clab: ClabClientDep, db: SessionDep, remove: bool = False
) -> DestroyResponse:
    """Tear down the running lab. Default (`remove=false`) keeps the record,
    flipping it to `destroyed` (redeployable) — and so requires the lab to be up.
    With `remove=true` it also soft-deletes the record (hidden from the catalog,
    row kept); tearing down is then best-effort, so a lab that isn't running is
    fine (a `destroyed` lab can be deleted from the list)."""
    result = await clab.destroy(lab_name)
    if isinstance(result, Err):
        not_found = result.error.status_code == HTTPStatus.NOT_FOUND
        # A not-running lab is fatal for a plain destroy, but expected when
        # deleting one that's already down. Any other upstream failure is a 502.
        if not remove or not not_found:
            raise HTTPException(
                status_code=404 if not_found else 502,
                detail={"stage": "clab-api", "message": result.error.message},
            )
        teardown_detail = "lab was not running"
    else:
        teardown_detail = result.value

    if remove:
        deleted = await lab_store.soft_delete(db, lab_name)
        if isinstance(deleted, lab_store.LabStoreError):
            # Absent or already deleted — nothing to remove from the catalog.
            raise HTTPException(
                status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
            )
        return DestroyResponse(status="deleted", detail=teardown_detail)

    # Retain the definition, flip status. not_found (deployed out-of-band) is fine.
    await lab_store.mark_destroyed(db, lab_name)
    return DestroyResponse(status="destroyed", detail=teardown_detail)


# --- Runtime control & observability (operate on live clab-api state, not the
# stored definition). Power control and save mutate the running lab, so they take
# lab:configure; logs and interfaces are read-only (lab:read). ---


# Netem link impairment (POST set/reset mutate → lab:configure; GET show → lab:read).
# These are keyed by container + interface; the node's container is resolved live.
# Declared BEFORE the `{action}` node route so the static `netem` segment isn't
# captured by the NodeAction path param (which would 422 instead of matching here).
@router.get(
    "/{lab_name}/nodes/{node_name}/netem",
    dependencies=[Depends(require(perms.LAB_READ))],
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
    dependencies=[Depends(require(perms.LAB_CONFIGURE))],
)
async def set_node_netem(
    lab_name: LabName, node_name: NodeName, request: NetemSetRequest, clab: ClabClientDep
) -> LabActionResponse:
    container = await _resolve_container(clab, lab_name, node_name)
    result = await clab.set_netem(
        container,
        request.interface,
        delay=request.delay,
        jitter=request.jitter,
        loss=request.loss,
        rate=request.rate,
        corruption=request.corruption,
    )
    if isinstance(result, Err):
        raise _clab_action_failed(result.error)
    return LabActionResponse(message=result.value)


@router.post(
    "/{lab_name}/nodes/{node_name}/netem/reset",
    dependencies=[Depends(require(perms.LAB_CONFIGURE))],
)
async def reset_node_netem(
    lab_name: LabName, node_name: NodeName, request: NetemResetRequest, clab: ClabClientDep
) -> LabActionResponse:
    container = await _resolve_container(clab, lab_name, node_name)
    result = await clab.reset_netem(container, request.interface)
    if isinstance(result, Err):
        raise _clab_action_failed(result.error)
    return LabActionResponse(message=result.value)


@router.post(
    "/{lab_name}/nodes/{node_name}/{action}",
    dependencies=[Depends(require(perms.LAB_CONFIGURE))],
)
async def node_lifecycle(
    lab_name: LabName, node_name: NodeName, action: NodeAction, clab: ClabClientDep
) -> LabActionResponse:
    result = await clab.node_action(lab_name, node_name, action)
    if isinstance(result, Err):
        raise _clab_action_failed(result.error)
    return LabActionResponse(message=result.value)


# Lab-level power controls use explicit action segments (not a `{action}` path
# param) so they sit unambiguously beside the other static POST routes under
# `/{lab_name}/` — configure, redeploy, save — with no variable segment able to
# shadow them.
@router.post("/{lab_name}/start", dependencies=[Depends(require(perms.LAB_CONFIGURE))])
async def start_lab(lab_name: LabName, clab: ClabClientDep) -> LabActionResponse:
    return await _lab_lifecycle(clab, lab_name, "start")


@router.post("/{lab_name}/stop", dependencies=[Depends(require(perms.LAB_CONFIGURE))])
async def stop_lab(lab_name: LabName, clab: ClabClientDep) -> LabActionResponse:
    return await _lab_lifecycle(clab, lab_name, "stop")


@router.post("/{lab_name}/restart", dependencies=[Depends(require(perms.LAB_CONFIGURE))])
async def restart_lab(lab_name: LabName, clab: ClabClientDep) -> LabActionResponse:
    return await _lab_lifecycle(clab, lab_name, "restart")


# clab-api has no whole-lab pause, so freeze/unfreeze fan out over the nodes.
@router.post("/{lab_name}/pause", dependencies=[Depends(require(perms.LAB_CONFIGURE))])
async def pause_lab(lab_name: LabName, clab: ClabClientDep) -> LabActionResponse:
    return await _lab_freeze(clab, lab_name, "pause")


@router.post("/{lab_name}/unpause", dependencies=[Depends(require(perms.LAB_CONFIGURE))])
async def unpause_lab(lab_name: LabName, clab: ClabClientDep) -> LabActionResponse:
    return await _lab_freeze(clab, lab_name, "unpause")


@router.post("/{lab_name}/save", dependencies=[Depends(require(perms.LAB_CONFIGURE))])
async def save_lab_config(lab_name: LabName, clab: ClabClientDep) -> SaveConfigResponse:
    result = await clab.save_config(lab_name)
    if isinstance(result, Err):
        raise _clab_action_failed(result.error)
    return SaveConfigResponse(message=result.value.message, output=result.value.output)


@router.get("/{lab_name}/nodes/{node_name}/logs", dependencies=[Depends(require(perms.LAB_READ))])
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


@router.get("/{lab_name}/interfaces", dependencies=[Depends(require(perms.LAB_READ))])
async def lab_interfaces(
    lab_name: LabName, clab: ClabClientDep, node: str | None = None
) -> list[NodeInterfaces]:
    result = await clab.interfaces(lab_name, node=node)
    if isinstance(result, Err):
        raise _clab_action_failed(result.error)
    return _interfaces_response(result.value)


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
        raise HTTPException(
            status_code=409,
            detail={"stage": "clab-api", "message": f"lab '{lab_name}' has no running nodes"},
        )
    failed = [
        node.node_name
        for node in nodes
        if isinstance(await clab.node_action(lab_name, node.node_name, action), Err)
    ]
    if failed:
        raise HTTPException(
            status_code=502,
            detail={"stage": "clab-api", "message": f"{action} failed on: {', '.join(failed)}"},
        )
    verb = "paused" if action == "pause" else "unpaused"
    return LabActionResponse(message=f"{verb} {len(nodes)} node(s)")


def _clab_action_failed(error: ClabApiError) -> HTTPException:
    # An unknown lab/node surfaces as 404; anything else is an upstream failure.
    status = 404 if error.status_code == HTTPStatus.NOT_FOUND else 502
    return HTTPException(status_code=status, detail={"stage": "clab-api", "message": error.message})


def _mgmt_subnet_failed(error: MgmtSubnetError) -> HTTPException:
    # A misconfigured pool is a server config error (500); an exhausted pool is a
    # capacity limit the operator can raise (503) — neither is the caller's fault.
    status = 500 if error.reason == "invalid_pool" else 503
    return HTTPException(
        status_code=status, detail={"stage": "mgmt-subnet", "message": error.message}
    )


def _builtin_collision(relpath: str) -> HTTPException:
    # A user template path uses a built-in's reserved namespace; a built-in is
    # non-deletable and cannot be shadowed. 409 so the caller renames its template.
    return HTTPException(
        status_code=409,
        detail={
            "stage": "labs",
            "message": f"template path '{relpath}' shadows a built-in template",
        },
    )


def _netlab_failed(message: str, stderr: str) -> HTTPException:
    return HTTPException(
        status_code=422, detail={"stage": "netlab", "message": message, "stderr": stderr}
    )


def _deploy_failed(message: str) -> HTTPException:
    return HTTPException(status_code=502, detail={"stage": "clab-api", "message": message})


def _ready_failed(error: RunnerError) -> HTTPException:
    # A bad definition is the caller's fault (422); otherwise the nodes didn't come
    # up in time — the lab is deployed but not usable yet (502, retry the deploy).
    status = 422 if error.reason == "bad_definition" else 502
    return HTTPException(
        status_code=status,
        detail={"stage": "ready", "reason": error.reason, "message": error.message},
    )


def _runner_failed(error: RunnerError) -> HTTPException:
    # A bad definition is the caller's fault; anything else is an upstream failure.
    status = 422 if error.reason == "bad_definition" else 502
    return HTTPException(
        status_code=status,
        detail={"stage": "configure", "reason": error.reason, "message": error.message},
    )


def _config_failed(lab_name: str, results: list[NodeConfigResult]) -> HTTPException:
    # The push ran but at least one node failed; surface which, and that the lab is
    # deployed (so the caller can retry configure or destroy it).
    failed = [r.node for r in results if r.status == "failed"]
    return HTTPException(
        status_code=502,
        detail={
            "stage": "configure",
            "message": f"config push failed on: {', '.join(failed)}",
            "lab_name": lab_name,
            "nodes": [r.model_dump() for r in results],
        },
    )
