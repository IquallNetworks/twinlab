import { z } from 'zod'

import {
  apiKeyCreatedSchema,
  apiKeyListSchema,
  deviceCatalogSchema,
  grantSchema,
  grantListSchema,
  groupListSchema,
  groupSummarySchema,
  jobListSchema,
  jobSchema,
  labActionResponseSchema,
  labDetailSchema,
  labInterfacesSchema,
  labFactsSchema,
  labLayoutSchema,
  labLinksSchema,
  labListSchema,
  labOwnerSchema,
  nodeLogsResponseSchema,
  nodeNetemSchema,
  principalsResponseSchema,
  roleListSchema,
  saveConfigResponseSchema,
  sshAccessSchema,
  sshKeyGeneratedSchema,
  sshKeyListSchema,
  sshKeySchema,
  customConfigResponseSchema,
  testSuitesResponseSchema,
  userInfoSchema,
  userListSchema,
  userSummarySchema,
  type FreezeAction,
  type Job,
  type LifecycleAction,
  type NetemSetInput,
  type NodeAction,
} from '@/lib/schemas'

// The frontend is served same-origin with the backend (the dev server proxies
// /api/v1 → backend), so the httpOnly session cookie rides along automatically;
// there is no token to store or attach here.
const BASE = '/api/v1'

