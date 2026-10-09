"""OIDC sign-in (contract delta 33): the pure rules and the token boundary.

The resolution rules, `next` sanitizing, username derivation, icon checks
and the secret box are pure; discovery, the code exchange and ID-token
validation run against httpx2.MockTransport with a key generated here. The
flow's database half and the routes are the blackbox suite's job.
"""

import base64
import dataclasses
import json
import time
import uuid
from collections.abc import Callable, Mapping

import httpx2
import pytest
from cryptography.fernet import Fernet
from joserfc import jwt
from joserfc.jwk import RSAKey
from pydantic import ValidationError

from twinlab_backend.api.oidc import ProviderCreate, ProviderReplace
from twinlab_backend.auth.oidc import icons, secret_box, tokens
from twinlab_backend.auth.oidc.metadata import (
    OidcCache,
    ProviderMetadata,
    fetch_jwks,
    fetch_metadata,
)
from twinlab_backend.auth.oidc.resolution import (
    Account,
    Claims,
    Create,
    Lookups,
    Policy,
    Refuse,
    SignIn,
    Tie,
    display_name_for,
    parse_email_verified,
    resolve,
    safe_next,
    username_candidates,
)
from twinlab_backend.result import Err, Ok

ISSUER = "https://idp.example.com"
CLIENT_ID = "twinlab"
NONCE = "the-nonce"

# --------------------------------------------------------------------------- #
# Resolution: link, then tie, then create
# --------------------------------------------------------------------------- #

ALICE = Account(uuid.uuid7(), is_active=True)
DISABLED = Account(uuid.uuid7(), is_active=False)


def _claims(*, email: str | None = "alice@example.com", verified: bool | None = True) -> Claims:
    return Claims(
        subject="sub-1",
        email=email,
        email_verified=verified,
        name="Alice Liddell",
        preferred_username="alice",
    )


def _policy(
    *,
    create: bool = False,
    tie: bool = False,
    trust: bool = False,
    domains: frozenset[str] = frozenset(),
) -> Policy:
    return Policy(
        allow_create_users=create,
        allow_email_tying=tie,
        trust_email=trust,
        allowed_email_domains=domains,
    )


def _lookups(
    *,
    linked: Account | None = None,
    holder: Account | None = None,
    holder_linked_here: bool = False,
) -> Lookups:
    return Lookups(linked=linked, email_holder=holder, email_holder_linked_here=holder_linked_here)


def test_a_linked_identity_signs_in_whatever_the_switches_say() -> None:
    decision = resolve(_claims(verified=False), _policy(), _lookups(linked=ALICE))
    assert decision == SignIn(ALICE.id)


def test_a_linked_but_deactivated_user_is_refused() -> None:
    assert resolve(_claims(), _policy(), _lookups(linked=DISABLED)) == Refuse("account_disabled")


def test_tying_needs_the_switch_and_a_verified_email() -> None:
    holder = _lookups(holder=ALICE)
    assert resolve(_claims(), _policy(tie=True), holder) == Tie(ALICE.id, "alice@example.com")
    # Unverified: an attacker who can set any address at the provider would
    # otherwise sign into the account that owns it.
    assert resolve(_claims(verified=False), _policy(tie=True), holder) == Refuse(
        "oidc_email_unverified"
    )
    assert resolve(_claims(verified=None), _policy(tie=True), holder) == Refuse(
        "oidc_email_unverified"
    )
    # Switch off: the address is taken, and this provider may not claim it.
    assert resolve(_claims(), _policy(), holder) == Refuse("oidc_email_in_use")


def test_tying_refuses_a_second_identity_on_the_same_provider() -> None:
    decision = resolve(
        _claims(), _policy(tie=True), _lookups(holder=ALICE, holder_linked_here=True)
    )
    assert decision == Refuse("oidc_identity_conflict")


def test_tying_refuses_a_deactivated_holder() -> None:
    decision = resolve(_claims(), _policy(tie=True), _lookups(holder=DISABLED))
    assert decision == Refuse("account_disabled")


def test_trust_email_counts_an_absent_claim_but_never_an_explicit_false() -> None:
    holder = _lookups(holder=ALICE)
    trusted = _policy(tie=True, trust=True)
    assert resolve(_claims(verified=None), trusted, holder) == Tie(ALICE.id, "alice@example.com")
    assert resolve(_claims(verified=False), trusted, holder) == Refuse("oidc_email_unverified")


