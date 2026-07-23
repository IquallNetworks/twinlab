import { z } from 'zod'

import {
  configureResponseSchema,
  deployResponseSchema,
  destroyResponseSchema,
  labActionResponseSchema,
  labDetailSchema,
  labInterfacesSchema,
  labListSchema,
  nodeLogsResponseSchema,
  nodeNetemSchema,
  saveConfigResponseSchema,
  suiteReportSchema,
  customConfigResponseSchema,
  testSuitesResponseSchema,
  userInfoSchema,
  userListSchema,
  userSummarySchema,
  type FreezeAction,
  type LifecycleAction,
  type NetemSetInput,
  type NodeAction,
} from '@/lib/schemas'

// The frontend is served same-origin with the backend (the dev server proxies
// /api/v1 → backend), so the httpOnly session cookie rides along automatically;
// there is no token to store or attach here.
const BASE = '/api/v1'

/** A failed backend response, carrying the HTTP status so callers can branch
 * (e.g. 401 → not authenticated) and a message lifted from FastAPI's `detail`. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function errorMessage(resp: Response): Promise<string> {
  try {
    const body: unknown = await resp.json()
    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    // Our lab/user errors return a structured detail object with a `message`.
    if (detail && typeof detail === 'object') {
      const message = (detail as { message?: unknown }).message
      if (typeof message === 'string') return message
      return JSON.stringify(detail)
    }
    return `HTTP ${resp.status}`
  } catch {
    return `HTTP ${resp.status}`
  }
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
  if (!resp.ok) throw new ApiError(resp.status, await errorMessage(resp))
  return schema.parse(await resp.json())
}

async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!resp.ok) throw new ApiError(resp.status, await errorMessage(resp))
}

export interface CreateUserInput {
  username: string
  password: string
  roles: string[]
}

export const api = {
  me: () => request('/auth/me', userInfoSchema),
  login: (username: string, password: string) =>
    request('/auth/login', userInfoSchema, {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: () => requestVoid('/auth/logout', { method: 'POST' }),

  listUsers: () => request('/users', userListSchema),
  createUser: (input: CreateUserInput) =>
    request('/users', userSummarySchema, { method: 'POST', body: JSON.stringify(input) }),
  setRoles: (userId: string, roles: string[]) =>
    request(`/users/${userId}/roles`, userSummarySchema, {
      method: 'PUT',
      body: JSON.stringify({ roles }),
    }),

  listLabs: () => request('/labs', labListSchema),
  getLab: (name: string) => request(`/labs/${encodeURIComponent(name)}`, labDetailSchema),
  // skipConfigTimeChecks bypasses the automatic config-time suites (only meaningful
  // alongside configure); it is off by default so convergence gating is on.
  deployLab: (name: string, definition: string, configure: boolean, skipConfigTimeChecks = false) =>
    request('/labs', deployResponseSchema, {
      method: 'POST',
      body: JSON.stringify({
        name,
        definition,
        configure,
        skip_config_time_checks: skipConfigTimeChecks,
      }),
    }),
  configureLab: (name: string, skipConfigTimeChecks = false) =>
    request(`/labs/${encodeURIComponent(name)}/configure`, configureResponseSchema, {
      method: 'POST',
      body: JSON.stringify({ skip_config_time_checks: skipConfigTimeChecks }),
    }),
  destroyLab: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}`, destroyResponseSchema, { method: 'DELETE' }),
  // Delete removes the lab from the catalog (soft-delete: the record is retained
  // server-side but hidden). `remove=true` also tears the lab down first if it's
  // still up, so a running or already-destroyed lab can both be deleted.
  deleteLab: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}?remove=true`, destroyResponseSchema, {
      method: 'DELETE',
    }),

  updateLabDefinition: (name: string, definition: string) =>
    request(`/labs/${encodeURIComponent(name)}`, labDetailSchema, {
      method: 'PUT',
      body: JSON.stringify({ definition }),
    }),
  redeployLab: (name: string, configure: boolean, skipConfigTimeChecks = false) =>
    request(`/labs/${encodeURIComponent(name)}/redeploy`, deployResponseSchema, {
      method: 'POST',
      body: JSON.stringify({ configure, skip_config_time_checks: skipConfigTimeChecks }),
    }),
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

  // Netem link impairment, keyed by node + interface (the backend resolves the
  // node to its container). Set/reset take lab:configure; show takes lab:read.
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
  resetNodeNetem: (name: string, node: string, iface: string) =>
    request(
      `/labs/${encodeURIComponent(name)}/nodes/${encodeURIComponent(node)}/netem/reset`,
      labActionResponseSchema,
      { method: 'POST', body: JSON.stringify({ interface: iface }) },
    ),

  // Test suites. Read/author (lab:read / lab:create); run one on demand
  // (lab:validate). `testSuites` is the raw suite map, validated server-side.
  getTestSuites: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}/test-suites`, testSuitesResponseSchema),
  putTestSuites: (name: string, testSuites: unknown) =>
    request(`/labs/${encodeURIComponent(name)}/test-suites`, testSuitesResponseSchema, {
      method: 'PUT',
      body: JSON.stringify({ test_suites: testSuites }),
    }),
  runTestSuite: (name: string, suite: string) =>
    request(
      `/labs/${encodeURIComponent(name)}/test-suites/${encodeURIComponent(suite)}/run`,
      suiteReportSchema,
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
}
