import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowRight, Plus } from 'lucide-react'

import { ActivityFeed } from '@/components/activity-feed'
import { HostResourcesCard } from '@/components/host/host-resources-card'
import { HostStorageCard } from '@/components/host/host-storage-card'
import { JobsTable } from '@/components/jobs/jobs-table'
import { LabStatusBadge } from '@/components/lab/status-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatRelativeTime } from '@/lib/format'
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
import { useNow } from '@/lib/use-now'

const PERM_USER_MANAGE = 'user:manage'
const PERM_GROUP_MANAGE = 'group:manage'
const PERM_LAB_CREATE = 'lab:create'

// The fleet board shows this many labs; the rest are one click away on /labs.
const BOARD_SIZE = 9

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

/** Ordering the board by what wants a human, not by recency: a failed
 * config-time gate first, then anything mid-flight, then a lab that is up but
 * short of its nodes, then the healthy live ones. Everything idle (created,
 * destroyed) sorts last and falls back to recency inside each rank. */
function attentionRank(lab: LabSummary): number {
  if (lab.config_time_status === 'failed') return 0
  if (lab.status === 'deploying') return 1
  if (lab.status === 'deployed' && lab.nodes_running < lab.nodes) return 2
  if (lab.status === 'deployed') return 3
  return 4
}

/** Running share of a lab's containers. Rendered even at 0 so every card in the
 * grid keeps the same height. */
function NodeBar({ running, total }: { running: number; total: number }) {
  const percent = total > 0 ? Math.round((running / total) * 100) : 0
  const short = total > 0 && running < total
  return (
    <div className="flex items-center gap-2">
      <div className="h-1 flex-1 bg-muted" aria-hidden="true">
        <div
          className={short ? 'h-full bg-destructive' : 'h-full bg-primary'}
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className="font-mono text-xs">
        <span className={running > 0 ? 'text-primary' : 'text-muted-foreground'}>{running}</span>
        <span className="text-muted-foreground">/{total}</span>
      </span>
    </div>
  )
}

/** One lab on the board: identity, lifecycle, how much of it is actually
 * running, and who/when. The whole card links to the caller's tab — authors
 * land on Overview, pure consumers on Nodes. */
function LabCard({ lab, now }: { lab: LabSummary; now: number }) {
  const failed = lab.config_time_status === 'failed'
  const params = { name: lab.name }
  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <span className="font-mono text-sm font-medium group-hover:text-primary group-hover:underline">
          {lab.name}
        </span>
        <LabStatusBadge status={lab.status} />
      </div>
      <NodeBar running={lab.nodes_running} total={lab.nodes} />
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="truncate">{lab.owner?.name ?? 'unowned'}</span>
        {failed ? (
          <Badge variant="destructive">config-time failed</Badge>
        ) : (
          <span className="font-mono">
            {formatRelativeTime(new Date(lab.updated_at).getTime(), now)}
          </span>
        )}
      </div>
    </>
  )
  const className = `group flex flex-col gap-3 border bg-card/60 p-4 hover:bg-card ${
    failed ? 'border-l-2 border-l-destructive' : ''
  }`

  return defaultLabTab(lab.permissions) === 'nodes' ? (
    <Link to="/labs/$name/nodes" params={params} className={className}>
      {body}
    </Link>
  ) : (
    <Link to="/labs/$name/overview" params={params} className={className}>
      {body}
    </Link>
  )
}

/** Role-aware landing. Labs and their state ARE the dashboard: the fleet
 * figures and the lab board come first, ordered by what needs attention;
 * operations and live activity sit below them as supporting detail. Admin
 * figures appear only with the permissions — their queries never fire without
 * them. */
export function DashboardPage() {
  useDocumentTitle('Dashboard')
  const { data: me } = useQuery(meQueryOptions)
  const { data: labs, isPending: labsPending, isError: labsError, refetch } = useQuery(labsQueryOptions)
  const recentJobs = useAllJobs({ limit: 10 })
  const now = useNow(30_000)

  const canManageUsers = me?.permissions.includes(PERM_USER_MANAGE) ?? false
  const canManageGroups = me?.permissions.includes(PERM_GROUP_MANAGE) ?? false
  const canCreate = me?.permissions.includes(PERM_LAB_CREATE) ?? false
  const { data: users } = useQuery({ ...usersQueryOptions, enabled: canManageUsers })
  const { data: groups } = useQuery({ ...groupsQueryOptions, enabled: canManageGroups })

  const deployed = (labs ?? []).filter((lab) => lab.status === 'deployed').length
  const nodesRunning = (labs ?? []).reduce((sum, lab) => sum + lab.nodes_running, 0)
  const nodesTotal = (labs ?? []).reduce((sum, lab) => sum + lab.nodes, 0)
  const configFailed = (labs ?? []).filter((lab) => lab.config_time_status === 'failed').length
  const board = (labs ?? [])
    .slice()
    .sort((a, b) => attentionRank(a) - attentionRank(b) || b.updated_at.localeCompare(a.updated_at))
    .slice(0, BOARD_SIZE)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <h1 className="font-heading text-2xl font-semibold">Dashboard</h1>
          {me && <span className="text-xs text-muted-foreground">{me.display_name}</span>}
        </div>
        {canCreate && (
          <Button asChild>
            {/* The create dialog is the labs page's; ?new=1 opens it there. */}
            <Link to="/labs" search={{ new: true }}>
              <Plus className="size-4" />
              New lab
            </Link>
          </Button>
        )}
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

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">Labs</CardTitle>
          <Link
            to="/labs"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            {labs && labs.length > BOARD_SIZE ? `View all ${labs.length}` : 'View all'}
            <ArrowRight className="size-3.5" />
          </Link>
        </CardHeader>
        <CardContent>
          {labsPending ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-24 w-full" />
              ))}
            </div>
          ) : labsError ? (
            <p className="text-sm text-destructive">
              Failed to load labs{' '}
              <button
                type="button"
                className="underline hover:text-foreground"
                onClick={() => void refetch()}
              >
                Retry
              </button>
            </p>
          ) : board.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              <span className="font-mono text-xs tracking-wide uppercase">no labs yet</span>
              <span className="mt-1 block">
                {canCreate ? (
                  <>
                    <Link
                      to="/labs"
                      search={{ new: true }}
                      className="underline hover:text-foreground"
                    >
                      Create your first lab
                    </Link>
                    , author its netlab definition, then deploy.
                  </>
                ) : (
                  <>
                    Nothing has been shared with you yet —{' '}
                    <Link to="/labs" className="underline hover:text-foreground">
                      browse labs
                    </Link>
                    .
                  </>
                )}
              </span>
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {board.map((lab) => (
                <LabCard key={lab.name} lab={lab} now={now} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

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
          {/* Above the activity feed on purpose: "is there room" is the
              question a fleet operator asks before anything else. */}
          <HostResourcesCard />
          <HostStorageCard />

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
