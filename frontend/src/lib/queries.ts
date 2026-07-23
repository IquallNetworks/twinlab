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
