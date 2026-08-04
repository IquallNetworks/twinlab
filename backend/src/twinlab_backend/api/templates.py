"""The template library (contract delta 21): reusable definition starting points.

Two sibling collections with independent namespaces — nothing ever consumes "a
template of either kind":

- `/templates/network` — complete netlab definitions. The builtin tier is the
  packaged library; the user tier is labs PUBLISHED via `PUT
  /labs/{name}/template` (see api.labs), each entry a LIVE view of its lab's
  stored definition.
- `/templates/node` — single-node attribute fragments the builder stamps into
  an open definition. User tier only today (`BUILTIN_NODE_TEMPLATE_NAMES` is
  the reserved namespace for a future shipped set).

Reads are any authenticated user — the library names no lab, and publishing
(gated by template:manage) deliberately makes a definition deployment-public.
Mutations ride the global-only `template:manage`.
"""

from typing import Annotated, cast

import yaml
from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.api_errors import ApiError
from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import CurrentUserDep, require_global
from twinlab_backend.db.models import Lab, NodeTemplate
from twinlab_backend.deps import NetworkTemplatesDep, SessionDep
from twinlab_backend.models import (
    NetworkTemplateOut,
    NetworkTemplateSummary,
    NodeTemplateCreate,
    NodeTemplateOut,
    NodeTemplateUpdate,
)
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services import lab_store, template_store

router = APIRouter(prefix="/templates", tags=["templates"])

# The builtin node collection ships empty (bare devices are the catalog's job;
# a preconfigured motif must earn its way in). Kept as the reserved namespace
# so shipping one later can't be shadowed by an existing user row.
BUILTIN_NODE_TEMPLATE_NAMES: frozenset[str] = frozenset()

# Same identifier charset as lab/node/suite names.
_TemplateName = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=64)]

# A fragment may not exceed what a whole definition reasonably would; this
# bounds the row without constraining any real single-node fragment.
_MAX_FRAGMENT_BYTES = 64 * 1024


def _not_found(name: str) -> ApiError:
    return ApiError(404, "template_not_found", f"unknown template '{name}'")


def published_lab_description(lab: Lab) -> str:
    """The publish toggle requires a description, so a published row without
    one is corrupt data — loud, never papered over with an empty card."""
    if lab.template_description is None:
        raise ApiError(
            500, "internal_error", f"published lab '{lab.name}' has no template description"
        )
    return lab.template_description


def published_lab_summary(lab: Lab) -> NetworkTemplateSummary:
    return NetworkTemplateSummary(
        name=lab.name,
        tier="user",
        description=published_lab_description(lab),
        source_lab=lab.name,
    )


def fragment_device(content: str) -> Result[str, str]:
    """Structural validation of a node fragment: parseable YAML mapping that
    names `device` (a node's device is intentful — a template must state it).
    Deliberately NOT a dry netlab run: a fragment may lean on lab-level
    constructs (vrfs, groups) no standalone topology could carry — the
    receiving lab's PUT stays the real validator. Returns the device."""
    if len(content.encode()) > _MAX_FRAGMENT_BYTES:
        return Err(f"fragment exceeds {_MAX_FRAGMENT_BYTES} bytes")
    try:
        parsed: object = yaml.safe_load(content)
    except yaml.YAMLError as error:
        return Err(f"fragment is not valid YAML: {error}")
    if not isinstance(parsed, dict):
        return Err("fragment must be a YAML mapping of node attributes")
    attributes = cast("dict[object, object]", parsed)
    device = attributes.get("device")
    if not isinstance(device, str) or not device:
        return Err("fragment must name its `device` (a node's device is intentful)")
    return Ok(device)


def _node_template_out(row: NodeTemplate) -> NodeTemplateOut:
    return NodeTemplateOut(
        name=row.name,
        tier="user",
        description=row.description,
        device=row.device,
        content=row.content,
    )


# ---------------------------------------------------------------------------
# Network collection
# ---------------------------------------------------------------------------


@router.get("/network")
async def list_network_templates(
    _: CurrentUserDep, library: NetworkTemplatesDep, db: SessionDep
) -> list[NetworkTemplateSummary]:
    builtin = [
        NetworkTemplateSummary(
            name=template.name,
            tier="builtin",
            description=template.description,
            source_lab=None,
        )
        for template in library.templates
    ]
    published = [published_lab_summary(lab) for lab in await lab_store.list_published_labs(db)]
    return builtin + published


