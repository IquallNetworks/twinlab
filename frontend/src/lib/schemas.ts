import { z } from 'zod'

// Response shapes mirror the backend's pydantic models (twinlab_backend.models,
// api.auth, api.users). Parsing with zod gives us runtime validation at the
// network boundary and the inferred TypeScript types in one place.

export const userInfoSchema = z.object({
  username: z.string(),
  roles: z.array(z.string()),
  permissions: z.array(z.string()),
})
export type UserInfo = z.infer<typeof userInfoSchema>

export const userSummarySchema = z.object({
  id: z.string(),
  username: z.string(),
  is_active: z.boolean(),
  roles: z.array(z.string()), // global roles
})
export type UserSummary = z.infer<typeof userSummarySchema>
export const userListSchema = z.array(userSummarySchema)

// --- RBAC: roles catalog, groups, and per-lab grants. ---

// A role from the code catalog: which scopes it can be bound at, what it grants.
export const roleSchema = z.object({
  name: z.string(),
  scopes: z.array(z.string()), // subset of "global" | "lab"
  permissions: z.array(z.string()),
})
export type Role = z.infer<typeof roleSchema>
export const roleListSchema = z.array(roleSchema)

export const groupMemberSchema = z.object({ id: z.string(), username: z.string() })
export type GroupMember = z.infer<typeof groupMemberSchema>

export const groupSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  members: z.array(groupMemberSchema),
  roles: z.array(z.string()), // global roles held by the group
})
export type GroupSummary = z.infer<typeof groupSummarySchema>
export const groupListSchema = z.array(groupSummarySchema)

// A pickable principal (user or group) for the grant UI: id + display name only.
export const principalSchema = z.object({ id: z.string(), name: z.string() })
export type Principal = z.infer<typeof principalSchema>
export const principalsResponseSchema = z.object({
  users: z.array(principalSchema),
  groups: z.array(principalSchema),
})
export type PrincipalsResponse = z.infer<typeof principalsResponseSchema>

// A role grant on a lab: who (user or group) holds which lab role.
export const grantSchema = z.object({
  id: z.string(),
  principal_type: z.string(), // "user" | "group"
  principal_id: z.string(),
  principal_name: z.string().nullable(),
  role: z.string(),
})
export type Grant = z.infer<typeof grantSchema>
export const grantListSchema = z.array(grantSchema)

export const labNodeStateSchema = z.object({
  name: z.string(),
  container: z.string(),
  image: z.string(),
  state: z.string(),
  mgmt_ip: z.string(), // bare management IP for the ssh command; "" when none
})
export type LabNodeState = z.infer<typeof labNodeStateSchema>

// config_time_status: the last config-time validation gate — "not_run" (never
// run / skipped since), "passed", or "failed" (the lab is deployed but its
// config-time suites did not all pass).
export const configTimeStatusSchema = z.enum(['not_run', 'passed', 'failed'])
export type ConfigTimeStatus = z.infer<typeof configTimeStatusSchema>

export const labSummarySchema = z.object({
  name: z.string(),
  status: z.string(), // "created" | "deploying" | "deployed" | "destroyed"
  owner: principalSchema.nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  nodes: z.number(), // containers present
  nodes_running: z.number(), // containers actually running
  config_time_status: configTimeStatusSchema,
  // Delta 19: true = the stored definition no longer matches the deployed
  // snapshot; null = nothing running to drift from (or snapshot unknown).
  definition_drifted: z.boolean().nullable(),
  permissions: z.array(z.string()), // the caller's effective permissions on this lab
})
export type LabSummary = z.infer<typeof labSummarySchema>
export const labListSchema = z.array(labSummarySchema)

