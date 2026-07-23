import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api } from '@/lib/api'
import { labInterfacesQueryOptions, nodeNetemQueryOptions } from '@/lib/queries'
import type { LabNodeState, NetemImpairment, NetemSetInput } from '@/lib/schemas'

// Impairment inputs are kept as raw strings; an empty field is left unchanged
// (omitted from the request) rather than sent as zero.
interface Fields {
  delay: string // ms
  jitter: string // ms
  loss: string // %
  rate: string // kbit/s
  corruption: string // %
}

const EMPTY_FIELDS: Fields = { delay: '', jitter: '', loss: '', rate: '', corruption: '' }

/** Turn the raw fields into a set request, or null when nothing is filled in
 * (the backend rejects an empty impairment set, so we don't send one). Delay and
 * jitter are ms numbers here; netem wants duration strings, so they get a `ms`. */
function buildInput(iface: string, f: Fields): NetemSetInput | null {
  const input: NetemSetInput = { interface: iface }
  if (f.delay.trim() !== '') input.delay = `${Number(f.delay)}ms`
  if (f.jitter.trim() !== '') input.jitter = `${Number(f.jitter)}ms`
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

function CurrentImpairments({
  name,
  node,
  enabled,
  onReset,
  resetting,
}: {
  name: string
  node: string
  enabled: boolean
  onReset: (iface: string) => void
  resetting: string | null
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
  if (!data || data.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        {isFetching ? 'Loading…' : 'No impairments applied on this node.'}
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
        {data.map((imp: NetemImpairment) => (
          <TableRow key={imp.interface}>
            <TableCell className="font-medium">{imp.interface}</TableCell>
            <TableCell>{imp.delay || '—'}</TableCell>
            <TableCell>{imp.jitter || '—'}</TableCell>
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

/** Link impairment (netem): apply delay / jitter / loss / rate / corruption to a
 * node interface and view or clear what's applied. Keyed by node + interface;
 * only meaningful while the lab is running, so the caller gates via `enabled`.
 * The set/reset form shows only with lab:configure; everyone with lab:read sees
 * the current-state table. */
export function NetemControls({
  name,
  nodes,
  enabled,
  canConfigure,
}: {
  name: string
  nodes: LabNodeState[]
  enabled: boolean
  canConfigure: boolean
}) {
  const queryClient = useQueryClient()
  const [node, setNode] = useState(nodes[0]?.name ?? '')
  const [iface, setIface] = useState('')
  const [fields, setFields] = useState<Fields>(EMPTY_FIELDS)
  const [resetting, setResetting] = useState<string | null>(null)

  // Interface options for the selected node come from the live inventory, which
  // keys each node by its container name (`clab-<lab>-<node>`), not the short node
  // name this control uses — so match on the node's container from the lab record.
  const { data: inventory } = useQuery({
    ...labInterfacesQueryOptions(name),
    enabled: enabled && node !== '',
  })
  const container = nodes.find((n) => n.name === node)?.container ?? ''
  const interfaces = inventory?.find((n) => n.node === container)?.interfaces ?? []

  async function invalidateNetem() {
    await queryClient.invalidateQueries({ queryKey: nodeNetemQueryOptions(name, node).queryKey })
  }

  const set = useMutation({
    mutationFn: (input: NetemSetInput) => api.setNodeNetem(name, node, input),
    onSuccess: async (result) => {
      await invalidateNetem()
      setFields(EMPTY_FIELDS)
      toast.success(result.message)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Failed to set impairment'),
  })

  const reset = useMutation({
    mutationFn: (target: string) => api.resetNodeNetem(name, node, target),
    onSuccess: async (result) => {
      await invalidateNetem()
      toast.success(result.message)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Failed to reset impairment'),
    onSettled: () => setResetting(null),
  })

  function onNodeChange(next: string) {
    setNode(next)
    setIface('') // the previous interface may not exist on the new node
  }

  function onReset(target: string) {
    setResetting(target)
    reset.mutate(target)
  }

  function apply() {
    const input = iface === '' ? null : buildInput(iface, fields)
    if (input === null) {
      toast.error('Pick an interface and set at least one impairment.')
      return
    }
    set.mutate(input)
  }

  const field = (key: keyof Fields, label: string, placeholder: string) => (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={`netem-${key}`}>{label}</Label>
      <Input
        id={`netem-${key}`}
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
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Link impairment (netem)</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {!enabled ? (
          <p className="text-muted-foreground text-sm">
            Link impairment is available while the lab is running.
          </p>
        ) : (
          <>
            {canConfigure && (
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div className="flex flex-col gap-1.5">
                    <Label>Node</Label>
                    <Select value={node} onValueChange={onNodeChange}>
                      <SelectTrigger>
                        <SelectValue placeholder="Node" />
                      </SelectTrigger>
                      <SelectContent>
                        {nodes.map((n) => (
                          <SelectItem key={n.name} value={n.name}>
                            {n.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label>Interface</Label>
                    <Select value={iface} onValueChange={setIface} disabled={interfaces.length === 0}>
                      <SelectTrigger>
                        <SelectValue placeholder={interfaces.length === 0 ? 'None' : 'Interface'} />
                      </SelectTrigger>
                      <SelectContent>
                        {interfaces.map((i) => (
                          <SelectItem key={i.name} value={i.name}>
                            {i.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
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
            )}

            <div className="flex flex-col gap-2">
              <div className="text-sm font-medium">Current impairment{node ? ` — ${node}` : ''}</div>
              <CurrentImpairments
                name={name}
                node={node}
                enabled={enabled}
                onReset={onReset}
                resetting={resetting}
              />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
