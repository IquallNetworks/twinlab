"""Sign-in through OIDC providers and the user-profile rules (contract delta 33).

The profile and provider-validation slices need nothing but the stack. The
`oidc`-marked slices additionally need the TEST provider layered on:
`docker compose -f compose.yaml -f oidc-test/compose.yaml up -d`, with
TWINLAB_DEX_ISSUER naming its issuer (http://dex.localhost:5556/dex for the
dev stack). They drive the real browser flow through Dex (see _oidc.py).
"""

import base64
import contextlib
import os
from collections.abc import AsyncIterator, Callable

import httpx2
import pytest
from twinlab_client import OidcProvider, TwinlabApiError, TwinlabClient, UserSummary

from _config import (
    DEFAULT_PASSWORD,
    GroupFactory,
    SuiteConfig,
    UserClientFactory,
    create_bb_user,
)
from _oidc import DEX_CLIENT_ID, DEX_CLIENT_SECRET, PROVIDER, sign_in

# --------------------------------------------------------------------------- #
# Users: email, display name, generated passwords
# --------------------------------------------------------------------------- #


async def test_users_carry_an_email_and_a_display_name(
    admin: TwinlabClient, unique: Callable[[str], str]
) -> None:
    name = unique("user")
    user = await create_bb_user(admin, name)
    try:
        assert user.email == f"{name}@bb.test"
        assert user.display_name == f"Blackbox {name}"
        assert user.identities == []
    finally:
        await admin.delete_user(user.id)


async def test_emails_are_unique_case_insensitively(
    admin: TwinlabClient, unique: Callable[[str], str]
) -> None:
    first = await create_bb_user(admin, unique("user"))
    try:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await admin.create_user(unique("user"), first.email.upper(), "Twin")
        assert excinfo.value.status_code == 409
        assert excinfo.value.code == "email_taken"
    finally:
        await admin.delete_user(first.id)


async def test_a_malformed_email_is_422(admin: TwinlabClient, unique: Callable[[str], str]) -> None:
    for bad in ("no-at-sign", "two@@example.com", "spa ce@example.com"):
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await admin.create_user(unique("user"), bad, "Bad", password=DEFAULT_PASSWORD)
        assert excinfo.value.status_code == 422, bad


async def test_an_omitted_password_is_generated_and_returned_once(
    admin: TwinlabClient, config: SuiteConfig, unique: Callable[[str], str]
) -> None:
    name = unique("user")
    created = await admin.create_user(name, f"{name}@bb.test", "Generated")
    try:
        assert created.generated_password is not None
        async with TwinlabClient(config.base_url) as fresh:
            info = await fresh.login(name, created.generated_password)
            assert info.email == f"{name}@bb.test"
        # A chosen password is never echoed back.
        other = unique("user")
        chosen = await admin.create_user(
            other, f"{other}@bb.test", "Chosen", password=DEFAULT_PASSWORD
        )
        assert chosen.generated_password is None
        await admin.delete_user(chosen.user.id)
    finally:
        await admin.delete_user(created.user.id)


async def test_admins_edit_any_profile_including_their_own(
    admin: TwinlabClient, unique: Callable[[str], str]
) -> None:
    user = await create_bb_user(admin, unique("user"))
    try:
        updated = await admin.update_user_profile(
            user.id, email=f"renamed-{user.email}", display_name="Renamed"
        )
        assert (updated.email, updated.display_name) == (f"renamed-{user.email}", "Renamed")
    finally:
        await admin.delete_user(user.id)

    me = await admin.me()
    own = next(entry for entry in await admin.list_users() if entry.username == me.username)
    restored = await admin.update_user_profile(
        own.id, email=own.email, display_name=own.display_name
    )
    assert restored.email == own.email


async def test_users_edit_only_their_own_display_name(
    make_user_client: UserClientFactory,
) -> None:
    summary, client = await make_user_client(None)
    info = await client.update_own_profile("A New Name")
    assert info.display_name == "A New Name"
    assert info.email == summary.email
    # Email is admin-only: a user who could set their own address to a
    # colleague's would receive that colleague's first provider sign-in.
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await client.update_user_profile(
            summary.id, email="elsewhere@bb.test", display_name="x"
        )
    assert excinfo.value.status_code == 403


