"""The MCP server (delta 34), driven through the MCP SDK's own client.

The server is a sidecar over the public API, acting with the caller's own API
key, so what these slices pin is the MCP surface itself: the tool set and its
hints, the guide resources, the bearer gate, and that a refusal from the
backend reaches the agent as a readable tool error. The `deploy`-marked slice
runs a whole lab lifecycle through MCP alone.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import cast

import httpx2
import pytest
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult, TextContent, TextResourceContents
from twinlab_client import TwinlabApiError, TwinlabClient

from _config import LINUX_LAB_DEFINITION, LabFactory, SuiteConfig, UserClientFactory

pytestmark = pytest.mark.mcp

GUIDE_PREFIX = "twinlab://guide/"
# Each call waits at most the server's 120s bound; this bounds the whole wait.
LIFECYCLE_WAIT_SECONDS = 600


def _mcp_url(config: SuiteConfig) -> str:
    return config.base_url.rstrip("/") + "/mcp"


@asynccontextmanager
async def _session(config: SuiteConfig, key: str) -> AsyncGenerator[Client]:
    # MCP's default timeouts, plus room for wait_job's 120s.
    http = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {key}"}, timeout=httpx2.Timeout(30, read=180)
    )
    async with (
        http,
        Client(streamable_http_client(_mcp_url(config), http_client=http)) as client,
    ):
        yield client


@asynccontextmanager
async def _api_key(client: TwinlabClient, name: str) -> AsyncGenerator[str]:
    created = await client.create_api_key(name)
    try:
        yield created.key
    finally:
        with contextlib.suppress(TwinlabApiError):
            await client.revoke_api_key(created.info.id)


def _text(result: CallToolResult) -> str:
    [content] = result.content
    assert isinstance(content, TextContent)
    return content.text


def _ok(result: CallToolResult) -> dict[str, object]:
    assert not result.is_error, _text(result)
    assert result.structured_content is not None
    return result.structured_content


def _error(result: CallToolResult) -> dict[str, object]:
    """The error envelope, after the SDK's `Error executing tool <name>: `."""
    assert result.is_error
    _, _, envelope = _text(result).partition(": ")
    return cast("dict[str, object]", json.loads(envelope))