export const labDetailSchema = z.object({
  name: z.string(),
  status: z.string(),
  definition: z.string().nullable(), // null until authored (status "created")
  // Delta 19: the definition of the last successful deploy — what the running
  // lab was built from; null until first deployed / after destroy.
  deployed_definition: z.string().nullable(),
  definition_drifted: z.boolean().nullable(),
  owner: principalSchema.nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  nodes: z.array(labNodeStateSchema),
  config_time_status: configTimeStatusSchema,
  // Delta 21: true while this lab is published as a network template (the
  // PUT /labs/{name}/template toggle) — the header renders the toggle state.
  template_published: z.boolean(),
  permissions: z.array(z.string()), // the caller's effective permissions on this lab
})
export type LabDetail = z.infer<typeof labDetailSchema>

// --- Topology layout (delta 19): ONE shared manual arrangement per lab,
// keyed by canvas element id (node names + pseudo-nodes like LAN hubs) —
// opaque to the server, replace-on-PUT. ---
export const layoutPositionSchema = z.object({ x: z.number(), y: z.number() })
// Delta 20: per-group canvas styling, keyed by group name (color is
// server-pinned to #rrggbb).
export const layoutGroupStyleSchema = z.object({ color: z.string() })
export const labLayoutSchema = z.object({
  positions: z.record(z.string(), layoutPositionSchema),
  groups: z.record(z.string(), layoutGroupStyleSchema),
})
export type LabLayout = z.infer<typeof labLayoutSchema>

// Ownership transfer response: the lab plus its new owner.
export const labOwnerSchema = z.object({
  lab: z.string(),
  owner: principalSchema,
})
export type LabOwner = z.infer<typeof labOwnerSchema>

// --- Test suites (v2, contract delta 17; see components/lab/test-suites). A
// suite groups tests; each test runs a device-keyed CASE on nodes — the case
// renders Jinja templates against the lab's facts, executes, optionally
// parses (json | textfsm), and asserts (raw matchers or a napalm-validate
// compare spec). A suite's stage controls only automatic execution. ---

export const testExpectationSchema = z.object({
  contains: z.string().nullable().optional(),
  not_contains: z.string().nullable().optional(),
  matches: z.string().nullable().optional(),
  compare: z.record(z.string(), z.unknown()).nullable().optional(),
})
export type TestExpectation = z.infer<typeof testExpectationSchema>

export const testCaseSchema = z.object({
  command: z.string(),
  expect: testExpectationSchema,
  parse: z.enum(['json', 'textfsm']).nullable().optional(),
  interactive: z.boolean().optional(),
})
export type TestCase = z.infer<typeof testCaseSchema>

export const validationTestSchema = z.object({
  nodes: z.array(z.string()),
  // One case for all nodes, or a device-keyed dict (a TestCase always carries
  // `command`, so presence of that key discriminates the union).
  run: z.union([testCaseSchema, z.record(z.string(), testCaseSchema)]),
  wait: z.number(),
  description: z.string(),
})
export type ValidationTest = z.infer<typeof validationTestSchema>

export const testSuiteSchema = z.object({
  stage: z.string(), // "config-time" | "runtime"
  description: z.string(),
  tests: z.record(z.string(), validationTestSchema),
})
export type TestSuite = z.infer<typeof testSuiteSchema>

export const testResultSchema = z.object({
  test: z.string(),
  node: z.string(),
  status: z.string(), // "pass" | "fail" | "skip" | "error"
  command: z.string(), // the RENDERED command (what actually ran)
  output: z.string(),
  detail: z.string(),
  diff: z.record(z.string(), z.unknown()).nullable().optional(),
  elapsed_ms: z.number(),
})
export type TestResult = z.infer<typeof testResultSchema>

export const labFactsSchema = z.object({
  // Raw netlab node dicts keyed by short node name — PROVISIONAL/unpinned
  // until the pre-v1.0 pinning decision; the endpoint is the insulation.
  nodes: z.record(z.string(), z.record(z.string(), z.unknown())),
})
export type LabFacts = z.infer<typeof labFactsSchema>

