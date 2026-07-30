import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api } from '@/lib/api'
import { formatDuration } from '@/lib/format'
import { labLinksQueryOptions, nodeNetemQueryOptions } from '@/lib/queries'
import type { NetemImpairment, NetemSetInput } from '@/lib/schemas'

// Impairment inputs are kept as raw strings. Set has REPLACE semantics: the
// request is the interface's complete desired impairment, so an empty field
// means that dimension is CLEARED (omitted from the request).
interface Fields {
  delay: string // ms
  jitter: string // ms
  loss: string // %
  rate: string // kbit/s
  corruption: string // %
}

const EMPTY_FIELDS: Fields = { delay: '', jitter: '', loss: '', rate: '', corruption: '' }

/** Turn the raw fields into a set request, or null when nothing is filled in
 * (an all-empty body would clear the interface — that's the Reset button's job,
 * so Apply treats it as a mistake). Delay and jitter are entered in ms and sent
 * as structured {value, unit} durations. */
function buildInput(iface: string, f: Fields): NetemSetInput | null {
  const input: NetemSetInput = { interface: iface }
  if (f.delay.trim() !== '') input.delay = { value: Number(f.delay), unit: 'ms' }
  if (f.jitter.trim() !== '') input.jitter = { value: Number(f.jitter), unit: 'ms' }
  if (f.loss.trim() !== '') input.loss = Number(f.loss)
  if (f.rate.trim() !== '') input.rate = Number(f.rate)
  if (f.corruption.trim() !== '') input.corruption = Number(f.corruption)
  const hasImpairment =
    input.delay !== undefined ||
    input.jitter !== undefined ||
    input.loss !== undefined ||
    input.rate !== undefined ||
    input.corruption !== undefined
  return hasImpairment ? input : null
}

function pct(value: number): string {
  return value > 0 ? `${value}%` : '—'
}

/** The netem set mutation with the node passed per call (no closed-over
 * selection state). Invalidates the node's netem view AND the link table —
 * canvas edge styling and the links card read impairment off the latter. */
export function useSetNetem(name: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ node, input }: { node: string; input: NetemSetInput }) =>
      api.setNodeNetem(name, node, input),
    onSuccess: async (result, { node }) => {
      await queryClient.invalidateQueries({ queryKey: nodeNetemQueryOptions(name, node).queryKey })
      await queryClient.invalidateQueries({ queryKey: labLinksQueryOptions(name).queryKey })
      toast.success(result.message)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Failed to set impairment'),
  })
}

/** The five impairment fields + Apply for one node interface. The target is the
 * caller's problem (Operations pairs it with node/interface selects; the
 * topology edge panel fixes it per endpoint). `idPrefix` keeps input ids unique
 * when several forms are mounted at once. */
export function NetemForm({
  name,
  node,
  iface,
  canConfigure,
  idPrefix = 'netem',
}: {
  name: string
  node: string
  iface: string
  canConfigure: boolean
  idPrefix?: string
}) {
  const [fields, setFields] = useState<Fields>(EMPTY_FIELDS)
  const set = useSetNetem(name)

  function apply() {
    const input = iface === '' ? null : buildInput(iface, fields)
    if (input === null) {
      toast.error('Pick an interface and set at least one impairment.')
      return
    }
    set.mutate({ node, input }, { onSuccess: () => setFields(EMPTY_FIELDS) })
  }

  const field = (key: keyof Fields, label: string, placeholder: string) => (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={`${idPrefix}-${key}`}>{label}</Label>
      <Input
        id={`${idPrefix}-${key}`}
        type="number"
        min={0}
        inputMode="decimal"
        placeholder={placeholder}
        value={fields[key]}
        onChange={(e) => setFields((prev) => ({ ...prev, [key]: e.target.value }))}
        disabled={!canConfigure || set.isPending}
      />
    </div>
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
        {field('delay', 'Delay (ms)', 'e.g. 50')}
        {field('jitter', 'Jitter (ms)', 'needs delay')}
        {field('loss', 'Loss (%)', '0–100')}
        {field('rate', 'Rate (kbit/s)', 'e.g. 1000')}
        {field('corruption', 'Corruption (%)', '0–100')}
      </div>
      <div>
        <Button onClick={apply} disabled={set.isPending}>
          {set.isPending ? 'Applying…' : 'Apply impairment'}
        </Button>
      </div>
    </div>
  )
}

/** The node's actively-impaired interfaces (netem show lists only those).
 * `interfaceFilter` narrows to one interface for per-endpoint surfaces. */
export function CurrentImpairments({
  name,
  node,
  enabled,
  onReset,
  resetting,
  interfaceFilter,
}: {
  name: string
  node: string
  enabled: boolean
  onReset: (iface: string) => void
  resetting: string | null
  interfaceFilter?: string
}) {
  const { data, isFetching, isError, error } = useQuery({
    ...nodeNetemQueryOptions(name, node),
    enabled: enabled && node !== '',
  })

  if (isError) {
    return (
      <p className="text-destructive text-sm">
        {error instanceof Error ? error.message : 'Failed to load netem state'}
      </p>
    )
  }
  const rows =
    interfaceFilter === undefined
      ? (data ?? [])
      : (data ?? []).filter((imp) => imp.interface === interfaceFilter)
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        {isFetching
          ? 'Loading…'
          : interfaceFilter === undefined
            ? 'No impairments applied on this node.'
            : 'No impairment applied on this interface.'}
      </p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Interface</TableHead>
          <TableHead>Delay</TableHead>
          <TableHead>Jitter</TableHead>
          <TableHead>Loss</TableHead>
          <TableHead>Rate</TableHead>
          <TableHead>Corruption</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((imp: NetemImpairment) => (
          <TableRow key={imp.interface}>
            <TableCell className="font-medium">{imp.interface}</TableCell>
            <TableCell>{formatDuration(imp.delay)}</TableCell>
            <TableCell>{formatDuration(imp.jitter)}</TableCell>
            <TableCell>{pct(imp.loss)}</TableCell>
            <TableCell>{imp.rate > 0 ? `${imp.rate} kbit/s` : '—'}</TableCell>
            <TableCell>{pct(imp.corruption)}</TableCell>
            <TableCell className="text-right">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onReset(imp.interface)}
                disabled={resetting !== null}
              >
                {resetting === imp.interface ? 'Resetting…' : 'Reset'}
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
