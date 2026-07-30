import { useQuery } from '@tanstack/react-query'

import { JobsTable } from '@/components/jobs/jobs-table'
import { CustomConfig } from '@/components/lab/custom-config'
import { LabLifecycleControls } from '@/components/lab/lab-lifecycle-controls'
import { NetemControls } from '@/components/lab/netem-controls'
import { TestSuites } from '@/components/lab/test-suites'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  PERM_LAB_CONFIGURE,
  PERM_LAB_EDIT,
  PERM_LAB_VALIDATE,
} from '@/lib/lab-permissions'
import { labJobsQueryOptions, labQueryOptions } from '@/lib/queries'
import { jobsRefetchInterval } from '@/lib/use-all-jobs'

/** Runtime operation of a deployed lab: power, impairment, validation (the
 * frozen test-suites panel, pending its backend rework), custom-config
 * templates, and the lab's job history. */
export function OperationsTab({ name }: { name: string }) {
  const { data: lab } = useQuery(labQueryOptions(name))
  // Live while a running job is visible (SSE won't announce suite-run ends).
  const jobsQuery = useQuery({
    ...labJobsQueryOptions(name),
    refetchInterval: jobsRefetchInterval(true),
  })
  if (!lab) return null
  const isDeployed = lab.status === 'deployed'
  const can = (perm: string) => lab.permissions.includes(perm)

  return (
    <div className="flex flex-col gap-6">
      {can(PERM_LAB_CONFIGURE) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Controls</CardTitle>
          </CardHeader>
          <CardContent>
            <LabLifecycleControls name={lab.name} />
          </CardContent>
        </Card>
      )}

      {/* Impairment needs a live network namespace: a stopped container makes
          clab-api's netem show/set fail, so only running nodes are offered. */}
      <NetemControls
        name={lab.name}
        nodes={lab.nodes.filter((node) => node.state === 'running')}
        enabled={isDeployed}
        canConfigure={can(PERM_LAB_CONFIGURE)}
      />

      <TestSuites
        name={lab.name}
        enabled={isDeployed}
        canValidate={can(PERM_LAB_VALIDATE)}
        canEdit={can(PERM_LAB_EDIT)}
      />

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
          />
        </CardContent>
      </Card>
    </div>
  )
}
