import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import {
  BUILDER_MODULES,
  FALLBACK_DEVICE_CATALOG,
  type BuilderModule,
  type CatalogDevice,
} from './device-catalog'
import { deviceCatalogQueryOptions } from './queries'
import type { DeviceCatalogWire } from './schemas'

export interface DeviceCatalogState {
  // False until the query settles (success OR error) — the Build tab waits
  // for it so the parse gate and the palette agree on one device list for
  // the life of the mount.
  ready: boolean
  devices: readonly CatalogDevice[]
  // True/false from a live server answer; null while on the fallback.
  live: boolean | null
}

function toBuilderCatalog(wire: DeviceCatalogWire): CatalogDevice[] {
  return wire.devices.map((device) => ({
    device: device.device,
    label: device.label,
    kind: device.role, // netlab "role" vocabulary == the builder's kind
    // The server serves netlab's full matrix; the builder can only author
    // its own module set, so intersect (order pinned to BUILDER_MODULES).
    modules: BUILDER_MODULES.filter((module: BuilderModule) =>
      device.modules.includes(module),
    ),
    imagePresent: wire.live ? device.image_present : null,
    // Delta 31: passed through, never recomputed — the server derives these
    // from the tables that actually decide, which is the whole reason they
    // are on the wire instead of in a second copy here.
    cliMode: device.cli_mode,
    textfsm: device.textfsm,
  }))
}

/** The deployable-device catalog (`GET /catalog`, delta 18). Falls back to
 * the static last-known list while loading or when the query errors — the
 * builder stays usable against a degraded backend. */
export function useDeviceCatalog(): DeviceCatalogState {
  const query = useQuery(deviceCatalogQueryOptions)
  const data = query.data
  return useMemo(() => {
    if (data === undefined) {
      return {
        ready: query.isError,
        devices: FALLBACK_DEVICE_CATALOG,
        live: null,
      }
    }
    return { ready: true, devices: toBuilderCatalog(data), live: data.live }
  }, [data, query.isError])
}