/** A failed backend response or job, carrying the HTTP status (so callers can
 * branch, e.g. 401 → not authenticated / 404 → no such lab), the stable error
 * code slug, and the human-readable message from the one v1.0 error envelope
 * `{code, message, extras}` every non-2xx wears. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string | null
  readonly extras: Record<string, unknown> | null

  constructor(
    status: number,
    message: string,
    code: string | null = null,
    extras: Record<string, unknown> | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.extras = extras
  }
}

interface Envelope {
  message: string
  code: string | null
  extras: Record<string, unknown> | null
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

async function envelope(resp: Response): Promise<Envelope> {
  try {
    const body: unknown = await resp.json()
    const { code, message, extras } = body as {
      code?: unknown
      message?: unknown
      extras?: unknown
    }
    if (typeof message === 'string') {
      return {
        message,
        code: typeof code === 'string' ? code : null,
        extras: isPlainRecord(extras) ? extras : null,
      }
    }
    return { message: `HTTP ${resp.status}`, code: null, extras: null }
  } catch {
    return { message: `HTTP ${resp.status}`, code: null, extras: null }
  }
}

async function toApiError(resp: Response): Promise<ApiError> {
  const { message, code, extras } = await envelope(resp)
  return new ApiError(resp.status, message, code, extras)
}

async function request<S extends z.ZodType>(
  path: string,
  schema: S,
  init?: RequestInit,
): Promise<z.infer<S>> {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!resp.ok) throw await toApiError(resp)
  return schema.parse(await resp.json())
}

async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!resp.ok) throw await toApiError(resp)
}

export interface CreateUserInput {
  username: string
  password: string
  roles: string[]
}

export interface CreateGrantInput {
  principal_type: 'user' | 'group'
  principal_id: string
  role: string
}

export const api = {
  me: () => request('/auth/me', userInfoSchema),
  login: (username: string, password: string) =>
    request('/auth/login', userInfoSchema, {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: () => requestVoid('/auth/logout', { method: 'POST' }),
  // Self-service change: needs the current password (403 invalid_credentials if
  // wrong). Keeps THIS session and revokes the user's others, so no re-login.
  changePassword: (currentPassword: string, newPassword: string) =>
    requestVoid('/auth/password', {
      method: 'PUT',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),

  listUsers: () => request('/users', userListSchema),
  createUser: (input: CreateUserInput) =>
    request('/users', userSummarySchema, { method: 'POST', body: JSON.stringify(input) }),
  setRoles: (userId: string, roles: string[]) =>
    request(`/users/${userId}/roles`, userSummarySchema, {
      method: 'PUT',
      body: JSON.stringify({ roles }),
    }),

  // The role catalog (names + scopes + permissions), served from the backend so
  // role pickers don't hardcode the list. Any authenticated user may read it.
  listRoles: () => request('/roles', roleListSchema),

  // The deployable-device catalog (delta 18): supported devices with module
  // support, default images, best-effort image presence. Any authenticated user.
  deviceCatalog: () => request('/catalog', deviceCatalogSchema),

  // Minimal user+group directory (id + name) for the grant picker, available to any
  // authenticated caller (a lab owner may lack the global user/group-manage rights).
  listPrincipals: () => request('/principals', principalsResponseSchema),

  // Groups (group:manage). A group holds global roles and can be granted lab roles;
  // members inherit both.
  listGroups: () => request('/groups', groupListSchema),
  createGroup: (name: string, description: string) =>
    request('/groups', groupSummarySchema, {
      method: 'POST',
      body: JSON.stringify({ name, description }),
    }),
  deleteGroup: (id: string) => requestVoid(`/groups/${id}`, { method: 'DELETE' }),
  setGroupMembers: (id: string, userIds: string[]) =>
    request(`/groups/${id}/members`, groupSummarySchema, {
      method: 'PUT',
      body: JSON.stringify({ user_ids: userIds }),
    }),
  setGroupRoles: (id: string, roles: string[]) =>
    request(`/groups/${id}/roles`, groupSummarySchema, {
      method: 'PUT',
      body: JSON.stringify({ roles }),
    }),

  // Per-lab grants + ownership (lab:grant on the lab). A grant binds a lab role to a
  // user or group; transfer reassigns ownership (owner-equivalent callers only).
  listGrants: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}/grants`, grantListSchema),
  createGrant: (name: string, input: CreateGrantInput) =>
    request(`/labs/${encodeURIComponent(name)}/grants`, grantSchema, {
      method: 'POST',
      body: JSON.stringify(input),
    }),
  deleteGrant: (name: string, bindingId: string) =>
    requestVoid(`/labs/${encodeURIComponent(name)}/grants/${bindingId}`, { method: 'DELETE' }),
  transferOwner: (name: string, userId: string) =>
    request(`/labs/${encodeURIComponent(name)}/owner`, labOwnerSchema, {
      method: 'PUT',
      body: JSON.stringify({ user_id: userId }),
    }),

  listLabs: () => request('/labs', labListSchema),
  getLab: (name: string) => request(`/labs/${encodeURIComponent(name)}`, labDetailSchema),

  // The lifecycle split: create a bare record (name only), author the definition
  // via PUT, then deploy from the stored definition. The four long operations
  // (deploy/configure/destroy/suite run) return 202 + a Job — await them with
  // waitJob() below.
  createLab: (name: string) =>
    request('/labs', labDetailSchema, { method: 'POST', body: JSON.stringify({ name }) }),
  updateLabDefinition: (name: string, definition: string) =>
    request(`/labs/${encodeURIComponent(name)}`, labDetailSchema, {
      method: 'PUT',
      body: JSON.stringify({ definition }),
    }),
  // skipConfigTimeChecks bypasses the automatic config-time suites (only meaningful
  // alongside configure); it is off by default so convergence gating is on.
  deployLab: (name: string, configure: boolean, skipConfigTimeChecks = false) =>
    request(`/labs/${encodeURIComponent(name)}/deploy`, jobSchema, {
      method: 'POST',
      body: JSON.stringify({ configure, skip_config_time_checks: skipConfigTimeChecks }),
    }),
  configureLab: (name: string, skipConfigTimeChecks = false) =>
    request(`/labs/${encodeURIComponent(name)}/configure`, jobSchema, {
      method: 'POST',
      body: JSON.stringify({ skip_config_time_checks: skipConfigTimeChecks }),
    }),
  destroyLab: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}`, jobSchema, { method: 'DELETE' }),
  // Delete removes the lab from the catalog (soft-delete: the record is retained
  // server-side but hidden). `remove=true` also tears the lab down first if it's
  // still up, so a running or already-destroyed lab can both be deleted.
  deleteLab: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}?remove=true`, jobSchema, { method: 'DELETE' }),

  getJob: (name: string, jobId: string) =>
    request(`/labs/${encodeURIComponent(name)}/jobs/${jobId}`, jobSchema),
  listJobs: (name: string, limit = 20) =>
    request(`/labs/${encodeURIComponent(name)}/jobs?limit=${limit}`, jobListSchema),
  // Every readable lab's recent jobs in one query (each job names its lab).
  // Excludes removed labs, so a destroy-with-remove leaves this list when its
  // record does — that job is followed by id on its own lab route.
  listAllJobs: (limit = 50) => request(`/jobs?limit=${limit}`, jobListSchema),
  nodeAction: (name: string, node: string, action: NodeAction) =>
    request(
      `/labs/${encodeURIComponent(name)}/nodes/${encodeURIComponent(node)}/${action}`,
      labActionResponseSchema,
      { method: 'POST' },
    ),
  labAction: (name: string, action: LifecycleAction) =>
    request(`/labs/${encodeURIComponent(name)}/${action}`, labActionResponseSchema, {
      method: 'POST',
    }),
  // Whole-lab freeze; the backend fans pause/unpause out over the nodes.
  freezeLab: (name: string, action: FreezeAction) =>
    request(`/labs/${encodeURIComponent(name)}/${action}`, labActionResponseSchema, {
      method: 'POST',
    }),
  saveLabConfig: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}/save`, saveConfigResponseSchema, {
      method: 'POST',
    }),
  nodeLogs: (name: string, node: string, tail = 200) =>
    request(
      `/labs/${encodeURIComponent(name)}/nodes/${encodeURIComponent(node)}/logs?tail=${tail}`,
      nodeLogsResponseSchema,
    ),
  labInterfaces: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}/interfaces`, labInterfacesSchema),
  // The netlab-derived logical link table with per-endpoint live state and
  // active impairment; 409 no_definition on a bare created record.
  labLinks: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}/links`, labLinksSchema),
  labLayout: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}/layout`, labLayoutSchema),
  // Full REPLACE ({} clears): the caller always sends the complete current
  // arrangement. lab:edit — the Build tab is the only writer.
  putLabLayout: (name: string, positions: Record<string, { x: number; y: number }>) =>
    request(`/labs/${encodeURIComponent(name)}/layout`, labLayoutSchema, {
      method: 'PUT',
      body: JSON.stringify({ positions }),
    }),

  // Netem link impairment, keyed by node + interface (the backend resolves the
  // node to its container). Set takes lab:configure; show takes lab:read. Set
  // REPLACES the interface's impairment: sending only { interface } clears it.
  nodeNetem: (name: string, node: string) =>
    request(
      `/labs/${encodeURIComponent(name)}/nodes/${encodeURIComponent(node)}/netem`,
      nodeNetemSchema,
    ),
  setNodeNetem: (name: string, node: string, input: NetemSetInput) =>
    request(
      `/labs/${encodeURIComponent(name)}/nodes/${encodeURIComponent(node)}/netem`,
      labActionResponseSchema,
      { method: 'POST', body: JSON.stringify(input) },
    ),

  // Test suites. Read/author (lab:read / lab:edit); run one on demand
  // (lab:validate). `testSuites` is the raw suite map, validated server-side.
  getTestSuites: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}/test-suites`, testSuitesResponseSchema),
  // The fact namespace suite templates render against (delta 17): raw netlab
  // node dicts, provisional until pinned; 409 no_definition on a bare record.
  labFacts: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}/facts`, labFactsSchema),
  putTestSuites: (name: string, testSuites: unknown) =>
    request(`/labs/${encodeURIComponent(name)}/test-suites`, testSuitesResponseSchema, {
      method: 'PUT',
      body: JSON.stringify({ test_suites: testSuites }),
    }),
  // Runs are async jobs; the terminal job's result is the SuiteReport.
  runTestSuite: (name: string, suite: string) =>
    request(
      `/labs/${encodeURIComponent(name)}/test-suites/${encodeURIComponent(suite)}/run`,
      jobSchema,
      { method: 'POST' },
    ),

  // Custom-config templates. Read (lab:read) returns the shipped built-in library
  // plus the lab's user templates; author (lab:create) replaces the user fileset.
  // `customConfig` is a { relpath: source } map, validated server-side.
  getCustomConfig: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}/custom-config`, customConfigResponseSchema),
  putCustomConfig: (name: string, customConfig: unknown) =>
    request(`/labs/${encodeURIComponent(name)}/custom-config`, customConfigResponseSchema, {
      method: 'PUT',
      body: JSON.stringify({ custom_config: customConfig }),
    }),

  // Self-service API keys (Bearer credentials). The secret is shown once at
  // creation and stored hashed server-side.
  listApiKeys: () => request('/auth/api-keys', apiKeyListSchema),
  createApiKey: (name: string) =>
    request('/auth/api-keys', apiKeyCreatedSchema, {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  deleteApiKey: (keyId: string) => requestVoid(`/auth/api-keys/${keyId}`, { method: 'DELETE' }),

  // Self-service SSH public keys for the jump host. Generate returns the
  // private half exactly once; the server never stores it.
  listSshKeys: () => request('/auth/ssh-keys', sshKeyListSchema),
  createSshKey: (name: string, publicKey: string) =>
    request('/auth/ssh-keys', sshKeySchema, {
      method: 'POST',
      body: JSON.stringify({ name, public_key: publicKey }),
    }),
  generateSshKey: (name: string) =>
    request('/auth/ssh-keys/generate', sshKeyGeneratedSchema, {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  deleteSshKey: (keyId: string) => requestVoid(`/auth/ssh-keys/${keyId}`, { method: 'DELETE' }),

  // Jump-host coordinates for external SSH to lab nodes (enabled:false when the
  // deployment advertises none).
  getSshAccess: () => request('/ssh-access', sshAccessSchema),
}

// How often a pending job is re-read. Long operations take minutes; 1.5 s keeps
// completion latency low without hammering the backend.
const JOB_POLL_MS = 1500

/** Poll a submitted job to its terminal state. Resolves with the terminal Job
 * on success (callers parse `job.result` with the matching result schema);
 * rejects with an ApiError built from the job's error envelope when the
 * operation could not run. No deadline: deploys legitimately take minutes, and
 * mutation pending-states communicate progress meanwhile. */
export async function waitJob(name: string, job: Job): Promise<Job> {
  let current = job
  while (current.status === 'running') {
    await new Promise((resolve) => setTimeout(resolve, JOB_POLL_MS))
    current = await api.getJob(name, current.id)
  }
  if (current.status === 'failed') {
    // A failed job always carries its error envelope; the fallback is defensive.
    const error = current.error
    throw error
      ? new ApiError(error.status_code, error.message, error.code, error.extras)
      : new ApiError(500, `${current.kind} job failed`)
  }
  return current
}
