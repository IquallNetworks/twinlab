import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDateTime, jobStatusBadgeVariant } from '@/lib/format'
import { labJobsQueryOptions, labQueryOptions } from '@/lib/queries'

/** Lab summary: record facts, the latest operation at a glance, and the
 * stored definition (the lab's source of truth). */
export function OverviewTab({ name }: { name: string }) {
  // Same cached query the layout resolved; never pending in practice.
  const { data: lab } = useQuery(labQueryOptions(name))
  const { data: jobs } = useQuery(labJobsQueryOptions(name))
  if (!lab) return null
  const lastJob = jobs?.[0]

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Details</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div>
            <div className="text-muted-foreground">Owner</div>
            <div>{lab.owner?.name ?? '—'}</div>
          </div>
          <div>
            <div className="text-muted-foreground">Nodes</div>
            <div className="font-mono">{lab.nodes.length}</div>
          </div>
          <div>
            <div className="text-muted-foreground">Created</div>
            <div className="font-mono text-xs">{formatDateTime(lab.created_at)}</div>
          </div>
          <div>
            <div className="text-muted-foreground">Updated</div>
            <div className="font-mono text-xs">{formatDateTime(lab.updated_at)}</div>
          </div>
        </CardContent>
      </Card>

      {lastJob && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>Last operation:</span>
          <span className="font-mono">{lastJob.kind}</span>
          <Badge variant={jobStatusBadgeVariant(lastJob.status)}>{lastJob.status}</Badge>
          <span className="font-mono text-xs">{formatDateTime(lastJob.created_at)}</span>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Definition</CardTitle>
        </CardHeader>
        <CardContent>
          {lab.definition === null ? (
            <p className="text-sm text-muted-foreground">
              No definition yet — use Edit definition to author this lab.
            </p>
          ) : (
            <pre className="overflow-x-auto rounded-md bg-muted p-4 font-mono text-xs">
              {lab.definition}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
