import { queryOptions } from '@tanstack/react-query'

import { api } from '@/lib/api'

// `me` drives the auth gate: retry:false so a 401 fails fast (→ redirect to
// /login) instead of retrying an unauthenticated request three times.
export const meQueryOptions = queryOptions({
  queryKey: ['me'],
  queryFn: () => api.me(),
  retry: false,
  staleTime: 60_000,
})

export const usersQueryOptions = queryOptions({
  queryKey: ['users'],
  queryFn: () => api.listUsers(),
})

// The role catalog rarely changes within a session; cache it a while.
export const rolesQueryOptions = queryOptions({
  queryKey: ['roles'],
  queryFn: () => api.listRoles(),
  staleTime: 300_000,
})

export const groupsQueryOptions = queryOptions({
  queryKey: ['groups'],
  queryFn: () => api.listGroups(),
})

export const principalsQueryOptions = queryOptions({
  queryKey: ['principals'],
  queryFn: () => api.listPrincipals(),
})

export const labGrantsQueryOptions = (name: string) =>
  queryOptions({
    queryKey: ['labs', name, 'grants'],
    queryFn: () => api.listGrants(name),
  })

export const labsQueryOptions = queryOptions({
  queryKey: ['labs'],
  queryFn: () => api.listLabs(),
})

export const labQueryOptions = (name: string) =>
  queryOptions({
    queryKey: ['labs', name],
    queryFn: () => api.getLab(name),
  })

export const labInterfacesQueryOptions = (name: string) =>
  queryOptions({
    queryKey: ['labs', name, 'interfaces'],
    queryFn: () => api.labInterfaces(name),
  })

// Server-cached on the lab record, but every SSE burst invalidates the
// ['labs'] prefix — a short staleTime damps refetch storms while still
// tracking oper state through lab events.
export const labLinksQueryOptions = (name: string) =>
  queryOptions({
    queryKey: ['labs', name, 'links'],
    queryFn: () => api.labLinks(name),
    staleTime: 15_000,
  })

export const nodeNetemQueryOptions = (name: string, node: string) =>
  queryOptions({
    queryKey: ['labs', name, 'netem', node],
    queryFn: () => api.nodeNetem(name, node),
  })

export const testSuitesQueryOptions = (name: string) =>
  queryOptions({
    queryKey: ['labs', name, 'test-suites'],
    queryFn: () => api.getTestSuites(name),
  })

export const customConfigQueryOptions = (name: string) =>
  queryOptions({
    queryKey: ['labs', name, 'custom-config'],
    queryFn: () => api.getCustomConfig(name),
  })

// Jobs live under their own root key (not ['labs', ...]) so the SSE handler can
// invalidate them explicitly alongside the lab tree.
export const labJobsQueryOptions = (name: string) =>
  queryOptions({
    queryKey: ['jobs', name],
    queryFn: () => api.listJobs(name),
  })

// Cross-lab job history. Under the same ['jobs'] root as the per-lab lists, so
// one invalidation (SSE, a submit) refreshes whichever is on screen.
export const allJobsQueryOptions = (limit: number) =>
  queryOptions({
    queryKey: ['jobs', 'all', limit],
    queryFn: () => api.listAllJobs(limit),
  })

export const apiKeysQueryOptions = queryOptions({
  queryKey: ['api-keys'],
  queryFn: () => api.listApiKeys(),
})

export const sshKeysQueryOptions = queryOptions({
  queryKey: ['ssh-keys'],
  queryFn: () => api.listSshKeys(),
})

// The jump coordinates are deployment config — static for the session.
export const sshAccessQueryOptions = queryOptions({
  queryKey: ['ssh-access'],
  queryFn: () => api.getSshAccess(),
  staleTime: Infinity,
})