async def _published_lab(db: AsyncSession, name: str) -> Lab | None:
    lab = await lab_store.get_lab(db, name)
    return lab if lab is not None and lab.template_published else None


@router.get("/network/{template_name}")
async def get_network_template(
    template_name: _TemplateName,
    _: CurrentUserDep,
    library: NetworkTemplatesDep,
    db: SessionDep,
) -> NetworkTemplateOut:
    builtin = library.get(template_name)
    if builtin is not None:
        return NetworkTemplateOut(
            name=builtin.name,
            tier="builtin",
            description=builtin.description,
            source_lab=None,
            content=builtin.content,
        )
    lab = await _published_lab(db, template_name)
    if lab is None:
        raise _not_found(template_name)
    # A live view of the lab's CURRENT stored definition. Publishing requires
    # one and authored definitions are never removed (only replaced, or the
    # whole record revived — which withdraws), so absence is corrupt data.
    if lab.definition is None:
        raise ApiError(
            500, "internal_error", f"published lab '{lab.name}' has no stored definition"
        )
    return NetworkTemplateOut(
        name=lab.name,
        tier="user",
        description=published_lab_description(lab),
        source_lab=lab.name,
        content=lab.definition,
    )


# ---------------------------------------------------------------------------
# Node collection
# ---------------------------------------------------------------------------


@router.get("/node")
async def list_node_templates(_: CurrentUserDep, db: SessionDep) -> list[NodeTemplateOut]:
    return [_node_template_out(row) for row in await template_store.list_node_templates(db)]


@router.get("/node/{template_name}")
async def get_node_template(
    template_name: _TemplateName, _: CurrentUserDep, db: SessionDep
) -> NodeTemplateOut:
    row = await template_store.get_node_template(db, template_name)
    if row is None:
        raise _not_found(template_name)
    return _node_template_out(row)


@router.post(
    "/node",
    status_code=201,
    dependencies=[Depends(require_global(perms.TEMPLATE_MANAGE))],
)
async def create_node_template(
    request: NodeTemplateCreate, user: CurrentUserDep, db: SessionDep
) -> NodeTemplateOut:
    device = fragment_device(request.content)
    if isinstance(device, Err):
        raise ApiError(422, "invalid_template", device.error)
    if request.name in BUILTIN_NODE_TEMPLATE_NAMES:
        raise ApiError(409, "name_taken", f"'{request.name}' is a builtin template name")
    created = await template_store.create_node_template(
        db,
        name=request.name,
        description=request.description,
        device=device.value,
        content=request.content,
        created_by=user.id,
    )
    if isinstance(created, template_store.TemplateStoreError):
        raise ApiError(409, "name_taken", f"template name '{request.name}' is taken")
    return _node_template_out(created)


@router.put(
    "/node/{template_name}",
    dependencies=[Depends(require_global(perms.TEMPLATE_MANAGE))],
)
async def update_node_template(
    template_name: _TemplateName, request: NodeTemplateUpdate, db: SessionDep
) -> NodeTemplateOut:
    if template_name in BUILTIN_NODE_TEMPLATE_NAMES:
        raise ApiError(409, "template_readonly", f"'{template_name}' is a builtin template")
    device = fragment_device(request.content)
    if isinstance(device, Err):
        raise ApiError(422, "invalid_template", device.error)
    updated = await template_store.update_node_template(
        db,
        template_name,
        description=request.description,
        device=device.value,
        content=request.content,
    )
    if isinstance(updated, template_store.TemplateStoreError):
        raise _not_found(template_name)
    return _node_template_out(updated)


@router.delete(
    "/node/{template_name}",
    status_code=204,
    dependencies=[Depends(require_global(perms.TEMPLATE_MANAGE))],
)
async def delete_node_template(template_name: _TemplateName, db: SessionDep) -> None:
    if template_name in BUILTIN_NODE_TEMPLATE_NAMES:
        raise ApiError(409, "template_readonly", f"'{template_name}' is a builtin template")
    deleted = await template_store.delete_node_template(db, template_name)
    if isinstance(deleted, template_store.TemplateStoreError):
        raise _not_found(template_name)
