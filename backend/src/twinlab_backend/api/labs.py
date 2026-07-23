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

import secrets
from http import HTTPStatus
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from starlette.concurrency import run_in_threadpool

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import CurrentUserDep, require
from twinlab_backend.db.models import Lab
from twinlab_backend.deps import ClabClientDep, RunnerClientDep, SessionDep
from twinlab_backend.models import (
    ConfigureResponse,
    DeployRequest,
    DeployResponse,
    DestroyResponse,
    LabActionResponse,
    LabDetail,
    LabNodeState,
    LabSummary,
    NodeConfigResult,
    NodeInterface,
    NodeInterfaces,
    NodeLogsResponse,
    RedeployRequest,
    SaveConfigResponse,
    UpdateDefinitionRequest,
)
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services import lab_store
from twinlab_backend.services.clab_api import (
    ClabApiClient,
    ClabApiError,
    DeployedLab,
    NodeInfo,
)
from twinlab_backend.services.clab_api import NodeInterfaces as ClabNodeInterfaces
from twinlab_backend.services.clab_api import NodeLogs as ClabNodeLogs
from twinlab_backend.services.netlab import create_clab_topology, read_lab_name, set_lab_name
from twinlab_backend.services.runner_client import ConfigureReport, RunnerClient, RunnerError

router = APIRouter(prefix="/labs", tags=["labs"])

# Lab names come from netlab (e.g. tmpXXXX). Constrain the path segment to a
# tight charset with a leading alphanumeric so it can't become "." / ".." or
# otherwise reshape the URL sent to clab-api.
LabName = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
# Node names come from the definition (e.g. r1); same tight, path-safe charset.
NodeName = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
# Whole-lab power controls clab-api exposes natively (POST /labs/{lab}/{action}).
LifecycleAction = Literal["start", "stop", "restart"]
# Per-node controls. clab-api adds pause/unpause on top of the lab-level set;
# they share the /nodes/{node}/{action} path, so node_action handles them as-is.
NodeAction = Literal["start", "stop", "restart", "pause", "unpause"]
# Lab-level freeze verbs. clab-api has no whole-lab pause, so these fan out over
# the lab's nodes (see `_lab_freeze`); non-atomic by nature.
FreezeAction = Literal["pause", "unpause"]


def _generate_lab_name() -> str:
    # Stable identity for a lab whose definition names none. Charset is clab-safe
    # (leading alnum) and short; the token keeps concurrent labs distinct.
    return f"tl-{secrets.token_hex(4)}"


def _named_definition(definition: str, name: str) -> str:
    named = set_lab_name(definition, name)
    if isinstance(named, Err):
        raise HTTPException(
            status_code=422, detail={"stage": "netlab", "message": named.error.message}
        )
    return named.value


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
    )


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


async def _push_config(
    runner: RunnerClient, definition: str
) -> Result[ConfigureReport, HTTPException]:
    report = await runner.configure(definition)
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


async def _run_deploy(definition: str, clab: ClabApiClient, *, reconfigure: bool) -> DeployedLab:
    """Generate the containerlab topology from a netlab definition and deploy it.
    `reconfigure` overwrites a lab of the same name (redeploy). Raises the mapped
    HTTPException on a netlab or clab-api failure."""
    # netlab create is blocking subprocess work; keep it off the event loop.
    topology = await run_in_threadpool(create_clab_topology, definition)
    if isinstance(topology, Err):
        raise _netlab_failed(topology.error.message, topology.error.stderr)
    deployed = await clab.deploy(topology.value, reconfigure=reconfigure)
    if isinstance(deployed, Err):
        raise _deploy_failed(deployed.error.message)
    return deployed.value


async def _finish_deploy(
    deployed: DeployedLab, definition: str, runner: RunnerClient, *, configure: bool
) -> DeployResponse:
    """Shared tail of deploy and redeploy: optionally push config, then build the
    response. Raises on a config-push failure."""
    nodes = [n.node_name for n in deployed.nodes]
    if not configure:
        return DeployResponse(status="deployed", lab_name=deployed.name, nodes=nodes)
    pushed = await _push_config(runner, definition)
    if isinstance(pushed, Err):
        raise pushed.error
    report = pushed.value
    configuration = _to_models(report)
    if not report.succeeded:
        raise _config_failed(report.lab_name, configuration)
    return DeployResponse(
        status="configured", lab_name=deployed.name, nodes=nodes, configuration=configuration
    )


