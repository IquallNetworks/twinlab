"""Persistence for user-tier node templates (contract delta 21).

The node collection's user tier lives here as plain rows; the builtin tier (none
shipped yet) would live in code beside the network library. The API layer owns
all validation (fragment structure, the device requirement, bounds) — this
module only persists, returning typed results the HTTP layer maps to status
codes. Published-lab network templates are NOT here: they are a live view of
lab rows (`lab_store.list_published_labs`).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.db.models import NodeTemplate


@dataclass(frozen=True, slots=True)
class TemplateStoreError:
    reason: str  # "not_found" | "name_taken"
    detail: str = ""


async def list_node_templates(session: AsyncSession) -> list[NodeTemplate]:
    return list((await session.scalars(select(NodeTemplate).order_by(NodeTemplate.name))).all())


async def get_node_template(session: AsyncSession, name: str) -> NodeTemplate | None:
    return await session.scalar(select(NodeTemplate).where(NodeTemplate.name == name))


async def create_node_template(
    session: AsyncSession,
    *,
    name: str,
    description: str,
    device: str,
    content: str,
    created_by: uuid.UUID | None,
) -> NodeTemplate | TemplateStoreError:
    """`name_taken` when the name exists — the unique index decides, so a
    concurrent create can't slip a duplicate through."""
    template = NodeTemplate(
        name=name,
        description=description,
        device=device,
        content=content,
        created_by=created_by,
    )
    session.add(template)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return TemplateStoreError("name_taken", name)
    return template


async def update_node_template(
    session: AsyncSession,
    name: str,
    *,
    description: str,
    device: str,
    content: str,
) -> NodeTemplate | TemplateStoreError:
    """Full replace of description + content (house PUT semantics); the name is
    the identity and does not change."""
    template = await get_node_template(session, name)
    if template is None:
        return TemplateStoreError("not_found", name)
    template.description = description
    template.device = device
    template.content = content
    await session.commit()
    # The UPDATE expires server-side `updated_at` (onupdate); load it here so
    # rendering the row can't trip a sync lazy-load.
    await session.refresh(template)
    return template


async def delete_node_template(session: AsyncSession, name: str) -> TemplateStoreError | None:
    """None = deleted."""
    template = await get_node_template(session, name)
    if template is None:
        return TemplateStoreError("not_found", name)
    await session.delete(template)
    await session.commit()
    return None