def test_creation_needs_the_switch_an_email_and_verification() -> None:
    nobody = _lookups()
    created = resolve(_claims(), _policy(create=True), nobody)
    assert created == Create(email="alice@example.com", display_name="Alice Liddell")
    assert resolve(_claims(email=None), _policy(create=True), nobody) == Refuse(
        "oidc_email_missing"
    )
    # An unverified address would squat the unique email column.
    assert resolve(_claims(verified=False), _policy(create=True), nobody) == Refuse(
        "oidc_email_unverified"
    )
    assert resolve(_claims(), _policy(), nobody) == Refuse("oidc_no_account")


def test_creation_never_takes_an_email_that_is_already_held() -> None:
    decision = resolve(_claims(), _policy(create=True), _lookups(holder=ALICE))
    assert decision == Refuse("oidc_email_in_use")


def test_tying_wins_over_creation_when_both_are_allowed() -> None:
    decision = resolve(_claims(), _policy(create=True, tie=True), _lookups(holder=ALICE))
    assert decision == Tie(ALICE.id, "alice@example.com")


# --------------------------------------------------------------------------- #
# Restricting tying and creation to email domains (delta 35)
# --------------------------------------------------------------------------- #

EXAMPLE_ONLY = frozenset({"example.com"})


def test_an_allowed_domain_ties_and_creates_whatever_its_case() -> None:
    shouting = _claims(email="Alice@EXAMPLE.Com")
    tie = _policy(tie=True, domains=EXAMPLE_ONLY)
    create = _policy(create=True, domains=EXAMPLE_ONLY)
    assert resolve(shouting, tie, _lookups(holder=ALICE)) == Tie(ALICE.id, "Alice@EXAMPLE.Com")
    assert isinstance(resolve(shouting, create, _lookups()), Create)


def test_any_other_domain_neither_ties_nor_creates() -> None:
    tie = _policy(tie=True, domains=EXAMPLE_ONLY)
    create = _policy(create=True, domains=EXAMPLE_ONLY)
    refused = Refuse("oidc_email_domain_not_allowed")
    # A subdomain is not its parent, and a lookalike suffix is not the domain.
    for email in ("alice@other.org", "alice@eu.example.com", "alice@badexample.com"):
        assert resolve(_claims(email=email), tie, _lookups(holder=ALICE)) == refused, email
        assert resolve(_claims(email=email), create, _lookups()) == refused, email
    # The domain follows the LAST @: a quoted local part cannot smuggle one in.
    smuggled = _claims(email='"alice@example.com"@other.org')
    assert resolve(smuggled, create, _lookups()) == refused


def test_the_domain_is_judged_only_on_a_verified_email() -> None:
    # Unverified is the more basic refusal: the domain of an address nobody
    # vouched for says nothing.
    unverified = _claims(email="alice@other.org", verified=False)
    assert resolve(unverified, _policy(create=True, domains=EXAMPLE_ONLY), _lookups()) == Refuse(
        "oidc_email_unverified"
    )


def test_a_refused_domain_is_reported_before_who_holds_the_address() -> None:
    held = _lookups(holder=ALICE)
    decision = resolve(
        _claims(email="alice@other.org"), _policy(create=True, domains=EXAMPLE_ONLY), held
    )
    assert decision == Refuse("oidc_email_domain_not_allowed")


def test_the_domains_never_touch_an_existing_link() -> None:
    # The link is the identity; the email was used once, when it was made.
    decision = resolve(
        _claims(email="alice@other.org"), _policy(domains=EXAMPLE_ONLY), _lookups(linked=ALICE)
    )
    assert decision == SignIn(ALICE.id)


def test_the_domain_list_is_normalized_and_checked() -> None:
    accepted = ProviderReplace.model_validate(
        {**_REPLACE, "allowed_email_domains": ["IQUALL.net", "iquall.net", "xn--bcher-kva.example"]}
    )
    assert accepted.allowed_email_domains == ["iquall.net", "xn--bcher-kva.example"]
    for bad in ("@iquall.net", "*.iquall.net", "iquall.net.", "-iquall.net", "iq uall.net", ""):
        with pytest.raises(ValidationError):
            _ = ProviderReplace.model_validate({**_REPLACE, "allowed_email_domains": [bad]})
    with pytest.raises(ValidationError):
        _ = ProviderReplace.model_validate(
            {**_REPLACE, "allowed_email_domains": [f"d{n}.example" for n in range(65)]}
        )


