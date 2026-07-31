import type { ComponentProps } from 'react'

import type { Badge } from '@/components/ui/badge'
import type { Duration, NetemImpairment } from '@/lib/schemas'

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

/** Link oper state (the pinned delta-14 roll-up) → badge style. */
export function linkOperBadgeVariant(state: 'up' | 'degraded' | 'down' | 'unknown'): BadgeVariant {
  if (state === 'up') return 'default'
  if (state === 'down') return 'destructive'
  if (state === 'degraded') return 'secondary'
  return 'outline'
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

/** An applied impairment as one line of table cell ("50 ms · 1% loss"). A zero
 * on the wire means "that dimension is unshaped", so it contributes nothing;
 * null (and an all-zero impairment) reads as unimpaired. */
export function impairmentSummary(impairment: NetemImpairment | null): string {
  if (impairment === null) return '—'
  const parts: string[] = []
  if (impairment.delay) parts.push(formatDuration(impairment.delay))
  if (impairment.jitter) parts.push(`±${formatDuration(impairment.jitter)}`)
  if (impairment.loss > 0) parts.push(`${impairment.loss}% loss`)
  if (impairment.rate > 0) parts.push(`${impairment.rate} kbit/s`)
  if (impairment.corruption > 0) parts.push(`${impairment.corruption}% corrupt`)
  return parts.length === 0 ? '—' : parts.join(' · ')
}

/** Compact "how long ago" for feeds ("12s", "3m", "2h", "5d"). */
export function formatRelativeTime(epochMs: number, nowMs: number): string {
  const seconds = Math.max(0, Math.round((nowMs - epochMs) / 1000))
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.round(hours / 24)}d`
}

/** Elapsed wall time between two instants ("0:42", "12:05", "1:03:20").
 * Client/server clock skew is clamped to zero. */
export function formatElapsed(fromIso: string, toMs: number): string {
  const from = new Date(fromIso).getTime()
  if (Number.isNaN(from)) return '—'
  const total = Math.max(0, Math.floor((toMs - from) / 1000))
  const seconds = total % 60
  const minutes = Math.floor(total / 60) % 60
  const hours = Math.floor(total / 3600)
  const mm = hours > 0 ? String(minutes).padStart(2, '0') : String(minutes)
  const ss = String(seconds).padStart(2, '0')
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
}
