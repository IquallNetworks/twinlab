import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { CurrentImpairments, NetemForm, useSetNetem } from '@/components/lab/netem-form'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { labInterfacesQueryOptions } from '@/lib/queries'
import type { LabNodeState } from '@/lib/schemas'

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
  const [node, setNode] = useState(nodes[0]?.name ?? '')
  const [iface, setIface] = useState('')
  const [resetting, setResetting] = useState<string | null>(null)
  // A separate mutation instance from NetemForm's, so a running reset doesn't
  // read as "applying" on the form (and vice versa).
  const reset = useSetNetem(name)

  // Interface options for the selected node come from the live inventory, keyed
  // by the same short node name this control uses.
  const { data: inventory } = useQuery({
    ...labInterfacesQueryOptions(name),
    enabled: enabled && node !== '',
  })
  const interfaces = inventory?.find((n) => n.node === node)?.interfaces ?? []

  function onNodeChange(next: string) {
    setNode(next)
    setIface('') // the previous interface may not exist on the new node
  }

  function onReset(target: string) {
    setResetting(target)
    // Clearing an interface = a set with no impairments (replace semantics).
    reset.mutate({ node, input: { interface: target } }, { onSettled: () => setResetting(null) })
  }

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
                <NetemForm name={name} node={node} iface={iface} canConfigure={canConfigure} />
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
