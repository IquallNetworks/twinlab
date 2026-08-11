import { Copy } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover'
import { copyText } from '@/lib/clipboard'

/** The nodes table has to fit a router's whole identity on one row, so the
 * long values are click-to-copy text rather than text plus a button. */

function copyValue(value: string, label: string) {
  void copyText(value).then((ok) =>
    ok ? toast.success(`Copied ${label}`) : toast.error('Copy failed'),
  )
}

/** Management address with a copy button. Working ssh recipes live in the
 * Connect drawer (the old inline `ssh -J jump@host:port ip` copy command was
 * a trap — -i never reaches the -J hop, and it omitted the node login). */
export function MgmtCell({ ip }: { ip: string }) {
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
        onClick={() => copyValue(ip, 'address')}
      >
        <Copy className="size-3.5" />
      </Button>
    </div>
  )
}

/** A long identifier that IS its own copy affordance — no icon button beside
 * it, which is a whole column of width on a table that already overflows. */
export function CopyCell({ value, label }: { value: string; label: string }) {
  return (
    <button
      type="button"
      className="text-left font-mono text-xs hover:text-primary"
      title={`Copy ${label}`}
      aria-label={`Copy ${label} ${value}`}
      onClick={() => copyValue(value, label)}
    >
      {value}
    </button>
  )
}

/** The image name minus its registry and tag, for a node whose device the
 * definition does not tell us (an `image:` override, or a definition the
 * builder's parser gates on). Basename FIRST: a registry may carry a port,
 * and splitting on ':' before that would cut the host in half. */
function imageLabel(image: string): string {
  const last = image.split('/').pop() ?? image
  return last.split('@')[0]?.split(':')[0] || image
}

/** The node's device, with the deployed image one hover away.
 *
 * The image is the widest thing a node row carries (a digest-pinned tag runs
 * past 40 characters) and the least often needed — what an operator reads at
 * a glance is "this is a vyos". So the cell shows the device and the full
 * reference lives in a popover, which a click copies. The image also rides
 * the button's aria-label, so it reaches a screen reader without the hover. */
export function DeviceCell({ device, image }: { device: string; image: string }) {
  const [open, setOpen] = useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <button
          type="button"
          className="font-mono text-xs underline decoration-dotted underline-offset-4 hover:text-primary"
          aria-label={`Image ${image} — click to copy`}
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onClick={() => copyValue(image, 'image')}
        >
          {device || imageLabel(image)}
        </button>
      </PopoverAnchor>
      <PopoverContent
        align="start"
        className="w-auto max-w-sm px-3 py-2"
        // Hover-opened: letting it take focus would immediately blur the
        // trigger and close it again.
        onOpenAutoFocus={(event) => event.preventDefault()}
      >
        <span className="font-mono text-xs break-all">{image}</span>
      </PopoverContent>
    </Popover>
  )
}