export const catalogDeviceSchema = z.object({
  device: z.string(), // netlab device slug; unpinned — the set widens by testing
  label: z.string(),
  role: z.enum(['router', 'host']),
  modules: z.array(z.string()), // netlab vocabulary; the builder intersects
  image: z.string(), // netlab's default clab image (untagged = ":latest")
  image_present: z.boolean().nullable(), // null = presence unknown (see live)
  config_import: z.boolean(), // delta 22: dumped configs of this device import
})
export type CatalogDeviceWire = z.infer<typeof catalogDeviceSchema>

export const deviceCatalogSchema = z.object({
  devices: z.array(catalogDeviceSchema),
  live: z.boolean(), // false = image presence could not be resolved
})
export type DeviceCatalogWire = z.infer<typeof deviceCatalogSchema>

// --- Template library (delta 21): two sibling collections with independent
// namespaces — /templates/network (complete definitions; builtin tier is
// shipped, user tier is a PUBLISHED lab served live) and /templates/node
// (single-node fragments the builder stamps into an open doc). ---
export const templateTierSchema = z.enum(['builtin', 'user'])

export const networkTemplateSummarySchema = z.object({
  name: z.string(),
  tier: templateTierSchema,
  description: z.string(), // the library-card text
  source_lab: z.string().nullable(), // user tier: the published lab (live view)
})
export type NetworkTemplateSummary = z.infer<typeof networkTemplateSummarySchema>
export const networkTemplateListSchema = z.array(networkTemplateSummarySchema)

export const networkTemplateSchema = networkTemplateSummarySchema.extend({
  content: z.string(), // a complete netlab definition; PUT re-pins name/subnet
})
export type NetworkTemplate = z.infer<typeof networkTemplateSchema>

export const nodeTemplateSchema = z.object({
  name: z.string(),
  tier: templateTierSchema,
  description: z.string(),
  device: z.string(), // the fragment's device (required in the fragment)
  content: z.string(), // YAML node-attribute mapping, no node name
})
export type NodeTemplateWire = z.infer<typeof nodeTemplateSchema>
export const nodeTemplateListSchema = z.array(nodeTemplateSchema)

// --- Config import (delta 22): the definition factory. Nothing is dropped —
// every source line is modeled (skeleton), carried (custom-config) or
// quarantined (kept unattached); the completeness is server-enforced. ---
export const quarantineClassSchema = z.enum(['mgmt', 'auth', 'telemetry', 'hardware'])
export type QuarantineClass = z.infer<typeof quarantineClassSchema>

export const quarantineEntrySchema = z.object({
  reason: quarantineClassSchema,
  content: z.string(), // verbatim source lines, hierarchy preserved
})
export type QuarantineEntry = z.infer<typeof quarantineEntrySchema>

export const importWarningSchema = z.object({
  node: z.string().nullable(), // null = network-level
  message: z.string(),
})
export type ImportWarning = z.infer<typeof importWarningSchema>

// Delta 23: the subnet join as ADVICE — proposed wiring to prefill the
// editor with. The import consumes only the explicit list it is then given.
export const wiringSuggestionSchema = z.object({
  wiring: z.array(z.array(z.string())), // "node:interface" endpoints
  warnings: z.array(importWarningSchema), // what addressing cannot place
})
export type WiringSuggestion = z.infer<typeof wiringSuggestionSchema>

export const networkImportSchema = z.object({
  definition: z.string(), // no name:/mgmt — the receiving lab's PUT pins both
  custom_config: z.record(z.string(), z.string()), // ready for the custom-config
  //   PUT verbatim; quarantine files are present but UNREFERENCED
  interface_map: z.record(z.string(), z.record(z.string(), z.string())),
  name_map: z.record(z.string(), z.string()),
  quarantine: z.record(z.string(), z.array(quarantineEntrySchema)),
  warnings: z.array(importWarningSchema),
})
export type NetworkImport = z.infer<typeof networkImportSchema>

export const nodeImportSchema = z.object({
  fragment: z.string(), // stampable node-attribute mapping naming device
  config: z.string(), // the carry — SOURCE interface names (the contract QUIRK)
  interfaces: z.record(z.string(), z.string().nullable()),
  quarantine: z.array(quarantineEntrySchema),
  warnings: z.array(importWarningSchema),
})
export type NodeImport = z.infer<typeof nodeImportSchema>

