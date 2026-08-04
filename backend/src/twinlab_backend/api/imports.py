"""Config import (contract delta 22): the definition factory endpoints.

Pure factories — no lab is touched; the client composes create_lab ->
update_definition -> put_custom_config. `POST /import/network` rides the
global `lab:create` (it is the create-a-lab flow's factory and runs a
netlab subprocess); `POST /import/node` is any authenticated user (a pure
parse, the template-read class).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints

from twinlab_backend.api_errors import ApiError
from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import CurrentUserDep, require_global
from twinlab_backend.result import Err
from twinlab_backend.services.configimport.model import QuarantineClass
from twinlab_backend.services.configimport.pipeline import (
    ImportProblem,
    ImportSourceSpec,
    NetworkImportResult,
    NodeImportResult,
    import_network,
    import_node,
    suggest,
)

router = APIRouter(prefix="/import", tags=["import"])

# Shape-only bounds (contract): <= 64 sources, <= 512 KiB each.
_MAX_SOURCE_BYTES = 512 * 1024

_SourceContent = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_SOURCE_BYTES)]
_DeviceSlug = Annotated[str, StringConstraints(min_length=1, max_length=64)]
_NameOverride = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=64)
]


class ImportSourceIn(BaseModel):
    device: _DeviceSlug
    content: _SourceContent
    name: _NameOverride | None = None


# One wiring endpoint: "node:interface" (SOURCE names; split on the FIRST
# colon so channelized interface names keep theirs). The pattern only bounds
# the shape — resolution and the real rules live in the wiring model.
_WiringEndpoint = Annotated[
    str, StringConstraints(pattern=r"^[^:]+:.+$", min_length=3, max_length=160)
]


class ImportNetworkRequest(BaseModel):
    sources: list[ImportSourceIn] = Field(min_length=1, max_length=64)
    # REQUIRED (delta 23): adjacency is never inferred. An empty list is
    # legal and means "no links" — every addressed interface becomes a stub.
    wiring: list[list[_WiringEndpoint]] = Field(max_length=512)


class WiringSuggestionRequest(BaseModel):
    sources: list[ImportSourceIn] = Field(min_length=1, max_length=64)


class WiringSuggestionOut(BaseModel):
    wiring: list[list[str]]
    warnings: list[ImportWarningOut]


class ImportNodeRequest(BaseModel):
    device: _DeviceSlug
    content: _SourceContent


class ImportWarningOut(BaseModel):
    node: str | None
    message: str


class QuarantineEntryOut(BaseModel):
    reason: QuarantineClass
    content: str


class NetworkImportOut(BaseModel):
    definition: str
    custom_config: dict[str, str]
    interface_map: dict[str, dict[str, str]]
    name_map: dict[str, str]
    quarantine: dict[str, list[QuarantineEntryOut]]
    warnings: list[ImportWarningOut]


class NodeImportOut(BaseModel):
    fragment: str
    config: str
    interfaces: dict[str, str | None]
    quarantine: list[QuarantineEntryOut]
    warnings: list[ImportWarningOut]


def _problem(problem: ImportProblem) -> ApiError:
    extras: dict[str, object] = {}
    if problem.stderr:
        extras["stderr"] = problem.stderr
    if problem.entry is not None:
        extras["entry"] = problem.entry
    return ApiError(422, problem.code, problem.message, extras or None)


def _specs(sources: list[ImportSourceIn]) -> list[ImportSourceSpec]:
    return [
        ImportSourceSpec(device=source.device, content=source.content, name=source.name)
        for source in sources
    ]


def _network_out(result: NetworkImportResult) -> NetworkImportOut:
    return NetworkImportOut(
        definition=result.definition,
        custom_config=result.custom_config,
        interface_map=result.interface_map,
        name_map=result.name_map,
        quarantine={
            node: [QuarantineEntryOut(reason=q.reason, content=q.content) for q in entries]
            for node, entries in result.quarantine.items()
        },
        warnings=[ImportWarningOut(node=n.node, message=n.message) for n in result.warnings],
    )


def _node_out(result: NodeImportResult) -> NodeImportOut:
    return NodeImportOut(
        fragment=result.fragment,
        config=result.config,
        interfaces=result.interfaces,
        quarantine=[
            QuarantineEntryOut(reason=q.reason, content=q.content) for q in result.quarantine
        ],
        warnings=[ImportWarningOut(node=n.node, message=n.message) for n in result.warnings],
    )


@router.post("/network", dependencies=[Depends(require_global(perms.LAB_CREATE))])
async def import_network_route(request: ImportNetworkRequest) -> NetworkImportOut:
    # The pipeline runs a blocking netlab subprocess (the dry create the
    # interface map joins on) — off the event loop.
    outcome = await run_in_threadpool(
        import_network, _specs(request.sources), [list(entry) for entry in request.wiring]
    )
    if isinstance(outcome, Err):
        raise _problem(outcome.error)
    return _network_out(outcome.value)


@router.post("/wiring-suggestion", dependencies=[Depends(require_global(perms.LAB_CREATE))])
async def wiring_suggestion_route(request: WiringSuggestionRequest) -> WiringSuggestionOut:
    # Advice, never action (delta 23): the subnet join proposes wiring for a
    # client to prefill an editor with; import_network consumes only the
    # explicit list it is then given. Pure parse — no netlab run.
    outcome = suggest(_specs(request.sources))
    if isinstance(outcome, Err):
        raise _problem(outcome.error)
    return WiringSuggestionOut(
        wiring=outcome.value.wiring,
        warnings=[
            ImportWarningOut(node=note.node, message=note.message) for note in outcome.value.notes
        ],
    )


@router.post("/node")
async def import_node_route(request: ImportNodeRequest, _: CurrentUserDep) -> NodeImportOut:
    outcome = import_node(request.device, request.content)
    if isinstance(outcome, Err):
        raise _problem(outcome.error)
    return _node_out(outcome.value)
