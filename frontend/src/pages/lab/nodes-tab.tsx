import { useQuery } from '@tanstack/react-query'
import { Copy } from 'lucide-react'
import { toast } from 'sonner'

import { LabInterfaces } from '@/components/lab/lab-interfaces'
import { LabLinks } from '@/components/lab/lab-links'
import { NodeConnectDrawer } from '@/components/lab/node-connect-drawer'
import { NodeControls } from '@/components/lab/node-controls'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { copyText } from '@/lib/clipboard'
import { nodeStateBadgeVariant } from '@/lib/format'
import {
  PERM_LAB_CONFIGURE,
  PERM_LAB_READ,
  PERM_LAB_TERMINAL,
} from '@/lib/lab-permissions'
import { labQueryOptions } from '@/lib/queries'

/** Management address with a copy button. Working ssh recipes live in the
 * Connect drawer (the old inline `ssh -J jump@host:port ip` copy command was
 * a trap — -i never reaches the -J hop, and it omitted the node login). */
function MgmtCell({ ip }: { ip: string }) {
  if (!ip) return <span className="text-muted-foreground">—</span>
  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-xs">{ip}</span>
      <Button
        variant="ghost"
        size="icon"
        className="size-6"
        title="Copy address"
        aria-label={`Copy address ${ip}`}
        onClick={() =>
          void copyText(ip).then((ok) =>
            ok ? toast.success('Copied address') : toast.error('Copy failed'),
          )
        }
      >
        <Copy className="size-3.5" />
      </Button>
    </div>
  )
}

/** The lab's runtime inventory: node states with per-node controls, and the
 * live interface listing. The consumer's landing tab. */
export function NodesTab({ name }: { name: string }) {
  const { data: lab } = useQuery(labQueryOptions(name))
  if (!lab) return null
  const isDeployed = lab.status === 'deployed'
  const can = (perm: string) => lab.permissions.includes(perm)

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Nodes</CardTitle>
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
                  <TableHead>Image</TableHead>
                  <TableHead>Management</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {lab.nodes.map((node) => (
                  <TableRow key={node.container}>
                    <TableCell className="font-mono text-sm font-medium">{node.name}</TableCell>
                    <TableCell className="font-mono text-xs">{node.container}</TableCell>
                    <TableCell className="font-mono text-xs">{node.image}</TableCell>
                    <TableCell>
                      <MgmtCell ip={node.mgmt_ip} />
                    </TableCell>
                    <TableCell>
                      <Badge variant={nodeStateBadgeVariant(node.state)}>{node.state}</Badge>
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
                        running={node.state === 'running'}
                          canConfigure={can(PERM_LAB_CONFIGURE)}
                          canRead={can(PERM_LAB_READ)}
                          canTerminal={can(PERM_LAB_TERMINAL)}
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
          lab — not just deployed ones (states are honestly unknown there). */}
      <LabLinks name={lab.name} enabled={lab.definition !== null} />
      <LabInterfaces name={lab.name} enabled={isDeployed} />
    </div>
  )
}
