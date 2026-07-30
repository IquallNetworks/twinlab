import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowRight } from 'lucide-react'

import { ActivityFeed } from '@/components/activity-feed'
import { JobsTable } from '@/components/jobs/jobs-table'
import { LabStatusBadge } from '@/components/lab/status-badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { defaultLabTab } from '@/lib/lab-permissions'
import {
  groupsQueryOptions,
  labsQueryOptions,
  meQueryOptions,
  usersQueryOptions,
} from '@/lib/queries'
import type { LabSummary } from '@/lib/schemas'
import { useAllJobs } from '@/lib/use-all-jobs'
import { useDocumentTitle } from '@/lib/use-document-title'

const PERM_USER_MANAGE = 'user:manage'
const PERM_GROUP_MANAGE = 'group:manage'
const PERM_LAB_CREATE = 'lab:create'

function StatTile({
  label,
  value,
  destructive = false,
}: {
  label: string
  value: string
  destructive?: boolean
}) {
  return (
    <div className="flex flex-col gap-1 border bg-card/60 p-4">
      <span className="font-mono text-[0.65rem] tracking-wide text-muted-foreground uppercase">
        {label}
      </span>
      <span className={`font-mono text-2xl font-semibold ${destructive ? 'text-destructive' : ''}`}>
        {value}
      </span>
    </div>
  )
}

/** A lab row that lands the caller on their tab: authors on Overview,
 * consumers on Nodes. */
function LabLink({ lab }: { lab: LabSummary }) {
  const tab = defaultLabTab(lab.permissions)
  const params = { name: lab.name }
  return tab === 'nodes' ? (
    <Link to="/labs/$name/nodes" params={params} className="font-mono text-sm font-medium hover:text-primary hover:underline">
      {lab.name}
    </Link>
  ) : (
    <Link to="/labs/$name/overview" params={params} className="font-mono text-sm font-medium hover:text-primary hover:underline">
      {lab.name}
    </Link>
  )
}

/** Role-aware landing: fleet at a glance, the labs you touch, operations in
 * flight, and live activity. Admin figures appear only with the permissions —
 * their queries never fire without them. */
export function DashboardPage() {
  useDocumentTitle('Dashboard')
  const { data: me } = useQuery(meQueryOptions)
  const { data: labs, isPending: labsPending } = useQuery(labsQueryOptions)
  const recentJobs = useAllJobs({ limit: 10 })

  const canManageUsers = me?.permissions.includes(PERM_USER_MANAGE) ?? false
  const canManageGroups = me?.permissions.includes(PERM_GROUP_MANAGE) ?? false
  const { data: users } = useQuery({ ...usersQueryOptions, enabled: canManageUsers })
  const { data: groups } = useQuery({ ...groupsQueryOptions, enabled: canManageGroups })

  const deployed = (labs ?? []).filter((lab) => lab.status === 'deployed').length
  const nodesRunning = (labs ?? []).reduce((sum, lab) => sum + lab.nodes_running, 0)
  const nodesTotal = (labs ?? []).reduce((sum, lab) => sum + lab.nodes, 0)
  const configFailed = (labs ?? []).filter((lab) => lab.config_time_status === 'failed').length
  const recentLabs = (labs ?? [])
    .slice()
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .slice(0, 6)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-baseline gap-3">
        <h1 className="font-heading text-2xl font-semibold">Dashboard</h1>
        {me && <span className="font-mono text-xs text-muted-foreground">{me.username}</span>}
      </div>

      {labsPending ? (
        <Skeleton className="h-24 w-full" />
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatTile label="labs" value={String(labs?.length ?? 0)} />
          <StatTile label="deployed" value={String(deployed)} />
          <StatTile label="nodes running" value={`${nodesRunning}/${nodesTotal}`} />
          <StatTile
            label="config-time failures"
            value={String(configFailed)}
            destructive={configFailed > 0}
          />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Recent operations</CardTitle>
            <Link
              to="/jobs"
              className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
            >
              View all
              <ArrowRight className="size-3.5" />
            </Link>
          </CardHeader>
          <CardContent>
            <JobsTable
              jobs={recentJobs.jobs}
              isPending={recentJobs.isPending}
              isError={recentJobs.isError}
              showLab
              limit={10}
            />
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Labs</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {recentLabs.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No labs yet.{' '}
                  {(me?.permissions.includes(PERM_LAB_CREATE) ?? false) ? (
                    <Link
                      to="/labs"
                      search={{ new: true }}
                      className="underline hover:text-foreground"
                    >
                      Create your first lab
                    </Link>
                  ) : (
                    <Link to="/labs" className="underline hover:text-foreground">
                      Browse labs
                    </Link>
                  )}
                </p>
              ) : (
                recentLabs.map((lab) => (
                  <div key={lab.name} className="flex items-center justify-between gap-2">
                    <LabLink lab={lab} />
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-muted-foreground">
                        {lab.nodes_running}/{lab.nodes}
                      </span>
                      <LabStatusBadge status={lab.status} />
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Activity</CardTitle>
            </CardHeader>
            <CardContent>
              <ActivityFeed />
            </CardContent>
          </Card>

          {(canManageUsers || canManageGroups) && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Administration</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm">
                {canManageUsers && (
                  <Link to="/users" className="flex items-center justify-between hover:text-primary">
                    <span>Users</span>
                    <span className="font-mono text-xs">{users?.length ?? '…'}</span>
                  </Link>
                )}
                {canManageGroups && (
                  <Link to="/groups" className="flex items-center justify-between hover:text-primary">
                    <span>Groups</span>
                    <span className="font-mono text-xs">{groups?.length ?? '…'}</span>
                  </Link>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
