import { useQuery } from '@tanstack/react-query'

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
import { labInterfacesQueryOptions } from '@/lib/queries'
import { nodeStateBadgeVariant } from '@/lib/format'

/** Per-node interface inventory, read live from clab-api. Only meaningful while
 * the lab is running, so the caller gates fetching via `enabled`. */
export function LabInterfaces({ name, enabled }: { name: string; enabled: boolean }) {
  const { data, isFetching, isError, error, refetch } = useQuery({
    ...labInterfacesQueryOptions(name),
    enabled,
  })

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Interfaces</CardTitle>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void refetch()}
          disabled={!enabled || isFetching}
        >
          {isFetching ? 'Loading…' : 'Refresh'}
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {!enabled ? (
          <p className="text-muted-foreground text-sm">Interfaces are available while the lab is running.</p>
        ) : isError ? (
          <p className="text-destructive text-sm">
            {error instanceof Error ? error.message : 'Failed to load interfaces'}
          </p>
        ) : !data || data.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {isFetching ? 'Loading…' : 'No interfaces reported.'}
          </p>
        ) : (
          data.map((node) => (
            <div key={node.node} className="flex flex-col gap-2">
              <div className="text-sm font-medium">{node.node}</div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Interface</TableHead>
                    <TableHead>MAC</TableHead>
                    <TableHead>MTU</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>State</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {node.interfaces.map((iface) => (
                    <TableRow key={iface.name}>
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
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  )
}
