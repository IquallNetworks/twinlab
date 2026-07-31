import { useState } from 'react'

import { NetemForm, type NetemEndpoint } from '@/components/lab/netem-form'
import { Button } from '@/components/ui/button'
import { impairmentSummary } from '@/lib/format'
import type { LabLink, LabNodeState, NetemImpairment } from '@/lib/schemas'

/** Identity of an applied impairment, for spotting endpoints that disagree.
 * Only the shaping counts — `interface` differs per endpoint by construction. */
function impairmentKey(impairment: NetemImpairment | null): string {
  if (impairment === null) return 'none'
  return JSON.stringify([
    impairment.delay,
    impairment.jitter,
    impairment.loss,
    impairment.rate,
    impairment.corruption,
  ])
}

/** The link's impairment as one cell of text. "mixed" when the directions
 * carry different shaping — a single line can't state two, and pretending
 * otherwise would hide an asymmetry someone set deliberately. */
export function linkImpairmentSummary(link: LabLink): string {
  const distinct = new Set(link.endpoints.map((endpoint) => impairmentKey(endpoint.impairment)))
  if (distinct.size > 1) return 'mixed'
  return impairmentSummary(link.endpoints[0]?.impairment ?? null)
}

/** Why an endpoint can't be shaped: netem needs a live namespace, and the
 * interface has to actually be there (veths don't survive a host reboot). */
function blockedReason(running: boolean): string {
  return running ? 'interface not present on the running node' : 'node not running'
}

/** Impairment for a whole link, in one place.
 *
 * By default the link is shaped BIDIRECTIONALLY: one editor whose values are
 * written to every endpoint. netem shapes egress per interface, so this is
 * literally "the same impairment leaving each end" — a 50 ms delay is 50 ms in
 * each direction, ~100 ms round trip. Advanced mode splits the editor per
 * endpoint for asymmetric shaping. */
export function LinkImpairment({
  name,
  link,
  nodes,
  canConfigure,
}: {
  name: string
  link: LabLink
  nodes: LabNodeState[]
  canConfigure: boolean
}) {
  const [advanced, setAdvanced] = useState(false)

  const isRunning = (node: string) => nodes.find((n) => n.name === node)?.state === 'running'
  const controllable = link.endpoints.filter((e) => isRunning(e.node) && e.state !== null)
  const blocked = link.endpoints.filter((e) => !(isRunning(e.node) && e.state !== null))

  // When the endpoints carry different impairments the single editor can't
  // represent them — say so instead of showing one of them as if it were both.
  const diverged = new Set(controllable.map((e) => impairmentKey(e.impairment))).size > 1
  const shared = diverged ? null : (controllable[0]?.impairment ?? null)
  const targets: NetemEndpoint[] = controllable.map((e) => ({
    node: e.node,
    interface: e.interface,
  }))

  if (controllable.length === 0) {
    return (
      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">No impairment control on this link:</span>
        {blocked.map((endpoint) => (
          <span key={`${endpoint.node}:${endpoint.interface}`} className="text-muted-foreground text-xs">
            {endpoint.node}:{endpoint.interface} — {blockedReason(isRunning(endpoint.node))}
          </span>
        ))}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium">
          Impairment
          {controllable.length === 2 ? ' — both directions' : null}
          {controllable.length > 2 ? ` — all ${controllable.length} endpoints` : null}
        </span>
        {controllable.length > 1 ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setAdvanced((on) => !on)}
            aria-pressed={advanced}
          >
            {advanced ? 'Simple' : 'Advanced'}
          </Button>
        ) : null}
      </div>

      {advanced ? (
        controllable.map((endpoint) => (
          <div key={`${endpoint.node}:${endpoint.interface}`} className="flex flex-col gap-2 border-t pt-2">
            <span className="font-mono text-xs">
              {endpoint.node}:{endpoint.interface}
              <span className="text-muted-foreground"> — traffic leaving {endpoint.node}</span>
            </span>
            <NetemForm
              name={name}
              endpoints={[{ node: endpoint.node, interface: endpoint.interface }]}
              current={endpoint.impairment}
              canConfigure={canConfigure}
              idPrefix={`netem-${endpoint.node}-${endpoint.interface}`}
            />
          </div>
        ))
      ) : (
        <>
          {diverged ? (
            <p className="text-muted-foreground text-xs">
              The directions currently differ — Advanced shows each. Applying here sets both to
              the same impairment.
            </p>
          ) : controllable.length > 1 ? (
            <p className="text-muted-foreground text-xs">
              Applied to each direction: 50 ms delay means 50 ms per direction (~100 ms round
              trip).
            </p>
          ) : null}
          <NetemForm
            name={name}
            endpoints={targets}
            current={shared}
            canConfigure={canConfigure}
            idPrefix={`netem-link-${link.index}`}
          />
        </>
      )}

      {blocked.length > 0 ? (
        <p className="text-muted-foreground text-xs">
          Not shaped:{' '}
          {blocked
            .map((e) => `${e.node}:${e.interface} (${blockedReason(isRunning(e.node))})`)
            .join(', ')}
        </p>
      ) : null}
    </div>
  )
}
