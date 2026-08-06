import { useQuery } from '@tanstack/react-query'
import { Copy } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { copyText } from '@/lib/clipboard'
import { sshAccessQueryOptions } from '@/lib/queries'
import type { LabNodeState } from '@/lib/schemas'
import { jumpCoordinates, labConfigBlocks, sshConfigBlock } from '@/lib/ssh'

function ConfigBlock({ label, text }: { label: string; text: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{label}</span>
        <Button
          variant="ghost"
          size="icon-xs"
          title={`Copy ${label}`}
          aria-label={`Copy ${label}`}
          onClick={() =>
            void copyText(text).then((ok) =>
              ok ? toast.success(`Copied ${label}`) : toast.error('Copy failed'),
            )
          }
        >
          <Copy className="size-3" />
        </Button>
      </div>
      <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 font-mono text-xs">{text}</pre>
    </div>
  )
}

/** Every node of the lab as ssh_config aliases, so a consumer pastes once and
 * then types `ssh r1.mylab` instead of looking up an address per node. The
 * per-node equivalent lives in the Connect drawer.
 *
 * One login field for the whole lab: it is the common case, and a mixed-NOS
 * lab is one edit away in the pasted text — better than a form that asks for
 * a login per node before it will show anything. */
export function LabSshConfigDialog({ name, nodes }: { name: string; nodes: LabNodeState[] }) {
  const { data: sshAccess } = useQuery(sshAccessQueryOptions)
  const [nodeUser, setNodeUser] = useState('')
  const jump = jumpCoordinates(sshAccess)
  const addressed = nodes.filter((node) => node.mgmt_ip)

  if (addressed.length === 0) return null

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          SSH config
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>SSH config — {name}</DialogTitle>
          <DialogDescription>
            Paste into <span className="font-mono">~/.ssh/config</span> to reach every node by
            name: <span className="font-mono">ssh {addressed[0]?.name}.{name}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2">
          <Label htmlFor="lab-ssh-user" className="text-xs whitespace-nowrap">
            Node login
          </Label>
          <Input
            id="lab-ssh-user"
            className="h-7 max-w-40 font-mono text-xs"
            placeholder="admin"
            value={nodeUser}
            onChange={(e) => setNodeUser(e.target.value)}
          />
          <span className="text-xs text-muted-foreground">
            Logins vary by NOS — edit the pasted text where they differ.
          </span>
        </div>

        {jump && <ConfigBlock label="jump host (once)" text={sshConfigBlock(jump)} />}
        <ConfigBlock
          label={`nodes (${addressed.length})`}
          text={labConfigBlocks(jump, name, addressed, nodeUser)}
        />

        <p className="text-xs text-muted-foreground">
          {jump
            ? 'Access rides your registered SSH key — point IdentityFile at it in the jump-host block.'
            : 'No jump host is advertised — these aliases only work from the lab host itself.'}
        </p>
      </DialogContent>
    </Dialog>
  )
}