# --------------------------------------------------------------------------- #
# Providers without a live provider
# --------------------------------------------------------------------------- #


async def test_provider_admin_needs_user_manage(make_user_client: UserClientFactory) -> None:
    _, client = await make_user_client(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await client.list_oidc_providers()
    assert excinfo.value.status_code == 403


async def test_an_unreachable_issuer_is_refused_at_create(
    admin: TwinlabClient, unique: Callable[[str], str]
) -> None:
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.create_oidc_provider(
            unique("idp"), "Nowhere", "https://idp.invalid", "twinlab", client_secret=None
        )
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "oidc_discovery_failed"


async def test_provider_input_is_validated_before_any_fetch(admin: TwinlabClient) -> None:
    cases: list[tuple[str, list[str] | None, list[str] | None]] = [
        ("Not-A-Slug", None, None),
        ("bb-noopenid", ["email"], None),
        ("bb-atdomain", None, ["@iquall.net"]),  # a domain is listed bare (delta 35)
    ]
    for name, scopes, domains in cases:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await admin.create_oidc_provider(
                name,
                "X",
                "https://idp.invalid",
                "c",
                client_secret=None,
                scopes=scopes,
                allowed_email_domains=domains,
            )
        assert excinfo.value.status_code == 422, name


async def test_the_login_page_list_is_public(anon: TwinlabClient) -> None:
    # Answers without a session; its content depends on the stack's providers.
    _ = await anon.login_providers()


# --------------------------------------------------------------------------- #
# The flow, against Dex
# --------------------------------------------------------------------------- #

# Dex's static users (oidc-test/compose.yaml).
ALICE = "alice@example.com"
BOB = "bob@example.com"
CAROL = "carol@example.com"
_DEX_EMAILS = {ALICE, BOB, CAROL}


async def _forget_dex_people(admin: TwinlabClient) -> None:
    """Accounts left by an earlier run would change what a sign-in resolves to."""
    for entry in await admin.list_users():
        if entry.email.lower() in _DEX_EMAILS:
            with contextlib.suppress(TwinlabApiError):
                await admin.delete_user(entry.id)


@pytest.fixture
def dex_issuer() -> str:
    value = os.environ.get("TWINLAB_DEX_ISSUER")
    if not value:
        pytest.exit(
            "oidc-marked tests need TWINLAB_DEX_ISSUER (see blackbox/README.md); "
            'deselect them with -m "not oidc"',
            4,
        )
    return value


@pytest.fixture
async def dex(admin: TwinlabClient, dex_issuer: str) -> AsyncIterator[OidcProvider]:
    """The test provider registered as `dex`, linked-only to start with; every
    trace of it (and of Dex's people) removed afterwards."""
    with contextlib.suppress(TwinlabApiError):
        await admin.delete_oidc_provider(PROVIDER)
    await _forget_dex_people(admin)
    provider = await admin.create_oidc_provider(
        PROVIDER, "Dex", dex_issuer, DEX_CLIENT_ID, client_secret=DEX_CLIENT_SECRET
    )
    yield provider
    with contextlib.suppress(TwinlabApiError):
        await admin.delete_oidc_provider(PROVIDER)
    await _forget_dex_people(admin)


async def _switch(
    admin: TwinlabClient,
    provider: OidcProvider,
    *,
    create: bool = False,
    tie: bool = False,
    enabled: bool = True,
    default_group: str | None = None,
    domains: list[str] | None = None,
) -> OidcProvider:
    group_id = None
    if default_group is not None:
        group_id = next(g.id for g in await admin.list_groups() if g.name == default_group)
    return await admin.update_oidc_provider(
        provider.name,
        display_name=provider.display_name,
        issuer=provider.issuer,
        client_id=provider.client_id,
        scopes=provider.scopes,
        allow_create_users=create,
        allow_email_tying=tie,
        trust_email=False,
        allowed_email_domains=domains or [],
        default_group_id=group_id,
        enabled=enabled,
    )


async def _user_with_email(admin: TwinlabClient, email: str) -> UserSummary:
    return next(u for u in await admin.list_users() if u.email.lower() == email.lower())


@pytest.mark.oidc
async def test_the_provider_reads_back_without_its_secret(
    admin: TwinlabClient, dex: OidcProvider, config: SuiteConfig
) -> None:
    assert dex.has_client_secret is True
    assert dex.client_secret_readable is True
    assert dex.callback_url is not None
    assert dex.callback_url.endswith(f"/api/v1/auth/oidc/{PROVIDER}/callback")
    assert dex.allow_create_users is False and dex.allow_email_tying is False
    assert dex.scopes == ["openid", "email", "profile"]
    assert dex.allowed_email_domains == []  # any domain, unless restricted
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.create_oidc_provider(
            "bb-dex-again", "Again", dex.issuer, "x", client_secret=None
        )
    assert excinfo.value.code == "issuer_taken"


@pytest.mark.oidc
async def test_the_issuer_cannot_change(admin: TwinlabClient, dex: OidcProvider) -> None:
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.update_oidc_provider(
            dex.name,
            display_name=dex.display_name,
            issuer=f"{dex.issuer}/other",
            client_id=dex.client_id,
            scopes=dex.scopes,
            allow_create_users=False,
            allow_email_tying=False,
            trust_email=False,
            allowed_email_domains=[],
            default_group_id=None,
            enabled=True,
        )
    assert excinfo.value.code == "issuer_immutable"


@pytest.mark.oidc
async def test_a_linked_only_provider_refuses_strangers(
    dex: OidcProvider, config: SuiteConfig
) -> None:
    outcome = await sign_in(config.base_url, ALICE)
    await outcome.browser.aclose()
    assert outcome.error == "oidc_no_account"


@pytest.mark.oidc
async def test_creation_makes_an_account_and_a_session(
    admin: TwinlabClient,
    dex: OidcProvider,
    config: SuiteConfig,
    make_group: GroupFactory,
) -> None:
    group = await make_group()
    _ = await _switch(admin, dex, create=True, default_group=group.name)
    outcome = await sign_in(config.base_url, ALICE, next_path="/labs/somewhere")
    try:
        assert outcome.signed_in, outcome.location
        assert outcome.location == "/labs/somewhere"
        me = await outcome.browser.get(f"{config.base_url}/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == ALICE
    finally:
        await outcome.browser.aclose()

    alice = await _user_with_email(admin, ALICE)
    assert [identity.provider for identity in alice.identities] == [PROVIDER]
    assert alice.roles == {"user"}
    members = {m.id for m in (await admin.get_group(group.id)).members}
    assert alice.id in members  # the default group, joined at creation

    # Signing in again follows the link, even with creation switched off.
    _ = await _switch(admin, dex)
    again = await sign_in(config.base_url, ALICE)
    await again.browser.aclose()
    assert again.signed_in, again.location


@pytest.mark.oidc
async def test_tying_needs_the_switch(
    admin: TwinlabClient, dex: OidcProvider, config: SuiteConfig, unique: Callable[[str], str]
) -> None:
    # An existing account whose email differs from Dex's only in case.
    bob = await admin.create_user(unique("bob"), BOB.upper(), "Bob Local")
    _ = await _switch(admin, dex, create=True)
    refused = await sign_in(config.base_url, BOB)
    await refused.browser.aclose()
    assert refused.error == "oidc_email_in_use"

    _ = await _switch(admin, dex, tie=True)
    tied = await sign_in(config.base_url, BOB)
    await tied.browser.aclose()
    assert tied.signed_in, tied.location
    linked = await admin.get_user(bob.user.id)
    assert [identity.provider for identity in linked.identities] == [PROVIDER]
    assert linked.display_name == "Bob Local"  # a tie never rewrites the profile


@pytest.mark.oidc
async def test_unlinking_sends_the_next_sign_in_back_through_the_rules(
    admin: TwinlabClient, dex: OidcProvider, config: SuiteConfig, unique: Callable[[str], str]
) -> None:
    carol = await admin.create_user(unique("carol"), CAROL, "Carol Local")
    _ = await _switch(admin, dex, tie=True)
    first = await sign_in(config.base_url, CAROL)
    await first.browser.aclose()
    assert first.signed_in, first.location

    identity = (await admin.get_user(carol.user.id)).identities[0]
    await admin.unlink_identity(carol.user.id, identity.id)
    _ = await _switch(admin, dex)  # linked-only
    again = await sign_in(config.base_url, CAROL)
    await again.browser.aclose()
    assert again.error == "oidc_email_in_use"


@pytest.mark.oidc
async def test_a_deactivated_account_is_refused(
    admin: TwinlabClient, dex: OidcProvider, config: SuiteConfig, unique: Callable[[str], str]
) -> None:
    bob = await admin.create_user(unique("bob"), BOB, "Bob")
    _ = await admin.set_user_active(bob.user.id, False)
    _ = await _switch(admin, dex, tie=True)
    outcome = await sign_in(config.base_url, BOB)
    await outcome.browser.aclose()
    assert outcome.error == "account_disabled"


@pytest.mark.oidc
async def test_a_disabled_provider_disappears_and_refuses(
    admin: TwinlabClient, anon: TwinlabClient, dex: OidcProvider, config: SuiteConfig
) -> None:
    assert PROVIDER in {p.name for p in await anon.login_providers()}
    _ = await _switch(admin, dex, create=True, enabled=False)
    assert PROVIDER not in {p.name for p in await anon.login_providers()}
    outcome = await sign_in(config.base_url, ALICE)
    await outcome.browser.aclose()
    assert outcome.error == "oidc_unavailable"


@pytest.mark.oidc
async def test_a_forged_callback_is_refused(dex: OidcProvider, config: SuiteConfig) -> None:
    async with httpx2.AsyncClient(follow_redirects=False) as browser:
        response = await browser.get(
            f"{config.base_url}/api/v1/auth/oidc/{PROVIDER}/callback",
            params={"code": "made-up", "state": "never-issued"},
        )
    assert response.status_code == 302
    assert "oidc_error=oidc_state_invalid" in response.headers["location"]


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.mark.oidc
async def test_icons_round_trip_as_data_uris(
    admin: TwinlabClient, anon: TwinlabClient, dex: OidcProvider
) -> None:
    with_icon = await admin.set_oidc_provider_icon(dex.name, _PNG, "image/png")
    assert with_icon.icon == "data:image/png;base64," + base64.b64encode(_PNG).decode()
    listed = {p.name: p for p in await anon.login_providers()}
    assert listed[PROVIDER].icon == with_icon.icon
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.set_oidc_provider_icon(dex.name, _PNG, "image/svg+xml")
    assert excinfo.value.code == "invalid_icon"
    cleared = await admin.clear_oidc_provider_icon(dex.name)
    assert cleared.icon is None


@pytest.mark.oidc
async def test_creation_and_tying_stay_inside_the_allowed_domains(
    admin: TwinlabClient, dex: OidcProvider, config: SuiteConfig, unique: Callable[[str], str]
) -> None:
    # Delta 35. Dex's people are all @example.com.
    restricted = await _switch(admin, dex, create=True, tie=True, domains=["Other.Example"])
    assert restricted.allowed_email_domains == ["other.example"]  # stored lowercase
    refused = await sign_in(config.base_url, ALICE)
    await refused.browser.aclose()
    assert refused.error == "oidc_email_domain_not_allowed"
    assert all(u.email.lower() != ALICE for u in await admin.list_users())

    carol = await admin.create_user(unique("carol"), CAROL, "Carol Local")
    untied = await sign_in(config.base_url, CAROL)
    await untied.browser.aclose()
    assert untied.error == "oidc_email_domain_not_allowed"
    assert (await admin.get_user(carol.user.id)).identities == []

    # Listing the domain (in any case) lets the same sign-ins through.
    _ = await _switch(admin, dex, create=True, tie=True, domains=["other.example", "EXAMPLE.COM"])
    created = await sign_in(config.base_url, ALICE)
    await created.browser.aclose()
    assert created.signed_in, created.location
    tied = await sign_in(config.base_url, CAROL)
    await tied.browser.aclose()
    assert tied.signed_in, tied.location

    # An existing link is the identity: narrowing the list later leaves it alone.
    _ = await _switch(admin, dex, domains=["other.example"])
    again = await sign_in(config.base_url, ALICE)
    await again.browser.aclose()
    assert again.signed_in, again.location
