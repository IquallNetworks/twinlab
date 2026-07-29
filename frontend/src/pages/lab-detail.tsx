import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { ChevronLeft, Copy } from 'lucide-react'
import { toast } from 'sonner'

import { CustomConfig } from '@/components/lab/custom-config'
import { DeployDialog } from '@/components/lab/deploy-dialog'
import { LabAccess } from '@/components/lab/lab-access'
import { EditDefinitionDialog } from '@/components/lab/edit-definition-dialog'
import { LabInterfaces } from '@/components/lab/lab-interfaces'
import { LabJobs } from '@/components/lab/lab-jobs'
import { LabLifecycleControls } from '@/components/lab/lab-lifecycle-controls'
import { NetemControls } from '@/components/lab/netem-controls'
import { NodeControls } from '@/components/lab/node-controls'
import { TestSuites } from '@/components/lab/test-suites'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api, ApiError, waitJob } from '@/lib/api'
import { copyText } from '@/lib/clipboard'
import { formatDateTime, nodeStateBadgeVariant, statusBadgeVariant } from '@/lib/format'
import {
  labQueryOptions,
  labsQueryOptions,
  sshAccessQueryOptions,
  testSuitesQueryOptions,
} from '@/lib/queries'
import { configureResponseSchema, type SshAccess } from '@/lib/schemas'

// Per-lab permissions (from the lab detail payload — see lab.permissions): editing
// the definition/suites/templates is lab:edit; delegating access is lab:grant.
const PERM_LAB_EDIT = 'lab:edit'
const PERM_LAB_CONFIGURE = 'lab:configure'
const PERM_LAB_DESTROY = 'lab:destroy'
const PERM_LAB_READ = 'lab:read'
const PERM_LAB_TERMINAL = 'lab:terminal'
const PERM_LAB_VALIDATE = 'lab:validate'
const PERM_LAB_GRANT = 'lab:grant'

/** Node management address plus a copy-paste ssh command. The command is
 * username-agnostic (device logins vary). When the stack advertises a jump host
 * it rides ProxyJump — reachable from anywhere, Ansible-ready (needs a
 * registered SSH key; see the Account page); otherwise it's a plain `ssh <ip>`
 * that only works from the lab host itself. */
function MgmtCell({ ip, jump }: { ip: string; jump: SshAccess | undefined }) {
  if (!ip) return <span className="text-muted-foreground">—</span>
  const command =
    jump?.enabled && jump.host !== null && jump.port !== null && jump.user !== null
      ? `ssh -J ${jump.user}@${jump.host}:${jump.port} ${ip}`
      : `ssh ${ip}`
  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-xs">{ip}</span>
      <Button
        variant="ghost"
        size="icon"
        className="size-6"
        title={`Copy "${command}"`}
        onClick={() =>
          void copyText(command).then((ok) =>
            ok ? toast.success('Copied ssh command') : toast.error('Copy failed'),
          )
        }
      >
        <Copy className="size-3.5" />
      </Button>
    </div>
  )
}

function BackLink() {
  return (
    <Link to="/labs" className="text-muted-foreground inline-flex items-center gap-1 text-sm hover:underline">
      <ChevronLeft className="size-4" />
      Labs
    </Link>
  )
}

