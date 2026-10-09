"""Provider records (delta 33): create, replace, delete, icons.

Gated by `user:manage` at the route. A provider decides who gets an account,
which is user management by another route, so it has no permission of its own.
"""

import enum
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth.oidc import icons, secret_box
from twinlab_backend.auth.oidc.metadata import OidcCache
from twinlab_backend.db.models import OidcProvider, UserIdentity
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services import rbac_store


class Unchanged(enum.Enum):
    """A write-only field left as stored on a replace — the field OMITTED on
    the wire. None cannot say it: for the client secret, None means remove."""

    UNCHANGED = "unchanged"


UNCHANGED = Unchanged.UNCHANGED


@dataclass(frozen=True, slots=True)
class ProviderError:
    # "provider_not_found" | "provider_name_taken" | "issuer_taken" |
    # "issuer_immutable" | "oidc_discovery_failed" | "group_not_found" |
    # "oidc_secret_key_unset" | "invalid_icon"
    reason: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """Everything a replace states. `issuer` rides it so a replace stays a
    complete statement of the record, and is checked against the stored one."""

    display_name: str
    issuer: str
    client_id: str
    scopes: list[str]
    allow_create_users: bool
    allow_email_tying: bool
    trust_email: bool
    allowed_email_domains: list[str]
    default_group_id: uuid.UUID | None
    enabled: bool


async def list_providers(db: AsyncSession) -> list[OidcProvider]:
    return list((await db.scalars(select(OidcProvider).order_by(OidcProvider.name))).all())


async def get_provider(db: AsyncSession, name: str) -> OidcProvider | None:
    return await db.scalar(select(OidcProvider).where(OidcProvider.name == name))


async def linked_counts(db: AsyncSession) -> dict[uuid.UUID, int]:
    rows = await db.execute(
        select(UserIdentity.provider_id, func.count()).group_by(UserIdentity.provider_id)
    )
    return {provider_id: count for provider_id, count in rows.tuples()}


def secret_readable(provider: OidcProvider, secret_key: str | None) -> bool:
    """False when a stored secret no longer decrypts (OIDC_SECRET_KEY changed or
    lost) — the admin read flags it so the fix, re-entering it, is visible."""
    if provider.client_secret_encrypted is None:
        return True
    if secret_key is None:
        return False
    return isinstance(secret_box.decrypt(secret_key, provider.client_secret_encrypted), Ok)


def _encrypt(secret: str, secret_key: str | None) -> Result[str, ProviderError]:
    if secret_key is None:
        return Err(
            ProviderError(
                "oidc_secret_key_unset",
                "this deployment has no OIDC_SECRET_KEY to encrypt a client secret with",
            )
        )
    return Ok(secret_box.encrypt(secret_key, secret))


async def _check_group(db: AsyncSession, group_id: uuid.UUID | None) -> ProviderError | None:
    if group_id is not None and await rbac_store.get_group(db, group_id) is None:
        return ProviderError("group_not_found", str(group_id))
    return None


def _apply(provider: OidcProvider, spec: ProviderSpec) -> None:
    provider.display_name = spec.display_name
    provider.client_id = spec.client_id
    provider.scopes = spec.scopes
    provider.allow_create_users = spec.allow_create_users
    provider.allow_email_tying = spec.allow_email_tying
    provider.trust_email = spec.trust_email
    provider.allowed_email_domains = spec.allowed_email_domains
    provider.default_group_id = spec.default_group_id
    provider.enabled = spec.enabled


async def create_provider(
    db: AsyncSession,
    cache: OidcCache,
    *,
    name: str,
    spec: ProviderSpec,
    client_secret: str | None,
    secret_key: str | None,
) -> Result[OidcProvider, ProviderError]:
    """Create a provider — after fetching its discovery document, so a mistyped
    issuer is refused in front of the admin who typed it rather than at the
    first user's sign-in."""
    if await get_provider(db, name) is not None:
        return Err(ProviderError("provider_name_taken", name))
    if await db.scalar(select(OidcProvider).where(OidcProvider.issuer == spec.issuer)):
        return Err(ProviderError("issuer_taken", spec.issuer))
    group_error = await _check_group(db, spec.default_group_id)
    if group_error is not None:
        return Err(group_error)
    encrypted: str | None = None
    if client_secret is not None:
        sealed = _encrypt(client_secret, secret_key)
        if isinstance(sealed, Err):
            return sealed
        encrypted = sealed.value
    discovered = await cache.metadata(spec.issuer)
    if isinstance(discovered, Err):
        return Err(ProviderError("oidc_discovery_failed", discovered.error))

    provider = OidcProvider(name=name, issuer=spec.issuer, client_secret_encrypted=encrypted)
    _apply(provider, spec)
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return Ok(provider)


async def update_provider(
    db: AsyncSession,
    *,
    name: str,
    spec: ProviderSpec,
    client_secret: str | None | Unchanged,
    secret_key: str | None,
) -> Result[OidcProvider, ProviderError]:
    """Replace a provider. Discovery is NOT re-fetched: the issuer cannot change,
    and an admin must be able to edit — above all DISABLE — a provider whose
    discovery endpoint is down."""
    provider = await get_provider(db, name)
    if provider is None:
        return Err(ProviderError("provider_not_found", name))
    if spec.issuer != provider.issuer:
        return Err(
            ProviderError(
                "issuer_immutable",
                "a provider's issuer cannot change; delete it and create a new one",
            )
        )
    group_error = await _check_group(db, spec.default_group_id)
    if group_error is not None:
        return Err(group_error)
    if not isinstance(client_secret, Unchanged):
        if client_secret is None:
            provider.client_secret_encrypted = None
        else:
            sealed = _encrypt(client_secret, secret_key)
            if isinstance(sealed, Err):
                return sealed
            provider.client_secret_encrypted = sealed.value
    _apply(provider, spec)
    await db.commit()
    await db.refresh(provider)
    return Ok(provider)


async def delete_provider(db: AsyncSession, name: str) -> Result[None, ProviderError]:
    """Deletes the provider's links (FK cascade) and keeps its users. Not
    blocked on stranded users: removing a compromised provider must work."""
    provider = await get_provider(db, name)
    if provider is None:
        return Err(ProviderError("provider_not_found", name))
    await db.delete(provider)
    await db.commit()
    return Ok(None)


async def set_icon(
    db: AsyncSession, name: str, content: bytes, content_type: str | None
) -> Result[OidcProvider, ProviderError]:
    provider = await get_provider(db, name)
    if provider is None:
        return Err(ProviderError("provider_not_found", name))
    checked = icons.check_icon(content, content_type)
    if isinstance(checked, Err):
        return Err(ProviderError("invalid_icon", checked.error))
    provider.icon = content
    provider.icon_type = checked.value
    await db.commit()
    await db.refresh(provider)
    return Ok(provider)


async def clear_icon(db: AsyncSession, name: str) -> Result[OidcProvider, ProviderError]:
    provider = await get_provider(db, name)
    if provider is None:
        return Err(ProviderError("provider_not_found", name))
    provider.icon = None
    provider.icon_type = None
    await db.commit()
    await db.refresh(provider)
    return Ok(provider)


def icon_uri(provider: OidcProvider) -> str | None:
    if provider.icon is None or provider.icon_type is None:
        return None
    return icons.data_uri(provider.icon, provider.icon_type)
