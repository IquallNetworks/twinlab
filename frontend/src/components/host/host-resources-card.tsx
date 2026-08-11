import { useQuery } from '@tanstack/react-query'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatBytes, formatDateTime } from '@/lib/format'
import { hostResourcesQueryOptions } from '@/lib/queries'

/** A share of something finite, as a track and a number. Turns destructive
 * past the point where a deploy is likely to be the thing that fills it. */
function Meter({ label, percent, detail }: { label: string; percent: number; detail: string }) {
  const clamped = Math.max(0, Math.min(100, percent))
  const pressed = clamped >= 90
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-[0.65rem] tracking-wide text-muted-foreground uppercase">
          {label}
        </span>
        <span className={`font-mono text-xs ${pressed ? 'text-destructive' : ''}`}>{detail}</span>
      </div>
      <div
        className="h-1.5 w-full bg-muted"
        role="meter"
        aria-label={label}
        aria-valuenow={Math.round(clamped)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={`h-full ${pressed ? 'bg-destructive' : 'bg-primary'}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  )
}

/** What the machine running the labs is spending (delta 30) — the "is there
 * room for this lab" answer. Sampled server-side on a timer, so this polls
 * rather than streams; `sampled_at` is the reading's real age. */
export function HostResourcesCard() {
  const query = useQuery(hostResourcesQueryOptions)
  const host = query.data

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Host</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {query.isError ? (
          <p className="text-sm text-muted-foreground">
            The host could not be sampled. {query.error.message}
          </p>
        ) : host === undefined ? (
          <>
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </>
        ) : (
          <>
            <Meter
              label="cpu"
              percent={host.cpu.utilization_percent}
              detail={`${host.cpu.utilization_percent.toFixed(0)}% of ${host.cpu.cores} cores`}
            />
            <Meter
              label="memory"
              percent={host.memory.percent}
              // Available, not free: reclaimable page cache is what a new lab
              // can actually claim, and it is the number that decides.
              detail={`${formatBytes(host.memory.available_bytes)} available of ${formatBytes(
                host.memory.total_bytes,
              )}`}
            />
            {host.swap.total_bytes > 0 && (
              <Meter
                label="swap"
                percent={host.swap.percent}
                detail={`${formatBytes(host.swap.used_bytes)} of ${formatBytes(
                  host.swap.total_bytes,
                )}`}
              />
            )}
            {host.disks.map((disk) => (
              <Meter
                key={disk.path}
                label={disk.path}
                percent={disk.percent}
                detail={`${formatBytes(disk.free_bytes)} free of ${formatBytes(disk.total_bytes)}`}
              />
            ))}
            <p className="font-mono text-[0.65rem] text-muted-foreground">
              load {host.cpu.load1.toFixed(2)} · {host.cpu.load5.toFixed(2)} ·{' '}
              {host.cpu.load15.toFixed(2)} · sampled {formatDateTime(host.sampled_at)}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}
