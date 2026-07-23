import type { ComponentProps } from 'react'

import type { Badge } from '@/components/ui/badge'

type BadgeVariant = NonNullable<ComponentProps<typeof Badge>['variant']>

/** Lab status → badge style: deployed reads as active, destroyed as muted. */
export function statusBadgeVariant(status: string): BadgeVariant {
  if (status === 'deployed') return 'default'
  if (status === 'destroyed') return 'outline'
  return 'secondary'
}

/** Node runtime state → badge style. */
export function nodeStateBadgeVariant(state: string): BadgeVariant {
  return state === 'running' ? 'default' : 'secondary'
}

/** Test result status → badge style: pass reads as active, fail/error as
 * destructive, skip as muted. */
export function testStatusBadgeVariant(status: string): BadgeVariant {
  if (status === 'pass') return 'default'
  if (status === 'fail' || status === 'error') return 'destructive'
  return 'secondary'
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}
