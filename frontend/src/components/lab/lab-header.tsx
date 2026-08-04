import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { MoreHorizontal } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { DeployDialog } from '@/components/lab/deploy-dialog'
import { LabPowerMenuItems } from '@/components/lab/lab-power-menu'
import { LabTemplateDialog } from '@/components/lab/lab-template-dialog'
import { LabStatusBadge } from '@/components/lab/status-badge'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { api, waitJob } from '@/lib/api'
import {
  PERM_LAB_CONFIGURE,
  PERM_LAB_DESTROY,
  PERM_LAB_EDIT,
} from '@/lib/lab-permissions'
import { toastError } from '@/lib/error-toast'
import { labQueryOptions, labsQueryOptions, meQueryOptions, testSuitesQueryOptions } from '@/lib/queries'
import { configureResponseSchema, type LabDetail } from '@/lib/schemas'

// Global-only (rides /auth/me, never the per-lab mask): the library-authoring
// gate for the "use as a template" toggle (delta 21).
const PERM_TEMPLATE_MANAGE = 'template:manage'

/** The lab page's identity row: the breadcrumb-prefixed name, lifecycle badges,
 * and the permission-gated action set (author / deploy / configure / destroy /
 * delete) on one line. The long operations are async jobs: submit → 202 + Job →
 * poll to terminal. A failed job rejects with its error envelope (onError
 * toast); an operation that ran with a bad outcome (config_failed/
 * validation_failed) is a SUCCEEDED job whose result.status says so. */
export function LabHeader({ lab }: { lab: LabDetail }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const name = lab.name
  const isDeployed = lab.status === 'deployed'
  const can = (perm: string) => lab.permissions.includes(perm)
  const { data: me } = useQuery(meQueryOptions)
  const canManageTemplates = me?.permissions.includes(PERM_TEMPLATE_MANAGE) ?? false
  // The two teardown verbs live in a menu, so their confirmations are opened by
  // state rather than by a nested trigger — a DropdownMenuItem unmounts its own
  // subtree on select, taking an AlertDialogTrigger's dialog with it. The
  // template dialog follows the same state-driven pattern.
  const [confirming, setConfirming] = useState<'destroy' | 'delete' | null>(null)
  const [templateOpen, setTemplateOpen] = useState(false)

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
    onError: (err) => toastError(err, 'Configure failed'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['jobs', name] }),
  })

  const destroy = useMutation({
    mutationFn: async () => waitJob(name, await api.destroyLab(name)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey })
      toast.success(`Destroyed ${name}`)
      await navigate({ to: '/labs' })
    },
    onError: (err) => toastError(err, 'Destroy failed'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['jobs', name] }),
  })

  const del = useMutation({
    mutationFn: async () => waitJob(name, await api.deleteLab(name)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey })
      toast.success(`Deleted ${name}`)
      await navigate({ to: '/labs' })
    },
    onError: (err) => toastError(err, 'Delete failed'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['jobs', name] }),
  })

  const busy = destroy.isPending || del.isPending

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 items-center gap-2">
        <Link
          to="/labs"
          className="text-sm text-muted-foreground hover:text-foreground hover:underline"
        >
          Labs
        </Link>
        <span aria-hidden="true" className="text-muted-foreground">
          /
        </span>
        <h1 className="truncate font-heading font-mono text-xl font-semibold">{lab.name}</h1>
        <LabStatusBadge status={lab.status} />
        {lab.config_time_status === 'failed' && (
          <Badge variant="destructive">config-time failed</Badge>
        )}
        {lab.definition_drifted === true && (
          <Badge
            variant="outline"
            title="The stored definition no longer matches the deployed lab — deploy to apply it"
          >
            drifted
          </Badge>
        )}
        {lab.template_published && (
          <Badge
            variant="outline"
            title="Published as a network template — its stored definition is a library entry"
          >
            template
          </Badge>
        )}
      </div>

      <div className="flex items-center gap-2">
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
        {(can(PERM_LAB_CONFIGURE) || can(PERM_LAB_DESTROY) || canManageTemplates) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon" disabled={busy} aria-label="Lab actions">
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {/* Power over the EXISTING containers — no rebuild, unlike the
                  Deploy button beside this menu. */}
              {can(PERM_LAB_CONFIGURE) && <LabPowerMenuItems lab={lab} />}
              {canManageTemplates && (
                <>
                  {can(PERM_LAB_CONFIGURE) && <DropdownMenuSeparator />}
                  <DropdownMenuItem onSelect={() => setTemplateOpen(true)}>
                    {lab.template_published ? 'Template settings…' : 'Use as a template…'}
                  </DropdownMenuItem>
                </>
              )}
              {(can(PERM_LAB_CONFIGURE) || canManageTemplates) && can(PERM_LAB_DESTROY) && (
                <DropdownMenuSeparator />
              )}
              {can(PERM_LAB_DESTROY) && (
                <>
                  {/* Destroy tears down running containers, so it needs some;
                      delete removes the record either way (teardown is
                      best-effort there) and stays available. */}
                  <DropdownMenuItem
                    disabled={lab.nodes.length === 0}
                    title={lab.nodes.length === 0 ? `lab is ${lab.status}` : undefined}
                    onSelect={() => setConfirming('destroy')}
                  >
                    Destroy
                  </DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" onSelect={() => setConfirming('delete')}>
                    Delete
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      <LabTemplateDialog lab={lab} open={templateOpen} onOpenChange={setTemplateOpen} />

      <AlertDialog
        open={confirming !== null}
        onOpenChange={(open) => {
          if (!open) setConfirming(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirming === 'delete' ? 'Delete' : 'Destroy'} {lab.name}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirming === 'delete' ? (
                <>
                  This removes the lab from the catalog
                  {isDeployed ? ', tearing down its running nodes first' : ''}. Unlike Destroy, it no
                  longer appears in the list; its definition is kept server-side but can only return
                  by deploying a new lab.
                </>
              ) : (
                <>
                  This tears down the running nodes. The lab&apos;s definition is retained, so it can
                  be redeployed later.
                </>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => (confirming === 'delete' ? del.mutate() : destroy.mutate())}
            >
              {confirming === 'delete' ? 'Delete' : 'Destroy'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
