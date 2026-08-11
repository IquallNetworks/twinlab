import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { LabInterfaces } from '@/components/lab/lab-interfaces'
import { LabLinks } from '@/components/lab/lab-links'
import { LabSshConfigDialog } from '@/components/lab/lab-ssh-config-dialog'
import { NodeConnectDrawer } from '@/components/lab/node-connect-drawer'
import { NodeControls } from '@/components/lab/node-controls'
import { CopyCell, DeviceCell, MgmtCell } from '@/components/lab/node-table-cells'
import { Badge } from '@/components/ui/badge'
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { parseBuildDoc } from '@/lib/build-doc'
import { formatBytes, formatPercent, nodeStateBadgeVariant } from '@/lib/format'
import {
  PERM_LAB_CONFIGURE,
  PERM_LAB_READ,
  PERM_LAB_TERMINAL,
} from '@/lib/lab-permissions'
import { labQueryOptions, labUsageQueryOptions } from '@/lib/queries'
import { useDeviceCatalog } from '@/lib/use-device-catalog'

/** The lab's runtime inventory: node states with per-node controls, and the
 * live interface listing. The consumer's landing tab. */
export function NodesTab({ name }: { name: string }) {
  const { data: lab } = useQuery(labQueryOptions(name))
  // Live per-node cost (delta 30). Before the early return so the hook order
  // is stable; only a deployed lab has containers to measure.
  const usage = useQuery({
    ...labUsageQueryOptions(name),
    enabled: lab?.status === 'deployed',
  })
  const usageByNode = new Map((usage.data?.nodes ?? []).map((node) => [node.node, node]))
  // A node's device is only in the DEFINITION — live state carries the image,
  // which is a different thing (a node may override it, and `linux` runs a
  // python image). Parsed with the same known-device list the builder uses;
  // a definition its gate rejects simply leaves the cell to fall back to the
  // image name.
  const catalog = useDeviceCatalog()
  const deviceByNode = useMemo(() => {
    const devices = new Map<string, string>()
    if (!lab?.definition) return devices
    const parsed = parseBuildDoc(
      lab.definition,
      catalog.devices.map((entry) => entry.device),
    )
    if (!parsed.ok) return devices
    for (const node of parsed.doc.nodes) {
      const device = node.device ?? parsed.doc.defaultDevice
      if (device) devices.set(node.name, device)
    }
    return devices
  }, [lab?.definition, catalog.devices])
  if (!lab) return null
  const isDeployed = lab.status === 'deployed'
  const can = (perm: string) => lab.permissions.includes(perm)

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Nodes</CardTitle>
          {/* Whole-lab ssh_config; the per-node equivalent is in Connect. */}
          <CardAction>
            <LabSshConfigDialog name={lab.name} nodes={lab.nodes} />
          </CardAction>
        </CardHeader>
        <CardContent>
          {lab.nodes.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {lab.status === 'created'
                ? 'No nodes yet — author a definition and deploy the lab.'
                : `No running nodes${lab.status === 'destroyed' ? ' (destroyed)' : ''}.`}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Node</TableHead>
                  <TableHead>Container</TableHead>
                  <TableHead>Device</TableHead>
                  <TableHead>Management</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead className="text-right">CPU</TableHead>
                  <TableHead className="text-right">Memory</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {lab.nodes.map((node) => (
                  <TableRow key={node.container}>
                    <TableCell className="font-mono text-sm font-medium">{node.name}</TableCell>
                    <TableCell>
                      <CopyCell value={node.container} label="container" />
                    </TableCell>
                    <TableCell>
                      <DeviceCell device={deviceByNode.get(node.name) ?? ''} image={node.image} />
                    </TableCell>
                    <TableCell>
                      <MgmtCell ip={node.mgmt_ip} />
                    </TableCell>
                    <TableCell>
                      <Badge variant={nodeStateBadgeVariant(node.state)}>{node.state}</Badge>
                    </TableCell>
                    {/* Unmeasured reads as "—", never 0: a stopped node is
                        not an idle one (delta 30). */}
                    <TableCell className="text-right font-mono text-xs">
                      {formatPercent(usageByNode.get(node.name)?.cpu_percent ?? null)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {formatBytes(usageByNode.get(node.name)?.memory_bytes ?? null)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <NodeConnectDrawer
                          name={lab.name}
                          node={node}
                          canRead={can(PERM_LAB_READ)}
                          canTerminal={can(PERM_LAB_TERMINAL)}
                        />
                        <NodeControls
                          name={lab.name}
                          node={node.name}
                          state={node.state}
                          canConfigure={can(PERM_LAB_CONFIGURE)}
                          canRead={can(PERM_LAB_READ)}
                        />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* The link table is definition-derived, so it renders for any authored
          lab — not just deployed ones (states are honestly unknown there).
          Both cards carry impairment: a link shapes both directions at once,
          an interface shapes its own. */}
      <LabLinks
        name={lab.name}
        nodes={lab.nodes}
        enabled={lab.definition !== null}
        canConfigure={can(PERM_LAB_CONFIGURE)}
      />
      <LabInterfaces
        name={lab.name}
        nodes={lab.nodes}
        enabled={isDeployed}
        canConfigure={can(PERM_LAB_CONFIGURE)}
      />
    </div>
  )
}
