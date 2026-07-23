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
  saveConfigResponseSchema,
  userInfoSchema,
  userListSchema,
  userSummarySchema,
  type FreezeAction,
  type LifecycleAction,
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
  deployLab: (definition: string, configure: boolean) =>
    request('/labs', deployResponseSchema, {
      method: 'POST',
      body: JSON.stringify({ definition, configure }),
    }),
  configureLab: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}/configure`, configureResponseSchema, {
      method: 'POST',
    }),
  destroyLab: (name: string) =>
    request(`/labs/${encodeURIComponent(name)}`, destroyResponseSchema, { method: 'DELETE' }),

  updateLabDefinition: (name: string, definition: string) =>
    request(`/labs/${encodeURIComponent(name)}`, labDetailSchema, {
      method: 'PUT',
      body: JSON.stringify({ definition }),
    }),
  redeployLab: (name: string, configure: boolean) =>
    request(`/labs/${encodeURIComponent(name)}/redeploy`, deployResponseSchema, {
      method: 'POST',
      body: JSON.stringify({ configure }),
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
}
