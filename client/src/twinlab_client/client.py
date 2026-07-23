"""The Twinlab API client.

Implements the v1.0 target contract (`docs/twinlab_client_shape.py` in the
Twinlab repository): every method is a coroutine, every wire shape a frozen
dataclass, every non-2xx a `TwinlabApiError`.

Conventions carried by every method (not repeated per docstring):

- Lab-guarded routes return **404** when the caller can't read the lab
  (existence hidden) and **403** when readable but lacking the permission.
- Names (lab/node/suite) match ``^[A-Za-z0-9][A-Za-z0-9_.-]*$``, max 64.
"""

import json
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Literal
from urllib.parse import urlencode
from uuid import UUID

import httpx

from twinlab_client import _wire
from twinlab_client._terminal import TerminalSession
from twinlab_client.errors import TwinlabProtocolError, error_from_response
from twinlab_client.models import (
    ApiKey,
    ApiKeyCreated,
    ConfigureResponse,
    CustomConfigResponse,
    DeployResponse,
    DestroyResponse,
    Duration,
    Grant,
    GroupSummary,
    LabActionResponse,
    LabDetail,
    LabEvent,
    LabOwner,
    LabPowerAction,
    LabSummary,
    Liveness,
    NetemImpairment,
    NodeInterfaces,
    NodeLogsResponse,
    NodePowerAction,
    Principals,
    Readiness,
    Role,
    SaveConfigResponse,
    SuiteReport,
    TerminalProtocol,
    TestSuite,
    TestSuitesResponse,
    UserInfo,
    UserSummary,
)


