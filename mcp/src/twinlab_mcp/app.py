"""The ASGI application: the SDK's streamable HTTP app behind the bearer guard.

Stateless with plain JSON responses: each request stands alone, so a restart
loses nothing and nginx needs no streaming configuration. No tool needs to
stream to the client; the one long wait (wait_job) is bounded and returns a
result.
"""

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp
from twinlab_client import TwinlabClient

from twinlab_mcp.guard import HEALTH_PATH, BearerGuard
from twinlab_mcp.guide import GuideError, load_guide
from twinlab_mcp.settings import SettingsError, load_settings
from twinlab_mcp.tools import ClientFactory, register_tools

# The path the server answers on. nginx maps `<base path>/mcp` onto it.
MCP_PATH = "/mcp"

# Beside the package in the source tree, a symlink to docs/guide; the image
# copies the guide to where the symlink points.
GUIDE_DIR = Path(__file__).parent / "guide"

INSTRUCTIONS = """\
Twinlab deploys reproducible network labs from a declarative netlab definition \
(YAML: provider, defaults.device, nodes, links, modules). Every tool acts as the \
owner of the API key, with exactly their permissions.

A lab's lifecycle: create_lab (an empty record) -> update_definition (validated by \
netlab) -> deploy_lab (a job) -> wait_job. deploy, configure, destroy and suite runs \
are jobs: follow them with wait_job, and read `status` and `result` when they end.

device_catalog lists the devices a definition may use and the netlab modules each \
supports. The network templates are worked example definitions. The user guide is \
available as resources under twinlab://guide/.
"""


def build_app(client_for: ClientFactory, guide_dir: Path) -> ASGIApp | GuideError:
    """`client_for` builds a client acting with one API key: the guard's key
    check and every tool call go through it."""
    guide = load_guide(guide_dir)
    if isinstance(guide, GuideError):
        return guide

    server = MCPServer("twinlab", instructions=INSTRUCTIONS)
    register_tools(server, client_for)
    for page in guide:
        server.add_resource(page)

    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    _ = server.custom_route(HEALTH_PATH, methods=["GET"])(health)

    app = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        # The SDK's DNS-rebinding check pins the Host header to localhost,
        # which a request through nginx never carries. Rebinding attacks a
        # server that trusts whoever can reach it; this one trusts only a
        # bearer key, which a rebinding page does not have.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return BearerGuard(app, client_for)


def create_app() -> ASGIApp:
    """uvicorn's factory: configuration from the environment, failing loudly."""
    settings = load_settings(os.environ)
    if isinstance(settings, SettingsError):
        raise SystemExit(f"twinlab-mcp: {settings.message}")
    api_url = settings.api_url

    def client_for(key: str) -> TwinlabClient:
        return TwinlabClient(api_url, api_key=key)

    app = build_app(client_for, GUIDE_DIR)
    if isinstance(app, GuideError):
        raise SystemExit(f"twinlab-mcp: {app.message}")
    return app
