import type { ComponentProps } from 'react'

import type { Badge } from '@/components/ui/badge'
import type { Duration } from '@/lib/schemas'

type BadgeVariant = NonNullable<ComponentProps<typeof Badge>['variant']>

/** Lab status → badge style: deployed reads as active, created/destroyed as
 * muted, deploying (and anything transitional) as secondary. */
export function statusBadgeVariant(status: string): BadgeVariant {
  if (status === 'deployed') return 'default'
  if (status === 'created' || status === 'destroyed') return 'outline'
  return 'secondary'
}

/** Job status → badge style: succeeded reads as done, failed as destructive,
 * running as in-flight. */
export function jobStatusBadgeVariant(status: string): BadgeVariant {
  if (status === 'succeeded') return 'default'
  if (status === 'failed') return 'destructive'
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

/** A netem duration for display, preserving the author's unit ("50 ms"). */
export function formatDuration(duration: Duration | null): string {
  return duration ? `${duration.value} ${duration.unit}` : '—'
}