async def test_no_key_is_401(config: SuiteConfig) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.post(
            _mcp_url(config),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_a_revoked_key_is_401(config: SuiteConfig, admin: TwinlabClient) -> None:
    async with _api_key(admin, "bb-mcp-revoked") as key:
        pass
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {key}"}) as http:
        response = await http.post(
            _mcp_url(config),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 401


async def test_the_tools_and_their_hints(config: SuiteConfig, admin: TwinlabClient) -> None:
    async with _api_key(admin, "bb-mcp-tools") as key, _session(config, key) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    # Identity and access administration is deliberately absent.
    assert not {name for name in tools if "user" in name or "grant" in name or "key" in name}
    for name in ("list_labs", "get_lab", "get_job", "wait_job", "device_catalog"):
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is True, name
    for name in ("deploy_lab", "destroy_lab", "lab_power", "node_power"):
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.destructive_hint is True, name
    for name in ("create_lab", "update_definition", "set_netem"):
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is False, name
        assert annotations.destructive_hint is False, name


async def test_the_guide_is_served_as_resources(config: SuiteConfig, admin: TwinlabClient) -> None:
    async with _api_key(admin, "bb-mcp-guide") as key, _session(config, key) as client:
        resources = (await client.list_resources()).resources
        uris = sorted(str(resource.uri) for resource in resources)
        assert GUIDE_PREFIX + "README.md" in uris
        for uri in uris:
            assert uri.startswith(GUIDE_PREFIX), uri
            [content] = (await client.read_resource(uri)).contents
            assert isinstance(content, TextResourceContents), uri
            assert content.mime_type == "text/markdown", uri
            assert content.text.startswith("#"), uri


async def test_a_read_acts_as_the_key_owner(
    config: SuiteConfig, make_user_client: UserClientFactory, make_lab: LabFactory
) -> None:
    user, user_client = await make_user_client({"creator"})
    lab = await make_lab(user_client)
    async with _api_key(user_client, "bb-mcp-read") as key, _session(config, key) as client:
        me = _ok(await client.call_tool("whoami", {}))
        labs = _ok(await client.call_tool("list_labs", {}))
        detail = _ok(await client.call_tool("get_lab", {"lab": lab.name}))
    assert me["username"] == user.username
    names = [cast("dict[str, object]", row)["name"] for row in cast("list[object]", labs["labs"])]
    assert lab.name in names
    assert detail["name"] == lab.name
    assert detail["status"] == "created"


async def test_a_refused_write_is_a_tool_error(
    config: SuiteConfig, make_user_client: UserClientFactory, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    _, viewer = await make_user_client({"global_viewer"})
    async with _api_key(viewer, "bb-mcp-viewer") as key, _session(config, key) as client:
        readable = await client.call_tool("get_lab", {"lab": lab.name})
        refused = await client.call_tool(
            "update_definition", {"lab": lab.name, "definition": LINUX_LAB_DEFINITION}
        )
    assert _ok(readable)["name"] == lab.name
    envelope = _error(refused)
    assert envelope["status"] == 403
    assert envelope["code"] == "permission_denied"


async def test_a_netlab_rejection_carries_its_stderr(
    config: SuiteConfig, admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    async with _api_key(admin, "bb-mcp-invalid") as key, _session(config, key) as client:
        result = await client.call_tool(
            "update_definition",
            {"lab": lab.name, "definition": "provider: clab\nnodes: [n1]\nlinks: [n1-nowhere]\n"},
        )
    envelope = _error(result)
    assert envelope["code"] == "netlab_invalid"
    extras = cast("dict[str, object]", envelope["extras"])
    assert extras["stderr"]


async def _wait(client: Client, lab: str, job_id: str) -> dict[str, object]:
    async with asyncio.timeout(LIFECYCLE_WAIT_SECONDS):
        while True:
            job = _ok(await client.call_tool("wait_job", {"lab": lab, "job_id": job_id}))
            if job["status"] != "running":
                return job


@pytest.mark.deploy
async def test_a_lab_lifecycle_through_mcp_alone(
    config: SuiteConfig, admin: TwinlabClient, unique: Callable[[str], str]
) -> None:
    name = unique("mcp")
    async with _api_key(admin, "bb-mcp-lifecycle") as key, _session(config, key) as client:
        try:
            _ok(await client.call_tool("create_lab", {"name": name}))
            _ok(
                await client.call_tool(
                    "update_definition", {"lab": name, "definition": LINUX_LAB_DEFINITION}
                )
            )
            deploy = _ok(await client.call_tool("deploy_lab", {"lab": name, "configure": True}))
            deployed = await _wait(client, name, cast("str", deploy["id"]))
            assert deployed["status"] == "succeeded", deployed
            result = cast("dict[str, object]", deployed["result"])
            assert result["status"] == "configured", result

            detail = _ok(await client.call_tool("get_lab", {"lab": name}))
            nodes = cast("list[dict[str, object]]", detail["nodes"])
            assert {node["name"] for node in nodes} == {"n1", "n2"}
            links = _ok(await client.call_tool("get_links", {"lab": name}))
            assert len(cast("list[object]", links["links"])) == 1

            destroy = _ok(await client.call_tool("destroy_lab", {"lab": name, "remove": True}))
            destroyed = await _wait(client, name, cast("str", destroy["id"]))
            assert destroyed["status"] == "succeeded", destroyed
        finally:
            with contextlib.suppress(TwinlabApiError, TimeoutError):
                job = await admin.destroy_lab(name, remove=True)
                _ = await admin.wait_job(name, job.id, timeout=120)
