import { Panel } from '@xyflow/react'
import { Plus, Router, Server, TriangleAlert, Waypoints } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { CatalogDevice } from '@/lib/device-catalog'
import { useDeviceCatalog } from '@/lib/use-device-catalog'

/** The builder's add menu, collapsed behind one button. Guidance step one —
 * a device is intentful, so picking it IS the act of adding a node. The
 * device list is the server catalog (what THIS deployment can run). */
export function BuilderPalette({
  onAddDevice,
  onAddLan,
}: {
  onAddDevice: (device: CatalogDevice) => void
  onAddLan: () => void
}) {
  const { devices } = useDeviceCatalog()
  return (
    <Panel position="top-left">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className="gap-1.5">
            <Plus className="size-3.5" />
            Add
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          {devices.map((device) => (
            <DropdownMenuItem key={device.device} onSelect={() => onAddDevice(device)}>
              {device.kind === 'host' ? (
                <Server className="size-3.5" />
              ) : (
                <Router className="size-3.5" />
              )}
              {device.label}
              {device.imagePresent === false && (
                <TriangleAlert
                  className="ml-auto size-3.5 text-primary"
                  aria-label="Default image not present on the host"
                >
                  <title>Default image not present on the host</title>
                </TriangleAlert>
              )}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={onAddLan}>
            <Waypoints className="size-3.5" />
            LAN segment
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </Panel>
  )
}
