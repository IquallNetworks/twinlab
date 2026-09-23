"""The Twinlab API client.

Implements the v1.0 target contract (`docs/twinlab_client_shape.py` in the
Twinlab repository): every method is a coroutine, every wire shape a frozen
dataclass, every non-2xx a `TwinlabApiError`.

Conventions carried by every method (not repeated per docstring):

- Lab-guarded routes return **404** when the caller can't read the lab
  (existence hidden) and **403** when readable but lacking the permission.
- Names (lab/node/suite) match ``^[A-Za-z0-9][A-Za-z0-9_.-]*$``, max 64.
"""

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from typing import Literal
from urllib.parse import urlencode
from uuid import UUID

import httpx2

from twinlab_client import _wire
from twinlab_client._terminal import TerminalSession
from twinlab_client.errors import TwinlabProtocolError, error_from_response
from twinlab_client.models import (
    UNCHANGED,
    ApiKey,
    ApiKeyCreated,
    ConfigDiffReport,
    ConfigTemplateSpec,
    CustomConfigResponse,
    DeviceCatalog,
    DiffSource,
    DockerUsage,
    Grant,
    GroupSummary,
    HostResources,
    ImportSource,
    Job,
    JobDetail,
    JobEvent,
    LabActionResponse,
    LabDetail,
    LabEvent,
    LabFacts,
    LabLayout,
    LabLinks,
    LabOwner,
    LabPowerAction,
    LabSummary,
    LabUsage,
    LayoutGroupStyle,
    LayoutPosition,
    Liveness,
    LoginProvider,
    NetemAction,
    NetemImpairment,
    NetworkImport,
    NetworkTemplate,
    NetworkTemplateSummary,
    NodeImport,
    NodeInterfaces,
    NodeLogsResponse,
    NodePowerAction,
    NodeTemplate,
    OidcIconType,
    OidcProvider,
    PowerAction,
    Principals,
    Readiness,
    Role,
    RuntimeActionsReport,
    SaveConfigResponse,
    SshAccess,
    SshKey,
    SshKeyGenerated,
    TerminalProtocol,
    TestCaseDraft,
    TestCaseDryRunResult,
    TestSuite,
    TestSuitesResponse,
    Unchanged,
    UserCreated,
    UserInfo,
    UserSummary,
    WiringEntry,
    WiringSuggestion,
)


