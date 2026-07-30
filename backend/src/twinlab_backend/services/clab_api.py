"""Client for the containerlab API server (github.com/srl-labs/clab-api-server).

The server authenticates a host (PAM) user via `POST /login`, returns a JWT, and
exposes lab lifecycle operations under `/api/v1`. Deploy accepts the topology
inline as `topologyContent`, so the netlab-generated YAML flows straight through
— no shared volume with the server is needed. Config push is not done here; it
lives in the netlab-runner sidecar.

httpx is a third-party boundary: its exceptions and the server's untyped JSON are
translated here into typed results; nothing propagates as an exception.
"""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from http import HTTPStatus

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import InvalidHandshake

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


def bare_mgmt_ip(ipv4_address: str) -> str:
    """The bare management IP from clab's CIDR `ipv4_address`, or "" when the
    node has none. A stopped container reports the literal "N/A" — naive
    prefix-stripping turns that into "N", so it must be treated as absent."""
    if ipv4_address in ("", "N/A"):
        return ""
    return ipv4_address.split("/", 1)[0]


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


@dataclass(frozen=True, slots=True)
class ExecResult:
    """The outcome of running one command on one node's container via clab-api's
    exec (`return-code`/`stdout`/`stderr`, as containerlab reports them). A
    non-zero `return_code` is not itself a failure here — it is data the caller's
    validation matches on."""

    container_name: str
    return_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class NetemImpairment:
    """The netem (tc) impairment currently applied to one container interface, as
    clab-api reports it. `delay`/`jitter` are netem duration strings (e.g. "50ms",
    empty when unset); `loss`/`corruption` are percentages; `rate` is kbit/s
    (0 meaning unshaped)."""

    interface: str
    delay: str
    jitter: str
    loss: float
    rate: int
    corruption: float


@dataclass(frozen=True, slots=True)
class LabEvent:
    """A lab lifecycle event from clab-api's /events stream, distilled to what the
    UI needs to react: which lab/node and what happened."""

    lab: str
    node: str | None
    action: str  # container action: create | start | stop | kill | die | destroy | …
    timestamp: str


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


class _TerminalSessionResponse(BaseModel):
    # clab-api answers a terminal-session create with a large TerminalSessionInfo;
    # we only need the id to open (and later delete) the stream.
    model_config = ConfigDict(extra="ignore")

    session_id: str = Field(alias="sessionId")


class _InterfaceInfo(BaseModel):
    name: str
    alias: str
    ifindex: int
    mac: str
    mtu: int
    state: str
    kind: str = Field(alias="type")


class _NodeInterfaces(BaseModel):
    # clab-api's `name` here is the container name (`clab-<lab>-<node>`), not the
    # short node name — the interface inventory is keyed differently from the rest.
    node_name: str = Field(alias="name")
    interfaces: list[_InterfaceInfo]


_NodeInterfacesList = TypeAdapter(list[_NodeInterfaces])


class _NetemInterfaceInfo(BaseModel):
    # clab-api's netem show entry. `packet_loss` is its JSON key; the impairment
    # fields default to unset (empty duration / 0) because a fresh interface has no
    # netem applied, and `corruption` is absent on older servers.
    model_config = ConfigDict(extra="ignore")

    interface: str
    delay: str = ""
    jitter: str = ""
    loss: float = Field(default=0.0, alias="packet_loss")
    rate: int = 0
    corruption: float = 0.0


# netem show answers with a {containerName: [interface impairments]} map; we query
# one container, so there is a single key.
_NetemShow = TypeAdapter(dict[str, list[_NetemInterfaceInfo]])


class _ExecResult(BaseModel):
    # clab-api's per-node exec result. `cmd` (the argv it ran) is unused here.
    return_code: int = Field(alias="return-code")
    stdout: str = ""
    stderr: str = ""


# exec answers with a {containerName: [results]} map; we filter to one node, so a
# single key with a single result (one command) is expected.
_ExecResponse = TypeAdapter(dict[str, list[_ExecResult]])


class _EventAttributes(BaseModel):
    # clab-api's event carries a large docker-labels blob; we only need which lab
    # (`containerlab`) and node (`clab-node-name`) the event is about.
    model_config = ConfigDict(extra="ignore")

    containerlab: str | None = None
    node_name: str | None = Field(default=None, alias="clab-node-name")


class _ClabEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str
    timestamp: str
    attributes: _EventAttributes = Field(default_factory=_EventAttributes)


def _ws_base(base_url: str) -> str:
    """The clab-api WebSocket stream lives on the same host/port as its HTTP API;
    only the scheme changes (http->ws, https->wss)."""
    if base_url.startswith("https://"):
        return "wss://" + base_url.removeprefix("https://")
    if base_url.startswith("http://"):
        return "ws://" + base_url.removeprefix("http://")
    return base_url


