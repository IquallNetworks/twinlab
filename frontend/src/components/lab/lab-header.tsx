import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { toast } from 'sonner'

import { DeployDialog } from '@/components/lab/deploy-dialog'
import { EditDefinitionDialog } from '@/components/lab/edit-definition-dialog'
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
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api, waitJob } from '@/lib/api'
import {
  PERM_LAB_CONFIGURE,
  PERM_LAB_DESTROY,
  PERM_LAB_EDIT,
} from '@/lib/lab-permissions'
import { labQueryOptions, labsQueryOptions, testSuitesQueryOptions } from '@/lib/queries'
import { configureResponseSchema, type LabDetail } from '@/lib/schemas'

/** The lab page's identity row: name, lifecycle badges, and the permission-
 * gated action set (author / deploy / configure / destroy / delete). The long
 * operations are async jobs: submit → 202 + Job → poll to terminal. A failed
 * job rejects with its error envelope (onError toast); an operation that ran
 * with a bad outcome (config_failed/validation_failed) is a SUCCEEDED job
 * whose result.status says so. */
export function LabHeader({ lab }: { lab: LabDetail }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const name = lab.name
  const isDeployed = lab.status === 'deployed'
  const can = (perm: string) => lab.permissions.includes(perm)

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

  return (
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <h1 className="font-heading font-mono text-2xl font-semibold">{lab.name}</h1>
        <LabStatusBadge status={lab.status} />
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
  )
}
