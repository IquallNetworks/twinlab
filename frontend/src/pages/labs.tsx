import { useForm } from '@tanstack/react-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'
import { z } from 'zod'

import { FieldError } from '@/components/field-error'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { formatDateTime, statusBadgeVariant } from '@/lib/format'
import { labsQueryOptions, meQueryOptions } from '@/lib/queries'

const PERM_LAB_CREATE = 'lab:create'

const DEFINITION_PLACEHOLDER = `provider: clab
defaults.device: vyos
module: [ospf]
nodes: [r1, r2]
links: [r1-r2]
`

const deploySchema = z.object({
  definition: z.string().min(1, 'A netlab definition is required'),
  configure: z.boolean(),
  skipConfigTimeChecks: z.boolean(),
})

function DeployLabDialog() {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const deploy = useMutation({
    mutationFn: (value: z.infer<typeof deploySchema>) =>
      api.deployLab(value.definition, value.configure, value.skipConfigTimeChecks),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey })
      if (result.status === 'validation_failed') {
        toast.error(`Lab ${result.lab_name} deployed, but config-time validation failed`)
      } else {
        toast.success(`Lab ${result.lab_name} ${result.status}`)
      }
      setOpen(false)
      await navigate({ to: '/labs/$name', params: { name: result.lab_name } })
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Deploy failed'),
  })

  const form = useForm({
    defaultValues: { definition: '', configure: false, skipConfigTimeChecks: false },
    validators: { onSubmit: deploySchema },
    onSubmit: async ({ value }) => {
      await deploy.mutateAsync(value)
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
        <Button>Deploy lab</Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            e.stopPropagation()
            void form.handleSubmit()
          }}
        >
          <DialogHeader>
            <DialogTitle>Deploy lab</DialogTitle>
            <DialogDescription>
              Paste a netlab definition. It must name each node&apos;s device and the provider.
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-4 py-4">
            <form.Field name="definition">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor={field.name}>Definition</Label>
                  <Textarea
                    id={field.name}
                    className="min-h-56 font-mono text-sm"
                    placeholder={DEFINITION_PLACEHOLDER}
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                  />
                  <FieldError errors={field.state.meta.errors} />
                </div>
              )}
            </form.Field>

            <form.Field name="configure">
              {(field) => (
                <div className="flex items-center gap-2">
                  <Checkbox
                    id={field.name}
                    checked={field.state.value}
                    onCheckedChange={(c) => field.handleChange(c === true)}
                  />
                  <Label htmlFor={field.name} className="font-normal">
                    Push configuration after deploy (adds minutes)
                  </Label>
                </div>
              )}
            </form.Field>

            <form.Subscribe selector={(s) => s.values.configure}>
              {(configureOn) =>
                configureOn ? (
                  <form.Field name="skipConfigTimeChecks">
                    {(field) => (
                      <div className="flex items-center gap-2 pl-6">
                        <Checkbox
                          id={field.name}
                          checked={field.state.value}
                          onCheckedChange={(c) => field.handleChange(c === true)}
                        />
                        <Label htmlFor={field.name} className="text-muted-foreground font-normal">
                          Skip config-time checks
                        </Label>
                      </div>
                    )}
                  </form.Field>
                ) : null
              }
            </form.Subscribe>
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
                  {isSubmitting ? 'Deploying…' : 'Deploy'}
                </Button>
              )}
            </form.Subscribe>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function LabsPage() {
  const { data: labs, isPending, isError, error } = useQuery(labsQueryOptions)
  const { data: me } = useQuery(meQueryOptions)
  const canCreate = me?.permissions.includes(PERM_LAB_CREATE) ?? false

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Labs</h1>
        {canCreate && <DeployLabDialog />}
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
            </TableRow>
          </TableHeader>
          <TableBody>
            {isPending ? (
              Array.from({ length: 3 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={5}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ))
            ) : labs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground text-center">
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
                  <TableCell>{lab.owner ?? <span className="text-muted-foreground">—</span>}</TableCell>
                  <TableCell>{lab.nodes}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(lab.created_at)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
