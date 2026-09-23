"""The sign-in flow (delta 33): start at the provider, finish into a session.

Authorization code + PKCE, run by the backend. Both halves are BROWSER
NAVIGATIONS, so a failure cannot reach anyone as the JSON error envelope: it
becomes a code the login page renders from its own text, and the detail —
which the redirect deliberately does not carry — is logged here instead,
where an admin debugging a provider can read it (`docker compose logs`).
"""

import base64
import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlencode

import httpx2
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth import user_management
from twinlab_backend.auth.oidc import resolution, secret_box, tokens
from twinlab_backend.auth.oidc.metadata import OidcCache
from twinlab_backend.auth.oidc.resolution import (
    Account,
    Create,
    Lookups,
    Policy,
    RefusalCode,
    Refuse,
    SignIn,
    Tie,
)
from twinlab_backend.config import Settings
from twinlab_backend.db.models import Group, OidcLoginAttempt, OidcProvider, User, UserIdentity
from twinlab_backend.result import Err, Ok, Result

logger = logging.getLogger("twinlab.oidc")

# Everything a failed sign-in can end in. The flow's own codes plus the
# resolution's refusals; the login page renders each from its own text.
FailureCode = (
    Literal["oidc_unavailable", "oidc_state_invalid", "oidc_provider_error", "oidc_token_invalid"]
    | RefusalCode
)

STATE_COOKIE = "twinlab_oidc_state"
# Long enough to type a password and pass an MFA prompt at the provider; short
# enough that an abandoned attempt's row and cookie do not linger.
ATTEMPT_SECONDS = 600

_STATE_BYTES = 32
_NONCE_BYTES = 32
# 48 bytes -> a 64-character verifier, inside RFC 7636's 43..128 window.
_VERIFIER_BYTES = 48


@dataclass(frozen=True, slots=True)
class Failure:
    code: FailureCode


@dataclass(frozen=True, slots=True)
class Started:
    authorization_url: str
    state: str  # the raw state, for the browser-binding cookie


@dataclass(frozen=True, slots=True)
class Finished:
    user_id: uuid.UUID
    next_path: str


@dataclass(frozen=True, slots=True)
class CallbackParams:
    code: str | None
    state: str | None
    error: str | None
    iss: str | None  # RFC 9207, when the provider sends it


def _fail(code: FailureCode, provider: str, detail: str) -> Err[Failure]:
    logger.warning("oidc sign-in via %r failed (%s): %s", provider, code, detail)
    return Err(Failure(code))


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def enabled(settings: Settings) -> bool:
    """Sign-in through a provider needs an origin to build the callback from."""
    return bool(settings.public_origin)


def callback_url(settings: Settings, provider_name: str) -> str | None:
    """The exact redirect URI registered at the provider — what the browser
    reaches: origin + base path + the API route."""
    if not settings.public_origin:
        return None
    return (
        f"{settings.public_origin}{settings.frontend_base_path}"
        f"/api/v1/auth/oidc/{provider_name}/callback"
    )


def state_cookie_path(settings: Settings) -> str:
    # The BROWSER-visible path (the base path included — nginx strips it only
    # on the way to the backend), scoped to the OIDC routes alone.
    return f"{settings.frontend_base_path}/api/v1/auth/oidc"


def login_error_location(settings: Settings, code: FailureCode) -> str:
    # Relative (origin-less): it resolves against the Twinlab URL the browser
    # is already on, so it works even when PUBLIC_ORIGIN is unset.
    return f"{settings.frontend_base_path}/login?{urlencode({'oidc_error': code})}"


def post_login_location(settings: Settings, next_path: str) -> str:
    return f"{settings.frontend_base_path}{next_path}"


