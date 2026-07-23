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
  roles: z.array(z.string()),
})
export type UserSummary = z.infer<typeof userSummarySchema>
export const userListSchema = z.array(userSummarySchema)

export const labNodeStateSchema = z.object({
  name: z.string(),
  container: z.string(),
  image: z.string(),
  state: z.string(),
  mgmt_ip: z.string(), // bare management IP for the ssh command; "" when none
})
export type LabNodeState = z.infer<typeof labNodeStateSchema>

// config_time_ok: the last config-time validation gate — null (not run / skipped
// / no config-time suites), true (passed), false (failed).
export const labSummarySchema = z.object({
  name: z.string(),
  status: z.string(), // "deployed" | "destroyed"
  owner: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  nodes: z.number(),
  config_time_ok: z.boolean().nullable(),
})
export type LabSummary = z.infer<typeof labSummarySchema>
export const labListSchema = z.array(labSummarySchema)

export const labDetailSchema = z.object({
  name: z.string(),
  status: z.string(),
  definition: z.string(),
  owner: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  nodes: z.array(labNodeStateSchema),
  config_time_ok: z.boolean().nullable(),
})
export type LabDetail = z.infer<typeof labDetailSchema>

// --- Test suites (see components/lab/test-suites). A suite groups tests; each
// runs a command on nodes and matches its stdout with one safe primitive. A
// suite's stage (config-time | runtime) controls only automatic execution. ---

export const testExpectationSchema = z.object({
  contains: z.string().nullable().optional(),
  not_contains: z.string().nullable().optional(),
  matches: z.string().nullable().optional(),
  json_path: z.string().nullable().optional(),
  equals: z.union([z.string(), z.number(), z.boolean()]).nullable().optional(),
})
export type TestExpectation = z.infer<typeof testExpectationSchema>

export const validationTestSchema = z.object({
  nodes: z.array(z.string()),
  command: z.string(),
  expect: testExpectationSchema,
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
  command: z.string(),
  output: z.string(),
  detail: z.string(),
  elapsed_ms: z.number(),
})
export type TestResult = z.infer<typeof testResultSchema>

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
  config_time_ok: z.boolean().nullable(),
})
export type TestSuitesResponse = z.infer<typeof testSuitesResponseSchema>

export const nodeConfigResultSchema = z.object({
  node: z.string(),
  status: z.string(), // "configured" | "failed"
  changed: z.number(),
  failed: z.number(),
})
export type NodeConfigResult = z.infer<typeof nodeConfigResultSchema>

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

// Current netem link impairment on one node interface (see components/lab/netem).
// delay/jitter are netem duration strings ("50ms", "" when unset); loss/corruption
// are percentages; rate is kbit/s (0 = unshaped).
export const netemImpairmentSchema = z.object({
  interface: z.string(),
  delay: z.string(),
  jitter: z.string(),
  loss: z.number(),
  rate: z.number(),
  corruption: z.number(),
})
export type NetemImpairment = z.infer<typeof netemImpairmentSchema>
export const nodeNetemSchema = z.array(netemImpairmentSchema)

// Impairment to apply. Every field is optional and independent; the backend
// rejects an all-empty set and jitter without delay. Omitted fields are left
// unchanged rather than zeroed, so we send only the ones the user filled in.
export interface NetemSetInput {
  interface: string
  delay?: string
  jitter?: string
  loss?: number
  rate?: number
  corruption?: number
}

// Whole-lab power controls (clab-api native). The node menu adds pause/unpause;
// whole-lab freeze reuses those verbs via a backend fan-out.
export type LifecycleAction = 'start' | 'stop' | 'restart'
export type FreezeAction = 'pause' | 'unpause'
export type NodeAction = LifecycleAction | FreezeAction

// A lab lifecycle event pushed over SSE (see lib/use-lab-events).
export const labEventSchema = z.object({
  lab: z.string(),
  node: z.string().nullable(),
  action: z.string(),
  timestamp: z.string(),
})
export type LabEvent = z.infer<typeof labEventSchema>
