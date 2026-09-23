"""Provider discovery and signing keys (delta 33), cached in-process.

Discovery (`{issuer}/.well-known/openid-configuration`) and the JWKS are
fetched through the app's shared httpx2 client and cached for an hour; the
JWKS is also refetched once on an unknown signing key, which is how a
provider's key rotation reaches Twinlab without waiting out the cache.
httpx2 and pydantic are the boundaries here — their exceptions become values.
"""

import time
from dataclasses import dataclass, field

import httpx2
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from twinlab_backend.result import Err, Ok, Result

# How long a discovery document or JWKS is trusted before a refetch. Long
# enough that a sign-in costs no extra round trips; short enough that a
# provider-side change (new endpoints, a retired key) lands within the hour.
CACHE_SECONDS = 3600.0

# Signing algorithms Twinlab accepts on an ID token: the asymmetric families.
# `none` is never acceptable, and the HMAC family (keyed by the client secret)
# is left out — no provider Twinlab targets signs ID tokens that way, and
# accepting it would make the secret a signing key.
_ASYMMETRIC_ALGS = frozenset(
    ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA")
)


class _Discovery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None = None
    # Both optional in the spec, whose defaults are stated where they are used.
    token_endpoint_auth_methods_supported: list[str] | None = None
    id_token_signing_alg_values_supported: list[str] | None = None


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None
    # None = the provider did not say; the spec default is client_secret_basic.
    token_endpoint_auth_methods: tuple[str, ...] | None
    id_token_algorithms: tuple[str, ...]


def discovery_url(issuer: str) -> str:
    # The issuer is compared EXACTLY elsewhere (a trailing slash is part of
    # some providers' issuer); only the well-known path join trims it.
    return f"{issuer.rstrip('/')}/.well-known/openid-configuration"


def _metadata_from(doc: _Discovery) -> ProviderMetadata:
    # Spec default when unstated: RS256 is the one algorithm every OP supports.
    advertised = doc.id_token_signing_alg_values_supported or ["RS256"]
    return ProviderMetadata(
        issuer=doc.issuer,
        authorization_endpoint=doc.authorization_endpoint,
        token_endpoint=doc.token_endpoint,
        jwks_uri=doc.jwks_uri,
        userinfo_endpoint=doc.userinfo_endpoint,
        token_endpoint_auth_methods=(
            tuple(doc.token_endpoint_auth_methods_supported)
            if doc.token_endpoint_auth_methods_supported is not None
            else None
        ),
        id_token_algorithms=tuple(alg for alg in advertised if alg in _ASYMMETRIC_ALGS),
    )


async def _get_json(client: httpx2.AsyncClient, url: str) -> Result[object, str]:
    try:
        response = await client.get(url, headers={"Accept": "application/json"})
    except httpx2.HTTPError as exc:
        return Err(f"could not reach {url}: {exc.__class__.__name__}")
    if response.status_code != 200:
        return Err(f"{url} answered HTTP {response.status_code}")
    try:
        return Ok(response.json())
    except ValueError:
        return Err(f"{url} did not answer JSON")


async def fetch_metadata(client: httpx2.AsyncClient, issuer: str) -> Result[ProviderMetadata, str]:
    """The provider's discovery document, checked: it parses, names every
    endpoint the flow needs, claims EXACTLY this issuer, and offers at least
    one signing algorithm Twinlab accepts."""
    body = await _get_json(client, discovery_url(issuer))
    if isinstance(body, Err):
        return body
    try:
        doc = _Discovery.model_validate(body.value)
    except ValidationError as exc:
        fields = ", ".join(str(error["loc"][0]) for error in exc.errors() if error["loc"])
        return Err(f"the discovery document is missing or malformed: {fields}")
    if doc.issuer != issuer:
        return Err(f"the discovery document names issuer {doc.issuer!r}, not {issuer!r}")
    metadata = _metadata_from(doc)
    if not metadata.id_token_algorithms:
        return Err("the provider offers no asymmetric ID-token signing algorithm")
    return Ok(metadata)


class _Jwks(BaseModel):
    model_config = ConfigDict(extra="ignore")

    keys: list[object]


# joserfc's own shape for one key: string members, or lists of strings (x5c).
_JwkMembers = TypeAdapter(dict[str, str | list[str]])


def _keys_of(raw: list[object]) -> list[dict[str, str | list[str]]]:
    """The keys joserfc can take. A key with another member shape is SKIPPED,
    not fatal — RFC 7517 §5 has a consumer ignore keys it does not understand,
    and one exotic key must not take down sign-in for the others."""
    keys: list[dict[str, str | list[str]]] = []
    for item in raw:
        try:
            keys.append(_JwkMembers.validate_python(item))
        except ValidationError:
            continue
    return keys


async def fetch_jwks(client: httpx2.AsyncClient, uri: str) -> Result[KeySet, str]:
    body = await _get_json(client, uri)
    if isinstance(body, Err):
        return body
    try:
        raw = _Jwks.model_validate(body.value)
    except ValidationError:
        return Err("the JWKS is not a key set")
    try:
        return Ok(KeySet.import_key_set({"keys": _keys_of(raw.keys)}))
    except JoseError, ValueError:
        return Err("the JWKS does not parse as a key set")


@dataclass(slots=True)
class OidcCache:
    """Per-process cache of discovery documents and key sets."""

    client: httpx2.AsyncClient
    _metadata: dict[str, tuple[float, ProviderMetadata]] = field(default_factory=dict)
    _jwks: dict[str, tuple[float, KeySet]] = field(default_factory=dict)

    async def metadata(self, issuer: str) -> Result[ProviderMetadata, str]:
        cached = self._metadata.get(issuer)
        if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
            return Ok(cached[1])
        fetched = await fetch_metadata(self.client, issuer)
        if isinstance(fetched, Ok):
            self._metadata[issuer] = (time.monotonic(), fetched.value)
        return fetched

    async def jwks(self, uri: str, *, refresh: bool) -> Result[KeySet, str]:
        cached = self._jwks.get(uri)
        if not refresh and cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
            return Ok(cached[1])
        fetched = await fetch_jwks(self.client, uri)
        if isinstance(fetched, Ok):
            self._jwks[uri] = (time.monotonic(), fetched.value)
        return fetched
