import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Fragment, useState } from 'react'

import { NetemForm } from '@/components/lab/netem-form'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { impairmentSummary, nodeStateBadgeVariant } from '@/lib/format'
import { labInterfacesQueryOptions, nodeNetemQueryOptions } from '@/lib/queries'
import type { LabNodeState } from '@/lib/schemas'

/** Interface inventory for ONE node, read live from clab-api — the whole lab's
 * interfaces at once was a wall of tables nobody read. Only meaningful while
 * the lab is running, so the caller gates fetching via `enabled`.
 *
 * Each row also impairs that interface ALONE, which is netem's native grain:
 * the qdisc shapes egress, so one interface is one direction. Shaping both
 * directions of a link at once is the Links card's job. */
export function LabInterfaces({
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
  const { data, isFetching, isError, error, refetch } = useQuery({
    ...labInterfacesQueryOptions(name),
    enabled,
  })
  const [picked, setPicked] = useState('')
  const [openIface, setOpenIface] = useState<string | null>(null)

  // Derived, not stored: the inventory can change under us (a node stops), and
  // a selection that no longer exists must fall back rather than show nothing.
  const selected =
    data?.find((node) => node.node === picked) ?? data?.[0] ?? null
  const node = selected?.node ?? ''
  const running = nodes.find((n) => n.name === node)?.state === 'running'

  // netem show lists only the ACTIVELY impaired interfaces of one node — the
  // rows not in it are unimpaired.
  const { data: impairments } = useQuery({
    ...nodeNetemQueryOptions(name, node),
    enabled: enabled && node !== '',
  })

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Interfaces</CardTitle>
        <div className="flex items-center gap-2">
          {data && data.length > 0 ? (
            <Select
              value={node}
              onValueChange={(next) => {
                setPicked(next)
                setOpenIface(null) // the open interface may not exist on the new node
              }}
            >
              <SelectTrigger className="w-40" aria-label="Node">
                <SelectValue placeholder="Node" />
              </SelectTrigger>
              <SelectContent>
                {data.map((entry) => (
                  <SelectItem key={entry.node} value={entry.node}>
                    {entry.node}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refetch()}
            disabled={!enabled || isFetching}
          >
            {isFetching ? 'Loading…' : 'Refresh'}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!enabled ? (
          <p className="text-muted-foreground text-sm">
            Interfaces are available while the lab is running.
          </p>
        ) : isError ? (
          <p className="text-destructive text-sm">
            {error instanceof Error ? error.message : 'Failed to load interfaces'}
          </p>
        ) : selected === null ? (
          <p className="text-muted-foreground text-sm">
            {isFetching ? 'Loading…' : 'No interfaces reported.'}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Interface</TableHead>
                <TableHead>MAC</TableHead>
                <TableHead>MTU</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Impairment</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {selected.interfaces.map((iface) => {
                const open = openIface === iface.name
                const current = impairments?.find((imp) => imp.interface === iface.name) ?? null
                return (
                  <Fragment key={iface.name}>
                    <TableRow>
                      <TableCell className="font-medium">
                        {iface.name}
                        {iface.alias ? (
                          <span className="text-muted-foreground"> ({iface.alias})</span>
                        ) : null}
                      </TableCell>
                      <TableCell className="font-mono text-xs">{iface.mac || '—'}</TableCell>
                      <TableCell>{iface.mtu}</TableCell>
                      <TableCell>{iface.kind}</TableCell>
                      <TableCell>
                        <Badge variant={nodeStateBadgeVariant(iface.state)}>{iface.state}</Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs">{impairmentSummary(current)}</span>
                          <Button
                            variant="outline"
                            size="sm"
                            aria-expanded={open}
                            onClick={() => setOpenIface(open ? null : iface.name)}
                          >
                            {canConfigure ? 'Impair' : 'Show'}
                            {open ? (
                              <ChevronUp className="size-3.5" />
                            ) : (
                              <ChevronDown className="size-3.5" />
                            )}
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                    {open ? (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={6} className="bg-muted/30">
                          {running ? (
                            <div className="flex flex-col gap-2">
                              <span className="text-muted-foreground text-xs">
                                Shapes traffic <span className="font-medium">leaving</span> {node}{' '}
                                on {iface.name} — this direction only. Use the Links table to shape
                                both.
                              </span>
                              <NetemForm
                                name={name}
                                endpoints={[{ node, interface: iface.name }]}
                                current={current}
                                canConfigure={canConfigure}
                                idPrefix={`netem-${node}-${iface.name}`}
                              />
                            </div>
                          ) : (
                            <p className="text-muted-foreground text-xs">
                              {node} is not running — netem needs a live network namespace.
                            </p>
                          )}
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </Fragment>
                )
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
