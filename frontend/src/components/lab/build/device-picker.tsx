import { ChevronsUpDown, Router, Server, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { CatalogDevice } from '@/lib/device-catalog'

// The supported set is a maintainer decision that grows (the NOS sweep admits
// platforms one at a time), so every surface that offers a device is a
// SEARCHABLE list rather than a menu that gets taller with each admission.
// One component serves both: the Add palette and the node inspector's Device
// control, so they filter and label identically.

function DeviceGlyph({ kind }: { kind: CatalogDevice['kind'] }) {
  return kind === 'host' ? <Server className="size-3.5" /> : <Router className="size-3.5" />
}

/** One device row. `keywords` feed cmdk's filter, so a device is findable by
 * its netlab name as well as its human label ("routeros7" finds "MikroTik
 * RouterOS 7 (CHR)"). */
export function DeviceItems({
  devices,
  onPick,
}: {
  devices: readonly CatalogDevice[]
  onPick: (device: CatalogDevice) => void
}) {
  return (
    <>
      {devices.map((device) => (
        <CommandItem
          key={device.device}
          value={device.device}
          keywords={[device.label]}
          onSelect={() => onPick(device)}
        >
          <DeviceGlyph kind={device.kind} />
          {device.label}
          {device.imagePresent === false && (
            <TriangleAlert
              className="ml-auto size-3.5 text-primary"
              aria-label="Default image not present on the host"
            >
              <title>Default image not present on the host</title>
            </TriangleAlert>
          )}
        </CommandItem>
      ))}
    </>
  )
}

/** A device control: the searchable list behind a combobox trigger. Serves
 * both the node's `device` and the lab's `defaults.device` — same catalog,
 * same filter — with `emptyLabel` naming what "no device set" MEANS on that
 * surface (inheriting the lab default, or leaving every node to pick). No
 * emptyLabel means the field cannot be cleared. */
export function DevicePicker({
  id,
  devices,
  value,
  emptyLabel,
  onChange,
}: {
  id: string
  devices: readonly CatalogDevice[]
  value: string | undefined
  emptyLabel?: string
  onChange: (device: string | undefined) => void
}) {
  const [open, setOpen] = useState(false)
  const current = devices.find((device) => device.device === value)
  const label = value === undefined ? (emptyLabel ?? 'pick a device') : (current?.label ?? value)

  const pick = (device: string | undefined) => {
    onChange(device)
    setOpen(false)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          variant="outline"
          size="sm"
          role="combobox"
          aria-expanded={open}
          className="justify-between font-normal"
        >
          <span className={value === undefined ? 'text-muted-foreground' : undefined}>{label}</span>
          <ChevronsUpDown className="size-3.5 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) min-w-56">
        <Command>
          <CommandInput placeholder="Search devices…" />
          <CommandList>
            <CommandEmpty>No device matches.</CommandEmpty>
            <CommandGroup>
              {emptyLabel !== undefined && (
                <CommandItem value="unset" keywords={['default', 'none']} onSelect={() => pick(undefined)}>
                  {emptyLabel}
                </CommandItem>
              )}
              <DeviceItems devices={devices} onPick={(device) => pick(device.device)} />
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
