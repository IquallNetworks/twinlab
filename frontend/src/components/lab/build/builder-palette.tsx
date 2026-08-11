import { useQuery } from '@tanstack/react-query'
import { Panel } from '@xyflow/react'
import { Bookmark, ChevronDown, FileUp, Plus, Waypoints } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { CatalogDevice } from '@/lib/device-catalog'
import { meQueryOptions } from '@/lib/queries'
import type { NodeTemplateWire } from '@/lib/schemas'
import { useDeviceCatalog } from '@/lib/use-device-catalog'
import { useNodeTemplates } from '@/lib/use-node-templates'

import { DeviceItems } from './device-picker'

/** The builder's add control, split in two. The left half is the common case
 * — one click adds the lab's DEFAULT device, because a topology is mostly one
 * device repeated and re-picking it from a menu every time is the tax this
 * removes. The right half opens everything else: a searchable device list
 * (the supported set grows with every admitted platform, so it is filtered,
 * not enumerated), node templates, LAN segments and config import.
 *
 * With no lab default there is nothing to add in one click, so the whole
 * button opens the menu instead of adding something arbitrary. */
export function BuilderPalette({
  defaultDevice,
  onAddDevice,
  onAddTemplate,
  onAddLan,
  onImportConfig,
}: {
  defaultDevice: string | undefined
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
  const [open, setOpen] = useState(false)

  // The default device only earns the one-click half once the catalog can
  // resolve it: adding a device the catalog does not know would create a node
  // the parse gate rejects.
  const quick = devices.find((device) => device.device === defaultDevice)
  const close = (run: () => void) => () => {
    setOpen(false)
    run()
  }

  return (
    <Panel position="top-left">
      <div className="flex items-center">
        {quick !== undefined && (
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5 rounded-r-none border-r-0"
            title={`Add a ${quick.label} node`}
            onClick={() => onAddDevice(quick)}
          >
            <Plus className="size-3.5" />
            Add {quick.label}
          </Button>
        )}
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              size={quick === undefined ? 'sm' : 'icon-sm'}
              className={quick === undefined ? 'gap-1.5' : 'rounded-l-none'}
              aria-label={quick === undefined ? undefined : 'More things to add'}
              title={quick === undefined ? undefined : 'More things to add'}
            >
              {quick === undefined && <Plus className="size-3.5" />}
              {quick === undefined ? 'Add' : null}
              <ChevronDown className="size-3.5" />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-64">
            <Command>
              <CommandInput placeholder="Search devices…" />
              <CommandList>
                <CommandEmpty>Nothing matches.</CommandEmpty>
                <CommandGroup heading="Devices">
                  <DeviceItems
                    devices={devices}
                    onPick={(device) => close(() => onAddDevice(device))()}
                  />
                </CommandGroup>
                {templates.length > 0 && (
                  <>
                    <CommandSeparator />
                    <CommandGroup heading="Node templates">
                      {templates.map((template) => (
                        <CommandItem
                          key={template.name}
                          value={`template:${template.name}`}
                          keywords={[template.name, template.device]}
                          title={template.description}
                          onSelect={close(() => onAddTemplate(template))}
                        >
                          <Bookmark className="size-3.5" />
                          {template.name}
                          <span className="ml-auto font-mono text-xs text-muted-foreground">
                            {template.device}
                          </span>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </>
                )}
                {templates.length === 0 && canManageTemplates && (
                  <>
                    <CommandSeparator />
                    <CommandItem disabled value="no-templates">
                      <Bookmark className="size-3.5" />
                      Node templates appear here — save one from a node&apos;s General tab
                    </CommandItem>
                  </>
                )}
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem value="lan-segment" onSelect={close(onAddLan)}>
                    <Waypoints className="size-3.5" />
                    LAN segment
                  </CommandItem>
                  {/* Single-node config import (delta 22) — stamps a fragment,
                      keeps the rest of the config unattached in custom config. */}
                  <CommandItem value="from-config-file" onSelect={close(onImportConfig)}>
                    <FileUp className="size-3.5" />
                    From config file…
                  </CommandItem>
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      </div>
    </Panel>
  )
}
