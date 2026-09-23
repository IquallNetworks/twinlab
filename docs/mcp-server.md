# MCP server (delta 34)

**Status: IMPLEMENTED 2026-09-23.** Proposed and approved the same day. The service is `mcp/`,
and the sections below describe it as built. Where building it changed a detail of the proposal,
the section says so.

## The problem

An agent can help people deploy and run labs. It can *talk* about labs without any help from
Twinlab, but to *act* on one it needs Twinlab's operations as tools. Today the only machine
surface is the REST API and the Python client over it, and no agent platform consumes either
directly. The Model Context Protocol (MCP) is the interface agent hosts do consume, so an MCP
server makes Twinlab usable from any of them. It is agent-neutral: it names no agent product and
assumes nothing about the host beyond MCP.

## Decisions

### A sidecar over `twinlab-client`, not a mount inside the backend

The server is a new compose service, **`mcp/`** (uv, Python 3.14, package `twinlab_mcp`). Each
tool call builds a `twinlab_client.TwinlabClient` with **the caller's own API key** and calls the
public REST API through it. The service holds no secrets and has no database. It never reaches the
backend's internals.

Why this and not a sub-application mounted in the backend:

- **It cannot exceed the REST contract, by construction.** Permission checks, validation, the
  per-lab job mutex and the error envelope all happen where they already happen. A mount calling
  the service layer would have to repeat each route's permission dependency by hand for every
  tool. Much of the logic also lives in the route handlers themselves (`api/labs.py` is 2,400
  lines), so a mount means either duplicating that logic or refactoring it first.
- **The contract stays the enforcement.** The blackbox suite already proves the client against a
  live stack, and the MCP server inherits that proof. If a REST change breaks a tool, it breaks
  the client first, where it is already caught.
- **The backend does not change.** No route is added and `docs/twinlab_client_shape.py` is
  untouched.

The cost is one extra hop per tool call, inside the compose network, and one more service to run.

**It is numbered delta 34 anyway** (decided 2026-09-23). Every earlier delta changed the REST
contract and this one does not, but it is a new served surface, and the Current State list is
the one index of those.

### Authentication: the caller's own API key, and nothing else

Every HTTP request to the MCP endpoint must carry `Authorization: Bearer <twinlab-api-key>`. A
request without one gets a 401 at the transport, before the MCP layer sees it. The key is checked
with one `GET /auth/me`, and each tool then acts with it. The agent can therefore do exactly what
the key's owner could do in the UI, and no more.

- **Session cookies are not accepted.** MCP clients send bearer tokens, and accepting cookies would
  add a CSRF surface for no user.
- **`/health` is the one unauthenticated path**, for the compose healthcheck.
- **The SDK's OAuth resource-server support is not used.** `mcp`'s `TokenVerifier` requires
  `AuthSettings.issuer_url` and advertises OAuth protected-resource metadata (RFC 9728). That
  would point clients at an authorization server Twinlab does not run. A small ASGI guard in
  front of the SDK's Starlette app does the job honestly. Serving the OIDC login as an MCP OAuth
  flow is possible later, but no client needs it now.
- **API keys are full-power**, meaning they carry all of the owner's permissions, with no scopes
  and no expiry. That is acceptable here, because the key belongs to the person using the agent.
  It is also why a key shared by several people is dangerous: the agent would act as the key's
  owner for all of them.

### Transport: streamable HTTP, stateless, plain JSON responses

`MCPServer.streamable_http_app(stateless_http=True, json_response=True)`. Each request stands
alone, so there is no session state to lose on restart. Plain JSON responses pass through nginx
with no buffering configuration. No tool needs server-to-client streaming. The one long wait
(`wait_job`, below) is bounded and returns a result, not progress events.

Exposure: nginx gains `location = ${BASE_PATH}/mcp` → `mcp:8000`, beside `/api/v1`, so the
server shares the frontend's origin and `FRONTEND_BASE_PATH` handling. An MCP client's URL is
`https://<twinlab>/mcp`. The location uses the same per-request DNS as `/api/v1`, with a 180s read
timeout to cover `wait_job`. In development the Vite server proxies `/mcp` too, to
`VITE_MCP_PROXY_TARGET` (set by `compose.dev.yaml`; unset means no `/mcp` route).

**The SDK's DNS-rebinding check is switched off.** Left to its defaults, the SDK pins the `Host`
header to localhost, which a request through nginx never carries. Rebinding defeats a server that
trusts whoever can reach it; this one trusts only a bearer key, which a rebinding page does not
have.

