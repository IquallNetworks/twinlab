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

// The login page's provider buttons (delta 33) — fetched before sign-in, so
// never retried into a spinner: no providers is a legitimate answer.
export const loginProvidersQueryOptions = queryOptions({
  queryKey: ['login-providers'],
  queryFn: () => api.loginProviders(),
  retry: false,
  staleTime: 60_000,
})

// Provider admin (user:manage). Its own root, so SSE lab bursts never churn it.
export const oidcProvidersQueryOptions = queryOptions({
  queryKey: ['oidc-providers'],
  queryFn: () => api.listOidcProviders(),
})

// The role catalog rarely changes within a session; cache it a while.
export const rolesQueryOptions = queryOptions({
  queryKey: ['roles'],
  queryFn: () => api.listRoles(),
  staleTime: 300_000,
})

// The device catalog changes only with a backend upgrade or an image
// pull/removal on the host; cache it like the role catalog.
export const deviceCatalogQueryOptions = queryOptions({
  queryKey: ['catalog'],
  queryFn: () => api.deviceCatalog(),
  staleTime: 300_000,
})

// Host resources (delta 30). Its own root, not under ['labs']: it describes
// the machine, not any lab, so SSE lab bursts must not churn it. The backend
// samples on a ~5s timer, so refetching faster than that would only re-serve
// the same snapshot.
export const hostResourcesQueryOptions = queryOptions({
  queryKey: ['host', 'resources'],
  queryFn: () => api.hostResources(),
  refetchInterval: 5_000,
  staleTime: 4_000,
})

// The daemon's footprint moves only when images are pulled or labs deployed,
// and the read costs a full inventory walk (~1s+) — so it is polled far more
// slowly than the machine's own load, and only where it is shown.
export const dockerUsageQueryOptions = queryOptions({
  queryKey: ['host', 'docker'],
  queryFn: () => api.hostDocker(),
  staleTime: 60_000,
  retry: false, // 503 when the runner is down; the card says so instead
})

// Per-node cost, polled while the Nodes tab is open. Matched to the host
// card's cadence so the two readings move together. Each poll costs the daemon
// one ~1s sampling window per running node (they run concurrently, so it is a
// WAIT rather than load) — enable it only where the numbers are shown.
export const labUsageQueryOptions = (name: string) =>
  queryOptions({
    queryKey: ['labs', name, 'usage'],
    queryFn: () => api.labUsage(name),
    refetchInterval: 5_000,
  })

// Template library (delta 21). Its own root — not under ['labs'] — so SSE
// bursts don't churn it; publish/save mutations invalidate ['templates']
// explicitly. Network entries move only on publish/withdraw (and lab PUTs
// behind a published entry, whose content is fetched per selection anyway).
export const networkTemplatesQueryOptions = queryOptions({
  queryKey: ['templates', 'network'],
  queryFn: () => api.networkTemplates(),
  staleTime: 60_000,
})

export const nodeTemplatesQueryOptions = queryOptions({
  queryKey: ['templates', 'node'],
  queryFn: () => api.nodeTemplates(),
  staleTime: 60_000,
})

export const networkTemplateQueryOptions = (name: string) =>
  queryOptions({
    queryKey: ['templates', 'network', name],
    queryFn: () => api.networkTemplate(name),
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

// The shared manual arrangement (delta 19). Under the ['labs'] root so the
// SSE invalidation refreshes it like every other lab read; staleTime damps
// the bursts.
export const labLayoutQueryOptions = (name: string) =>
  queryOptions({
    queryKey: ['labs', name, 'layout'],
    queryFn: () => api.labLayout(name),
    staleTime: 30_000,
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

// Definition-derived and server-cached; only a definition change moves it.
export const labFactsQueryOptions = (name: string) =>
  queryOptions({
    queryKey: ['labs', name, 'facts'],
    queryFn: () => api.labFacts(name),
    staleTime: 60_000,
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

// One job with its step log (contract delta 29) — the only read that carries
// steps, which is why the drawer fetches instead of rendering the row it was
// handed. A running job is re-read on an interval: steps are durable data on
// the record, so they arrive by polling rather than over the (lossy, poke-only)
// SSE stream.
export const jobQueryOptions = (lab: string, jobId: string, isRunning: boolean) =>
  queryOptions({
    queryKey: ['jobs', lab, jobId],
    queryFn: () => api.getJob(lab, jobId),
    refetchInterval: isRunning ? 2000 : false,
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