export const nodeConfigDiffSchema = z.object({
  node: z.string(),
  matched: z.number(),
  missing: z.array(z.string()), // the lines to look at
  extra: z.array(z.string()), // expected noise (lab baseline, NOS defaults)
  quarantined: z.number(),
})
export const configDiffReportSchema = z.object({
  nodes: z.array(nodeConfigDiffSchema),
})
export type ConfigDiffReport = z.infer<typeof configDiffReportSchema>

export const suiteReportSchema = z.object({
  suite: z.string(),
  stage: z.string(),
  passed: z.number(),
  failed: z.number(),
  skipped: z.number(),
  errored: z.number(),
  ran_at: z.string(),
  results: z.array(testResultSchema),
})
export type SuiteReport = z.infer<typeof suiteReportSchema>

export const testSuitesResponseSchema = z.object({
  test_suites: z.record(z.string(), testSuiteSchema),
  last_validation: z.record(z.string(), suiteReportSchema),
  config_time_status: configTimeStatusSchema,
})
export type TestSuitesResponse = z.infer<typeof testSuitesResponseSchema>

export const builtinTemplateSchema = z.object({
  name: z.string(),
  description: z.string(),
  files: z.record(z.string(), z.string()),
})
export type BuiltinTemplate = z.infer<typeof builtinTemplateSchema>

export const customConfigResponseSchema = z.object({
  builtin: z.array(builtinTemplateSchema),
  custom_config: z.record(z.string(), z.string()),
})
export type CustomConfigResponse = z.infer<typeof customConfigResponseSchema>

export const nodeConfigResultSchema = z.object({
  node: z.string(),
  status: z.string(), // "configured" | "failed"
  changed: z.number(),
  failed: z.number(),
})
export type NodeConfigResult = z.infer<typeof nodeConfigResultSchema>

// Deploy/configure/destroy shapes are JOB RESULT payloads (parsed out of
// job.result once the job succeeds), not response bodies.
export const deployResponseSchema = z.object({
  status: z.string(),
  lab_name: z.string(),
  nodes: z.array(z.string()),
  configuration: z.array(nodeConfigResultSchema).nullable().optional(),
  validation: z.array(suiteReportSchema).nullable().optional(),
})
export type DeployResponse = z.infer<typeof deployResponseSchema>

export const configureResponseSchema = z.object({
  status: z.string(),
  lab_name: z.string(),
  configuration: z.array(nodeConfigResultSchema),
  validation: z.array(suiteReportSchema).nullable().optional(),
})
export type ConfigureResponse = z.infer<typeof configureResponseSchema>

export const destroyResponseSchema = z.object({
  status: z.string(),
  detail: z.string(),
})
export type DestroyResponse = z.infer<typeof destroyResponseSchema>

export const labActionResponseSchema = z.object({
  message: z.string(),
})
export type LabActionResponse = z.infer<typeof labActionResponseSchema>

export const nodeLogsResponseSchema = z.object({
  node: z.string(),
  container: z.string(),
  logs: z.string(),
})
export type NodeLogsResponse = z.infer<typeof nodeLogsResponseSchema>

export const nodeInterfaceSchema = z.object({
  name: z.string(),
  alias: z.string(),
  ifindex: z.number(),
  mac: z.string(),
  mtu: z.number(),
  state: z.string(),
  kind: z.string(),
})
export type NodeInterface = z.infer<typeof nodeInterfaceSchema>

export const nodeInterfacesSchema = z.object({
  node: z.string(),
  interfaces: z.array(nodeInterfaceSchema),
})
export type NodeInterfaces = z.infer<typeof nodeInterfacesSchema>
export const labInterfacesSchema = z.array(nodeInterfacesSchema)

export const saveConfigResponseSchema = z.object({
  message: z.string(),
  output: z.string(),
})
export type SaveConfigResponse = z.infer<typeof saveConfigResponseSchema>