### Tools

The tools are a curated set, not one tool per route. An agent chooses tools better from a short
list with good descriptions than from ninety routes. Each tool carries MCP `ToolAnnotations`
(`readOnlyHint`, `destructiveHint`, `idempotentHint`). A host that asks a person before running
certain tools can default from those hints.

**Read**: every tool here has `readOnlyHint`.

| Tool | Client call | Gate |
| --- | --- | --- |
| `whoami` | `me` | authenticated |
| `list_labs` | `list_labs` | authenticated; the list is already filtered to readable labs |
| `get_lab` | `get_lab` (status, nodes, definition, deployed snapshot, drift) | `lab:read` |
| `list_jobs` | `list_jobs` / `list_all_jobs` (`lab` optional) | `lab:read` / authenticated |
| `get_job` | `get_job` (the step log included) | `lab:read` |
| `wait_job` | `wait_job`, bounded at ≤120s; still running after that returns the job, not an error | `lab:read` |
| `get_links` | `links` | `lab:read` |
| `get_interfaces` | `interfaces` | `lab:read` |
| `get_facts` | `facts` (fact namespace plus the resolved group map) | `lab:read` |
| `get_usage` | `lab_usage` | `lab:read` |
| `node_logs` | `node_logs` (`tail` capped at 1,000 lines) | `lab:read` |
| `show_netem` | `show_netem` | `lab:read` |
| `get_test_suites` | `get_test_suites` (suites plus last results) | `lab:read` |
| `device_catalog` | `device_catalog` | authenticated |
| `host_resources` | `host_resources` | authenticated |
| `list_network_templates` / `get_network_template` | same names | authenticated |

**Act**

| Tool | Client call | Gate | Hints |
| --- | --- | --- | --- |
| `create_lab` | `create_lab` | `lab:create` | — |
| `update_definition` | `update_definition` | `lab:edit` | idempotent |
| `deploy_lab` | `deploy_lab` (`configure` flag) | `lab:edit` | destructive when the lab is already deployed: a redeploy overwrites it in place |
| `configure_lab` | `configure_lab` | `lab:configure` | — |
| `put_test_suites` | `put_test_suites` | `lab:edit` | idempotent |
| `run_test_suite` | `run_test_suite` | `lab:validate` | — |
| `dry_run_test_case` | `dry_run_test_case` | `lab:validate` | **not** read-only: it executes the command on the node |
| `lab_power` / `node_power` | same names | `lab:configure` | destructive for stop and restart |
| `set_netem` | `set_netem` | `lab:configure` | idempotent (replace semantics) |
| `save_config` | `save_config` | `lab:configure` | idempotent |
| `destroy_lab` | `destroy_lab` (`remove` flag) | `lab:destroy` | destructive |

The "Gate" column is documentation. The MCP server checks nothing itself; the backend decides.

**Hints are static per tool.** A tool that is destructive for only some arguments is marked
destructive: `deploy_lab` (a redeploy), and `lab_power` and `node_power` (stop and restart). MCP's
own defaults for a tool that is not read-only are destructive and non-idempotent, so every act tool
states both hints.

**Inputs are the client's own types.** The SDK derives each tool's input schema from its
signature, and the structured parameters are typed with the client's dataclasses: `TestSuite` for
`put_test_suites`, `TestExpectation` for `dry_run_test_case`, `Duration` for `set_netem`. So the
agent gets the suite schema itself as the tool's schema, including the device-keyed `run` union,
and the server needs no JSON loader of its own. Where a parameter could have had a default that
not every caller wants, it has none: `deploy_lab` takes `configure` and `destroy_lab` takes
`remove` explicitly.

**Deliberately excluded**:

- **Identity and access administration**: users, groups, roles, grants, API keys, SSH keys and
  OIDC providers. An agent that can mint credentials or grant access turns a prompt injection
  into a privilege escalation.
- **The web terminal**: an interactive session, not a tool call.
- **The SSE event stream**: nothing in MCP consumes it; jobs are followed with `wait_job`.
- **Layout**: presentation only, and the Build tab is its only writer.

