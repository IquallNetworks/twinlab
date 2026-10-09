"""Who a provider sign-in is (delta 33): link, then tie, then create.

Pure — the caller gathers the lookups, this decides. The durable identity is
(provider, `sub`); email is used ONCE, to find the account to link, and after
that the link decides. docs/oidc.md carries the reasoning for every rule here.
"""

import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Literal

# The refusals a sign-in can end in. Each is rendered by the login page from
# its own text — never from provider-supplied text.
RefusalCode = Literal[
    "account_disabled",
    "oidc_email_domain_not_allowed",
    "oidc_email_missing",
    "oidc_email_unverified",
    "oidc_email_in_use",
    "oidc_identity_conflict",
    "oidc_no_account",
]

_USERNAME_MAX = 64
_DISPLAY_NAME_MAX = 128


@dataclass(frozen=True, slots=True)
class Claims:
    """The identity claims a decision needs, parsed at the token boundary."""

    subject: str
    email: str | None
    # True = the claim is exactly JSON `true`; None = ABSENT; False = anything
    # else (explicit false, or a non-conformant "true" string, which is not
    # guessed at: guessing is how verification gets bypassed).
    email_verified: bool | None
    name: str | None
    preferred_username: str | None


@dataclass(frozen=True, slots=True)
class Policy:
    allow_create_users: bool
    allow_email_tying: bool
    trust_email: bool
    # The lowercase domains an email must be AT to tie or create (delta 35).
    # EMPTY = any domain, which is what a provider without the setting did.
    allowed_email_domains: frozenset[str]


@dataclass(frozen=True, slots=True)
class Account:
    id: uuid.UUID
    is_active: bool


@dataclass(frozen=True, slots=True)
class Lookups:
    # The user already linked to (provider, sub), if any.
    linked: Account | None
    # The user whose email equals the claim's, compared case-insensitively.
    email_holder: Account | None
    # Whether `email_holder` is already linked to a DIFFERENT subject on this
    # provider (a user has at most one identity per provider).
    email_holder_linked_here: bool


@dataclass(frozen=True, slots=True)
class SignIn:
    user_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class Tie:
    user_id: uuid.UUID
    email: str


@dataclass(frozen=True, slots=True)
class Create:
    email: str
    display_name: str


@dataclass(frozen=True, slots=True)
class Refuse:
    code: RefusalCode


type Decision = SignIn | Tie | Create | Refuse


def parse_email_verified(claims: Mapping[str, object]) -> bool | None:
    if "email_verified" not in claims:
        return None
    return claims["email_verified"] is True


def email_counts_as_verified(claims: Claims, policy: Policy) -> bool:
    """Exactly `true` verifies. On a `trust_email` provider an ABSENT claim
    counts too — but an explicit false is still believed: a provider that says
    an address is unverified is taken at its word even when otherwise trusted."""
    if claims.email_verified is None:
        return policy.trust_email
    return claims.email_verified


def email_domain_allowed(email: str, policy: Policy) -> bool:
    """The domain is everything after the LAST `@` (a quoted local part may
    hold one, a domain never does), matched exactly and case-insensitively:
    a subdomain is not its parent, so each one an admin wants is listed."""
    if not policy.allowed_email_domains:
        return True
    return email.rpartition("@")[2].lower() in policy.allowed_email_domains


def resolve(claims: Claims, policy: Policy, lookups: Lookups) -> Decision:
    if lookups.linked is not None:
        if not lookups.linked.is_active:
            return Refuse("account_disabled")
        return SignIn(lookups.linked.id)

    email = claims.email
    verified = email_counts_as_verified(claims, policy)

    if policy.allow_email_tying and email is not None and lookups.email_holder is not None:
        if not verified:
            return Refuse("oidc_email_unverified")
        if not email_domain_allowed(email, policy):
            return Refuse("oidc_email_domain_not_allowed")
        if lookups.email_holder_linked_here:
            return Refuse("oidc_identity_conflict")
        if not lookups.email_holder.is_active:
            return Refuse("account_disabled")
        return Tie(lookups.email_holder.id, email)

    if policy.allow_create_users:
        if email is None:
            return Refuse("oidc_email_missing")
        # An unverified address would claim a spot in the unique email column
        # that its real owner could then never use.
        if not verified:
            return Refuse("oidc_email_unverified")
        # Before the in-use check: an address this provider may never act on
        # is refused for that reason, not for who already holds it.
        if not email_domain_allowed(email, policy):
            return Refuse("oidc_email_domain_not_allowed")
        if lookups.email_holder is not None:
            return Refuse("oidc_email_in_use")
        return Create(email=email, display_name=display_name_for(claims, email))

    if lookups.email_holder is not None:
        return Refuse("oidc_email_in_use")
    return Refuse("oidc_no_account")


def display_name_for(claims: Claims, email: str) -> str:
    for candidate in (claims.name, claims.preferred_username, email):
        if candidate is not None and candidate.strip():
            return candidate.strip()[:_DISPLAY_NAME_MAX]
    return email[:_DISPLAY_NAME_MAX]


def username_candidates(claims: Claims, email: str) -> Iterator[str]:
    """`preferred_username`, else the email's local part, truncated to fit;
    then `-2`, `-3`, … — deterministic, so the same collision always yields
    the same name. Infinite: the caller stops at the first free one."""
    preferred = (claims.preferred_username or "").strip()
    base = preferred or email.partition("@")[0].strip() or "user"
    yield base[:_USERNAME_MAX]
    counter = 2
    while True:
        suffix = f"-{counter}"
        yield base[: _USERNAME_MAX - len(suffix)] + suffix
        counter += 1


def safe_next(value: str | None) -> str:
    """The post-sign-in path inside the app, or "/" when it is not a plain
    relative path. Refused: anything not starting with "/", a protocol-relative
    "//host" (or its "/\\host" spelling, which browsers normalize the same way),
    and control characters — the open redirect every post-login redirect
    otherwise opens."""
    if value is None or not value.startswith("/") or value.startswith(("//", "/\\")):
        return "/"
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return "/"
    return value