def _parse_event(line: str) -> LabEvent | None:
    """Parse one NDJSON event line into a LabEvent, or None to drop it: a malformed
    line, or an event not scoped to a lab (no `containerlab` attribute)."""
    try:
        parsed = _ClabEvent.model_validate_json(line)
    except ValidationError:
        return None
    lab = parsed.attributes.containerlab
    if lab is None:
        return None
    return LabEvent(
        lab=lab, node=parsed.attributes.node_name, action=parsed.action, timestamp=parsed.timestamp
    )


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


def _to_netem(info: _NetemInterfaceInfo) -> NetemImpairment:
    # netem show decorates the interface with its link ("eth1 (r1 -> r2)"), but
    # set/reset — and our interface picker — key on the bare name; strip the
    # annotation so a reset built from show's output targets the right interface.
    interface = info.interface.split(" (", 1)[0]
    return NetemImpairment(
        interface=interface,
        delay=info.delay,
        jitter=info.jitter,
        loss=info.loss,
        rate=info.rate,
        corruption=info.corruption,
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
        self, lab_name: str, container_name: str, tail: str = "all"
    ) -> Result[NodeLogs, ClabApiError]:
        """Fetch a node's container logs (GET .../nodes/{container}/logs). Unlike the
        node lifecycle actions (which accept the short node name), clab-api's logs
        endpoint matches on the full container name (`clab-<lab>-<node>`) and rejects
        a short name — so the caller resolves the node to its container first. `tail`
        is the number of trailing lines, or "all"; the `follow` (stream) mode is unused."""
        sent = await self._authed(
            "GET",
            f"/api/v1/labs/{lab_name}/nodes/{container_name}/logs",
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
        # clab-api serialises "no reporting nodes" (e.g. every container
        # stopped) as a JSON null, not an empty array.
        if resp.content in (b"", b"null"):
            return Ok(())
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

    async def exec(
        self, lab_name: str, container_name: str, command: str
    ) -> Result[ExecResult, ClabApiError]:
        """Run one command on one node and return its output (POST .../exec). The
        `nodeFilter` query param scopes it to a single node and takes the container
        name (`clab-<lab>-<node>`), like logs/netem — not the short node name. The
        response maps container name -> results; we filter to one, so we read the
        single entry. An empty map means the filter matched no node."""
        sent = await self._authed(
            "POST",
            f"/api/v1/labs/{lab_name}/exec",
            params={"nodeFilter": container_name},
            json={"command": command},
            timeout=_LAB_OP_TIMEOUT_SECONDS,
        )
        if isinstance(sent, Err):
            return sent
        resp = sent.value
        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"exec rejected: {resp.text}", resp.status_code))
        try:
            by_container = _ExecResponse.validate_json(resp.content)
        except ValidationError as exc:
            return Err(ClabApiError(f"unexpected exec response: {exc}", resp.status_code))
        # Prefer the entry for the container we filtered on; fall back to the sole
        # entry if the server keyed it differently, so a naming mismatch still reads.
        results = by_container.get(container_name)
        if results is None and len(by_container) == 1:
            results = next(iter(by_container.values()))
        if not results:
            return Err(
                ClabApiError(f"exec produced no result for '{container_name}'", resp.status_code)
            )
        first = results[0]
        return Ok(
            ExecResult(
                container_name=container_name,
                return_code=first.return_code,
                stdout=first.stdout,
                stderr=first.stderr,
            )
        )

    async def set_netem(
        self,
        container_name: str,
        interface: str,
        *,
        delay: str | None,
        jitter: str | None,
        loss: float | None,
        rate: int | None,
        corruption: float | None,
    ) -> Result[str, ClabApiError]:
        """Apply netem link impairment to one container interface (POST
        .../tools/netem/set). Only the impairments the caller set are sent — an
        omitted field leaves that dimension unchanged rather than zeroing it."""
        body: dict[str, object] = {"containerName": container_name, "interface": interface}
        if delay is not None:
            body["delay"] = delay
        if jitter is not None:
            body["jitter"] = jitter
        if loss is not None:
            body["loss"] = loss
        if rate is not None:
            body["rate"] = rate
        if corruption is not None:
            body["corruption"] = corruption
        sent = await self._authed("POST", "/api/v1/tools/netem/set", json=body)
        return self._parse_message(sent, "netem set")

    async def reset_netem(self, container_name: str, interface: str) -> Result[str, ClabApiError]:
        """Clear all netem impairment from one container interface (POST
        .../tools/netem/reset)."""
        sent = await self._authed(
            "POST",
            "/api/v1/tools/netem/reset",
            json={"containerName": container_name, "interface": interface},
        )
        return self._parse_message(sent, "netem reset")

    async def show_netem(
        self, container_name: str
    ) -> Result[tuple[NetemImpairment, ...], ClabApiError]:
        """Read the current netem impairment on each of a container's interfaces
        (GET .../tools/netem/show). The response maps the container name to its
        interface list; we flatten it since we query one container."""
        sent = await self._authed(
            "GET", "/api/v1/tools/netem/show", params={"containerName": container_name}
        )
        if isinstance(sent, Err):
            return sent
        resp = sent.value
        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"netem show rejected: {resp.text}", resp.status_code))
        try:
            parsed = _NetemShow.validate_json(resp.content)
        except ValidationError as exc:
            return Err(ClabApiError(f"unexpected netem show response: {exc}", resp.status_code))
        return Ok(tuple(_to_netem(info) for infos in parsed.values() for info in infos))

    async def create_terminal_session(
        self,
        lab_name: str,
        node_name: str,
        *,
        protocol: str,
        cols: int,
        rows: int,
        ssh_username: str | None = None,
    ) -> Result[str, ClabApiError]:
        """Open an interactive terminal session on a node (POST
        .../nodes/{node}/terminal-sessions) and return its session id. `protocol`
        is `ssh` or `shell` (constrained at the HTTP boundary); `cols`/`rows` are
        the initial terminal size. `ssh_username` overrides the login user for
        `protocol=ssh` (clab-api's own default is `admin`, wrong for e.g. vyos);
        omitted when unset so shell sessions and the server default are unaffected.
        The session's WebSocket is opened separately via `open_terminal_stream`,
        and it must be closed with `delete_terminal_session`."""
        body: dict[str, object] = {"protocol": protocol, "cols": cols, "rows": rows}
        if ssh_username is not None:
            body["sshUsername"] = ssh_username
        sent = await self._authed(
            "POST",
            f"/api/v1/labs/{lab_name}/nodes/{node_name}/terminal-sessions",
            json=body,
        )
        if isinstance(sent, Err):
            return sent
        resp = sent.value
        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"terminal session rejected: {resp.text}", resp.status_code))
        try:
            parsed = _TerminalSessionResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(
                ClabApiError(f"unexpected terminal session response: {exc}", resp.status_code)
            )
        return Ok(parsed.session_id)

    async def delete_terminal_session(self, session_id: str) -> Result[None, ClabApiError]:
        """End a terminal session (DELETE .../terminal-sessions/{id}). Best-effort
        cleanup on the proxy's exit path; a non-200 is surfaced, not raised."""
        sent = await self._authed("DELETE", f"/api/v1/terminal-sessions/{session_id}")
        if isinstance(sent, Err):
            return sent
        resp = sent.value
        if resp.status_code != HTTPStatus.OK:
            return Err(
                ClabApiError(f"terminal session delete rejected: {resp.text}", resp.status_code)
            )
        return Ok(None)

    async def open_terminal_stream(self, session_id: str) -> Result[ClientConnection, ClabApiError]:
        """Open the terminal session's WebSocket (GET .../terminal-sessions/{id}/stream)
        with a fresh JWT on the handshake, and return the live connection. The caller
        owns the connection and must close it. httpx can't speak client WebSocket, so
        this uses the `websockets` client; its handshake/transport errors are trapped
        here into a typed error."""
        auth = await self._login()
        if isinstance(auth, Err):
            return auth
        url = f"{_ws_base(self.base_url)}/api/v1/terminal-sessions/{session_id}/stream"
        try:
            conn = await ws_connect(
                url, additional_headers={"Authorization": f"Bearer {auth.value}"}
            )
        except (OSError, InvalidHandshake, TimeoutError) as exc:
            return Err(ClabApiError(f"terminal stream connect failed: {exc}", None))
        return Ok(conn)

    async def stream_events(self) -> AsyncIterator[LabEvent]:
        """Stream lab lifecycle events from clab-api's /events (NDJSON), yielding the
        parsed, lab-scoped ones. Ends quietly on a login failure, a non-200, or the
        upstream closing — the SSE layer lets the browser reconnect. `read=None`
        disables the read timeout since events are sparse; connect/write are bounded."""
        auth = await self._login()
        if isinstance(auth, Err):
            return
        try:
            async with self.client.stream(
                "GET",
                f"{self.base_url}/api/v1/events",
                headers={"Authorization": f"Bearer {auth.value}"},
                timeout=httpx.Timeout(10.0, read=None),
            ) as resp:
                if resp.status_code != HTTPStatus.OK:
                    return
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    event = _parse_event(line)
                    if event is not None:
                        yield event
        except httpx.HTTPError:
            return

    async def health(self) -> Result[None, ClabApiError]:
        """Probe the server's unauthenticated health endpoint (readiness only)."""
        try:
            resp = await self.client.get(f"{self.base_url}/health")
        except httpx.HTTPError as exc:
            return Err(ClabApiError(f"health request failed: {exc}", None))

        if resp.status_code != HTTPStatus.OK:
            return Err(ClabApiError(f"unhealthy: {resp.text}", resp.status_code))
        return Ok(None)