export function LabDetailPage({ name }: { name: string }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { data: lab, isPending, isError, error } = useQuery(labQueryOptions(name))
  const { data: sshAccess } = useQuery(sshAccessQueryOptions)

  // The long operations are async jobs: submit → 202 + Job → poll to terminal.
  // A failed job rejects with its error envelope, landing in the onError toast;
  // an operation that ran with a bad outcome (config_failed/validation_failed)
  // is a SUCCEEDED job whose result.status says so.
  const configure = useMutation({
    mutationFn: async () => waitJob(name, await api.configureLab(name)),
    onSuccess: async (job) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: labQueryOptions(name).queryKey }),
        queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey }),
        queryClient.invalidateQueries({ queryKey: testSuitesQueryOptions(name).queryKey }),
      ])
      const result = configureResponseSchema.parse(job.result)
      if (result.status === 'validation_failed') {
        toast.error(`Configured ${result.lab_name}, but config-time validation failed`)
      } else if (result.status === 'config_failed') {
        toast.error(`Config push to ${result.lab_name} failed on at least one node`)
      } else {
        toast.success(`Configured ${result.lab_name} (${result.configuration.length} nodes)`)
      }
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Configure failed'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['jobs', name] }),
  })

  const destroy = useMutation({
    mutationFn: async () => waitJob(name, await api.destroyLab(name)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey })
      toast.success(`Destroyed ${name}`)
      await navigate({ to: '/labs' })
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Destroy failed'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['jobs', name] }),
  })

  const del = useMutation({
    mutationFn: async () => waitJob(name, await api.deleteLab(name)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey })
      toast.success(`Deleted ${name}`)
      await navigate({ to: '/labs' })
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Delete failed'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['jobs', name] }),
  })

  if (isPending) {
    return (
      <div className="flex flex-col gap-6">
        <BackLink />
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (isError) {
    const notFound = error instanceof ApiError && error.status === 404
    return (
      <div className="flex flex-col gap-6">
        <BackLink />
        <p className="text-destructive text-sm">
          {notFound ? `No lab named ${name}.` : error instanceof Error ? error.message : 'Failed to load lab'}
        </p>
      </div>
    )
  }

  const isDeployed = lab.status === 'deployed'
  // Gate on the caller's effective permissions *on this lab* (owner-implicit +
  // global + per-lab grants), carried on the detail payload.
  const can = (perm: string) => lab.permissions.includes(perm)

  return (
    <div className="flex flex-col gap-6">
      <BackLink />

      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold">{lab.name}</h1>
          <Badge variant={statusBadgeVariant(lab.status)}>{lab.status}</Badge>
          {lab.config_time_status === 'failed' && (
            <Badge variant="destructive">config-time failed</Badge>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {can(PERM_LAB_EDIT) && <EditDefinitionDialog name={lab.name} definition={lab.definition} />}
          {can(PERM_LAB_EDIT) && (
            <DeployDialog
              name={lab.name}
              hasDefinition={lab.definition !== null}
              isRedeploy={isDeployed}
            />
          )}
          {can(PERM_LAB_CONFIGURE) && (
            <Button variant="outline" onClick={() => configure.mutate()} disabled={configure.isPending}>
              {configure.isPending ? 'Configuring…' : 'Configure'}
            </Button>
          )}
          {can(PERM_LAB_DESTROY) && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" disabled={destroy.isPending || del.isPending}>
                  Destroy
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Destroy {lab.name}?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This tears down the running nodes. The lab&apos;s definition is retained, so it
                    can be redeployed later.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={() => destroy.mutate()}>Destroy</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
          {can(PERM_LAB_DESTROY) && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" disabled={destroy.isPending || del.isPending}>
                  Delete
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete {lab.name}?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This removes the lab from the catalog{isDeployed ? ', tearing down its running nodes first' : ''}.
                    Unlike Destroy, it no longer appears in the list; its definition is kept
                    server-side but can only return by deploying a new lab.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={() => del.mutate()}>Delete</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      </div>

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
            <div>{lab.nodes.length}</div>
          </div>
          <div>
            <div className="text-muted-foreground">Created</div>
            <div>{formatDateTime(lab.created_at)}</div>
          </div>
          <div>
            <div className="text-muted-foreground">Updated</div>
            <div>{formatDateTime(lab.updated_at)}</div>
          </div>
        </CardContent>
      </Card>

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

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Nodes</CardTitle>
        </CardHeader>
        <CardContent>
          {lab.nodes.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {lab.status === 'created'
                ? 'No nodes yet — author a definition and deploy the lab.'
                : `No running nodes${lab.status === 'destroyed' ? ' (destroyed)' : ''}.`}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Node</TableHead>
                  <TableHead>Container</TableHead>
                  <TableHead>Image</TableHead>
                  <TableHead>Management</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {lab.nodes.map((node) => (
                  <TableRow key={node.container}>
                    <TableCell className="font-medium">{node.name}</TableCell>
                    <TableCell className="font-mono text-xs">{node.container}</TableCell>
                    <TableCell className="font-mono text-xs">{node.image}</TableCell>
                    <TableCell>
                      <MgmtCell ip={node.mgmt_ip} jump={sshAccess} />
                    </TableCell>
                    <TableCell>
                      <Badge variant={nodeStateBadgeVariant(node.state)}>{node.state}</Badge>
                    </TableCell>
                    <TableCell>
                      <NodeControls
                        name={lab.name}
                        node={node.name}
                        running={node.state === 'running'}
                        canConfigure={can(PERM_LAB_CONFIGURE)}
                        canRead={can(PERM_LAB_READ)}
                        canTerminal={can(PERM_LAB_TERMINAL)}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <LabInterfaces name={lab.name} enabled={isDeployed} />

      <NetemControls
        name={lab.name}
        nodes={lab.nodes}
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

      {can(PERM_LAB_GRANT) && <LabAccess name={lab.name} owner={lab.owner} />}

      <LabJobs name={lab.name} />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Definition</CardTitle>
        </CardHeader>
        <CardContent>
          {lab.definition === null ? (
            <p className="text-muted-foreground text-sm">
              No definition yet — use Edit definition to author this lab.
            </p>
          ) : (
            <pre className="bg-muted overflow-x-auto rounded-md p-4 font-mono text-xs">
              {lab.definition}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