class TwinlabClient(AbstractAsyncContextManager["TwinlabClient"]):
    """Async Twinlab API client. One instance = one session (cookie jar on the
    instance); use as ``async with TwinlabClient(...) as client``.

    Deploy/configure are synchronous long calls server-side (minutes on some
    NOSes) — hence the separate ``action_timeout``.
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
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """`base_url` = backend origin (e.g. "http://localhost:8000");
        `subpath` is appended to it. `api_key` authenticates every request as
        `Authorization: Bearer <key>` instead of a login session.
        `action_timeout` covers deploy/configure/destroy and suite runs.
        `transport` is a testing seam (httpx.MockTransport)."""
        if not base_url.startswith(("http://", "https://")):
            raise ValueError(f"base_url must be an http(s) origin, got {base_url!r}")
        self._origin = base_url.rstrip("/")
        self._subpath = "/" + subpath.strip("/") if subpath.strip("/") else ""
        self._api_key = api_key
        self._timeout = timeout
        self._action_timeout = action_timeout
        headers = {"Authorization": f"Bearer {api_key}"} if api_key is not None else {}
        self._http = httpx.AsyncClient(
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
    ) -> httpx.Response:
        if long:
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
    ) -> object:
        response = await self._send(method, path, json_body=json_body, params=params, long=long)
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

    # ------------------------------------------------------------------ #
    # Users (global user:manage)
    # ------------------------------------------------------------------ #

    async def create_user(
        self, username: str, password: str, roles: set[str] | None = None
    ) -> UserSummary:
        """POST /users — 201. `roles` = GLOBAL roles. 409 username_taken;
        422 unknown_roles; password min 8."""
        body: dict[str, object] = {"username": username, "password": password}
        if roles is not None:
            body["roles"] = sorted(roles)
        return _wire.parse_user_summary(await self._send_json("POST", "/users", json_body=body))

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

    # ------------------------------------------------------------------ #
    # Labs — lifecycle: create (record) -> author (PUTs) -> deploy
    # ------------------------------------------------------------------ #

    async def create_lab(self, name: str) -> LabDetail:
        """POST /labs {name} — 201. GLOBAL lab:create; caller becomes owner.

        Record only: allocates the lab's mgmt /24, status "created" — no
        definition yet, nothing deployed. `name` is the lab's durable
        identity. 409 name taken; 503 subnet pool exhausted."""
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
    ) -> DeployResponse:
        """POST /labs/{name}/deploy — lab:edit. Deploys from the stored
        definition + suites + custom config: fresh if "created"/"destroyed",
        overwrite-in-place if running. Long call — waits for NOS readiness
        even without `configure`.

        Errors: 409 no stored definition yet; 409 a deploy of this lab is
        already in flight (the deploying-status mutex); 422 netlab rejects the
        stored definition; 502 clab-api/runner failure. A push or gate failure
        after a successful deploy is a 2xx (see DeployResponse)."""
        payload = await self._send_json(
            "POST",
            f"/labs/{name}/deploy",
            json_body={
                "configure": configure,
                "skip_config_time_checks": skip_config_time_checks,
            },
            long=True,
        )
        return _wire.parse_deploy_response(payload)

    async def configure_lab(
        self, name: str, *, skip_config_time_checks: bool = False
    ) -> ConfigureResponse:
        """POST /labs/{name}/configure — lab:configure. Pushes config from the
        stored definition, then runs config-time suites unless skipped (the
        automatic run rides lab:configure, not lab:validate — deliberate).
        422 bad definition; 502 runner failure (nothing ran)."""
        payload = await self._send_json(
            "POST",
            f"/labs/{name}/configure",
            json_body={"skip_config_time_checks": skip_config_time_checks},
            long=True,
        )
        return _wire.parse_configure_response(payload)

    async def destroy_lab(self, name: str, *, remove: bool = False) -> DestroyResponse:
        """DELETE /labs/{name} — lab:destroy.

        remove=False: tear down; record -> "destroyed" (redeployable);
        requires the lab to be RUNNING — 404 if already down.
        remove=True: also soft-delete the record; teardown best-effort, so a
        down lab is fine."""
        payload = await self._send_json(
            "DELETE", f"/labs/{name}", params={"remove": remove}, long=True
        )
        return _wire.parse_destroy_response(payload)

    # ------------------------------------------------------------------ #
    # Labs — test suites
    # ------------------------------------------------------------------ #

    async def get_test_suites(self, name: str) -> TestSuitesResponse:
        """GET /labs/{name}/test-suites — lab:read."""
        payload = await self._send_json("GET", f"/labs/{name}/test-suites")
        return _wire.parse_test_suites_response(payload)

    async def put_test_suites(self, name: str, suites: dict[str, TestSuite]) -> TestSuitesResponse:
        """PUT /labs/{name}/test-suites — lab:edit. Full replace; takes effect
        on the next run."""
        payload = await self._send_json(
            "PUT",
            f"/labs/{name}/test-suites",
            json_body={"test_suites": _wire.test_suites_to_wire(suites)},
        )
        return _wire.parse_test_suites_response(payload)

    async def run_test_suite(self, name: str, suite: str) -> SuiteReport:
        """POST /labs/{name}/test-suites/{suite}/run — lab:validate. Runs one
        suite (any stage); persists as its last run but NEVER moves the
        config-time gate. 404 unknown suite. Long call (per-test `wait`)."""
        payload = await self._send_json("POST", f"/labs/{name}/test-suites/{suite}/run", long=True)
        return _wire.parse_suite_report(payload)

    # ------------------------------------------------------------------ #
    # Labs — custom config
    # ------------------------------------------------------------------ #

    async def get_custom_config(self, name: str) -> CustomConfigResponse:
        """GET /labs/{name}/custom-config — lab:read."""
        payload = await self._send_json("GET", f"/labs/{name}/custom-config")
        return _wire.parse_custom_config_response(payload)

    async def put_custom_config(self, name: str, fileset: dict[str, str]) -> CustomConfigResponse:
        """PUT /labs/{name}/custom-config — lab:edit. Full replace of the USER
        fileset. 409 if a path shadows a built-in. Applies on the next
        configure/deploy."""
        payload = await self._send_json(
            "PUT", f"/labs/{name}/custom-config", json_body={"custom_config": fileset}
        )
        return _wire.parse_custom_config_response(payload)

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

    async def show_netem(self, name: str, node: str) -> list[NetemImpairment]:
        """GET /labs/{name}/nodes/{node}/netem — lab:read."""
        payload = await self._send_json("GET", f"/labs/{name}/nodes/{node}/netem")
        return [
            _wire.parse_netem_impairment(v) for v in _wire.as_list(payload, "NetemImpairment[]")
        ]

    async def set_netem(
        self,
        name: str,
        node: str,
        interface: str,
        *,
        delay: Duration | None = None,
        jitter: Duration | None = None,
        loss: float | None = None,
        rate: int | None = None,
        corruption: float | None = None,
    ) -> LabActionResponse:
        """POST /labs/{name}/nodes/{node}/netem — lab:configure. REPLACE
        semantics: the call states the interface's COMPLETE desired impairment
        — an omitted/None dimension is cleared, and a call with no impairments
        clears everything. jitter requires delay; loss/corruption 0-100 %,
        rate kbit/s."""
        payload = await self._send_json(
            "POST",
            f"/labs/{name}/nodes/{node}/netem",
            json_body={
                "interface": interface,
                "delay": _wire.duration_to_wire(delay),
                "jitter": _wire.duration_to_wire(jitter),
                "loss": loss,
                "rate": rate,
                "corruption": corruption,
            },
        )
        return _wire.parse_lab_action_response(payload)

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

    def events(self) -> AsyncIterator[LabEvent]:
        """GET /events (SSE) — any authenticated user; filtered to readable
        labs (set refreshes ~30 s, so a mid-stream grant lags up to that).
        Iterate with `async for`; keepalives are consumed, not yielded. Useful
        for awaiting deploy/destroy side effects instead of polling."""
        return self._event_stream()

    async def _event_stream(self) -> AsyncIterator[LabEvent]:
        # No read timeout: the stream idles between events (keepalive comments
        # keep the connection alive, not the read clock).
        timeout = httpx.Timeout(self._timeout, read=None)
        async with self._http.stream("GET", "/events", timeout=timeout) as response:
            if response.is_error:
                _ = await response.aread()
                raise error_from_response(response)
            data_lines: list[str] = []
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif line == "" and data_lines:
                    payload_text = "\n".join(data_lines)
                    data_lines = []
                    try:
                        payload: object = json.loads(payload_text)
                    except ValueError as exc:
                        raise TwinlabProtocolError(
                            "/events", f"non-JSON event: {payload_text[:80]!r}"
                        ) from exc
                    yield _wire.parse_lab_event(payload)
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