def test_the_domain_list_defaults_to_any_on_create_only() -> None:
    created = ProviderCreate.model_validate(
        {
            "name": "p",
            "display_name": "P",
            "issuer": ISSUER,
            "client_id": "c",
            "client_secret": None,
        }
    )
    assert created.allowed_email_domains == []
    # A replace states the whole record, the list included.
    without = {k: v for k, v in _REPLACE.items() if k != "allowed_email_domains"}
    with pytest.raises(ValidationError):
        _ = ProviderReplace.model_validate(without)


_REPLACE: dict[str, object] = {
    "display_name": "P",
    "issuer": ISSUER,
    "client_id": "c",
    "scopes": ["openid"],
    "allow_create_users": True,
    "allow_email_tying": False,
    "trust_email": False,
    "allowed_email_domains": [],
    "default_group_id": None,
    "enabled": True,
}


def test_email_verified_is_true_only_for_json_true() -> None:
    assert parse_email_verified({"email_verified": True}) is True
    assert parse_email_verified({}) is None
    # A non-conformant string is not guessed at: guessing is how verification
    # gets bypassed.
    for value in ("true", 1, "yes", None, False):
        assert parse_email_verified({"email_verified": value}) is False, value


# --------------------------------------------------------------------------- #
# Naming and redirects
# --------------------------------------------------------------------------- #


def test_display_name_prefers_name_then_username_then_email() -> None:
    assert display_name_for(_claims(), "a@x") == "Alice Liddell"
    bare = Claims("s", "a@x", True, name=None, preferred_username="  ")
    assert display_name_for(bare, "a@x") == "a@x"


def test_username_candidates_are_deterministic_and_fit_the_column() -> None:
    names = username_candidates(_claims(), "alice@example.com")
    assert [next(names) for _ in range(3)] == ["alice", "alice-2", "alice-3"]

    long_name = "x" * 80
    claims = Claims("s", "a@x", True, name=None, preferred_username=long_name)
    candidates = username_candidates(claims, "a@x")
    first, second = next(candidates), next(candidates)
    assert first == "x" * 64
    assert second == "x" * 62 + "-2"

    from_email = Claims("s", "bob@x", True, name=None, preferred_username=None)
    assert next(username_candidates(from_email, "bob@x")) == "bob"


def test_safe_next_keeps_only_in_app_paths() -> None:
    assert safe_next("/labs/core?tab=nodes") == "/labs/core?tab=nodes"
    for hostile in (
        None,
        "",
        "labs",
        "https://evil.example",
        "//evil.example",
        "/\\evil.example",
        "/labs\r\nSet-Cookie: x",
    ):
        assert safe_next(hostile) == "/", hostile


# --------------------------------------------------------------------------- #
# Icons and the secret box
# --------------------------------------------------------------------------- #

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect/></svg>'


def test_icons_must_be_what_they_declare() -> None:
    assert icons.check_icon(PNG, "image/png") == Ok("image/png")
    assert icons.check_icon(WEBP, "image/webp") == Ok("image/webp")
    assert icons.check_icon(SVG, "image/svg+xml; charset=utf-8") == Ok("image/svg+xml")
    assert isinstance(icons.check_icon(PNG, "image/svg+xml"), Err)
    assert isinstance(icons.check_icon(SVG, "image/png"), Err)
    assert isinstance(icons.check_icon(PNG, "image/gif"), Err)
    assert isinstance(icons.check_icon(PNG, None), Err)
    assert isinstance(icons.check_icon(b"", "image/png"), Err)


def test_svg_icons_refuse_a_dtd_and_non_svg_roots() -> None:
    laughs = b'<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg>&a;</svg>'
    assert isinstance(icons.check_icon(laughs, "image/svg+xml"), Err)
    assert isinstance(icons.check_icon(b"<html></html>", "image/svg+xml"), Err)
    assert isinstance(icons.check_icon(b"<svg", "image/svg+xml"), Err)


def test_icons_are_bounded() -> None:
    oversized = PNG + b"\x00" * icons.MAX_ICON_BYTES
    assert isinstance(icons.check_icon(oversized, "image/png"), Err)


def test_icons_render_as_data_uris() -> None:
    uri = icons.data_uri(PNG, "image/png")
    assert uri == "data:image/png;base64," + base64.b64encode(PNG).decode()


