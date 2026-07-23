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

export const labSummarySchema = z.object({
  name: z.string(),
  status: z.string(), // "deployed" | "destroyed"
  owner: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  nodes: z.number(),
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
})
export type LabDetail = z.infer<typeof labDetailSchema>

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
})
export type DeployResponse = z.infer<typeof deployResponseSchema>

export const configureResponseSchema = z.object({
  status: z.string(),
  lab_name: z.string(),
  configuration: z.array(nodeConfigResultSchema),
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

// Whole-lab power controls (clab-api native). The node menu adds pause/unpause;
// whole-lab freeze reuses those verbs via a backend fan-out.
export type LifecycleAction = 'start' | 'stop' | 'restart'
export type FreezeAction = 'pause' | 'unpause'
export type NodeAction = LifecycleAction | FreezeAction