**Deferred from the first version** (decided 2026-09-23): **config import** (`import_network`
and the wiring suggestion, a natural fit for "turn these router configs into a lab"), **custom
config** read and write, and **batch actions** (`apply_actions`, the natural shape for "degrade
these three links"). Each is a clean addition later: one tool over an existing client call.

**Errors.** The client raises `TwinlabApiError` carrying the `{code, message, extras}` envelope.
The tool boundary turns that into an MCP tool result with `isError: true`, whose text is the SDK's
own `Error executing tool <name>: ` followed by the envelope as JSON: `{status, code, message,
extras}`. This is deliberately a *result*, not a protocol error: the agent is
meant to read it. The case that matters most is `netlab_invalid`, whose `extras.stderr` is what
lets an agent repair a definition it wrote. A transport failure (the backend unreachable) is also
a tool error, never a crash of the server.

**Outputs** are the client's models serialized to JSON objects, as `structuredContent` with a
text mirror. A list comes wrapped under a key (`{"labs": [...]}`), since structured content is an
object. Tools declare **no per-tool output schema**: the SDK cannot derive one from the client's
slotted dataclass subclasses (`JobDetail`), and a full schema on every tool would bloat each
`tools/list` for little gain. One addition: **`get_lab` omits `deployed_definition` unless the lab
is drifted**. The two are identical text otherwise, and definitions are the largest thing an agent
reads.

### Knowledge

An agent authoring a netlab definition needs more than tools. The building blocks already exist:
`device_catalog` (what runs, and which modules each device supports) and the builtin network
templates (the `examples/` definitions).

**The user guide is served as MCP resources** (decided 2026-09-23): each page of `docs/guide/`
is a `text/markdown` resource, `twinlab://guide/<file>`, titled from its first heading, so every
MCP client gets the same reference material a person reads. The URI keeps the file name,
extension included (`twinlab://guide/02-first-lab.md`), so the pages' own relative links resolve
to other resources' URIs. The pages are read once at startup, and a guide with no pages fails the
startup rather than serving nothing.

The guide reaches the image the way it reaches the frontend's. `mcp/src/twinlab_mcp/guide` is a
symlink to `docs/guide`, the `docs` additional build context puts the pages where the symlink
points, and a `test -f` in the build stage guards it. The client, a path dependency, arrives the
same way through a `client` context.

The server also carries MCP `instructions`: the lab lifecycle as tool calls, that the long
operations are jobs to follow with `wait_job`, and where the catalog, templates and guide are.

### Configuration

| Setting | Why |
| --- | --- |
| `TWINLAB_API_URL` | The backend's base URL inside the compose network. Required, with no default: the sidecar has one job and cannot guess where it points. |
| `MCP_WAIT_JOB_MAX_SECONDS` | Not a setting. The 120s cap is a constant, because it bounds a tool call and no deployment has a reason to raise it. |

### Dependency

`mcp` 2.2.0 (MIT) was approved 2026-09-23. It depends on `httpx2` (the same line the tree moved
to for OIDC), and not on the unmaintained `httpx` that the 1.x releases pulled in. v2 renamed
`FastMCP` to `mcp.server.mcpserver.MCPServer`. The SDK exposes request headers to a tool through
the context, and documents them as client input, never an identity assertion. That is why
authentication happens in the guard, and a tool reads the key from the same request only after
the guard has verified it.

`uvicorn` (BSD-3-Clause) serves the app, as it does the other Python services. Every transitive
dependency was checked: all are MIT, BSD or Apache-2.0. The blackbox suite adds `mcp` too, for
the SDK's client.

### Testing

- **Unit** (`mcp/tests/`): the real ASGI app driven by the SDK's own client in-process, over
  the real `twinlab-client`, with the backend faked at its HTTP boundary (`httpx2.MockTransport`).
  So the fake is the wire, not the client, and every test also exercises the client's request
  building and parsing. This covers the tool set and its hints, argument mapping, the
  error-to-result translation, the `wait_job` bound, the guard's 401 and 502 paths, and the
  guide resources.
- **Blackbox** (`blackbox/tests/test_mcp.py`): a new `mcp` marker drives the server at
  `TWINLAB_URL/mcp` through the SDK's own client against a live stack. It checks the 401s (no key,
  a revoked key), the listed tools and their annotations, that every guide page is listed and
  readable as a resource, a read acting as the key's owner, a refused write under a
  `global_viewer` key (the backend's 403 surfacing as a tool error), a netlab rejection carrying
  its stderr, and under the `deploy` marker, create → define → deploy → `wait_job` → destroy
  through MCP alone.
