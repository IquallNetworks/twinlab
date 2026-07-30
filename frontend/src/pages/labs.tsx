import { useForm } from '@tanstack/react-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { z } from 'zod'

import { FieldError } from '@/components/field-error'
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
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api, waitJob } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { labsQueryOptions, meQueryOptions } from '@/lib/queries'
import { useDocumentTitle } from '@/lib/use-document-title'

const PERM_LAB_CREATE = 'lab:create'
const PERM_LAB_DESTROY = 'lab:destroy'

const createSchema = z.object({
  // Same path-safe charset the backend enforces (`_Name`): the name keys the
  // record and every /labs/{name} route, so it must be a safe URL segment.
  name: z
    .string()
    .min(1, 'A lab name is required')
    .max(64, 'At most 64 characters')
    .regex(
      /^[A-Za-z0-9][A-Za-z0-9_.-]*$/,
      'Start with a letter or digit; then letters, digits, dot, dash or underscore',
    ),
})

/** Create a bare lab record (the lifecycle split's first step) and jump to its
 * detail page, where the definition is authored and deployed. Open state is
 * the page's: the command palette can open it via ?new=1. */
function CreateLabDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const create = useMutation({
    mutationFn: (value: z.infer<typeof createSchema>) => api.createLab(value.name),
    onSuccess: async (lab) => {
      await queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey })
      toast.success(`Lab ${lab.name} created — author its definition, then deploy`)
      onOpenChange(false)
      await navigate({ to: '/labs/$name', params: { name: lab.name } })
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Create failed'),
  })

  const form = useForm({
    defaultValues: { name: '' },
    validators: { onSubmit: createSchema },
    onSubmit: async ({ value }) => {
      await create.mutateAsync(value)
    },
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next)
        if (!next) form.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <Plus className="size-4" />
          New lab
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            e.stopPropagation()
            void form.handleSubmit()
          }}
        >
          <DialogHeader>
            <DialogTitle className="font-heading">New lab</DialogTitle>
            <DialogDescription>
              Name the lab. You author its netlab definition and deploy it from the lab page — the
              name is its durable identity.
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-4 py-4">
            <form.Field name="name">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor={field.name}>Name</Label>
                  <Input
                    id={field.name}
                    className="font-mono text-sm"
                    placeholder="mpls-l3vpn"
                    autoComplete="off"
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                  />
                  <FieldError errors={field.state.meta.errors} />
                </div>
              )}
            </form.Field>
          </div>

          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <form.Subscribe selector={(s) => ({ canSubmit: s.canSubmit, isSubmitting: s.isSubmitting })}>
              {({ canSubmit, isSubmitting }) => (
                <Button type="submit" disabled={!canSubmit || isSubmitting}>
                  {isSubmitting ? 'Creating…' : 'Create'}
                </Button>
              )}
            </form.Subscribe>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Per-row delete: soft-deletes the lab (tearing it down first if it's up) and
 * refreshes the list. The teardown is an async job we poll to completion.
 * Confirmed behind an alert dialog since it's destructive. */
function DeleteLabAction({ name }: { name: string }) {
  const queryClient = useQueryClient()
  const del = useMutation({
    mutationFn: async () => waitJob(name, await api.deleteLab(name)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey })
      toast.success(`Deleted ${name}`)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Delete failed'),
  })

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-destructive"
          disabled={del.isPending}
          title={`Delete ${name}`}
          aria-label={`Delete ${name}`}
        >
          <Trash2 className="size-4" />
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {name}?</AlertDialogTitle>
          <AlertDialogDescription>
            This removes the lab from the catalog, tearing down its running nodes first if it&apos;s
            up. Its definition is kept server-side but it no longer appears here.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={() => del.mutate()}>Delete</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export function LabsPage() {
  useDocumentTitle('Labs')
  const { data: labs, isPending, isError, error, refetch } = useQuery(labsQueryOptions)
  const { data: me } = useQuery(meQueryOptions)
  const navigate = useNavigate()
  // ?new=1 (palette / dashboard CTA) opens the create dialog; closing clears
  // the param so back/refresh doesn't reopen it.
  const search = useSearch({ strict: false })
  const [createOpen, setCreateOpen] = useState(false)
  const openFromSearch = 'new' in search && search.new === true
  const createDialogOpen = createOpen || openFromSearch
  const setCreateDialogOpen = (next: boolean) => {
    setCreateOpen(next)
    if (!next && openFromSearch) {
      void navigate({ to: '/labs', search: {}, replace: true })
    }
  }
  // Creating a new lab is a global right; deleting is per-lab (from each row's
  // permissions), so the Actions column shows when any listed lab is deletable.
  const canCreate = me?.permissions.includes(PERM_LAB_CREATE) ?? false
  const anyDeletable = (labs ?? []).some((lab) => lab.permissions.includes(PERM_LAB_DESTROY))
  // Base columns (name/status/owner/nodes/created) plus the actions column when
  // any lab is deletable — keeps the loading/empty colSpan in step.
  const colCount = anyDeletable ? 6 : 5

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="font-heading text-2xl font-semibold">Labs</h1>
          {labs && (
            <span className="font-mono text-xs text-muted-foreground">
              {labs.length} {labs.length === 1 ? 'record' : 'records'}
            </span>
          )}
        </div>
        {canCreate && <CreateLabDialog open={createDialogOpen} onOpenChange={setCreateDialogOpen} />}
      </div>

      {isError ? (
        <p className="text-sm text-destructive">
          {error instanceof Error ? error.message : 'Failed to load labs'}{' '}
          <button
            type="button"
            className="underline hover:text-foreground"
            onClick={() => void refetch()}
          >
            Retry
          </button>
        </p>
      ) : (
        <div className="border bg-card/60">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Owner</TableHead>
                <TableHead>Nodes</TableHead>
                <TableHead>Created</TableHead>
                {anyDeletable && <TableHead className="w-0 text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {isPending ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={colCount}>
                      <Skeleton className="h-6 w-full" />
                    </TableCell>
                  </TableRow>
                ))
              ) : labs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={colCount} className="py-10 text-center text-muted-foreground">
                    <span className="font-mono text-xs tracking-wide uppercase">no lab records</span>
                    {canCreate && (
                      <span className="mt-1 block text-sm">
                        Create one, author its netlab definition, then deploy.
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              ) : (
                labs.map((lab) => (
                  <TableRow key={lab.name}>
                    <TableCell>
                      <Link
                        to="/labs/$name"
                        params={{ name: lab.name }}
                        className="font-mono text-sm font-medium hover:text-primary hover:underline"
                      >
                        {lab.name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <LabStatusBadge status={lab.status} />
                    </TableCell>
                    <TableCell>
                      {lab.owner?.name ?? <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      {/* running / present containers; 0/0 until deployed */}
                      <span className={lab.nodes_running > 0 ? 'text-primary' : undefined}>
                        {lab.nodes_running}
                      </span>
                      <span className="text-muted-foreground">/{lab.nodes}</span>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {formatDateTime(lab.created_at)}
                    </TableCell>
                    {anyDeletable && (
                      <TableCell className="text-right">
                        {lab.permissions.includes(PERM_LAB_DESTROY) && (
                          <DeleteLabAction name={lab.name} />
                        )}
                      </TableCell>
                    )}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
