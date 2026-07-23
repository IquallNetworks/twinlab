"""Client for the containerlab API server (github.com/srl-labs/clab-api-server).

The server authenticates a host (PAM) user via `POST /login`, returns a JWT, and
exposes lab lifecycle operations under `/api/v1`. Deploy accepts the topology
inline as `topologyContent`, so the netlab-generated YAML flows straight through
— no shared volume with the server is needed. Config push is not done here; it
lives in the netlab-runner sidecar.

httpx is a third-party boundary: its exceptions and the server's untyped JSON are
translated here into typed results; nothing propagates as an exception.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus

import httpx
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from twinlab_backend.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class ClabApiError:
    message: str
    status_code: int | None


@dataclass(frozen=True, slots=True)
class NodeInfo:
    """A deployed lab node. `node_name` is netlab's short name (e.g. `r1`);
    `container_name` is what the exec `nodeFilter` needs (`clab-<lab>-r1`).
    `ipv4_address` is the node's management address as clab reports it (CIDR,
    e.g. `192.168.121.101/24`); empty for a node with no mgmt interface."""

    node_name: str
    container_name: str
    image: str
    state: str
    ipv4_address: str


@dataclass(frozen=True, slots=True)
class DeployedLab:
    name: str
    nodes: tuple[NodeInfo, ...]


@dataclass(frozen=True, slots=True)
class NodeLogs:
    container_name: str
    logs: str


@dataclass(frozen=True, slots=True)
class InterfaceInfo:
    name: str
    alias: str
    ifindex: int
    mac: str
    mtu: int
    state: str
    kind: str  # clab-api's `type`; renamed to avoid shadowing the builtin


@dataclass(frozen=True, slots=True)
class NodeInterfaces:
    node_name: str
    interfaces: tuple[InterfaceInfo, ...]


@dataclass(frozen=True, slots=True)
class SaveResult:
    message: str
    output: str


# clab-api runs lab operations synchronously: deploy/destroy block until the lab
# is fully up/down, which for several nodes can take minutes — well past the
# client's default timeout.
_LAB_OP_TIMEOUT_SECONDS = 600.0


class _LoginResponse(BaseModel):
    token: str


class _ClabNode(BaseModel):
    # clab-api emits camelCase / kebab keys; map them to our snake_case fields.
    node_name: str = Field(alias="nodeName")
    container_name: str = Field(alias="name")
    image: str
    state: str
    # clab reports the mgmt address here (already snake_case) as CIDR. Default ""
    # because a node may have no mgmt interface, or a node lacks the key entirely;
    # a missing mgmt IP is a display concern, not a parse failure.
    ipv4_address: str = ""


# The deploy and list responses are keyed by lab name -> node list; inspect
# answers with a bare node array for the one lab.
_NodesByLab = TypeAdapter(dict[str, list[_ClabNode]])
_NodeList = TypeAdapter(list[_ClabNode])


class _MessageResponse(BaseModel):
    # Node/lab lifecycle actions answer with a single human-readable message.
    message: str


class _LogsResponse(BaseModel):
    container_name: str = Field(alias="containerName")
    logs: str


class _SaveResponse(BaseModel):
    message: str
    output: str


class _InterfaceInfo(BaseModel):
    name: str
    alias: str
    ifindex: int
    mac: str
    mtu: int
    state: str
    kind: str = Field(alias="type")


class _NodeInterfaces(BaseModel):
    node_name: str = Field(alias="name")
    interfaces: list[_InterfaceInfo]


_NodeInterfacesList = TypeAdapter(list[_NodeInterfaces])


def _to_node_info(node: _ClabNode) -> NodeInfo:
    return NodeInfo(
        node_name=node.node_name,
        container_name=node.container_name,
        image=node.image,
        state=node.state,
        ipv4_address=node.ipv4_address,
    )


def _to_node_interfaces(node: _NodeInterfaces) -> NodeInterfaces:
    return NodeInterfaces(
        node_name=node.node_name,
        interfaces=tuple(
            InterfaceInfo(
                name=i.name,
                alias=i.alias,
                ifindex=i.ifindex,
                mac=i.mac,
                mtu=i.mtu,
                state=i.state,
                kind=i.kind,
            )
            for i in node.interfaces
        ),
    )


@dataclass(frozen=True, slots=True)
class ClabApiClient:
    """Stateless client; a JWT is fetched per operation via `_login`. `client`
    is injected so its lifecycle (and TLS/verify policy) is owned by the app."""

    client: httpx.AsyncClient
    base_url: str
    username: str
    password: str

    async def _login(self) -> Result[str, ClabApiError]:
        try:
            resp = await self.client.post(
                f"{self.base_url}/login",
                json={"username": self.username, "password": self.password},
            )
        except httpx.HTTPError as exc:
            return Err(ClabApiError(f"login request failed: {exc}", None))

        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"login rejected: {resp.text}", resp.status_code))

        try:
            parsed = _LoginResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(ClabApiError(f"unexpected login response: {exc}", resp.status_code))
        return Ok(parsed.token)

    async def _authed(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | bool] | None = None,
        json: object | None = None,
        timeout: float | None = None,
    ) -> Result[httpx.Response, ClabApiError]:
        """Log in, then send one authenticated request to `path`. Returns the raw
        response for the caller to status-check and parse; only transport failures
        are turned into errors here. `timeout=None` uses the client default (not
        httpx's "disable timeout")."""
        auth = await self._login()
        if isinstance(auth, Err):
            return auth
        timeout_arg = httpx.USE_CLIENT_DEFAULT if timeout is None else timeout
        try:
            resp = await self.client.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {auth.value}"},
                timeout=timeout_arg,
            )
        except httpx.HTTPError as exc:
            return Err(ClabApiError(f"{method} {path} failed: {exc}", None))
        return Ok(resp)

    async def deploy(
        self, topology: Mapping[str, object], *, reconfigure: bool = False
    ) -> Result[DeployedLab, ClabApiError]:
        """Deploy a containerlab topology. The server expects the topology as a
        JSON object under `topologyContent` and answers with a `{lab: [nodes]}`
        map; we return the lab name and its nodes so a follow-on config push can
        target each container. `reconfigure=True` allows overwriting a lab of the
        same name the caller already owns — this is how a redeploy rebuilds a
        running lab from a (possibly edited) definition."""
        sent = await self._authed(
            "POST",
            "/api/v1/labs",
            params={"reconfigure": True} if reconfigure else None,
            json={"topologyContent": topology},
            timeout=_LAB_OP_TIMEOUT_SECONDS,
        )
        if isinstance(sent, Err):
            return sent
        resp = sent.value

        if resp.status_code not in (HTTPStatus.OK, HTTPStatus.CREATED):
            return Err(ClabApiError(f"deploy rejected: {resp.text}", resp.status_code))

        try:
            by_lab = _NodesByLab.validate_json(resp.content)
        except ValidationError as exc:
            return Err(ClabApiError(f"unexpected deploy response: {exc}", resp.status_code))
        if len(by_lab) != 1:
            return Err(ClabApiError(f"deploy response named {len(by_lab)} labs, expected 1", None))
        name, nodes = next(iter(by_lab.items()))
        return Ok(DeployedLab(name=name, nodes=tuple(_to_node_info(n) for n in nodes)))

    async def destroy(self, lab_name: str) -> Result[str, ClabApiError]:
        """Destroy a lab by name (DELETE /api/v1/labs/{labName}). `cleanup=true`
        also removes the lab's on-disk artifacts. `lab_name` is validated at the
        HTTP boundary before it reaches here."""
        sent = await self._authed(
            "DELETE",
            f"/api/v1/labs/{lab_name}",
            params={"cleanup": True},
            timeout=_LAB_OP_TIMEOUT_SECONDS,
        )
        if isinstance(sent, Err):
            return sent
        resp = sent.value

        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"destroy rejected: {resp.text}", resp.status_code))
        return Ok(resp.text)

    async def list_labs(self) -> Result[dict[str, tuple[NodeInfo, ...]], ClabApiError]:
        """List running labs the clab-api user owns (GET /api/v1/labs) as a
        `{lab_name: nodes}` map. Used to enrich our stored records with live node
        state; a lab absent from the map simply has no running nodes."""
        sent = await self._authed("GET", "/api/v1/labs")
        if isinstance(sent, Err):
            return sent
        resp = sent.value

        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"list rejected: {resp.text}", resp.status_code))

        try:
            by_lab = _NodesByLab.validate_json(resp.content)
        except ValidationError as exc:
            return Err(ClabApiError(f"unexpected list response: {exc}", resp.status_code))
        return Ok({name: tuple(_to_node_info(n) for n in nodes) for name, nodes in by_lab.items()})

    async def inspect(self, lab_name: str) -> Result[tuple[NodeInfo, ...], ClabApiError]:
        """Inspect one lab's containers (GET /api/v1/labs/{labName}); the response
        is a bare node array. A 404 (lab not currently deployed) carries its
        status so the caller can distinguish it from an upstream failure."""
        sent = await self._authed("GET", f"/api/v1/labs/{lab_name}")
        if isinstance(sent, Err):
            return sent
        resp = sent.value

        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"inspect rejected: {resp.text}", resp.status_code))

        try:
            nodes = _NodeList.validate_json(resp.content)
        except ValidationError as exc:
            return Err(ClabApiError(f"unexpected inspect response: {exc}", resp.status_code))
        return Ok(tuple(_to_node_info(n) for n in nodes))

    @staticmethod
    def _parse_message(
        sent: Result[httpx.Response, ClabApiError], op: str
    ) -> Result[str, ClabApiError]:
        """Status-check a lifecycle response and lift its `message` field. Shared
        by the node/lab start/stop/restart actions, which all answer the same."""
        if isinstance(sent, Err):
            return sent
        resp = sent.value
        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"{op} rejected: {resp.text}", resp.status_code))
        try:
            parsed = _MessageResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(ClabApiError(f"unexpected {op} response: {exc}", resp.status_code))
        return Ok(parsed.message)

    async def node_action(
        self, lab_name: str, node_name: str, action: str
    ) -> Result[str, ClabApiError]:
        """Start/stop/restart a single node (POST .../nodes/{node}/{action}).
        `action` is constrained to that set at the HTTP boundary before it
        reaches here."""
        sent = await self._authed(
            "POST",
            f"/api/v1/labs/{lab_name}/nodes/{node_name}/{action}",
            timeout=_LAB_OP_TIMEOUT_SECONDS,
        )
        return self._parse_message(sent, f"node {action}")

    async def lab_action(self, lab_name: str, action: str) -> Result[str, ClabApiError]:
        """Start/stop/restart every node in a lab (POST .../labs/{lab}/{action}).
        The streaming variants are not used; this waits for the action to finish."""
        sent = await self._authed(
            "POST",
            f"/api/v1/labs/{lab_name}/{action}",
            timeout=_LAB_OP_TIMEOUT_SECONDS,
        )
        return self._parse_message(sent, f"lab {action}")

    async def node_logs(
        self, lab_name: str, node_name: str, tail: str = "all"
    ) -> Result[NodeLogs, ClabApiError]:
        """Fetch a node's container logs (GET .../nodes/{node}/logs). `tail` is the
        number of trailing lines, or "all". The `follow` (stream) mode is not used."""
        sent = await self._authed(
            "GET",
            f"/api/v1/labs/{lab_name}/nodes/{node_name}/logs",
            params={"tail": tail},
        )
        if isinstance(sent, Err):
            return sent
        resp = sent.value
        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"logs rejected: {resp.text}", resp.status_code))
        try:
            parsed = _LogsResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(ClabApiError(f"unexpected logs response: {exc}", resp.status_code))
        return Ok(NodeLogs(container_name=parsed.container_name, logs=parsed.logs))

    async def interfaces(
        self, lab_name: str, node: str | None = None
    ) -> Result[tuple[NodeInterfaces, ...], ClabApiError]:
        """List each node's interfaces (GET .../interfaces), optionally filtered to
        one `node`. The response is an array of per-node interface lists."""
        sent = await self._authed(
            "GET",
            f"/api/v1/labs/{lab_name}/interfaces",
            params={"node": node} if node is not None else None,
        )
        if isinstance(sent, Err):
            return sent
        resp = sent.value
        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"interfaces rejected: {resp.text}", resp.status_code))
        try:
            parsed = _NodeInterfacesList.validate_json(resp.content)
        except ValidationError as exc:
            return Err(ClabApiError(f"unexpected interfaces response: {exc}", resp.status_code))
        return Ok(tuple(_to_node_interfaces(n) for n in parsed))

    async def save_config(
        self, lab_name: str, node_filter: str | None = None
    ) -> Result[SaveResult, ClabApiError]:
        """Persist running config on the lab's nodes (POST .../save). `node_filter`
        (comma-separated names) narrows it; absent means every node."""
        sent = await self._authed(
            "POST",
            f"/api/v1/labs/{lab_name}/save",
            params={"nodeFilter": node_filter} if node_filter is not None else None,
            timeout=_LAB_OP_TIMEOUT_SECONDS,
        )
        if isinstance(sent, Err):
            return sent
        resp = sent.value
        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"save rejected: {resp.text}", resp.status_code))
        try:
            parsed = _SaveResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(ClabApiError(f"unexpected save response: {exc}", resp.status_code))
        return Ok(SaveResult(message=parsed.message, output=parsed.output))

    async def health(self) -> Result[None, ClabApiError]:
        """Probe the server's unauthenticated health endpoint (readiness only)."""
        try:
            resp = await self.client.get(f"{self.base_url}/health")
        except httpx.HTTPError as exc:
            return Err(ClabApiError(f"health request failed: {exc}", None))

        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"unhealthy: {resp.text}", resp.status_code))
        return Ok(None)
