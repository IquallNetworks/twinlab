import { useQuery } from '@tanstack/react-query'

import { JobsTable } from '@/components/jobs/jobs-table'
import { CustomConfig } from '@/components/lab/custom-config'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PERM_LAB_EDIT } from '@/lib/lab-permissions'
import { labJobsQueryOptions, labQueryOptions } from '@/lib/queries'
import { jobsRefetchInterval } from '@/lib/use-all-jobs'

/** Runtime operation of a deployed lab: custom-config templates and the lab's
 * job history. Validation moved to its own Tests tab — it is authoring as much
 * as operating, and it had outgrown a card.
 *
 * The lab's own verbs are NOT here — power and save live in the header's action
 * menu beside deploy/destroy, and impairment beside the links and interfaces it
 * applies to on the Nodes tab. What's left is the work that needs a page. */
export function OperationsTab({ name }: { name: string }) {
  const { data: lab } = useQuery(labQueryOptions(name))
  // Live while a running job is visible (SSE won't announce suite-run ends).
  const jobsQuery = useQuery({
    ...labJobsQueryOptions(name),
    refetchInterval: jobsRefetchInterval(true),
  })
  if (!lab) return null
  const can = (perm: string) => lab.permissions.includes(perm)

  return (
    <div className="flex flex-col gap-6">
      <CustomConfig name={lab.name} canEdit={can(PERM_LAB_EDIT)} />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Job history</CardTitle>
        </CardHeader>
        <CardContent>
          <JobsTable
            jobs={jobsQuery.data ?? []}
            isPending={jobsQuery.isPending}
            isError={jobsQuery.isError}
            onRetry={() => void jobsQuery.refetch()}
          />
        </CardContent>
      </Card>
    </div>
  )
}
