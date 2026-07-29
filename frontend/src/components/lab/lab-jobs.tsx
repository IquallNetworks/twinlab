import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDateTime, jobStatusBadgeVariant } from '@/lib/format'
import { labJobsQueryOptions } from '@/lib/queries'

/** Recent async operations on the lab (deploy/configure/destroy/suite runs),
 * newest first. A FAILED job shows its error message; an operation that ran
 * with a bad outcome (config/validation failed) is a succeeded job — its
 * outcome lives in the lab's own status badges. */
export function LabJobs({ name }: { name: string }) {
  const { data: jobs, isPending, isError, error } = useQuery(labJobsQueryOptions(name))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Operations</CardTitle>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : isError ? (
          <p className="text-destructive text-sm">
            {error instanceof Error ? error.message : 'Failed to load jobs'}
          </p>
        ) : jobs.length === 0 ? (
          <p className="text-muted-foreground text-sm">No operations yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Kind</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Submitted</TableHead>
                <TableHead>Finished</TableHead>
                <TableHead>Error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.map((job) => (
                <TableRow key={job.id}>
                  <TableCell className="font-medium">{job.kind}</TableCell>
                  <TableCell>
                    <Badge variant={jobStatusBadgeVariant(job.status)}>{job.status}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(job.created_at)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {job.finished_at ? formatDateTime(job.finished_at) : '—'}
                  </TableCell>
                  <TableCell className="text-destructive text-xs">
                    {job.error?.message ?? ''}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