// A netem duration as a structured {value, unit} pair; the author's unit
// choice is preserved by the backend.
export const durationSchema = z.object({
  value: z.number(),
  unit: z.enum(['us', 'ms', 's']),
})
export type Duration = z.infer<typeof durationSchema>

// Current netem link impairment on one node interface (see components/lab/netem).
// null / 0 means that dimension is unshaped; loss/corruption are percentages;
// rate is kbit/s.
export const netemImpairmentSchema = z.object({
  interface: z.string(),
  delay: durationSchema.nullable(),
  jitter: durationSchema.nullable(),
  loss: z.number(),
  rate: z.number(),
  corruption: z.number(),
})
export type NetemImpairment = z.infer<typeof netemImpairmentSchema>
export const nodeNetemSchema = z.array(netemImpairmentSchema)

// The lab's logical link table (contract delta 14): netlab-derived links with
// per-endpoint live state and active impairment. `endpoint.interface` is the
// container-side name — exactly what /interfaces reports and netem accepts.
export const linkEndpointSchema = z.object({
  node: z.string(),
  interface: z.string(),
  ifname: z.string(),
  ifindex: z.number(),
  ipv4: z.string().nullable(),
  ipv6: z.string().nullable(),
  // Live oper state passthrough (unpinned, like NodeInterface.state); null =
  // unknown. Impairment is orthogonal to state on purpose.
  state: z.string().nullable(),
  impairment: netemImpairmentSchema.nullable(),
})
export type LinkEndpoint = z.infer<typeof linkEndpointSchema>

export const labLinkSchema = z.object({
  index: z.number(),
  name: z.string().nullable(),
  // netlab's vocabulary — unpinned and NOT a rendering signal (a linux-host
  // p2p comes out "lan"); discriminate on endpoints.length instead.
  type: z.string(),
  prefix_ipv4: z.string().nullable(),
  prefix_ipv6: z.string().nullable(),
  bandwidth: z.number().nullable(),
  mtu: z.number().nullable(),
  // Twinlab-derived, so pinned: the roll-up of the endpoints' states.
  oper_state: z.enum(['up', 'degraded', 'down', 'unknown']),
  endpoints: z.array(linkEndpointSchema),
})
export type LabLink = z.infer<typeof labLinkSchema>
export type LinkOperState = LabLink['oper_state']

// `live: false` = oper state could not be resolved (undeployed lab, or the
// inventory was unavailable) — every state is then "unknown".
export const labLinksSchema = z.object({
  links: z.array(labLinkSchema),
  live: z.boolean(),
})
export type LabLinks = z.infer<typeof labLinksSchema>

// Impairment to apply — REPLACE semantics: the body is the interface's COMPLETE
// desired impairment. An omitted dimension is cleared, and a body with only the
// interface clears everything on it (there is no separate reset endpoint).
export interface NetemSetInput {
  interface: string
  delay?: Duration
  jitter?: Duration
  loss?: number
  rate?: number
  corruption?: number
}

// Whole-lab power controls (clab-api native). The node menu adds pause/unpause;
// whole-lab freeze reuses those verbs via a backend fan-out.
export type LifecycleAction = 'start' | 'stop' | 'restart'
export type FreezeAction = 'pause' | 'unpause'
export type NodeAction = LifecycleAction | FreezeAction

// Batch runtime actions (delta 24): many impairments + node power events in one
// request. A netem item is the single route's body plus `node` and the `kind`
// tag — the same shape, never a second spelling.
export type RuntimeActionInput =
  | ({ kind: 'netem'; node: string } & NetemSetInput)
  | { kind: 'power'; node: string; action: NodeAction }

// Index-aligned with the submitted list. A failed item is DATA — the batch
// itself still returns 2xx, so `ok` is the only place failure shows up.
export const runtimeActionResultSchema = z.object({
  ok: z.boolean(),
  code: z.string().nullable(),
  message: z.string(),
})
export const runtimeActionsReportSchema = z.object({
  results: z.array(runtimeActionResultSchema),
})
export type RuntimeActionsReport = z.infer<typeof runtimeActionsReportSchema>

