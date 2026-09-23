"""The tools: a curated set over `twinlab-client`, each acting with the
caller's own API key.

The server checks no permission itself. Every tool is one or two client calls,
and the backend decides what the key's owner may do, exactly as it does for
the UI. A refused call comes back as a tool error the agent can read.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Annotated, cast
from uuid import UUID

import httpx2
import pydantic_core
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field
from twinlab_client import (
    CommandMode,
    Duration,
    LabPowerAction,
    NetemAction,
    NodePowerAction,
    TestCaseDraft,
    TestExpectation,
    TestSuite,
    TwinlabApiError,
    TwinlabClient,
    TwinlabProtocolError,
)
from twinlab_client.models import ParseMode

from twinlab_mcp.guard import bearer_token

type ClientFactory = Callable[[str], TwinlabClient]
# A plain alias, not a `type` statement: the SDK reads the return annotation to
# decide the output shape, and only a literal `dict[str, ...]` is served as the
# structured result itself rather than wrapped in {"result": ...}.
JsonObject = dict[str, object]

# Bounds one tool call. A deploy can take many minutes; the agent calls
# wait_job again rather than holding a request open for all of it.
WAIT_JOB_MAX_SECONDS = 120
# How often wait_job re-reads the job. The job's own step log changes on this
# order, and a poll is one cheap GET.
WAIT_JOB_POLL_SECONDS = 2.0
NODE_LOGS_MAX_LINES = 1000

# Hints are static per tool, so a tool that is destructive for only some
# arguments (a redeploy, a stop) is marked destructive. MCP's own defaults for
# a non-read-only tool are destructive and non-idempotent, so every act tool
# spells both. No tool reaches outside Twinlab.
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def _act(*, destructive: bool, idempotent: bool) -> ToolAnnotations:
    return ToolAnnotations(
        read_only_hint=False,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=False,
    )


type LabName = Annotated[str, Field(description="The lab's name.")]
type NodeName = Annotated[str, Field(description="A node's short name, as the definition has it.")]


def _jsonable(value: object) -> object:
    # The client's frozen dataclasses, UUIDs, datetimes and sets, as JSON.
    return pydantic_core.to_jsonable_python(value)


def _json(value: object) -> JsonObject:
    converted = _jsonable(value)
    if not isinstance(converted, dict):
        raise TypeError(f"expected an object, got {type(converted).__name__}")
    return cast("JsonObject", converted)


def _error_text(exc: TwinlabApiError) -> str:
    # The whole envelope, extras included: `netlab_invalid` carries netlab's
    # stderr there, and that is what lets an agent repair a definition.
    return json.dumps(
        {
            "status": exc.status_code,
            "code": exc.code,
            "message": exc.message,
            "extras": exc.extras,
        },
        default=str,
    )


def register_tools(server: MCPServer, client_for: ClientFactory) -> None:
    async def run[T](ctx: Context, op: Callable[[TwinlabClient], Awaitable[T]]) -> T:
        # The guard has already verified this header on this same request.
        headers = ctx.headers
        key = bearer_token(headers.get("authorization") if headers is not None else None)
        if key is None:
            raise ToolError("no API key on the request")
        try:
            async with client_for(key) as client:
                return await op(client)
        except TwinlabApiError as exc:
            raise ToolError(_error_text(exc)) from exc
        except TwinlabProtocolError as exc:
            raise ToolError(f"the backend answered outside the contract: {exc}") from exc
        except httpx2.HTTPError as exc:
            raise ToolError(f"the backend could not be reached: {exc}") from exc

    # ---------------------------------------------------------------- read

    @server.tool(annotations=READ)
    async def whoami(ctx: Context) -> JsonObject:
        """Who the API key belongs to, and their global permissions."""
        return _json(await run(ctx, lambda c: c.me()))

    @server.tool(annotations=READ)
    async def list_labs(ctx: Context) -> JsonObject:
        """The labs you can read, with status, node counts, drift and your
        permissions on each."""
        return {"labs": _jsonable(await run(ctx, lambda c: c.list_labs()))}

    @server.tool(annotations=READ)
    async def get_lab(lab: LabName, ctx: Context) -> JsonObject:
        """One lab: its status, live nodes (state and management IP), its
        stored netlab definition and your permissions on it.

        `deployed_definition` (the definition the running lab was built from)
        is included only when `definition_drifted` is true, since it is
        otherwise identical to `definition`."""
        detail = _json(await run(ctx, lambda c: c.get_lab(lab)))
        if detail.get("definition_drifted") is not True:
            del detail["deployed_definition"]
        return detail

    @server.tool(annotations=READ)
    async def list_jobs(
        ctx: Context,
        lab: Annotated[
            str | None, Field(description="Only this lab's jobs. Omit for every lab you can read.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
    ) -> JsonObject:
        """Recent jobs (deploy, configure, destroy, suite runs), newest first."""
        # 20 is the API's own default, and "recent" is what the question is.
        if lab is None:
            jobs = await run(ctx, lambda c: c.list_all_jobs(limit=limit))
        else:
            jobs = await run(ctx, lambda c: c.list_jobs(lab, limit=limit))
        return {"jobs": _jsonable(jobs)}

    @server.tool(annotations=READ)
    async def get_job(lab: LabName, job_id: UUID, ctx: Context) -> JsonObject:
        """One job, with its step log: what the operation did, in order. A
        failed job means the operation could not run (see `error`); one that
        ran but found problems succeeded with `result.status` saying so
        (`config_failed`, `validation_failed`)."""
        return _json(await run(ctx, lambda c: c.get_job(lab, job_id)))

    @server.tool(annotations=READ)
    async def wait_job(
        lab: LabName,
        job_id: UUID,
        ctx: Context,
        timeout_seconds: Annotated[int, Field(ge=1, le=WAIT_JOB_MAX_SECONDS)] = (
            WAIT_JOB_MAX_SECONDS
        ),
    ) -> JsonObject:
        """Wait for a job to finish, up to the timeout (at most 120 seconds),
        and return it. A job still running at the timeout is returned as it
        is, not as an error: call wait_job again to keep waiting."""

        # The longest wait is the default: a caller asking to wait wants the
        # job finished, and the cap already bounds the call.
        async def wait(client: TwinlabClient) -> object:
            try:
                return await client.wait_job(
                    lab, job_id, timeout=timeout_seconds, poll_interval=WAIT_JOB_POLL_SECONDS
                )
            except TimeoutError:
                return await client.get_job(lab, job_id)

        return _json(await run(ctx, wait))

    @server.tool(annotations=READ)
    async def get_links(lab: LabName, ctx: Context) -> JsonObject:
        """The lab's logical links (a LAN is one link with many endpoints),
        with addressing, interface names, oper state and active impairment."""
        return _json(await run(ctx, lambda c: c.links(lab)))

    @server.tool(annotations=READ)
    async def get_interfaces(
        lab: LabName,
        ctx: Context,
        node: Annotated[str | None, Field(description="Only this node. Omit for all.")] = None,
    ) -> JsonObject:
        """Live interface inventory per node, as the containers see it."""
        nodes = await run(ctx, lambda c: c.interfaces(lab, node=node))
        return {"nodes": _jsonable(nodes)}

    @server.tool(annotations=READ)
    async def get_facts(lab: LabName, ctx: Context) -> JsonObject:
        """The lab's fact namespace (netlab's per-node data: interfaces,
        neighbors, loopbacks, routing subtrees) that test commands render
        against as `{{ node... }}`, plus the resolved group membership."""
        return _json(await run(ctx, lambda c: c.facts(lab)))

    @server.tool(annotations=READ)
    async def get_usage(lab: LabName, ctx: Context) -> JsonObject:
        """Per-node CPU, memory and network use right now. A node that is not
        running has no measures (null, never zero)."""
        return _json(await run(ctx, lambda c: c.lab_usage(lab)))

    @server.tool(annotations=READ)
    async def node_logs(
        lab: LabName,
        node: NodeName,
        ctx: Context,
        tail: Annotated[int, Field(ge=1, le=NODE_LOGS_MAX_LINES)] = 200,
    ) -> JsonObject:
        """A node's container logs (not the NOS's syslog), last `tail` lines."""
        # 200 is the API's own default: enough to see a boot fail.
        return _json(await run(ctx, lambda c: c.node_logs(lab, node, tail=tail)))

    @server.tool(annotations=READ)
    async def show_netem(lab: LabName, node: NodeName, ctx: Context) -> JsonObject:
        """The node's interfaces that carry an active impairment (delay,
        jitter, loss, rate, corruption). An unimpaired interface is absent."""
        impairments = await run(ctx, lambda c: c.show_netem(lab, node))
        return {"impairments": _jsonable(impairments)}

    @server.tool(annotations=READ)
    async def get_test_suites(lab: LabName, ctx: Context) -> JsonObject:
        """The lab's test suites and each suite's last results."""
        return _json(await run(ctx, lambda c: c.get_test_suites(lab)))

    @server.tool(annotations=READ)
    async def device_catalog(ctx: Context) -> JsonObject:
        """The devices a lab can use: netlab device name, which netlab modules
        each supports, its default image and whether that image is present,
        and whether test cases may use `mode: cli` or `parse: textfsm` on it."""
        return _json(await run(ctx, lambda c: c.device_catalog()))

    @server.tool(annotations=READ)
    async def host_resources(ctx: Context) -> JsonObject:
        """The lab host's CPU, load, memory, swap and disk: whether there is
        room for another lab."""
        return _json(await run(ctx, lambda c: c.host_resources()))

    @server.tool(annotations=READ)
    async def list_network_templates(ctx: Context) -> JsonObject:
        """Ready-made lab definitions: the builtin examples and labs people
        have published. Content is omitted; get_network_template has it."""
        templates = await run(ctx, lambda c: c.list_network_templates())
        return {"templates": _jsonable(templates)}

    @server.tool(annotations=READ)
    async def get_network_template(
        name: Annotated[str, Field(description="The template's name.")], ctx: Context
    ) -> JsonObject:
        """A network template with its netlab definition: a worked example to
        start a lab from (create_lab, then update_definition with it)."""
        return _json(await run(ctx, lambda c: c.get_network_template(name)))

    # ----------------------------------------------------------------- act

    @server.tool(annotations=_act(destructive=False, idempotent=False))
    async def create_lab(
        name: Annotated[
            str,
            Field(
                description="A netlab identifier: a letter, then letters, digits, "
                "dashes or underscores, at most 16 characters."
            ),
        ],
        ctx: Context,
    ) -> JsonObject:
        """Create an empty lab record, owned by you. It has no definition yet:
        write one with update_definition, then deploy_lab."""
        return _json(await run(ctx, lambda c: c.create_lab(name)))

    @server.tool(annotations=_act(destructive=False, idempotent=True))
    async def update_definition(
        lab: LabName,
        definition: Annotated[str, Field(description="The complete netlab topology, as YAML.")],
        ctx: Context,
    ) -> JsonObject:
        """Replace the lab's stored netlab definition. It is validated with a
        dry `netlab create`; a rejection carries netlab's stderr in
        `extras.stderr`. Every node must state its `device`. The lab's name
        and management subnet are pinned by Twinlab. Nothing running changes
        until the next deploy."""
        return _json(await run(ctx, lambda c: c.update_definition(lab, definition)))

    @server.tool(annotations=_act(destructive=True, idempotent=False))
    async def deploy_lab(
        lab: LabName,
        configure: Annotated[
            bool, Field(description="Also push device configuration after the nodes are up.")
        ],
        ctx: Context,
        skip_config_time_checks: bool = False,
    ) -> JsonObject:
        """Deploy the lab from its stored definition. On a lab that is already
        deployed this REDEPLOYS IT IN PLACE, replacing the running nodes.
        Returns the running job; follow it with wait_job."""
        # False runs the lab's config-time suites, which is what they are for.
        job = await run(
            ctx,
            lambda c: c.deploy_lab(
                lab, configure=configure, skip_config_time_checks=skip_config_time_checks
            ),
        )
        return _json(job)

    @server.tool(annotations=_act(destructive=False, idempotent=False))
    async def configure_lab(
        lab: LabName, ctx: Context, skip_config_time_checks: bool = False
    ) -> JsonObject:
        """Push device configuration from the stored definition to the running
        lab, then run its config-time suites. Returns the running job."""
        job = await run(
            ctx,
            lambda c: c.configure_lab(lab, skip_config_time_checks=skip_config_time_checks),
        )
        return _json(job)

    @server.tool(annotations=_act(destructive=False, idempotent=True))
    async def put_test_suites(
        lab: LabName,
        suites: Annotated[
            dict[str, TestSuite],
            Field(description="Every suite of the lab, by name. Replaces them all."),
        ],
        ctx: Context,
    ) -> JsonObject:
        """Replace the lab's test suites. Commands and expectations may use
        Jinja2 over the lab's facts (see get_facts). Try a case first with
        dry_run_test_case."""
        return _json(await run(ctx, lambda c: c.put_test_suites(lab, suites)))

    @server.tool(annotations=_act(destructive=False, idempotent=False))
    async def run_test_suite(
        lab: LabName,
        suite: Annotated[str, Field(description="The suite's name.")],
        ctx: Context,
    ) -> JsonObject:
        """Run one test suite against the running lab. Returns the running
        job; its result is the suite report."""
        return _json(await run(ctx, lambda c: c.run_test_suite(lab, suite)))

    @server.tool(annotations=_act(destructive=False, idempotent=False))
    async def dry_run_test_case(
        lab: LabName,
        node: NodeName,
        command: str,
        ctx: Context,
        mode: CommandMode = "shell",
        parse: ParseMode | None = None,
        interactive: bool = False,
        expect: TestExpectation | None = None,
    ) -> JsonObject:
        """EXECUTE one unsaved test case on one node and return the rendered
        command, its output and, with `parse`, the parsed structure a
        `compare` expectation is written against. Saves nothing.

        `mode: shell` sends the command to the transport's shell (for most
        devices the container's shell, not the NOS CLI); `mode: cli` runs it
        in the device's own CLI."""
        # The defaults are TestCase's own: a plain shell command, unparsed.
        draft = TestCaseDraft(
            command=command, expect=expect, parse=parse, mode=mode, interactive=interactive
        )
        return _json(await run(ctx, lambda c: c.dry_run_test_case(lab, node, draft)))

    @server.tool(annotations=_act(destructive=True, idempotent=False))
    async def lab_power(lab: LabName, action: LabPowerAction, ctx: Context) -> JsonObject:
        """Start, stop, restart, pause or unpause every node of the lab."""
        return _json(await run(ctx, lambda c: c.lab_power(lab, action)))

    @server.tool(annotations=_act(destructive=True, idempotent=False))
    async def node_power(
        lab: LabName, node: NodeName, action: NodePowerAction, ctx: Context
    ) -> JsonObject:
        """Start, stop, restart, pause or unpause one node."""
        return _json(await run(ctx, lambda c: c.node_power(lab, node, action)))

    @server.tool(annotations=_act(destructive=False, idempotent=True))
    async def set_netem(
        lab: LabName,
        node: NodeName,
        interface: Annotated[
            str, Field(description="The container-side name, as get_links reports it.")
        ],
        ctx: Context,
        delay: Duration | None = None,
        jitter: Annotated[Duration | None, Field(description="Requires delay.")] = None,
        loss: Annotated[float | None, Field(ge=0, le=100, description="Percent.")] = None,
        rate: Annotated[int | None, Field(ge=0, description="kbit/s.")] = None,
        corruption: Annotated[float | None, Field(ge=0, le=100, description="Percent.")] = None,
    ) -> JsonObject:
        """Set the COMPLETE impairment of one interface's egress. Anything
        omitted is cleared, so a call with none of them clears the interface.
        Netem shapes egress only: impair a link both ways by setting both
        endpoints."""
        # Every dimension defaults to absent, which is what REPLACE semantics
        # means by "clear it".
        action = NetemAction(
            node=node,
            interface=interface,
            delay=delay,
            jitter=jitter,
            loss=loss,
            rate=rate,
            corruption=corruption,
        )
        return _json(await run(ctx, lambda c: c.set_netem(lab, action)))

    @server.tool(annotations=_act(destructive=False, idempotent=True))
    async def save_config(lab: LabName, ctx: Context) -> JsonObject:
        """Save each node's running configuration inside the node."""
        return _json(await run(ctx, lambda c: c.save_config(lab)))

    @server.tool(annotations=_act(destructive=True, idempotent=False))
    async def destroy_lab(
        lab: LabName,
        remove: Annotated[
            bool,
            Field(
                description="False tears the lab down and keeps its record, to deploy "
                "again. True also deletes the record: definition, suites and history."
            ),
        ],
        ctx: Context,
    ) -> JsonObject:
        """Tear the lab's nodes down. Returns the running job."""
        return _json(await run(ctx, lambda c: c.destroy_lab(lab, remove=remove)))