async def start(
    db: AsyncSession,
    cache: OidcCache,
    settings: Settings,
    provider_name: str,
    next_param: str | None,
) -> Result[Started, Failure]:
    redirect_uri = callback_url(settings, provider_name)
    if redirect_uri is None:
        return _fail("oidc_unavailable", provider_name, "PUBLIC_ORIGIN is not set")
    provider = await db.scalar(select(OidcProvider).where(OidcProvider.name == provider_name))
    if provider is None or not provider.enabled:
        return _fail("oidc_unavailable", provider_name, "no such enabled provider")
    metadata = await cache.metadata(provider.issuer)
    if isinstance(metadata, Err):
        return _fail("oidc_unavailable", provider_name, metadata.error)

    now = datetime.now(UTC)
    _ = await db.execute(delete(OidcLoginAttempt).where(OidcLoginAttempt.expires_at <= now))
    state = secrets.token_urlsafe(_STATE_BYTES)
    nonce = secrets.token_urlsafe(_NONCE_BYTES)
    verifier = secrets.token_urlsafe(_VERIFIER_BYTES)
    db.add(
        OidcLoginAttempt(
            state_hash=_hash(state),
            provider_id=provider.id,
            nonce=nonce,
            code_verifier=verifier,
            next_path=resolution.safe_next(next_param),
            expires_at=now + timedelta(seconds=ATTEMPT_SECONDS),
        )
    )
    await db.commit()

    query = urlencode(
        {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(provider.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": _s256(verifier),
            "code_challenge_method": "S256",
        }
    )
    endpoint = metadata.value.authorization_endpoint
    separator = "&" if "?" in endpoint else "?"
    return Ok(Started(authorization_url=f"{endpoint}{separator}{query}", state=state))


async def _consume_attempt(
    db: AsyncSession, state: str | None, cookie_state: str | None
) -> OidcLoginAttempt | None:
    """The pending attempt this callback finishes — consumed (deleted) whatever
    happens next, so a code/state pair works exactly once. The state must
    also equal the browser's cookie: without that binding, an attacker could
    finish THEIR sign-in in a victim's browser, and the victim would silently
    be working inside the attacker's account."""
    if state is None:
        return None
    attempt = await db.scalar(
        select(OidcLoginAttempt).where(OidcLoginAttempt.state_hash == _hash(state))
    )
    if attempt is None:
        return None
    await db.delete(attempt)
    await db.commit()
    if cookie_state is None or not secrets.compare_digest(cookie_state, state):
        return None
    if attempt.expires_at <= datetime.now(UTC):
        return None
    return attempt


async def _lookups(db: AsyncSession, provider: OidcProvider, claims: resolution.Claims) -> Lookups:
    linked_identity = await db.scalar(
        select(UserIdentity).where(
            UserIdentity.provider_id == provider.id, UserIdentity.subject == claims.subject
        )
    )
    linked_user = (
        await db.get(User, linked_identity.user_id) if linked_identity is not None else None
    )
    holder = (
        await user_management.find_by_email(db, claims.email) if claims.email is not None else None
    )
    holder_linked_here = (
        holder is not None
        and await db.scalar(
            select(UserIdentity).where(
                UserIdentity.provider_id == provider.id, UserIdentity.user_id == holder.id
            )
        )
        is not None
    )
    return Lookups(
        linked=Account(linked_user.id, linked_user.is_active) if linked_user else None,
        email_holder=Account(holder.id, holder.is_active) if holder else None,
        email_holder_linked_here=holder_linked_here,
    )


async def _free_username(db: AsyncSession, claims: resolution.Claims, email: str) -> str:
    for candidate in resolution.username_candidates(claims, email):
        if not await user_management.username_taken(db, candidate):
            return candidate
    # username_candidates is infinite; the loop only ends by returning.
    raise AssertionError("unreachable")


async def _create_account(
    db: AsyncSession, provider: OidcProvider, claims: resolution.Claims, decision: Create
) -> Result[uuid.UUID, str]:
    """User + link (+ default group) in ONE transaction, so a race that loses
    on any unique constraint leaves nothing half-made."""
    username = await _free_username(db, claims, decision.email)
    created = await user_management.create_user(
        db,
        username=username,
        email=decision.email,
        display_name=decision.display_name,
        # A random password nobody ever sees: there is no password-less state,
        # and an admin reset is how this user gains password sign-in.
        password=None,
        role_names=[perms.DEFAULT_USER_ROLE],
        commit=False,
    )
    if isinstance(created, Err):
        await db.rollback()
        return Err(f"{created.error.reason}: {created.error.detail}")
    user = created.value.user
    db.add(
        UserIdentity(
            user_id=user.id,
            provider_id=provider.id,
            subject=claims.subject,
            email_at_link=decision.email,
            last_login_at=datetime.now(UTC),
        )
    )
    if provider.default_group_id is not None:
        group = await db.get(Group, provider.default_group_id)
        if group is not None:
            group.members.append(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return Err("a concurrent sign-in claimed the same username, email or identity")
    return Ok(user.id)


async def _apply(
    db: AsyncSession,
    provider: OidcProvider,
    claims: resolution.Claims,
    decision: SignIn | Tie | Create,
) -> Result[uuid.UUID, str]:
    now = datetime.now(UTC)
    match decision:
        case SignIn(user_id=user_id):
            identity = await db.scalar(
                select(UserIdentity).where(
                    UserIdentity.provider_id == provider.id,
                    UserIdentity.subject == claims.subject,
                )
            )
            if identity is not None:
                identity.last_login_at = now
                await db.commit()
            return Ok(user_id)
        case Tie(user_id=user_id, email=email):
            db.add(
                UserIdentity(
                    user_id=user_id,
                    provider_id=provider.id,
                    subject=claims.subject,
                    email_at_link=email,
                    last_login_at=now,
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                return Err("a concurrent sign-in linked this account or subject first")
            return Ok(user_id)
        case Create():
            return await _create_account(db, provider, claims, decision)


async def finish(
    db: AsyncSession,
    cache: OidcCache,
    settings: Settings,
    *,
    provider_name: str,
    params: CallbackParams,
    cookie_state: str | None,
    transport: httpx2.AsyncBaseTransport,
) -> Result[Finished, Failure]:
    redirect_uri = callback_url(settings, provider_name)
    if redirect_uri is None:
        return _fail("oidc_unavailable", provider_name, "PUBLIC_ORIGIN is not set")
    attempt = await _consume_attempt(db, params.state, cookie_state)
    if params.error is not None:
        # The provider refused (the user cancelled, consent denied, …). Its
        # error string is logged, never shown: the page renders its own text.
        return _fail("oidc_provider_error", provider_name, f"provider error {params.error!r}")
    if attempt is None:
        return _fail("oidc_state_invalid", provider_name, "no live attempt matches this state")
    provider = await db.get(OidcProvider, attempt.provider_id)
    if provider is None or provider.name != provider_name or not provider.enabled:
        # Bound to its provider: one provider's code replayed against another
        # (the "mix-up" attack) ends here.
        return _fail("oidc_state_invalid", provider_name, "the attempt belongs to another provider")
    if params.iss is not None and params.iss != provider.issuer:
        return _fail("oidc_state_invalid", provider_name, f"iss {params.iss!r} is not ours")
    if params.code is None:
        return _fail("oidc_token_invalid", provider_name, "the callback carries no code")

    metadata = await cache.metadata(provider.issuer)
    if isinstance(metadata, Err):
        return _fail("oidc_unavailable", provider_name, metadata.error)
    client_secret: str | None = None
    if provider.client_secret_encrypted is not None:
        key = settings.oidc_secret_key
        opened = (
            secret_box.decrypt(key.get_secret_value(), provider.client_secret_encrypted)
            if key is not None
            else None
        )
        if not isinstance(opened, Ok):
            return _fail(
                "oidc_unavailable", provider_name, "the stored client secret does not decrypt"
            )
        client_secret = opened.value

    token_set = await tokens.exchange_code(
        metadata.value,
        client_id=provider.client_id,
        client_secret=client_secret,
        code=params.code,
        code_verifier=attempt.code_verifier,
        redirect_uri=redirect_uri,
        transport=transport,
    )
    if isinstance(token_set, Err):
        return _fail("oidc_token_invalid", provider_name, token_set.error)
    validated = await tokens.validate_id_token(
        cache,
        metadata.value,
        token_set.value.id_token,
        client_id=provider.client_id,
        nonce=attempt.nonce,
    )
    if isinstance(validated, Err):
        return _fail("oidc_token_invalid", provider_name, validated.error)
    merged = await tokens.merge_userinfo(
        cache.client, metadata.value, validated.value, token_set.value.access_token
    )
    if isinstance(merged, Err):
        return _fail("oidc_token_invalid", provider_name, merged.error)
    claims = tokens.identity_claims(merged.value)
    if isinstance(claims, Err):
        return _fail("oidc_token_invalid", provider_name, claims.error)

    policy = Policy(
        allow_create_users=provider.allow_create_users,
        allow_email_tying=provider.allow_email_tying,
        trust_email=provider.trust_email,
    )
    decision = resolution.resolve(claims.value, policy, await _lookups(db, provider, claims.value))
    if isinstance(decision, Refuse):
        return _fail(decision.code, provider_name, f"subject {claims.value.subject!r}")
    applied = await _apply(db, provider, claims.value, decision)
    if isinstance(applied, Err):
        return _fail("oidc_identity_conflict", provider_name, applied.error)
    return Ok(Finished(user_id=applied.value, next_path=attempt.next_path))
