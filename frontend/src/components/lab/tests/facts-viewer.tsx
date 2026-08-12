import { useQuery } from '@tanstack/react-query'
import { Table2 } from 'lucide-react'
import { useState } from 'react'

import { CodeEditor } from '@/components/code-editor'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { labFactsQueryOptions } from '@/lib/queries'

/** Read-only viewer for the lab's fact namespace — what suite templates like
 * `{{ nodes.pe1.loopback.ipv4 | address }}` resolve against. Loaded lazily on
 * open (a bare record has no facts; the 409 renders as the error line).
 *
 * The payload is partitioned server-side (contract delta 26), so the two
 * stability tiers are visible in the JSON itself: anything under an `_extras`
 * key is netlab-shaped and unpromised. The copy below says so, because the
 * structural signal alone doesn't explain the consequence. */
export function FactsViewer({ name }: { name: string }) {
  const [open, setOpen] = useState(false)
  const facts = useQuery({ ...labFactsQueryOptions(name), enabled: open })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Table2 className="size-3.5" />
          Facts
        </Button>
      </DialogTrigger>
      <DialogContent className="flex flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Node facts</DialogTitle>
          <DialogDescription>
            The per-node namespace test templates render against — reference it as{' '}
            <span className="font-mono">{'{{ node.… }}'}</span> (the executing node) or{' '}
            <span className="font-mono">{'{{ nodes.<name>.… }}'}</span>, with the{' '}
            <span className="font-mono">| address</span> filter stripping a CIDR&apos;s prefix
            length. Derived from the definition.
          </DialogDescription>
        </DialogHeader>
        <p className="text-muted-foreground text-xs">
          Two tiers: everything <strong className="text-foreground">outside</strong>{' '}
          <span className="font-mono">_extras</span> is stable — it keeps its shape across netlab
          upgrades. Keys <strong className="text-foreground">inside</strong> an{' '}
          <span className="font-mono">_extras</span> object are netlab&apos;s own, carry{' '}
          <strong className="text-foreground">no promises</strong>, and may change or disappear
          when netlab does. A template may read them; it just isn&apos;t guaranteed to keep
          working.
        </p>
        {facts.isPending && open ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : facts.isError ? (
          <p className="text-destructive text-sm">
            {facts.error instanceof Error ? facts.error.message : 'Failed to load facts'}
          </p>
        ) : facts.data ? (
          <CodeEditor
            value={JSON.stringify(facts.data.nodes, null, 2)}
            language="json"
            readOnly
            className="max-h-[60vh] min-h-48 flex-1"
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