class TwinlabClient(AbstractAsyncContextManager["TwinlabClient"]):
    """Async Twinlab API client. One instance = one session (cookie jar on the
    instance); use as ``async with TwinlabClient(...) as client``.

    The four long operations (deploy/configure/destroy/suite run) are ASYNC
    JOBS: submit returns 202 + a running `Job`; the caller polls `get_job`
    (or `wait_job`) for the terminal state. `action_timeout` is the default
    `wait_job` deadline, i.e. how long a submitted operation may take end to
    end.
    """

    def __init__(
        self,
        base_url: str,
        *,
        subpath: str = "/api/v1",
        api_key: str | None = None,
        timeout: float = 30.0,
        action_timeout: float = 1800.0,
        verify_tls: bool = True,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """`base_url` = backend origin (e.g. "http://localhost:8000");
        `subpath` is appended to it. `api_key` authenticates every request as
        `Authorization: Bearer <key>` instead of a login session.
        `action_timeout` is the default `wait_job` deadline — submits
        themselves are fast 202s. `transport` is a testing seam
        (httpx2.MockTransport)."""
        if not base_url.startswith(("http://", "https://")):
            raise ValueError(f"base_url must be an http(s) origin, got {base_url!r}")
        self._origin = base_url.rstrip("/")
        self._subpath = "/" + subpath.strip("/") if subpath.strip("/") else ""
        self._api_key = api_key
        self._timeout = timeout
        self._action_timeout = action_timeout
        headers = {"Authorization": f"Bearer {api_key}"} if api_key is not None else {}
        self._http = httpx2.AsyncClient(
            base_url=self._origin + self._subpath,
            headers=headers,
            timeout=timeout,
            verify=verify_tls,
            transport=transport,
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client (also done by `async with`)."""
        await self._http.aclose()

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ #
    # Plumbing
    # ------------------------------------------------------------------ #

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        params: dict[str, str | int | bool] | None = None,
        long: bool = False,
        content: tuple[bytes, str] | None = None,
    ) -> httpx2.Response:
        """`content` = a raw (body, media type) pair, for the one endpoint that
        takes bytes rather than JSON (a provider icon)."""
        if content is not None:
            body, media_type = content
            response = await self._http.request(
                method, path, content=body, headers={"Content-Type": media_type}
            )
        elif long:
            response = await self._http.request(
                method, path, json=json_body, params=params, timeout=self._action_timeout
            )
        else:
            response = await self._http.request(method, path, json=json_body, params=params)
        if response.is_error:
            raise error_from_response(response)
        return response

    async def _send_json(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        params: dict[str, str | int | bool] | None = None,
        long: bool = False,
        content: tuple[bytes, str] | None = None,
    ) -> object:
        response = await self._send(
            method, path, json_body=json_body, params=params, long=long, content=content
        )
        try:
            return response.json()
        except ValueError as exc:
            raise TwinlabProtocolError(path, "response body is not JSON") from exc

    def _ws_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        cookies = [
            f"{cookie.name}={cookie.value}"
            for cookie in self._http.cookies.jar
            if cookie.value is not None
        ]
        if cookies:
            headers["Cookie"] = "; ".join(cookies)
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    # ------------------------------------------------------------------ #
    # Health (unauthenticated)
    # ------------------------------------------------------------------ #

    async def health(self) -> Liveness:
        """GET /health — dependency-free liveness."""
        return _wire.parse_liveness(await self._send_json("GET", "/health"))

    async def ready(self) -> Readiness:
        """GET /health/ready — parses both 200 and 503 (degraded is data, not
        an error)."""
        response = await self._http.get("/health/ready")
        if response.is_error and response.status_code != 503:
            raise error_from_response(response)
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise TwinlabProtocolError("/health/ready", "response body is not JSON") from exc
        return _wire.parse_readiness(payload)

    # ------------------------------------------------------------------ #
    # Auth
    # ------------------------------------------------------------------ #

    async def login(self, username: str, password: str) -> UserInfo:
        """POST /auth/login — sets the session cookie. 401 "invalid
        credentials" for both unknown-user and wrong-password (deliberately
        opaque)."""
        payload = await self._send_json(
            "POST", "/auth/login", json_body={"username": username, "password": password}
        )
        return _wire.parse_user_info(payload)

    async def logout(self) -> None:
        """POST /auth/logout — 204; idempotent."""
        _ = await self._send("POST", "/auth/logout")

    async def me(self) -> UserInfo:
        """GET /auth/me — identity + GLOBAL roles/permissions."""
        return _wire.parse_user_info(await self._send_json("GET", "/auth/me"))

    async def change_password(self, current: str, new: str) -> None:
        """PUT /auth/password — self-service change, requires the current
        password. 204; revokes the user's OTHER sessions, keeps this one."""
        _ = await self._send(
            "PUT",
            "/auth/password",
            json_body={"current_password": current, "new_password": new},
        )

    async def update_own_profile(self, display_name: str) -> UserInfo:
        """PUT /auth/profile — the caller's own display name (1 to 128 chars).
        Deliberately not the email: with OIDC email tying, a user who could set
        their own address to a colleague's would receive that colleague's first
        provider sign-in. Only an admin edits an email (`update_user_profile`)."""
        payload = await self._send_json(
            "PUT", "/auth/profile", json_body={"display_name": display_name}
        )
        return _wire.parse_user_info(payload)

    # OIDC sign-in (delta 33) is BROWSER-ONLY and has no method here: a person
    # has to be at the provider's login form. An OIDC user automates by
    # signing in through the browser once and creating an API key.

    async def login_providers(self) -> list[LoginProvider]:
        """GET /auth/oidc/providers — UNAUTHENTICATED; the enabled providers,
        for a login page. Empty when none are configured or the deployment's
        PUBLIC_ORIGIN is unset."""
        payload = await self._send_json("GET", "/auth/oidc/providers")
        return [_wire.parse_login_provider(v) for v in _wire.as_list(payload, "LoginProvider[]")]

    async def create_api_key(self, name: str) -> ApiKeyCreated:
        """POST /auth/api-keys — 201. The secret is returned only here.
        409 name_taken (per user)."""
        payload = await self._send_json("POST", "/auth/api-keys", json_body={"name": name})
        return _wire.parse_api_key_created(payload)

    async def list_api_keys(self) -> list[ApiKey]:
        """GET /auth/api-keys — the caller's own keys, no secrets."""
        payload = await self._send_json("GET", "/auth/api-keys")
        return [_wire.parse_api_key(v) for v in _wire.as_list(payload, "ApiKey[]")]

    async def revoke_api_key(self, key_id: UUID) -> None:
        """DELETE /auth/api-keys/{key_id} — 204, immediate."""
        _ = await self._send("DELETE", f"/auth/api-keys/{key_id}")

    # SSH keys: registered PUBLIC keys unlock the stack's SSH jump host.
    # Through it a key's owner reaches ALL TCP ports of nodes in labs where
    # they hold lab:terminal (owner-implicit included) — TCP forwarding only,
    # no shell/PTY on the jump itself. Authorization is re-evaluated from
    # live RBAC at every NEW connection: deleting a key, revoking
    # lab:terminal, or deactivating the user takes effect on the next
    # connection (established tunnels survive until closed), and the
    # permitted node set is frozen per connection (reconnect after a
    # redeploy changes node IPs).

    async def create_ssh_key(self, name: str, public_key: str) -> SshKey:
        """POST /auth/ssh-keys — 201. `public_key` is one OpenSSH
        authorized_keys-format line ("<algorithm> <base64> [comment]", no
        options). 422 invalid_public_key / unsupported_key_type; 409
        name_taken (per user); 409 key_already_registered — fingerprints are
        GLOBALLY unique, a key identifies one person at the jump."""
        payload = await self._send_json(
            "POST", "/auth/ssh-keys", json_body={"name": name, "public_key": public_key}
        )
        return _wire.parse_ssh_key(payload)

    async def generate_ssh_key(self, name: str) -> SshKeyGenerated:
        """POST /auth/ssh-keys/generate — 201. Server-side ed25519 pair for
        users without their own key: the public half is registered under
        `name` (equivalent to create_ssh_key from then on), the private half
        is returned only here and never stored. 409 name_taken (per user);
        a fingerprint conflict cannot occur (the key is freshly random)."""
        payload = await self._send_json("POST", "/auth/ssh-keys/generate", json_body={"name": name})
        return _wire.parse_ssh_key_generated(payload)

    async def list_ssh_keys(self) -> list[SshKey]:
        """GET /auth/ssh-keys — the caller's own keys."""
        payload = await self._send_json("GET", "/auth/ssh-keys")
        return [_wire.parse_ssh_key(v) for v in _wire.as_list(payload, "SshKey[]")]

    async def delete_ssh_key(self, key_id: UUID) -> None:
        """DELETE /auth/ssh-keys/{key_id} — 204. 404 ssh_key_not_found (own
        keys only; someone else's id is indistinguishable from absent)."""
        _ = await self._send("DELETE", f"/auth/ssh-keys/{key_id}")

    async def get_ssh_access(self) -> SshAccess:
        """GET /ssh-access — jump-host coordinates; any authenticated user."""
        return _wire.parse_ssh_access(await self._send_json("GET", "/ssh-access"))

    # ------------------------------------------------------------------ #
    # Users (global user:manage)
    # ------------------------------------------------------------------ #

    async def create_user(
        self,
        username: str,
        email: str,
        display_name: str,
        *,
        password: str | None = None,
        roles: set[str] | None = None,
    ) -> UserCreated:
        """POST /users — 201. `roles` = GLOBAL roles; omitted/empty = the
        baseline "user" role (authenticated, no access). `password` omitted =
        the server generates one and returns it ONCE on
        `UserCreated.generated_password`. 409 username_taken / email_taken
        (emails are unique case-insensitively); 422 unknown_roles; password
        min 8."""
        body: dict[str, object] = {
            "username": username,
            "email": email,
            "display_name": display_name,
        }
        if password is not None:
            body["password"] = password
        if roles is not None:
            body["roles"] = sorted(roles)
        return _wire.parse_user_created(await self._send_json("POST", "/users", json_body=body))

    async def update_user_profile(
        self, user_id: UUID, *, email: str, display_name: str
    ) -> UserSummary:
        """PUT /users/{user_id}/profile — both fields, for ANY user including the
        caller. 404 user_not_found; 409 email_taken. The user's linked
        identities are untouched."""
        payload = await self._send_json(
            "PUT",
            f"/users/{user_id}/profile",
            json_body={"email": email, "display_name": display_name},
        )
        return _wire.parse_user_summary(payload)

    async def unlink_identity(self, user_id: UUID, identity_id: UUID) -> None:
        """DELETE /users/{user_id}/identities/{identity_id} — 204. 404
        identity_not_found (also for another user's identity). The next sign-in
        through that provider goes through its tie/create rules again."""
        _ = await self._send("DELETE", f"/users/{user_id}/identities/{identity_id}")

    async def list_users(self) -> list[UserSummary]:
        """GET /users. No pagination anywhere (explicit v1.0 decision)."""
        payload = await self._send_json("GET", "/users")
        return [_wire.parse_user_summary(v) for v in _wire.as_list(payload, "UserSummary[]")]

    async def get_user(self, user_id: UUID) -> UserSummary:
        """GET /users/{user_id} — 404 user_not_found."""
        return _wire.parse_user_summary(await self._send_json("GET", f"/users/{user_id}"))

    async def set_user_roles(self, user_id: UUID, roles: set[str]) -> UserSummary:
        """PUT /users/{user_id}/roles — full replace of global roles.
        404 user_not_found; 422 unknown/non-global role."""
        payload = await self._send_json(
            "PUT", f"/users/{user_id}/roles", json_body={"roles": sorted(roles)}
        )
        return _wire.parse_user_summary(payload)

    async def set_user_password(self, user_id: UUID, password: str) -> None:
        """PUT /users/{user_id}/password — admin reset. 204; revokes ALL the
        user's sessions."""
        _ = await self._send("PUT", f"/users/{user_id}/password", json_body={"password": password})

    async def set_user_active(self, user_id: UUID, is_active: bool) -> UserSummary:
        """PUT /users/{user_id}/active — deactivate/reactivate. Deactivation
        revokes the user's sessions and stops their API keys; record, bindings,
        and owned labs are untouched. Refuses deactivating the last active
        admin (409)."""
        payload = await self._send_json(
            "PUT", f"/users/{user_id}/active", json_body={"is_active": is_active}
        )
        return _wire.parse_user_summary(payload)

    async def delete_user(self, user_id: UUID) -> None:
        """DELETE /users/{user_id} — 204. Revokes sessions, cascades role
        bindings the user RECEIVED; keeps rows where they were the actor
        (owned labs -> owner NULL). Refuses deleting the last admin (409)."""
        _ = await self._send("DELETE", f"/users/{user_id}")

    # ------------------------------------------------------------------ #
    # OIDC providers (global user:manage)
    # ------------------------------------------------------------------ #

    async def list_oidc_providers(self) -> list[OidcProvider]:
        """GET /oidc-providers — all of them, enabled or not."""
        payload = await self._send_json("GET", "/oidc-providers")
        return [_wire.parse_oidc_provider(v) for v in _wire.as_list(payload, "OidcProvider[]")]

    async def get_oidc_provider(self, name: str) -> OidcProvider:
        """GET /oidc-providers/{name} — 404 provider_not_found."""
        return _wire.parse_oidc_provider(await self._send_json("GET", f"/oidc-providers/{name}"))

    async def create_oidc_provider(
        self,
        name: str,
        display_name: str,
        issuer: str,
        client_id: str,
        *,
        client_secret: str | None,
        scopes: list[str] | None = None,
        allow_create_users: bool = False,
        allow_email_tying: bool = False,
        trust_email: bool = False,
        default_group_id: UUID | None = None,
        enabled: bool = True,
    ) -> OidcProvider:
        """POST /oidc-providers — 201. `client_secret` None = a public client
        (PKCE alone); it is a required keyword so a confidential client is never
        created without its secret by omission. `scopes` None = the server's
        default (openid, email, profile); the three switches default OFF, the
        safe state. The server fetches the issuer's discovery document first:
        422 oidc_discovery_failed. 409 provider_name_taken / issuer_taken /
        oidc_secret_key_unset; 422 group_not_found."""
        body: dict[str, object] = {
            "name": name,
            "display_name": display_name,
            "issuer": issuer,
            "client_id": client_id,
            "client_secret": client_secret,
            "allow_create_users": allow_create_users,
            "allow_email_tying": allow_email_tying,
            "trust_email": trust_email,
            "default_group_id": str(default_group_id) if default_group_id is not None else None,
            "enabled": enabled,
        }
        if scopes is not None:
            body["scopes"] = scopes
        payload = await self._send_json("POST", "/oidc-providers", json_body=body)
        return _wire.parse_oidc_provider(payload)

    async def update_oidc_provider(
        self,
        name: str,
        *,
        display_name: str,
        issuer: str,
        client_id: str,
        scopes: list[str],
        allow_create_users: bool,
        allow_email_tying: bool,
        trust_email: bool,
        default_group_id: UUID | None,
        enabled: bool,
        client_secret: str | None | Unchanged = UNCHANGED,
    ) -> OidcProvider:
        """PUT /oidc-providers/{name} — full replace, except: `issuer` must equal
        the stored one (422 issuer_immutable), and `client_secret` is
        write-only — UNCHANGED keeps it, a string replaces it, None removes it.
        The icon has its own methods."""
        body: dict[str, object] = {
            "display_name": display_name,
            "issuer": issuer,
            "client_id": client_id,
            "scopes": scopes,
            "allow_create_users": allow_create_users,
            "allow_email_tying": allow_email_tying,
            "trust_email": trust_email,
            "default_group_id": str(default_group_id) if default_group_id is not None else None,
            "enabled": enabled,
        }
        if not isinstance(client_secret, Unchanged):
            body["client_secret"] = client_secret
        payload = await self._send_json("PUT", f"/oidc-providers/{name}", json_body=body)
        return _wire.parse_oidc_provider(payload)

    async def delete_oidc_provider(self, name: str) -> None:
        """DELETE /oidc-providers/{name} — 204. Drops the provider's links and
        keeps its users (see `OidcProvider.linked_users`)."""
        _ = await self._send("DELETE", f"/oidc-providers/{name}")

    async def set_oidc_provider_icon(
        self, name: str, content: bytes, content_type: OidcIconType
    ) -> OidcProvider:
        """PUT /oidc-providers/{name}/icon — the raw image, at most 32 KiB. 422
        invalid_icon when the bytes are not the declared type."""
        payload = await self._send_json(
            "PUT", f"/oidc-providers/{name}/icon", content=(content, content_type)
        )
        return _wire.parse_oidc_provider(payload)

    async def clear_oidc_provider_icon(self, name: str) -> OidcProvider:
        """DELETE /oidc-providers/{name}/icon — back to the monogram; idempotent."""
        payload = await self._send_json("DELETE", f"/oidc-providers/{name}/icon")
        return _wire.parse_oidc_provider(payload)

    # ------------------------------------------------------------------ #
    # Groups (global group:manage)
    # ------------------------------------------------------------------ #

    async def create_group(self, name: str, description: str = "") -> GroupSummary:
        """POST /groups — 201. 409 name_taken."""
        payload = await self._send_json(
            "POST", "/groups", json_body={"name": name, "description": description}
        )
        return _wire.parse_group_summary(payload)

    async def list_groups(self) -> list[GroupSummary]:
        """GET /groups."""
        payload = await self._send_json("GET", "/groups")
        return [_wire.parse_group_summary(v) for v in _wire.as_list(payload, "GroupSummary[]")]

    async def get_group(self, group_id: UUID) -> GroupSummary:
        """GET /groups/{group_id} — 404 group_not_found."""
        return _wire.parse_group_summary(await self._send_json("GET", f"/groups/{group_id}"))

    async def delete_group(self, group_id: UUID) -> None:
        """DELETE /groups/{group_id} — 204. Also deletes the group's bindings;
        members untouched."""
        _ = await self._send("DELETE", f"/groups/{group_id}")

    async def set_group_members(self, group_id: UUID, user_ids: list[UUID]) -> GroupSummary:
        """PUT /groups/{group_id}/members — full replace. 404 group_not_found;
        422 user_not_found."""
        payload = await self._send_json(
            "PUT",
            f"/groups/{group_id}/members",
            json_body={"user_ids": [str(user_id) for user_id in user_ids]},
        )
        return _wire.parse_group_summary(payload)

    async def set_group_roles(self, group_id: UUID, roles: set[str]) -> GroupSummary:
        """PUT /groups/{group_id}/roles — full replace of GLOBAL roles (lab
        grants go through create_grant). 422 non-global-bindable role."""
        payload = await self._send_json(
            "PUT", f"/groups/{group_id}/roles", json_body={"roles": sorted(roles)}
        )
        return _wire.parse_group_summary(payload)

    # ------------------------------------------------------------------ #
    # Catalog / directory (any authenticated user)
    # ------------------------------------------------------------------ #

    async def list_roles(self) -> list[Role]:
        """GET /roles — the code-defined role catalog; never hardcode it."""
        payload = await self._send_json("GET", "/roles")
        return [_wire.parse_role(v) for v in _wire.as_list(payload, "Role[]")]

    async def list_principals(self) -> Principals:
        """GET /principals — id+name of all users/groups, for grantors."""
        return _wire.parse_principals(await self._send_json("GET", "/principals"))

    async def device_catalog(self) -> DeviceCatalog:
        """GET /catalog — the deployable-device catalog (delta 18): the
        supported device set with per-device module support, the default clab
        image, and best-effort image presence (`live` False = presence could
        not be checked). Image presence is advisory — deploy does not
        pre-flight it."""
        return _wire.parse_device_catalog(await self._send_json("GET", "/catalog"))

    # ------------------------------------------------------------------ #
    # Host resources (delta 30)
    # ------------------------------------------------------------------ #

    async def host_resources(self) -> HostResources:
        """GET /host — what the machine running the labs is spending: CPU,
        load, memory, swap and the filesystems the backend can see. Any
        authenticated user may read it. The server samples on a timer, so
        `sampled_at` is the reading's real age."""
        return _wire.parse_host_resources(await self._send_json("GET", "/host"))

    async def docker_usage(self) -> DockerUsage:
        """GET /host/docker — the Docker daemon's counts and disk footprint,
        mirroring `docker system df`. Read through the netlab-runner (the only
        component with the socket) and noticeably slower than `host_resources`,
        since the daemon walks every image and cache record; a runner outage
        raises `docker_usage_unavailable` rather than reporting zeros."""
        return _wire.parse_docker_usage(await self._send_json("GET", "/host/docker"))

    async def lab_usage(self, name: str) -> LabUsage:
        """GET /labs/{name}/usage — what a lab's nodes cost right now
        (`lab:read`). Live-only and best-effort like the link table: an
        undeployed lab or an unreachable upstream comes back `live=False`
        rather than an error, and a node that is not running carries no
        measures at all."""
        return _wire.parse_lab_usage(await self._send_json("GET", f"/labs/{name}/usage"))

    # ------------------------------------------------------------------ #
    # Template library (delta 21)
    # ------------------------------------------------------------------ #

    # Two sibling collections with independent namespaces. Reads are any
    # authenticated user; mutations ride the global-only template:manage.
    # Instantiation has NO verb: compose get_network_template -> create_lab ->
    # update_definition, or stamp a node fragment client-side.

    async def list_network_templates(self) -> list[NetworkTemplateSummary]:
        """GET /templates/network — both tiers, content omitted. A published
        lab's definition is deliberately deployment-public (see
        set_lab_template)."""
        payload = await self._send_json("GET", "/templates/network")
        return [
            _wire.parse_network_template_summary(v)
            for v in _wire.as_list(payload, "NetworkTemplateSummary[]")
        ]

    async def get_network_template(self, name: str) -> NetworkTemplate:
        """GET /templates/network/{name} — the entry with its content. For a
        published-lab entry the content is that lab's CURRENT stored
        definition (a live view, never a stale copy). 404
        template_not_found."""
        payload = await self._send_json("GET", f"/templates/network/{name}")
        return _wire.parse_network_template(payload)

    async def list_node_templates(self) -> list[NodeTemplate]:
        """GET /templates/node — both tiers, FULL entries (fragments are
        small and bounded; the builder palette stamps straight from the
        list)."""
        payload = await self._send_json("GET", "/templates/node")
        return [_wire.parse_node_template(v) for v in _wire.as_list(payload, "NodeTemplate[]")]

    async def get_node_template(self, name: str) -> NodeTemplate:
        """GET /templates/node/{name}. 404 template_not_found."""
        payload = await self._send_json("GET", f"/templates/node/{name}")
        return _wire.parse_node_template(payload)

    async def create_node_template(
        self, name: str, *, description: str, content: str
    ) -> NodeTemplate:
        """POST /templates/node — global template:manage; 201. `content` is a
        YAML node-attribute mapping that MUST name `device`; validation is
        STRUCTURAL only (the receiving lab's PUT stays the real validator).
        409 name_taken; 422 invalid_template."""
        payload = await self._send_json(
            "POST",
            "/templates/node",
            json_body={"name": name, "description": description, "content": content},
        )
        return _wire.parse_node_template(payload)

    async def update_node_template(
        self, name: str, *, description: str, content: str
    ) -> NodeTemplate:
        """PUT /templates/node/{name} — global template:manage. Full REPLACE
        of a USER-tier entry. 409 template_readonly on a builtin."""
        payload = await self._send_json(
            "PUT",
            f"/templates/node/{name}",
            json_body={"description": description, "content": content},
        )
        return _wire.parse_node_template(payload)

    async def delete_node_template(self, name: str) -> None:
        """DELETE /templates/node/{name} — global template:manage; 204. USER
        tier only (409 template_readonly on a builtin). The network
        collection has no delete: the set_lab_template toggle is its user
        tier's whole lifecycle."""
        _ = await self._send("DELETE", f"/templates/node/{name}")

    async def set_lab_template(
        self, name: str, *, published: bool, description: str | None = None
    ) -> NetworkTemplateSummary | None:
        """PUT /labs/{name}/template — the "use as a template" toggle:
        publishes this lab's stored definition into the network collection as
        a LIVE template, or withdraws it. Global template:manage PLUS
        lab:read (404 existence-hiding). `description` is the library-card
        text: REQUIRED when publishing (422), ignored when withdrawing;
        re-publishing just updates it. Returns the entry, None once
        withdrawn. While published the definition is readable by EVERY
        authenticated user; soft-deleting the lab withdraws the entry;
        instantiation COPIES. 409 no_definition on an unauthored lab; 409
        name_taken against a builtin's name."""
        payload = await self._send_json(
            "PUT",
            f"/labs/{name}/template",
            json_body={"published": published, "description": description},
        )
        return None if payload is None else _wire.parse_network_template_summary(payload)

    # ------------------------------------------------------------------ #
    # Definition import (delta 22)
    # ------------------------------------------------------------------ #

    async def import_network(
        self, sources: list[ImportSource], wiring: list[WiringEntry]
    ) -> NetworkImport:
        """POST /import/network — the definition factory: dumped running
        configs + the EXPLICIT wiring in; netlab definition + carry +
        quarantine + maps out. PURE (no lab is touched): compose create_lab
        -> put_custom_config -> update_definition (custom config FIRST — the
        definition PUT validates its `config:` references against the stored
        templates). GLOBAL lab:create.

        `wiring` is REQUIRED (delta 23): adjacency is never inferred. Each
        entry lists "node:interface" endpoints — 2 = p2p, 3+ = LAN,
        all-unaddressed = an L2 link; an addressed interface in no entry
        becomes a stub, and `[]` is legal (a linkless set of stubs).
        suggest_wiring() exists to prefill an editor, never to feed this
        call implicitly. 422 unsupported_device / config_unparseable /
        duplicate_node / netlab_invalid (stderr in extras) / wiring_invalid
        / wiring_conflict (extras carry the offending `entry` index)."""
        payload = await self._send_json(
            "POST",
            "/import/network",
            json_body={
                "sources": [
                    {"device": s.device, "content": s.content, "name": s.name} for s in sources
                ],
                "wiring": wiring,
            },
        )
        return _wire.parse_network_import(payload)

    async def suggest_wiring(self, sources: list[ImportSource]) -> WiringSuggestion:
        """POST /import/wiring-suggestion — the subnet join as ADVICE: a
        proposed wiring list from the sources' addressing, plus warnings for
        what it cannot place (unnumbered interfaces). Pure parse, no netlab
        run; GLOBAL lab:create. The import never consumes a suggestion
        implicitly: review, edit, then pass it to import_network."""
        payload = await self._send_json(
            "POST",
            "/import/wiring-suggestion",
            json_body={
                "sources": [
                    {"device": s.device, "content": s.content, "name": s.name} for s in sources
                ]
            },
        )
        return _wire.parse_wiring_suggestion(payload)

    async def import_node(self, device: str, content: str) -> NodeImport:
        """POST /import/node — the single-node granularity: a stampable
        fragment plus its carry (SOURCE interface names — the contract
        QUIRK; the network flow is the fidelity-complete path). Any
        authenticated user. Same 422 slugs as import_network."""
        payload = await self._send_json(
            "POST", "/import/node", json_body={"device": device, "content": content}
        )
        return _wire.parse_node_import(payload)

    async def config_diff(self, name: str, sources: list[DiffSource]) -> ConfigDiffReport:
        """POST /labs/{name}/config-diff — the import-fidelity proof:
        collects each named node's RUNNING config over the exec transport
        and classifies every comparable source line (matched / missing /
        extra, modulo quarantine and the recomputed interface map).
        lab:validate; requires a deployed lab (409 lab_not_running, 409
        no_definition); 422 unknown_node. Informational, never a gate."""
        payload = await self._send_json(
            "POST",
            f"/labs/{name}/config-diff",
            json_body={
                "sources": [
                    {"node": s.node, "content": s.content, "interface_map": s.interface_map}
                    for s in sources
                ]
            },
        )
        return _wire.parse_config_diff_report(payload)

    # ------------------------------------------------------------------ #
    # Labs — lifecycle: create (record) -> author (PUTs) -> deploy
    # ------------------------------------------------------------------ #

    async def create_lab(self, name: str) -> LabDetail:
        """POST /labs {name} — 201. GLOBAL lab:create; caller becomes owner.

        Record only: allocates the lab's mgmt /24, status "created" — no
        definition yet, nothing deployed. `name` is the lab's durable
        identity and must be a netlab identifier — a leading letter then
        letters/digits/dash/underscore, at most 16 characters — because it is
        pinned into the stored definition as netlab's topology `name:`.
        409 name taken; 422 invalid name; 503 subnet pool exhausted."""
        payload = await self._send_json("POST", "/labs", json_body={"name": name})
        return _wire.parse_lab_detail(payload)

    async def list_labs(self) -> list[LabSummary]:
        """GET /labs — filtered to labs with lab:read (owned, granted, group,
        global). No access = [] — never 403."""
        payload = await self._send_json("GET", "/labs")
        return [_wire.parse_lab_summary(v) for v in _wire.as_list(payload, "LabSummary[]")]

    async def get_lab(self, name: str) -> LabDetail:
        """GET /labs/{name} — lab:read. 404 if absent OR unreadable; 502 on
        clab-api failure other than lab-not-deployed."""
        return _wire.parse_lab_detail(await self._send_json("GET", f"/labs/{name}"))

    async def update_definition(self, name: str, definition: str) -> LabDetail:
        """PUT /labs/{name} — lab:edit. Replaces the STORED definition only
        (applies on next deploy). The definition must name each node's
        `device` and the `provider`; any `name:` in it is overridden by the
        record, and the mgmt subnet is re-pinned (explicit
        `addressing.mgmt.ipv4` wins). Validated by a dry `netlab create`
        (422). 409 subnet clash."""
        payload = await self._send_json(
            "PUT", f"/labs/{name}", json_body={"definition": definition}
        )
        return _wire.parse_lab_detail(payload)

    async def deploy_lab(
        self,
        name: str,
        *,
        configure: bool = False,
        skip_config_time_checks: bool = False,
    ) -> Job:
        """POST /labs/{name}/deploy — lab:edit. **202 + the running deploy
        Job** (terminal `result`: DeployResponse). Deploys from the stored
        definition + suites + custom config: fresh if "created"/"destroyed",
        overwrite-in-place if running.

        Pre-accept (synchronous) errors: 409 no stored definition yet; 409
        `job_in_flight` — ONE running job per lab, any kind. Post-accept
        failures — netlab rejecting the stored definition, clab-api/runner
        unreachable — fail the JOB; a push that ran but failed and a red
        gate stay job successes (see DeployResponse)."""
        payload = await self._send_json(
            "POST",
            f"/labs/{name}/deploy",
            json_body={
                "configure": configure,
                "skip_config_time_checks": skip_config_time_checks,
            },
        )
        return _wire.parse_job(payload)

    async def configure_lab(self, name: str, *, skip_config_time_checks: bool = False) -> Job:
        """POST /labs/{name}/configure — lab:configure. **202 + the running
        configure Job** (result: ConfigureResponse). Pushes config from the
        stored definition, then runs config-time suites unless skipped (the
        automatic run rides lab:configure, not lab:validate — deliberate).
        Pre-accept: 409 no definition; 409 job_in_flight. A push that
        couldn't run fails the job; one that ran-but-failed succeeds with
        result.status="config_failed"."""
        payload = await self._send_json(
            "POST",
            f"/labs/{name}/configure",
            json_body={"skip_config_time_checks": skip_config_time_checks},
        )
        return _wire.parse_job(payload)

    async def destroy_lab(self, name: str, *, remove: bool = False) -> Job:
        """DELETE /labs/{name} — lab:destroy. **202 + the running destroy
        Job** (result: DestroyResponse).

        remove=False: tear down; record -> "destroyed" (redeployable, keeps
        its mgmt-subnet reservation). Requires the lab to be RUNNING — a
        synchronous 409 at submit (404 stays reserved for existence-hiding).
        remove=True: also soft-delete the record and release its mgmt-subnet
        reservation; teardown best-effort, so a down lab is fine. The job
        stays pollable AFTER the soft-delete.
        Pre-accept: 409 lab_not_running (remove=False); 409 job_in_flight."""
        payload = await self._send_json("DELETE", f"/labs/{name}", params={"remove": remove})
        return _wire.parse_job(payload)

    # ------------------------------------------------------------------ #
    # Labs — jobs (async operations)
    # ------------------------------------------------------------------ #

    async def get_job(self, lab_name: str, job_id: UUID) -> JobDetail:
        """GET /labs/{lab_name}/jobs/{job_id} — lab:read. 404 hides both an
        unreadable lab and an unknown job id. Works on a soft-deleted lab
        (a destroy-with-remove job must stay pollable to its terminal
        state).

        The single-job read is the one that carries `steps` (contract delta
        29): what the operation did, growing while it runs, kept after it
        finishes. The listings return plain `Job`."""
        return _wire.parse_job_detail(
            await self._send_json("GET", f"/labs/{lab_name}/jobs/{job_id}")
        )

    async def list_jobs(self, lab_name: str, *, limit: int = 20) -> list[Job]:
        """GET /labs/{lab_name}/jobs?limit= — lab:read, newest first. Recent
        history, not an audit log: finished jobs beyond the newest ~20 per
        lab are pruned."""
        payload = await self._send_json("GET", f"/labs/{lab_name}/jobs", params={"limit": limit})
        return [_wire.parse_job(v) for v in _wire.as_list(payload, "Job[]")]

    async def list_all_jobs(self, *, limit: int = 20) -> list[Job]:
        """GET /jobs?limit= — recent jobs across every lab the caller may read,
        newest first (each `Job` names its `lab_name`). Any authenticated user;
        the readable-lab filter is the events stream's, so an unreadable lab is
        invisible rather than an error. `limit` is 1-200.

        Jobs of REMOVED labs are excluded: a destroy-with-remove job drops out
        of this list when its lab record does, and its terminal state is read
        with `get_job`, which stays readable on a removed lab."""
        payload = await self._send_json("GET", "/jobs", params={"limit": limit})
        return [_wire.parse_job(v) for v in _wire.as_list(payload, "Job[]")]

    async def wait_job(
        self,
        lab_name: str,
        job_id: UUID,
        *,
        timeout: float | None = None,
        poll_interval: float = 2.0,
    ) -> JobDetail:
        """Poll `get_job` until the job is terminal; return the terminal Job —
        a `JobDetail`, so the step log of what just happened comes with it.
        Pure client-side convenience — no wire surface beyond the polling.

        Does NOT raise on a failed job — the caller inspects
        status/result/error. Raises TimeoutError when `timeout` (default:
        the client's `action_timeout`) elapses with the job still running —
        the job keeps running server-side; the caller can resume waiting."""
        deadline = time.monotonic() + (timeout if timeout is not None else self._action_timeout)
        while True:
            job = await self.get_job(lab_name, job_id)
            if job.status != "running":
                return job
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"job {job_id} on lab {lab_name!r} still running after the wait deadline"
                )
            await asyncio.sleep(poll_interval)

    # ------------------------------------------------------------------ #
    # Labs — test suites
    # ------------------------------------------------------------------ #

    async def get_test_suites(self, name: str) -> TestSuitesResponse:
        """GET /labs/{name}/test-suites — lab:read."""
        payload = await self._send_json("GET", f"/labs/{name}/test-suites")
        return _wire.parse_test_suites_response(payload)

    async def facts(self, name: str) -> LabFacts:
        """GET /labs/{name}/facts — lab:read. The per-node fact namespace suite
        templates render against, partitioned into the promised core and
        per-object ``_extras`` (see `LabFacts` for the two tiers and what each
        promises). 409 ``no_definition`` on a bare created record — no
        definition, no facts."""
        payload = await self._send_json("GET", f"/labs/{name}/facts")
        return _wire.parse_lab_facts(payload)

    async def put_test_suites(self, name: str, suites: dict[str, TestSuite]) -> TestSuitesResponse:
        """PUT /labs/{name}/test-suites — lab:edit. Full replace; takes effect
        on the next run. 422 ``template_invalid`` when a Jinja template fails
        to parse — or, when the lab has a definition (facts exist), to
        dry-render (``extras['problems']`` names each suite/test/field)."""
        payload = await self._send_json(
            "PUT",
            f"/labs/{name}/test-suites",
            json_body={"test_suites": _wire.test_suites_to_wire(suites)},
        )
        return _wire.parse_test_suites_response(payload)

    async def run_test_suite(self, name: str, suite: str) -> Job:
        """POST /labs/{name}/test-suites/{suite}/run — lab:validate. **202 +
        the running suite_run Job** (result: SuiteReport — its worst case is
        the sum of every test's `wait`, hence a job). Runs one suite (any
        stage); persists as its last run but NEVER moves the config-time
        gate. Pre-accept: 404 unknown suite; 409 job_in_flight."""
        payload = await self._send_json("POST", f"/labs/{name}/test-suites/{suite}/run")
        return _wire.parse_job(payload)

    async def dry_run_test_case(
        self, name: str, node: str, run: TestCaseDraft
    ) -> TestCaseDryRunResult:
        """POST /labs/{name}/test-suites/dry-run — lab:validate. Run ONE
        unsaved case on ONE node and get back what it did: the rendered and
        adapted command, the stdout, and — when the draft declared `parse` —
        the parsed structure a `compare` has to be written against.

        **Synchronous**, unlike `run_test_suite`. A suite run is a job because
        its worst case is the sum of every test's `wait`; a draft has no
        `wait` at all, so this is one exec. Staying sync also keeps it usable
        WHILE a job holds the per-lab mutex — an authoring aid that 409s
        because someone else is deploying is not an aid.

        Writes nothing: no last_validation, no config-time gate, no job row.

        lab:validate rather than lab:edit, because it EXECUTES on a node. It
        grants nothing new — `run_test_suite` already runs arbitrary commands
        under that permission; this aims it at a case that is not stored yet.

        409 ``no_definition`` / ``lab_not_running``; 422 ``unknown_node`` and
        ``invalid_case`` (a template that will not render, a `cli` case on a
        device whose CatalogDevice.cli_mode is False); 502 ``exec_failed``
        when the command could not be run at all. A command that RAN and
        whose output would not parse is a success carrying ``parse_error``."""
        payload = await self._send_json(
            "POST",
            f"/labs/{name}/test-suites/dry-run",
            json_body={"node": node, "run": _wire.test_case_draft_to_wire(run)},
        )
        return _wire.parse_test_case_dry_run_result(payload)

    # ------------------------------------------------------------------ #
    # Labs — custom config
    # ------------------------------------------------------------------ #

    async def get_custom_config(self, name: str) -> CustomConfigResponse:
        """GET /labs/{name}/custom-config — lab:read."""
        payload = await self._send_json("GET", f"/labs/{name}/custom-config")
        return _wire.parse_custom_config_response(payload)

    async def put_custom_config(
        self, name: str, templates: list[ConfigTemplateSpec]
    ) -> CustomConfigResponse:
        """PUT /labs/{name}/custom-config — lab:edit. Full replace of the USER
        tier (delta 27). 409 ``builtin_template_shadowed`` if a name equals a
        built-in's; 422 on shape violations (duplicate names or scope keys,
        both device+node set, a non-catalog device). Applies on the next
        configure/deploy."""
        payload = await self._send_json(
            "PUT",
            f"/labs/{name}/custom-config",
            json_body={
                "templates": [_wire.config_template_spec_to_wire(spec) for spec in templates]
            },
        )
        return _wire.parse_custom_config_response(payload)

    # ------------------------------------------------------------------ #
    # Labs — topology layout (delta 19)
    # ------------------------------------------------------------------ #

    async def get_layout(self, name: str) -> LabLayout:
        """GET /labs/{name}/layout — lab:read. The shared manual arrangement;
        empty positions when none was ever saved. Deliberately NOT 409-gated
        on a definition (unlike links/facts): an empty layout is honest, not
        a lie."""
        payload = await self._send_json("GET", f"/labs/{name}/layout")
        return _wire.parse_lab_layout(payload)

    async def put_layout(
        self,
        name: str,
        positions: dict[str, LayoutPosition],
        groups: dict[str, LayoutGroupStyle] | None = None,
    ) -> LabLayout:
        """PUT /labs/{name}/layout — lab:edit. Full REPLACE of the whole
        layout resource — positions AND group styles (delta 20); {} clears,
        no separate DELETE, and omitting `groups` clears any stored styles.
        lab:edit because the shared layout is authoring: only the Build tab
        edits topology or arrangement, read/operate-only canvases never
        write this. Colors are server-pinned to "#rrggbb" (422 otherwise)."""
        payload = await self._send_json(
            "PUT",
            f"/labs/{name}/layout",
            json_body={
                "positions": {key: {"x": pos.x, "y": pos.y} for key, pos in positions.items()},
                "groups": {key: {"color": style.color} for key, style in (groups or {}).items()},
            },
        )
        return _wire.parse_lab_layout(payload)

    # ------------------------------------------------------------------ #
    # Labs — runtime control & observability (live clab-api state)
    # ------------------------------------------------------------------ #

    async def lab_power(self, name: str, action: LabPowerAction) -> LabActionResponse:
        """POST /labs/{name}/{action} — lab:configure. pause/unpause fan out
        per node (non-atomic; see LabPowerAction)."""
        payload = await self._send_json("POST", f"/labs/{name}/{action}", long=True)
        return _wire.parse_lab_action_response(payload)

    async def node_power(self, name: str, node: str, action: NodePowerAction) -> LabActionResponse:
        """POST /labs/{name}/nodes/{node}/{action} — lab:configure."""
        payload = await self._send_json("POST", f"/labs/{name}/nodes/{node}/{action}", long=True)
        return _wire.parse_lab_action_response(payload)

    async def save_config(self, name: str) -> SaveConfigResponse:
        """POST /labs/{name}/save — lab:configure. containerlab save."""
        payload = await self._send_json("POST", f"/labs/{name}/save", long=True)
        return _wire.parse_save_config_response(payload)

    async def node_logs(self, name: str, node: str, *, tail: int = 200) -> NodeLogsResponse:
        """GET /labs/{name}/nodes/{node}/logs?tail= — lab:read. Container
        logs, not NOS syslog."""
        payload = await self._send_json(
            "GET", f"/labs/{name}/nodes/{node}/logs", params={"tail": tail}
        )
        return _wire.parse_node_logs_response(payload)

    async def interfaces(self, name: str, *, node: str | None = None) -> list[NodeInterfaces]:
        """GET /labs/{name}/interfaces[?node=] — lab:read. Keyed by SHORT node
        name."""
        params: dict[str, str | int | bool] | None = None if node is None else {"node": node}
        payload = await self._send_json("GET", f"/labs/{name}/interfaces", params=params)
        return [_wire.parse_node_interfaces(v) for v in _wire.as_list(payload, "NodeInterfaces[]")]

    async def links(self, name: str) -> LabLinks:
        """GET /labs/{name}/links — the lab's logical link table with derived
        oper state and per-endpoint active impairment (delta 14). lab:read.
        409 `no_definition` on a bare created record. Works on any authored
        lab: undeployed labs return the full table with every oper_state
        "unknown" and live=False."""
        payload = await self._send_json("GET", f"/labs/{name}/links")
        return _wire.parse_lab_links(payload)

    async def show_netem(self, name: str, node: str) -> list[NetemImpairment]:
        """GET /labs/{name}/nodes/{node}/netem — lab:read. Lists only the
        interfaces with ACTIVE impairment; a cleared interface is absent, not
        zeroed."""
        payload = await self._send_json("GET", f"/labs/{name}/nodes/{node}/netem")
        return [
            _wire.parse_netem_impairment(v) for v in _wire.as_list(payload, "NetemImpairment[]")
        ]

    async def set_netem(self, name: str, action: NetemAction) -> LabActionResponse:
        """POST /labs/{name}/nodes/{node}/netem — lab:configure. REPLACE
        semantics: the call states the interface's COMPLETE desired impairment
        — an omitted/None dimension is cleared, and a call with no impairments
        clears everything. jitter requires delay; loss/corruption 0-100 %,
        rate kbit/s.

        Takes THE impairment spelling (delta 24): the same NetemAction applies
        standalone here or batched in `apply_actions`. `action.node` becomes
        the path segment, the rest the body. Failure here is an HTTP error
        (TwinlabApiError) — the fail-loudly semantics a batch item trades for
        per-item reporting."""
        payload = await self._send_json(
            "POST",
            f"/labs/{name}/nodes/{action.node}/netem",
            json_body=_wire.netem_body_to_wire(action),
        )
        return _wire.parse_lab_action_response(payload)

    async def apply_actions(
        self, name: str, actions: list[NetemAction | PowerAction]
    ) -> RuntimeActionsReport:
        """POST /labs/{name}/actions — lab:configure (delta 24). Many netem
        sets/clears and node power events in ONE request, executed
        SEQUENTIALLY in list order, continuing past failures; the report is
        index-aligned per-item outcomes.

        NOT a transaction: no rollback, no isolation against concurrent single
        verbs. At most 64 items. A structurally invalid item (jitter without
        delay, an out-of-range percentage, an empty or over-long list) is a 422
        with NOTHING executed; live failures (unknown node, netem on a stopped
        container) land on the item's result, never on the HTTP status. Sync —
        usable while a job runs, exactly like the single verbs it mirrors."""
        payload = await self._send_json(
            "POST",
            f"/labs/{name}/actions",
            json_body={
                "actions": [
                    _wire.netem_action_to_wire(action)
                    if isinstance(action, NetemAction)
                    else _wire.power_action_to_wire(action)
                    for action in actions
                ]
            },
        )
        return _wire.parse_runtime_actions_report(payload)

    # ------------------------------------------------------------------ #
    # Labs — grants & ownership (lab:grant on the lab)
    # ------------------------------------------------------------------ #

    async def list_grants(self, name: str) -> list[Grant]:
        """GET /labs/{name}/grants."""
        payload = await self._send_json("GET", f"/labs/{name}/grants")
        return [_wire.parse_grant(v) for v in _wire.as_list(payload, "Grant[]")]

    async def create_grant(
        self,
        name: str,
        principal_type: Literal["user", "group"],
        principal_id: UUID,
        role: str,
    ) -> Grant:
        """POST /labs/{name}/grants — 201. 422 unless the role is
        lab-bindable; 403 anti-escalation (role's permissions must be ⊆ the
        caller's on this lab). Duplicates are idempotent."""
        payload = await self._send_json(
            "POST",
            f"/labs/{name}/grants",
            json_body={
                "principal_type": principal_type,
                "principal_id": str(principal_id),
                "role": role,
            },
        )
        return _wire.parse_grant(payload)

    async def delete_grant(self, name: str, binding_id: UUID) -> None:
        """DELETE /labs/{name}/grants/{binding_id} — 204. 404 if absent or on
        another lab."""
        _ = await self._send("DELETE", f"/labs/{name}/grants/{binding_id}")

    async def transfer_owner(self, name: str, user_id: UUID) -> LabOwner:
        """PUT /labs/{name}/owner. Requires owner-EQUIVALENCE (the full owner
        permission set on the lab), else 403. 404 unknown user."""
        payload = await self._send_json(
            "PUT", f"/labs/{name}/owner", json_body={"user_id": str(user_id)}
        )
        return _wire.parse_lab_owner(payload)

    # ------------------------------------------------------------------ #
    # Streams
    # ------------------------------------------------------------------ #

    def events(self) -> AsyncGenerator[LabEvent | JobEvent]:
        """GET /events (SSE) — any authenticated user; filtered to readable
        labs (set refreshes ~30 s, so a mid-stream grant lags up to that).
        Iterate with `async for`; keepalives are consumed, not yielded.

        Two payloads, discriminated by the SSE event NAME and yielded as a
        union (match with `isinstance`):

          ``lab`` -> LabEvent   container lifecycle, relayed from
                                containerlab. A configure or suite-run job
                                touches no container, so it emits none.
          ``job`` -> JobEvent   a job was submitted or reached a terminal
                                state.

        NOT a durable log: the stream has no replay, so a reconnect silently
        misses whatever happened while it was down. A caller that must not
        miss a completion still reads the record — `wait_job` polls for
        exactly this reason.

        When abandoning the stream early, close it deterministically (e.g.
        `contextlib.aclosing`) so the underlying connection is released."""
        return self._event_stream()

    async def _event_stream(self) -> AsyncGenerator[LabEvent | JobEvent]:
        # No read timeout: the stream idles between events (keepalive comments
        # keep the connection alive, not the read clock).
        timeout = httpx2.Timeout(self._timeout, read=None)
        async with self._http.stream("GET", "/events", timeout=timeout) as response:
            if response.is_error:
                _ = await response.aread()
                raise error_from_response(response)
            data_lines: list[str] = []
            name = ""
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif line == "" and data_lines:
                    payload_text = "\n".join(data_lines)
                    data_lines = []
                    event_name, name = name, ""
                    try:
                        payload: object = json.loads(payload_text)
                    except ValueError as exc:
                        raise TwinlabProtocolError(
                            "/events", f"non-JSON event: {payload_text[:80]!r}"
                        ) from exc
                    match event_name:
                        case "lab":
                            yield _wire.parse_lab_event(payload)
                        case "job":
                            yield _wire.parse_job_event(payload)
                        case _:
                            # An event we have no shape for: skip it rather
                            # than fail the stream, so the server can add one
                            # without breaking older clients.
                            continue
                # comments (": keepalive") and other SSE fields are consumed

    def terminal(
        self,
        name: str,
        node: str,
        *,
        protocol: TerminalProtocol = "ssh",
        cols: int = 80,
        rows: int = 24,
        ssh_username: str | None = None,
    ) -> TerminalSession:
        """Open the node terminal WS (lab:terminal) — ``async with
        client.terminal(...) as term``. `ssh_username`: the server defaults to
        "admin" (wrong for e.g. VyOS); ignored for protocol="shell"."""
        query: dict[str, str] = {"protocol": protocol, "cols": str(cols), "rows": str(rows)}
        if ssh_username is not None:
            query["ssh_username"] = ssh_username
        ws_origin = "ws" + self._origin.removeprefix("http")
        url = f"{ws_origin}{self._subpath}/labs/{name}/nodes/{node}/terminal?{urlencode(query)}"
        return TerminalSession(url, self._ws_headers())