def test_secret_box_round_trips_and_detects_a_changed_key() -> None:
    key = Fernet.generate_key().decode()
    sealed = secret_box.encrypt(key, "s3cret")
    assert "s3cret" not in sealed
    assert secret_box.decrypt(key, sealed) == Ok("s3cret")
    assert isinstance(secret_box.decrypt(Fernet.generate_key().decode(), sealed), Err)


# --------------------------------------------------------------------------- #
# Discovery, exchange, ID-token validation
# --------------------------------------------------------------------------- #

DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/auth",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/keys",
    "userinfo_endpoint": f"{ISSUER}/userinfo",
    "id_token_signing_alg_values_supported": ["RS256", "HS256"],
}


def _client(handler: Callable[[httpx2.Request], httpx2.Response]) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


async def test_discovery_is_checked_against_the_configured_issuer() -> None:
    async with _client(lambda _: httpx2.Response(200, json=DISCOVERY)) as client:
        fetched = await fetch_metadata(client, ISSUER)
        assert isinstance(fetched, Ok)
        # HS256 is dropped: an HMAC-signed ID token would make the client
        # secret a signing key.
        assert fetched.value.id_token_algorithms == ("RS256",)

        mismatch = await fetch_metadata(client, f"{ISSUER}/other")
        assert isinstance(mismatch, Err)
        assert "names issuer" in mismatch.error


async def test_discovery_reports_what_is_missing() -> None:
    partial = {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/auth"}
    async with _client(lambda _: httpx2.Response(200, json=partial)) as client:
        fetched = await fetch_metadata(client, ISSUER)
    assert isinstance(fetched, Err)
    assert "token_endpoint" in fetched.error


async def test_an_unreachable_issuer_is_a_value() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    async with _client(refuse) as client:
        assert isinstance(await fetch_metadata(client, ISSUER), Err)


def _metadata() -> ProviderMetadata:
    return ProviderMetadata(
        issuer=ISSUER,
        authorization_endpoint=f"{ISSUER}/auth",
        token_endpoint=f"{ISSUER}/token",
        jwks_uri=f"{ISSUER}/keys",
        userinfo_endpoint=f"{ISSUER}/userinfo",
        token_endpoint_auth_methods=None,
        id_token_algorithms=("RS256",),
    )


def test_client_authentication_follows_the_provider() -> None:
    meta = _metadata()
    assert tokens.auth_method_for(meta, has_secret=False) == "none"
    assert tokens.auth_method_for(meta, has_secret=True) == "client_secret_basic"
    post_only = dataclasses.replace(meta, token_endpoint_auth_methods=("client_secret_post",))
    assert tokens.auth_method_for(post_only, has_secret=True) == "client_secret_post"


async def test_the_code_exchange_sends_the_verifier_and_authenticates() -> None:
    seen: list[httpx2.Request] = []

    def token_endpoint(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200, json={"id_token": "x.y.z", "access_token": "at", "token_type": "Bearer"}
        )

    exchanged = await tokens.exchange_code(
        _metadata(),
        client_id=CLIENT_ID,
        client_secret="s3cret",
        code="the-code",
        code_verifier="v" * 64,
        redirect_uri="https://twinlab.example/api/v1/auth/oidc/idp/callback",
        transport=httpx2.MockTransport(token_endpoint),
    )
    assert exchanged == Ok(tokens.TokenSet("x.y.z", "at"))
    body = dict(pair.split("=", 1) for pair in seen[0].content.decode().split("&"))
    assert body["grant_type"] == "authorization_code"
    assert body["code"] == "the-code"
    assert body["code_verifier"] == "v" * 64
    assert seen[0].headers["authorization"].startswith("Basic ")


async def test_a_refused_code_is_a_value() -> None:
    exchanged = await tokens.exchange_code(
        _metadata(),
        client_id=CLIENT_ID,
        client_secret=None,
        code="stale",
        code_verifier="v" * 64,
        redirect_uri="https://twinlab.example/cb",
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(400, json={"error": "invalid_grant"})
        ),
    )
    assert isinstance(exchanged, Err)
    assert "invalid_grant" in exchanged.error


KEY = RSAKey.generate_key(2048, parameters={"kid": "k1"}, private=True)


def _jwks_client(*keys: RSAKey) -> httpx2.AsyncClient:
    public = {"keys": [key.as_dict(private=False) for key in keys]}
    return _client(lambda _: httpx2.Response(200, json=public))