// --- Async jobs (contract delta 12). The four long operations (deploy,
// configure, destroy, suite run) return 202 + a Job; callers poll it to its
// terminal state. `result` is set only on "succeeded" and is the operation's
// payload (DeployResponse / ConfigureResponse / DestroyResponse / SuiteReport,
// typed by `kind`). A FAILED job means could-not-run; an operation that ran
// with a bad outcome (config_failed / validation_failed) is a SUCCEEDED job
// whose result.status says so. ---

export const jobErrorSchema = z.object({
  status_code: z.number(), // HTTP vocabulary classifier, not a response status
  code: z.string(),
  message: z.string(),
  extras: z.record(z.string(), z.unknown()),
})
export type JobError = z.infer<typeof jobErrorSchema>

export const jobSchema = z.object({
  id: z.string(),
  lab_name: z.string(),
  kind: z.enum(['deploy', 'configure', 'destroy', 'suite_run']),
  status: z.enum(['running', 'succeeded', 'failed']),
  request: z.record(z.string(), z.unknown()),
  result: z.record(z.string(), z.unknown()).nullable(),
  error: jobErrorSchema.nullable(),
  created_at: z.string(),
  finished_at: z.string().nullable(),
})
export type Job = z.infer<typeof jobSchema>
export const jobListSchema = z.array(jobSchema)

// --- Self-service credentials (API keys, SSH keys) and the jump coordinates. ---

export const apiKeySchema = z.object({
  id: z.string(),
  name: z.string(),
  created_at: z.string(),
  last_used_at: z.string().nullable(),
})
export type ApiKey = z.infer<typeof apiKeySchema>
export const apiKeyListSchema = z.array(apiKeySchema)

// The Bearer secret is returned only at creation, stored hashed server-side.
export const apiKeyCreatedSchema = z.object({
  key: z.string(),
  info: apiKeySchema,
})
export type ApiKeyCreated = z.infer<typeof apiKeyCreatedSchema>

export const sshKeySchema = z.object({
  id: z.string(),
  name: z.string(),
  algorithm: z.string(),
  fingerprint: z.string(), // "SHA256:<base64>", as `ssh-keygen -lf` prints
  comment: z.string().nullable(),
  created_at: z.string(),
  last_used_at: z.string().nullable(), // last OFFERED at the jump host
})
export type SshKey = z.infer<typeof sshKeySchema>
export const sshKeyListSchema = z.array(sshKeySchema)

// The private key exists only in this response — the public half is registered,
// the private half is never stored server-side.
export const sshKeyGeneratedSchema = z.object({
  private_key: z.string(),
  info: sshKeySchema,
})
export type SshKeyGenerated = z.infer<typeof sshKeyGeneratedSchema>

// Jump-host coordinates for external SSH to lab nodes:
// ssh -o ProxyJump={user}@{host}:{port} <node-user>@<node-mgmt-ip>
export const sshAccessSchema = z.object({
  enabled: z.boolean(),
  host: z.string().nullable(),
  port: z.number().nullable(),
  user: z.string().nullable(),
})
export type SshAccess = z.infer<typeof sshAccessSchema>

// A lab lifecycle event pushed over SSE (see lib/use-lab-events).
export const labEventSchema = z.object({
  lab: z.string(),
  node: z.string().nullable(),
  action: z.string(),
  timestamp: z.string(),
})
export type LabEvent = z.infer<typeof labEventSchema>

// The stream's other payload (SSE event name `job`): a poke saying which job
// changed and to what — the record is read back from the jobs endpoints.
export const jobEventSchema = z.object({
  lab: z.string(),
  job_id: z.string(),
  kind: z.enum(['deploy', 'configure', 'destroy', 'suite_run']),
  status: z.enum(['running', 'succeeded', 'failed']),
  timestamp: z.string(),
})
export type JobEvent = z.infer<typeof jobEventSchema>
