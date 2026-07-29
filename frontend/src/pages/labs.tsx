import { useForm } from '@tanstack/react-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { z } from 'zod'

import { FieldError } from '@/components/field-error'
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
import { formatDateTime, statusBadgeVariant } from '@/lib/format'
import { labsQueryOptions, meQueryOptions } from '@/lib/queries'

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
 * detail page, where the definition is authored and deployed. */
function CreateLabDialog() {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const create = useMutation({
    mutationFn: (value: z.infer<typeof createSchema>) => api.createLab(value.name),
    onSuccess: async (lab) => {
      await queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey })
      toast.success(`Lab ${lab.name} created — author its definition, then deploy`)
      setOpen(false)
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
        setOpen(next)
        if (!next) form.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button>New lab</Button>
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
            <DialogTitle>New lab</DialogTitle>
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
          className="text-muted-foreground hover:text-destructive size-8"
          disabled={del.isPending}
          title={`Delete ${name}`}
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
  const { data: labs, isPending, isError, error } = useQuery(labsQueryOptions)
  const { data: me } = useQuery(meQueryOptions)
  // Creating a new lab is a global right; deleting is per-lab (from each row's
  // permissions), so the Actions column shows when any listed lab is deletable.
  const canCreate = me?.permissions.includes(PERM_LAB_CREATE) ?? false
  const anyDeletable = (labs ?? []).some((lab) => lab.permissions.includes(PERM_LAB_DESTROY))
  // Base columns (name/status/owner/nodes/created) plus the actions column when
  // any lab is deletable — keeps the loading/empty colSpan in step.
  const colCount = anyDeletable ? 6 : 5

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Labs</h1>
        {canCreate && <CreateLabDialog />}
      </div>

      {isError ? (
        <p className="text-destructive text-sm">
          {error instanceof Error ? error.message : 'Failed to load labs'}
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
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
                <TableCell colSpan={colCount} className="text-muted-foreground text-center">
                  No labs yet.
                </TableCell>
              </TableRow>
            ) : (
              labs.map((lab) => (
                <TableRow key={lab.name}>
                  <TableCell className="font-medium">
                    <Link
                      to="/labs/$name"
                      params={{ name: lab.name }}
                      className="hover:underline"
                    >
                      {lab.name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusBadgeVariant(lab.status)}>{lab.status}</Badge>
                  </TableCell>
                  <TableCell>
                    {lab.owner?.name ?? <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell>
                    {/* running / present containers; 0/0 until deployed */}
                    {lab.nodes_running}/{lab.nodes}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
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
      )}
    </div>
  )
}
