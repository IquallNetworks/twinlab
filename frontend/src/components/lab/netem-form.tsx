import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { labLinksQueryOptions, nodeNetemQueryOptions } from '@/lib/queries'
import type { Duration, NetemImpairment, NetemSetInput } from '@/lib/schemas'

/** One interface to impair. Several targets get the SAME impairment — that is
 * how a link is shaped in both directions (netem is per-interface egress). */
export interface NetemEndpoint {
  node: string
  interface: string
}

// Impairment inputs are kept as raw strings, seeded from the interface's
// CURRENT impairment: the form IS the desired state, which is exactly the
// wire's REPLACE semantics — an emptied field clears that dimension.
interface Fields {
  delay: string // ms
  jitter: string // ms
  loss: string // %
  rate: string // kbit/s
  corruption: string // %
}

const EMPTY_FIELDS: Fields = { delay: '', jitter: '', loss: '', rate: '', corruption: '' }

const MS_PER_UNIT: Record<Duration['unit'], number> = { us: 0.001, ms: 1, s: 1000 }

/** A wire duration as the form's milliseconds. Values round-trip through a
 * fixed precision so 0.5 s reads "500", not "500.0000000001". */
function durationField(duration: Duration | null): string {
  if (duration === null) return ''
  return String(Number((duration.value * MS_PER_UNIT[duration.unit]).toFixed(3)))
}

/** Seed the fields from what is currently applied (null = nothing applied).
 * Zero means "unshaped" on the wire, so it seeds an empty field. */
function fieldsFrom(current: NetemImpairment | null): Fields {
  if (current === null) return EMPTY_FIELDS
  return {
    delay: durationField(current.delay),
    jitter: durationField(current.jitter),
    loss: current.loss > 0 ? String(current.loss) : '',
    rate: current.rate > 0 ? String(current.rate) : '',
    corruption: current.corruption > 0 ? String(current.corruption) : '',
  }
}

/** The fields as a set request for one interface. Empty fields are simply
 * absent — under REPLACE semantics that clears those dimensions, so an
 * all-empty form is a valid "clear everything". */
function buildInput(iface: string, f: Fields): NetemSetInput {
  const input: NetemSetInput = { interface: iface }
  if (f.delay.trim() !== '') input.delay = { value: Number(f.delay), unit: 'ms' }
  if (f.jitter.trim() !== '') input.jitter = { value: Number(f.jitter), unit: 'ms' }
  if (f.loss.trim() !== '') input.loss = Number(f.loss)
  if (f.rate.trim() !== '') input.rate = Number(f.rate)
  if (f.corruption.trim() !== '') input.corruption = Number(f.corruption)
  return input
}

type FieldErrors = Partial<Record<keyof Fields, string>>

/** Mirror of the server's NetemSetRequest constraints (jitter requires delay;
 * percentages 0–100; rate whole kbit/s; nothing negative). The wire stays the
 * authority — this only says it sooner, and in the field, instead of coming
 * back as a 422 the user has to decode. */
function validateFields(f: Fields): FieldErrors {
  const errors: FieldErrors = {}
  const checkNumber = (key: keyof Fields, max?: number) => {
    const raw = f[key].trim()
    if (raw === '') return
    const value = Number(raw)
    if (!Number.isFinite(value)) errors[key] = 'Enter a number.'
    else if (value < 0) errors[key] = 'Cannot be negative.'
    else if (max !== undefined && value > max) errors[key] = `Cannot exceed ${max}.`
  }
  checkNumber('delay')
  checkNumber('jitter')
  checkNumber('loss', 100)
  checkNumber('rate')
  checkNumber('corruption', 100)
  if (errors.rate === undefined && f.rate.trim() !== '' && !Number.isInteger(Number(f.rate))) {
    errors.rate = 'Whole kbit/s only.'
  }
  // netem layers jitter onto a delay — there is nothing to vary without one.
  if (f.jitter.trim() !== '' && f.delay.trim() === '') errors.jitter = 'Needs a delay value.'
  return errors
}

/** Apply an impairment to one or more interfaces, then refresh both views of
 * it (the per-node netem query and the link table).
 *
 * ONE request for every target (delta 24): the backend applies them
 * sequentially — clab-api serializes netem per lab and answers a concurrent
 * call with 409 "busy with netem operation" — so the fan-out that used to live
 * here is now the server's job. A 2xx means the batch RAN: per-item failures
 * come back as data, so partial success is reported honestly instead of
 * abandoning the remaining targets mid-loop. */