def _id_token(key: RSAKey, overrides: Mapping[str, object]) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "sub-1",
        "iat": now,
        "exp": now + 300,
        "nonce": NONCE,
        "email": "alice@example.com",
        "email_verified": True,
    }
    claims.update(overrides)
    return jwt.encode({"alg": "RS256", "kid": key.kid or ""}, claims, key)


async def test_a_valid_id_token_yields_its_claims() -> None:
    async with _jwks_client(KEY) as client:
        validated = await tokens.validate_id_token(
            OidcCache(client=client),
            _metadata(),
            _id_token(KEY, {}),
            client_id=CLIENT_ID,
            nonce=NONCE,
        )
    assert isinstance(validated, Ok)
    assert validated.value["sub"] == "sub-1"


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://someone-else.example"},
        {"aud": "another-client"},
        {"nonce": "replayed"},
        {"exp": int(time.time()) - 3600},
        {"aud": [CLIENT_ID, "other"]},  # several audiences and no azp
    ],
)
async def test_id_token_claims_are_enforced(overrides: dict[str, object]) -> None:
    async with _jwks_client(KEY) as client:
        validated = await tokens.validate_id_token(
            OidcCache(client=client),
            _metadata(),
            _id_token(KEY, overrides),
            client_id=CLIENT_ID,
            nonce=NONCE,
        )
    assert isinstance(validated, Err), overrides


async def test_a_token_signed_by_another_key_is_refused() -> None:
    impostor = RSAKey.generate_key(2048, parameters={"kid": "k1"}, private=True)
    async with _jwks_client(KEY) as client:
        validated = await tokens.validate_id_token(
            OidcCache(client=client),
            _metadata(),
            _id_token(impostor, {}),
            client_id=CLIENT_ID,
            nonce=NONCE,
        )
    assert isinstance(validated, Err)


async def test_an_unknown_kid_refetches_the_key_set_once() -> None:
    rotated = RSAKey.generate_key(2048, parameters={"kid": "k2"}, private=True)
    served = [KEY]
    fetches: list[int] = []

    def jwks(_: httpx2.Request) -> httpx2.Response:
        fetches.append(1)
        return httpx2.Response(200, json={"keys": [k.as_dict(private=False) for k in served]})

    async with _client(jwks) as client:
        cache = OidcCache(client=client)
        first = await tokens.validate_id_token(
            cache, _metadata(), _id_token(KEY, {}), client_id=CLIENT_ID, nonce=NONCE
        )
        assert isinstance(first, Ok)
        served.append(rotated)  # the provider rotates
        second = await tokens.validate_id_token(
            cache, _metadata(), _id_token(rotated, {}), client_id=CLIENT_ID, nonce=NONCE
        )
    assert isinstance(second, Ok)
    assert len(fetches) == 2  # cached once, refetched once on the unknown kid


async def test_userinfo_fills_gaps_but_must_name_the_same_subject() -> None:
    claims: dict[str, object] = {"sub": "sub-1"}

    def userinfo(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["authorization"] == "Bearer at"
        return httpx2.Response(
            200, content=json.dumps({"sub": "sub-1", "email": "a@x", "email_verified": True})
        )

    async with _client(userinfo) as client:
        merged = await tokens.merge_userinfo(client, _metadata(), claims, "at")
    assert merged == Ok({"sub": "sub-1", "email": "a@x", "email_verified": True})

    async with _client(lambda _: httpx2.Response(200, json={"sub": "someone-else"})) as client:
        assert isinstance(await tokens.merge_userinfo(client, _metadata(), claims, "at"), Err)


def test_identity_claims_parse_at_the_boundary() -> None:
    parsed = tokens.identity_claims(
        {"sub": "s", "email": "a@x", "email_verified": "true", "name": "A"}
    )
    assert parsed == Ok(Claims("s", "a@x", False, "A", None))
    assert isinstance(tokens.identity_claims({"email": "a@x"}), Err)


async def test_the_jwks_keeps_the_keys_it_can_read() -> None:
    # A key with a member shape joserfc cannot take is skipped, not fatal
    # (RFC 7517 §5): one exotic key must not take down sign-in for the rest.
    exotic = {"kty": "RSA", "kid": "weird", "n": 12345, "e": "AQAB"}
    body = {"keys": [exotic, KEY.as_dict(private=False)]}
    async with _client(lambda _: httpx2.Response(200, json=body)) as client:
        fetched = await fetch_jwks(client, f"{ISSUER}/keys")
    assert isinstance(fetched, Ok)
    assert fetched.value.get_by_kid("k1").kid == "k1"
