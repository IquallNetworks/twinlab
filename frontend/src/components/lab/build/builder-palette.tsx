import { useQuery } from '@tanstack/react-query'
import { Panel } from '@xyflow/react'
import { Bookmark, FileUp, Plus, Router, Server, TriangleAlert, Waypoints } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { CatalogDevice } from '@/lib/device-catalog'
import { meQueryOptions } from '@/lib/queries'
import type { NodeTemplateWire } from '@/lib/schemas'
import { useDeviceCatalog } from '@/lib/use-device-catalog'
import { useNodeTemplates } from '@/lib/use-node-templates'

/** The builder's add menu, collapsed behind one button. Guidance step one —
 * a device is intentful, so picking it IS the act of adding a node. The
 * device list is the server catalog (what THIS deployment can run); node
 * templates (delta 21) stamp a preconfigured node from the library. */
export function BuilderPalette({
  onAddDevice,
  onAddTemplate,
  onAddLan,
  onImportConfig,
}: {
  onAddDevice: (device: CatalogDevice) => void
  onAddTemplate: (template: NodeTemplateWire) => void
  onAddLan: () => void
  onImportConfig: () => void
}) {
  const { devices } = useDeviceCatalog()
  const templates = useNodeTemplates()
  // The empty-library hint only makes sense for someone who can fill it.
  const { data: me } = useQuery(meQueryOptions)
  const canManageTemplates = me?.permissions.includes('template:manage') ?? false
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
          {templates.length === 0 && canManageTemplates && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem disabled>
                <Bookmark className="size-3.5" />
                Node templates appear here — save one from a node&apos;s General tab
              </DropdownMenuItem>
            </>
          )}
          {templates.length > 0 && (
            <>
              <DropdownMenuSeparator />
              {templates.map((template) => (
                <DropdownMenuItem
                  key={template.name}
                  title={template.description}
                  onSelect={() => onAddTemplate(template)}
                >
                  <Bookmark className="size-3.5" />
                  {template.name}
                  <span className="ml-auto font-mono text-xs text-muted-foreground">
                    {template.device}
                  </span>
                </DropdownMenuItem>
              ))}
            </>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={onAddLan}>
            <Waypoints className="size-3.5" />
            LAN segment
          </DropdownMenuItem>
          {/* Single-node config import (delta 22) — stamps a fragment, keeps
              the rest of the config unattached in custom config. */}
          <DropdownMenuItem onSelect={onImportConfig}>
            <FileUp className="size-3.5" />
            From config file…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </Panel>
  )
}