export function useApplyNetem(name: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (targets: { node: string; input: NetemSetInput }[]) =>
      api.applyActions(
        name,
        targets.map((target) => ({ kind: 'netem' as const, node: target.node, ...target.input })),
      ),
    onSuccess: async (report, targets) => {
      for (const node of new Set(targets.map((t) => t.node))) {
        await queryClient.invalidateQueries({ queryKey: nodeNetemQueryOptions(name, node).queryKey })
      }
      await queryClient.invalidateQueries({ queryKey: labLinksQueryOptions(name).queryKey })
      const failed = report.results.filter((result) => !result.ok)
      if (failed.length > 0) {
        toast.error(
          failed.length === report.results.length
            ? failed[0].message
            : `${report.results.length - failed.length} of ${report.results.length} interfaces impaired — ${failed[0].message}`,
        )
        return
      }
      toast.success(
        report.results.length === 1
          ? report.results[0].message
          : `Impairment applied to ${report.results.length} interfaces`,
      )
    },
    onError: (err) => toastError(err, 'Failed to set impairment'),
  })
}

/** In-place impairment editor: the five fields show what is applied right now
 * and are edited in place — Apply writes exactly what they say (REPLACE
 * semantics), Clear removes everything. Every endpoint in `endpoints` gets the
 * same impairment, which is how both directions of a link are shaped.
 *
 * `current` is the shared applied impairment, or null when nothing is applied
 * (or when the endpoints disagree — the caller says so in its own copy). */
export function NetemForm({
  name,
  endpoints,
  current,
  canConfigure,
  idPrefix = 'netem',
}: {
  name: string
  endpoints: NetemEndpoint[]
  current: NetemImpairment | null
  canConfigure: boolean
  idPrefix?: string
}) {
  const seedKey = JSON.stringify(fieldsFrom(current))
  const [fields, setFields] = useState<Fields>(() => JSON.parse(seedKey) as Fields)
  const seeded = useRef(seedKey)
  const apply = useApplyNetem(name)

  // Re-seed when what's applied actually changes (someone else shaped it, or
  // our own write landed) — never on an identical refetch, which would wipe
  // whatever the user is typing.
  useEffect(() => {
    if (seeded.current === seedKey) return
    seeded.current = seedKey
    setFields(JSON.parse(seedKey) as Fields)
  }, [seedKey])

  const errors = validateFields(fields)
  const invalid = Object.keys(errors).length > 0
  const dirty = JSON.stringify(fields) !== seedKey
  const pending = apply.isPending

  function onApply() {
    apply.mutate(
      endpoints.map((endpoint) => ({
        node: endpoint.node,
        input: buildInput(endpoint.interface, fields),
      })),
    )
  }

  function onClear() {
    setFields(EMPTY_FIELDS)
    // A set with no impairments IS the clear (there is no reset endpoint).
    apply.mutate(
      endpoints.map((endpoint) => ({
        node: endpoint.node,
        input: { interface: endpoint.interface },
      })),
    )
  }

  const field = (key: keyof Fields, label: string, placeholder: string) => {
    const error = errors[key]
    return (
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
          disabled={!canConfigure || pending}
          aria-invalid={error !== undefined}
          aria-describedby={error !== undefined ? `${idPrefix}-${key}-error` : undefined}
        />
        {error !== undefined ? (
          <p id={`${idPrefix}-${key}-error`} className="text-destructive text-xs">
            {error}
          </p>
        ) : null}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {field('delay', 'Delay (ms)', 'none')}
        {field('jitter', 'Jitter (ms)', 'needs delay')}
        {field('loss', 'Loss (%)', 'none')}
        {field('rate', 'Rate (kbit/s)', 'unlimited')}
        {field('corruption', 'Corruption (%)', 'none')}
      </div>
      {canConfigure ? (
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={onApply} disabled={pending || invalid || !dirty}>
            {pending ? 'Applying…' : dirty ? 'Apply' : 'Applied'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={onClear}
            disabled={pending || (current === null && !dirty)}
          >
            Clear
          </Button>
        </div>
      ) : null}
    </div>
  )
}