@router.post("", status_code=201, dependencies=[Depends(require(perms.LAB_CREATE))])
async def deploy_lab(
    request: DeployRequest,
    clab: ClabClientDep,
    runner: RunnerClientDep,
    db: SessionDep,
    user: CurrentUserDep,
) -> DeployResponse:
    name = read_lab_name(request.definition) or _generate_lab_name()

    existing = await lab_store.get_lab(db, name)
    if existing is not None and existing.status == lab_store.STATUS_DEPLOYED:
        raise HTTPException(
            status_code=409,
            detail={"stage": "labs", "message": f"lab '{name}' is already deployed"},
        )

    definition = _named_definition(request.definition, name)

    deployed = await _run_deploy(definition, clab, reconfigure=False)

    # Persist the definition now that the lab is up; configure reuses it.
    await lab_store.save_deployed(db, deployed.name, definition, user.id)

    return await _finish_deploy(deployed, definition, runner, configure=request.configure)


@router.put("/{lab_name}", dependencies=[Depends(require(perms.LAB_CREATE))])
async def update_lab_definition(
    lab_name: LabName, request: UpdateDefinitionRequest, clab: ClabClientDep, db: SessionDep
) -> LabDetail:
    # Editing a lab's definition is authoring the topology, so it takes lab:create.
    # The lab's name is fixed by the record and re-pinned here, so the edit can't
    # rename (and orphan) the lab. The running lab is untouched until a redeploy;
    # we validate the new definition by generating from it and reject a broken one.
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )

    definition = _named_definition(request.definition, lab_name)
    validated = await run_in_threadpool(create_clab_topology, definition)
    if isinstance(validated, Err):
        raise _netlab_failed(validated.error.message, validated.error.stderr)

    updated = await lab_store.update_definition(db, lab_name, definition)
    if isinstance(updated, lab_store.LabStoreError):
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )
    return await _live_detail(updated, clab)


@router.post("/{lab_name}/redeploy", dependencies=[Depends(require(perms.LAB_CREATE))])
async def redeploy_lab(
    lab_name: LabName,
    request: RedeployRequest,
    clab: ClabClientDep,
    runner: RunnerClientDep,
    db: SessionDep,
) -> DeployResponse:
    # Rebuild a lab from its stored definition (as-is, or after a PUT edit). The
    # caller never resupplies it. reconfigure=true overwrites the running lab if
    # present; on a destroyed lab it deploys fresh.
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )

    deployed = await _run_deploy(lab.definition, clab, reconfigure=True)
    # Preserve the original owner and definition; only flip status back to deployed.
    _ = await lab_store.mark_deployed(db, lab_name)
    return await _finish_deploy(deployed, lab.definition, runner, configure=request.configure)


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
    lab_name: LabName, runner: RunnerClientDep, db: SessionDep
) -> ConfigureResponse:
    # The definition is the lab's stored source of truth; the caller does not
    # resupply it. Config rendering is deterministic, so it reproduces the
    # intended per-node config.
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )

    pushed = await _push_config(runner, lab.definition)
    if isinstance(pushed, Err):
        raise pushed.error
    report = pushed.value
    configuration = _to_models(report)
    if not report.succeeded:
        raise _config_failed(lab_name, configuration)
    return ConfigureResponse(status="configured", lab_name=lab_name, configuration=configuration)


@router.delete("/{lab_name}", dependencies=[Depends(require(perms.LAB_DESTROY))])
async def destroy_lab(lab_name: LabName, clab: ClabClientDep, db: SessionDep) -> DestroyResponse:
    result = await clab.destroy(lab_name)
    if isinstance(result, Err):
        # Distinguish "no such lab" from an upstream failure.
        status = 404 if result.error.status_code == HTTPStatus.NOT_FOUND else 502
        raise HTTPException(
            status_code=status,
            detail={"stage": "clab-api", "message": result.error.message},
        )
    # Retain the definition, flip status. not_found (deployed out-of-band) is fine.
    await lab_store.mark_destroyed(db, lab_name)
    return DestroyResponse(status="destroyed", detail=result.value)


# --- Runtime control & observability (operate on live clab-api state, not the
# stored definition). Power control and save mutate the running lab, so they take
# lab:configure; logs and interfaces are read-only (lab:read). ---


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
    result = await clab.node_logs(lab_name, node_name, tail=str(tail))
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


def _netlab_failed(message: str, stderr: str) -> HTTPException:
    return HTTPException(
        status_code=422, detail={"stage": "netlab", "message": message, "stderr": stderr}
    )


def _deploy_failed(message: str) -> HTTPException:
    return HTTPException(status_code=502, detail={"stage": "clab-api", "message": message})


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
