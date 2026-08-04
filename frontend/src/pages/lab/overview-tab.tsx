import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { DefinitionView } from '@/components/lab/definition-view'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDateTime, jobStatusBadgeVariant } from '@/lib/format'
import { PERM_LAB_EDIT } from '@/lib/lab-permissions'
import { labJobsQueryOptions, labQueryOptions } from '@/lib/queries'

/** Lab summary: the definition as topology or source (the lab's own answer to
 * "what is this"), then the record facts and the latest operation. */
export function OverviewTab({ name }: { name: string }) {
  // Same cached query the layout resolved; never pending in practice.
  const { data: lab } = useQuery(labQueryOptions(name))
  const { data: jobs, isError: jobsError } = useQuery(labJobsQueryOptions(name))
  if (!lab) return null
  const lastJob = jobs?.[0]
  const canEdit = lab.permissions.includes(PERM_LAB_EDIT)

  return (
    <div className="flex flex-col gap-6">
      {lab.message !== null && (
        <Card className="border-primary/40">
          <CardHeader>
            <CardTitle className="text-base">About this lab</CardTitle>
          </CardHeader>
          <CardContent>
            {/* The definition's `message:` — the author's how-to note netlab
             * would print after `netlab up`; multi-line messages keep their
             * line breaks. */}
            <p className="text-sm whitespace-pre-wrap text-muted-foreground">{lab.message}</p>
          </CardContent>
        </Card>
      )}
      {lab.status === 'created' &&
        (canEdit ? (
          <Card className="border-primary/40">
            <CardHeader>
              <CardTitle className="text-base">Getting started</CardTitle>
            </CardHeader>
            <CardContent>
              <ol className="flex list-inside list-decimal flex-col gap-1.5 text-sm text-muted-foreground">
                <li>
                  {lab.definition === null ? (
                    <>
                      Author the topology on the{' '}
                      <Link
                        to="/labs/$name/build"
                        params={{ name }}
                        className="underline hover:text-foreground"
                      >
                        Build
                      </Link>{' '}
                      tab.
                    </>
                  ) : (
                    <>
                      Definition authored — refine it any time on the{' '}
                      <Link
                        to="/labs/$name/build"
                        params={{ name }}
                        className="underline hover:text-foreground"
                      >
                        Build
                      </Link>{' '}
                      tab.
                    </>
                  )}
                </li>
                <li>Deploy from the controls above (config push optional).</li>
                <li>Connect to the running nodes from the Nodes tab.</li>
              </ol>
            </CardContent>
          </Card>
        ) : (
          <p className="text-sm text-muted-foreground">
            This lab hasn&apos;t been deployed yet — nodes appear once it is.
          </p>
        ))}

      <DefinitionView lab={lab} />

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

      {jobsError ? (
        <p className="text-sm text-muted-foreground">Last operation: unavailable.</p>
      ) : (
        lastJob && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span>Last operation:</span>
            <span className="font-mono">{lastJob.kind}</span>
            <Badge variant={jobStatusBadgeVariant(lastJob.status)}>{lastJob.status}</Badge>
            <span className="font-mono text-xs">{formatDateTime(lastJob.created_at)}</span>
          </div>
        )
      )}
    </div>
  )
}
