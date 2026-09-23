"""The token half of the flow (delta 33): exchange the code, validate the ID
token, and read userinfo when the ID token leaves the email out.

Authlib does the token-endpoint exchange (client authentication, the PKCE
verifier, error-response parsing); joserfc validates the ID token. Both, and
httpx2, raise — this module is the boundary that turns that into values.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import httpx2
from authlib.integrations.base_client import OAuthError
from authlib.integrations.httpx_client import AsyncOAuth2Client
from joserfc import jwt
from joserfc.errors import ClaimError, InvalidKeyIdError, JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import ClaimsOption, JWTClaimsRegistry
from pydantic import TypeAdapter, ValidationError

from twinlab_backend.auth.oidc.metadata import OidcCache, ProviderMetadata
from twinlab_backend.auth.oidc.resolution import Claims, parse_email_verified
from twinlab_backend.result import Err, Ok, Result

# The client-authentication methods Twinlab uses at the token endpoint.
type TokenEndpointAuthMethod = Literal["client_secret_basic", "client_secret_post", "none"]

_AUDIENCE: TypeAdapter[str | list[str]] = TypeAdapter(str | list[str])
_JSON_OBJECT = TypeAdapter(dict[str, object])

# Clock skew tolerated on exp/iat/nbf: a minute covers ordinary NTP drift
# between Twinlab's host and the provider's without widening replay much.
CLOCK_LEEWAY_SECONDS = 60

# The token endpoint is one round trip; 30s matches the backend's other
# upstream calls.
TOKEN_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class TokenSet:
    id_token: str
    access_token: str | None


def auth_method_for(metadata: ProviderMetadata, *, has_secret: bool) -> TokenEndpointAuthMethod:
    """How the client authenticates at the token endpoint: none for a public
    client; otherwise basic when the provider supports it (the spec default
    when it does not say), else post."""
    if not has_secret:
        return "none"
    supported = metadata.token_endpoint_auth_methods
    if supported is None or "client_secret_basic" in supported:
        return "client_secret_basic"
    if "client_secret_post" in supported:
        return "client_secret_post"
    # Neither offered: basic is still the spec default, and the provider's own
    # error will then say why it refused — clearer than failing here.
    return "client_secret_basic"


async def exchange_code(
    metadata: ProviderMetadata,
    *,
    client_id: str,
    client_secret: str | None,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    transport: httpx2.AsyncBaseTransport,
) -> Result[TokenSet, str]:
    method = auth_method_for(metadata, has_secret=client_secret is not None)
    async with AsyncOAuth2Client(
        client_id,
        client_secret,
        method,
        code_challenge_method="S256",
        timeout=TOKEN_TIMEOUT_SECONDS,
        transport=transport,
    ) as oauth:
        try:
            token = await oauth.fetch_token(
                metadata.token_endpoint,
                code=code,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
            )
        except OAuthError as exc:
            return Err(f"the token endpoint refused the code ({exc.error})")
        except httpx2.HTTPError as exc:
            return Err(f"could not reach the token endpoint: {exc.__class__.__name__}")
        except ValueError:
            return Err("the token endpoint did not answer JSON")
    id_token = token.get("id_token")
    if not isinstance(id_token, str):
        return Err("the token response carries no ID token (is `openid` in the scopes?)")
    access_token = token.get("access_token")
    return Ok(TokenSet(id_token, access_token if isinstance(access_token, str) else None))


def _decode(id_token: str, keys: KeySet, algorithms: tuple[str, ...]) -> Result[jwt.Token, str]:
    try:
        return Ok(jwt.decode(id_token, keys, algorithms=list(algorithms)))
    except InvalidKeyIdError:
        return Err("unknown_kid")
    except JoseError as exc:
        return Err(f"the ID token does not verify ({exc.error})")
    except ValueError:
        return Err("the ID token is malformed")


def check_claims(
    claims: Mapping[str, object], *, issuer: str, client_id: str, nonce: str
) -> Result[None, str]:
    """iss exact, aud containing the client (and azp naming it when there are
    several audiences), sub present, exp/iat within leeway, nonce ours."""
    registry = JWTClaimsRegistry(
        leeway=CLOCK_LEEWAY_SECONDS,
        iss=ClaimsOption(essential=True, value=issuer),
        aud=ClaimsOption(essential=True, value=client_id),
        sub=ClaimsOption(essential=True),
        exp=ClaimsOption(essential=True),
        iat=ClaimsOption(essential=True),
        nonce=ClaimsOption(essential=True, value=nonce),
    )
    try:
        registry.validate(dict(claims))
    except ClaimError as exc:
        return Err(f"the ID token's claims are invalid ({exc.error}: {exc.description})")
    try:
        audience = _AUDIENCE.validate_python(claims.get("aud"))
    except ValidationError:
        return Err("the ID token's audience is neither a string nor a list of strings")
    if isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != client_id:
        return Err("the ID token has several audiences and `azp` does not name this client")
    return Ok(None)


async def validate_id_token(
    cache: OidcCache,
    metadata: ProviderMetadata,
    id_token: str,
    *,
    client_id: str,
    nonce: str,
) -> Result[dict[str, object], str]:
    keys = await cache.jwks(metadata.jwks_uri, refresh=False)
    if isinstance(keys, Err):
        return keys
    decoded = _decode(id_token, keys.value, metadata.id_token_algorithms)
    if isinstance(decoded, Err) and decoded.error == "unknown_kid":
        # The provider rotated its keys since the cache filled: refetch ONCE.
        keys = await cache.jwks(metadata.jwks_uri, refresh=True)
        if isinstance(keys, Err):
            return keys
        decoded = _decode(id_token, keys.value, metadata.id_token_algorithms)
    if isinstance(decoded, Err):
        if decoded.error == "unknown_kid":
            return Err("the ID token is signed with a key the provider does not publish")
        return decoded
    claims: dict[str, object] = dict(decoded.value.claims)
    checked = check_claims(claims, issuer=metadata.issuer, client_id=client_id, nonce=nonce)
    if isinstance(checked, Err):
        return checked
    return Ok(claims)


async def merge_userinfo(
    client: httpx2.AsyncClient,
    metadata: ProviderMetadata,
    claims: dict[str, object],
    access_token: str | None,
) -> Result[dict[str, object], str]:
    """Some providers keep `email`/`email_verified` to userinfo. Fetched ONLY
    when the ID token lacks either; its `sub` must match the ID token's, and it
    fills gaps without overriding what the (signed) ID token said."""
    if "email" in claims and "email_verified" in claims:
        return Ok(claims)
    if metadata.userinfo_endpoint is None or access_token is None:
        return Ok(claims)
    try:
        response = await client.get(
            metadata.userinfo_endpoint, headers={"Authorization": f"Bearer {access_token}"}
        )
    except httpx2.HTTPError as exc:
        return Err(f"could not reach the userinfo endpoint: {exc.__class__.__name__}")
    if response.status_code != 200:
        return Err(f"the userinfo endpoint answered HTTP {response.status_code}")
    try:
        info = _JSON_OBJECT.validate_json(response.content)
    except ValidationError:
        return Err("the userinfo response is not a JSON object")
    if info.get("sub") != claims.get("sub"):
        return Err("the userinfo response names a different subject than the ID token")
    return Ok({**info, **claims})


def _str_claim(claims: Mapping[str, object], name: str) -> str | None:
    value = claims.get(name)
    return value if isinstance(value, str) and value else None


def identity_claims(claims: Mapping[str, object]) -> Result[Claims, str]:
    subject = _str_claim(claims, "sub")
    if subject is None:
        return Err("the ID token has no subject")
    if len(subject) > 255:
        return Err("the subject exceeds 255 characters")
    email = _str_claim(claims, "email")
    return Ok(
        Claims(
            subject=subject,
            email=email if email is not None and len(email) <= 320 else None,
            email_verified=parse_email_verified(claims),
            name=_str_claim(claims, "name"),
            preferred_username=_str_claim(claims, "preferred_username"),
        )
    )
