import { useQuery } from '@tanstack/react-query'
import { Cable, Copy } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { NodeLogsDialog } from '@/components/lab/node-logs-dialog'
import { NodeTerminalDialog } from '@/components/lab/node-terminal-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { copyText } from '@/lib/clipboard'
import { nodeStateBadgeVariant } from '@/lib/format'
import { sshAccessQueryOptions } from '@/lib/queries'
import type { LabNodeState } from '@/lib/schemas'
import {
  jumpCoordinates,
  nodeConfigBlock,
  sshAliasCommand,
  sshConfigBlock,
  sshDirectCommand,
  sshProxyCommand,
} from '@/lib/ssh'

function CopyBlock({ label, text }: { label: string; text: string }) {
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
      <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs">{text}</pre>
    </div>
  )
}

/** The per-node connect surface — a consumer's whole world in one drawer:
 * management address, working SSH recipes, the web console, and logs.
 *
 * The SSH guidance deliberately never suggests `ssh -i key -J jump@host ip`:
 * command-line -i does not reach the -J hop, so that form always fails for
 * registered keys. Both offered recipes route the identity correctly.
 *
 * The config recipe names the node (`ssh r1.mylab`) rather than its address:
 * the alias is a client-side ssh_config entry whose HostName is still the
 * management IP, so nothing on the jump host has to resolve it. Every node of
 * the lab in one paste is on the Nodes tab. */
export function NodeConnectDrawer({
  name,
  node,
  canRead,
  canTerminal,
}: {
  name: string
  node: LabNodeState
  canRead: boolean
  canTerminal: boolean
}) {
  const { data: sshAccess } = useQuery(sshAccessQueryOptions)
  // Device logins vary by NOS (vyos, admin, cisco, …) — the user says who.
  const [nodeUser, setNodeUser] = useState('')
  const jump = jumpCoordinates(sshAccess)
  const running = node.state === 'running'

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm" disabled={!node.mgmt_ip}>
          <Cable className="size-3.5" />
          Connect
        </Button>
      </SheetTrigger>
      <SheetContent className="overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="font-mono">{node.name}</SheetTitle>
          <SheetDescription className="flex items-center gap-2">
            <Badge variant={nodeStateBadgeVariant(node.state)}>{node.state}</Badge>
            <span className="font-mono text-xs">{node.image}</span>
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-col gap-6 px-4 pb-4">
          <div className="flex flex-col gap-1.5">
            <span className="text-xs text-muted-foreground">Management address</span>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm">{node.mgmt_ip || '—'}</span>
              {node.mgmt_ip && (
                <Button
                  variant="ghost"
                  size="icon-xs"
                  title="Copy address"
                  aria-label="Copy management address"
                  onClick={() =>
                    void copyText(node.mgmt_ip).then((ok) =>
                      ok ? toast.success('Copied address') : toast.error('Copy failed'),
                    )
                  }
                >
                  <Copy className="size-3" />
                </Button>
              )}
            </div>
          </div>

          {(canTerminal || canRead) && (
            <div className="flex flex-col gap-1.5">
              <span className="text-xs text-muted-foreground">In the browser</span>
              <div className="flex items-center gap-2">
                {canTerminal && running && <NodeTerminalDialog name={name} node={node.name} />}
                {canTerminal && !running && (
                  <span className="text-xs text-muted-foreground">
                    Console available while the node is running.
                  </span>
                )}
                {canRead && <NodeLogsDialog name={name} node={node.name} />}
              </div>
            </div>
          )}

          {node.mgmt_ip && (
            <div className="flex flex-col gap-3">
              <span className="text-xs text-muted-foreground">SSH from your machine</span>

              <div className="flex items-center gap-2">
                <Label htmlFor={`node-user-${node.name}`} className="text-xs whitespace-nowrap">
                  Node login
                </Label>
                <Input
                  id={`node-user-${node.name}`}
                  className="h-7 max-w-40 font-mono text-xs"
                  placeholder="admin"
                  value={nodeUser}
                  onChange={(e) => setNodeUser(e.target.value)}
                />
              </div>

              {jump ? (
                <Tabs defaultValue="config">
                  <TabsList>
                    <TabsTrigger value="config">~/.ssh/config</TabsTrigger>
                    <TabsTrigger value="proxy">One-liner</TabsTrigger>
                  </TabsList>
                  <TabsContent value="config" className="flex flex-col gap-3">
                    <CopyBlock label="config block (once)" text={sshConfigBlock(jump)} />
                    <CopyBlock
                      label="config block (this node)"
                      text={nodeConfigBlock(jump, name, node, nodeUser)}
                    />
                    <CopyBlock label="command" text={sshAliasCommand(name, node.name)} />
                  </TabsContent>
                  <TabsContent value="proxy">
                    <CopyBlock
                      label="command"
                      text={sshProxyCommand(jump, nodeUser, node.mgmt_ip)}
                    />
                  </TabsContent>
                </Tabs>
              ) : (
                <div className="flex flex-col gap-2">
                  <CopyBlock label="command" text={sshDirectCommand(nodeUser, node.mgmt_ip)} />
                  <p className="text-xs text-muted-foreground">
                    No jump host is advertised — this only works from the lab host itself.
                  </p>
                </div>
              )}

              {jump && (
                <p className="text-xs text-muted-foreground">
                  Access rides your registered SSH key — set{' '}
                  <span className="font-mono">IdentityFile</span> to it, or register one on the
                  Account page. Never pass <span className="font-mono">-i</span> next to{' '}
                  <span className="font-mono">-J</span>: it does not reach the jump hop.
                </p>
              )}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
